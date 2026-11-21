"""Independent checker (does not use the optimizer's own parser).
usage: verify.py original.gcode optimized.gcode [--reordered]"""
import sys, re, collections
o = open(sys.argv[1]).read().splitlines(); n = open(sys.argv[2]).read().splitlines()
reordered = '--reordered' in sys.argv
E = re.compile(r'\bE([-+]?[\d.]+)')
def layers(L):
    out = []; cur = None
    for t in L:
        if t.startswith('; CHANGE_LAYER'): cur = []; out.append(cur)
        elif t.startswith('; MACHINE_END_GCODE_START'): cur = None
        if cur is not None: cur.append(t)
    return out
lo, ln = layers(o), layers(n)
res = collections.OrderedDict()
res['layers_orig'] = len(lo); res['layers_new'] = len(ln)
def esum(L, pos_only):
    s = 0.0
    for t in L:
        c = t.split(';')[0]
        if c[:3] in ('G0 ', 'G1 ', 'G2 ', 'G3 '):
            m = E.search(c)
            if m:
                v = float(m.group(1))
                xy = re.search(r'\s[XY][-+]?[\d.]', c) is not None
                if not pos_only or (v > 0 and xy): s += v
    return s
res['E_total_orig'] = round(sum(esum(l, False) for l in lo), 5)
res['E_total_new'] = round(sum(esum(l, False) for l in ln), 5)
res['max_layer_E_diff'] = max(abs(esum(a, False) - esum(b, False)) for a, b in zip(lo, ln))
res['max_layer_positiveE_diff'] = max(abs(esum(a, True) - esum(b, True)) for a, b in zip(lo, ln))
# start / end blocks identical
i0 = next(i for i, t in enumerate(o) if t.startswith('; CHANGE_LAYER')); j0 = next(i for i, t in enumerate(n) if t.startswith('; CHANGE_LAYER'))
res['start_block_identical'] = o[:i0] == n[:j0]
ie = next(i for i, t in enumerate(o) if t.startswith('; MACHINE_END_GCODE_START')); je = next(i for i, t in enumerate(n) if t.startswith('; MACHINE_END_GCODE_START'))
res['end_block_identical'] = o[ie:] == n[je:]
temps = lambda L: [t for t in L if t[:4] in ('M104', 'M109', 'M140', 'M190', 'M141', 'M191')]
res['temperature_lines_identical'] = temps(o) == temps(n)
prot = lambda L: [t for t in L if t.startswith(('M620', 'M621', 'M622', 'M623', 'M991', 'M971', 'M1004', 'M993', '; SKIPP', 'M73 L'))]
res['protected_cmds_identical'] = prot(o) == prot(n)
strip = lambda t: re.sub(r'\s[FS][-+]?[\d.]+', '', t).rstrip()
kinds = collections.Counter(); bad = []
if not reordered:
    a = i0; b = j0
    while a < ie and b < je:
        if o[a] == n[b]: a += 1; b += 1; continue
        if strip(o[a]) == strip(n[b]):
            kinds['F changed' if o[a].startswith('G') else ('fan S changed' if o[a].startswith('M106') else 'M73 R changed')] += 1; a += 1; b += 1; continue
        if o[a].startswith('M73 P') and n[b].startswith('M73 P'): kinds['M73 R changed'] += 1; a += 1; b += 1; continue
        t = n[b]
        if re.match(r'^(M106 S[\d.]+|G1 F\d+|M204 S\d+|; LINE_WIDTH: [\d.]+|G1 E-?[\d.]+ F\d+ ; PO anti-string (un)?retract)$', t):
            kinds['inserted: ' + t.split()[0] + (' (anti-string)' if 'anti-string' in t else '')] += 1; b += 1; continue
        bad.append((a + 1, o[a], n[b])); a += 1; b += 1
        if len(bad) > 5: break
else:
    for x, y in zip(lo, ln):
        isx = lambda t: E.search(t.split(';')[0]) and float(E.search(t.split(';')[0]).group(1)) > 0 and re.search(r'\s[XY][-+]?[\d.]', t.split(';')[0])
        ex = sorted(strip(t) for t in x if isx(t))
        ey = sorted(strip(t) for t in y if isx(t))
        if ex != ey: bad.append(('layer', len(ex), len(ey))); break
res['line_changes'] = dict(kinds); res['unexpected_changes'] = bad
fo = [float(m) for t in o if t.startswith('M106 S') for m in re.findall(r'S([\d.]+)', t)]
fn = [float(m) for t in n if t.startswith('M106 S') for m in re.findall(r'S([\d.]+)', t)]
res['max_fan_S_orig/new'] = (max(fo), max(fn))
Fs = lambda L: [float(m) for t in L if t.startswith(('G1', 'G0', 'G2', 'G3')) for m in re.findall(r'\sF([\d.]+)', t)]
res['max_F_orig/new'] = (max(Fs(o)), max(Fs(n)))
ok = (res['layers_orig'] == res['layers_new'] and res['max_layer_E_diff'] < 1e-6 and res['max_layer_positiveE_diff'] < 1e-6 and res['start_block_identical']
      and res['end_block_identical'] and res['temperature_lines_identical'] and res['protected_cmds_identical'] and not bad)
for k, v in res.items(): print('%-30s %s' % (k, v))
print('PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
