"""Write the optimised G-code and verify it against the original."""
import math, re
from gcode_model import GcodeFile, Kinematics, estimate_times, split_comment, parse_words

_F_RE = re.compile(r'(\s)F[-+]?(?:\d+\.?\d*|\.\d+)')

def fmtF(F):
    return '%d' % int(round(F))

def set_F(text, F):
    code, com = split_comment(text.rstrip('\r\n'))
    nl = text[len(text.rstrip('\r\n')):] or '\n'
    if re.search(r'\sF[-+]?(?:\d+\.?\d*|\.\d+)', ' ' + code):
        code2 = _F_RE.sub(lambda m: m.group(1) + 'F' + fmtF(F), ' ' + code, count=1)[1:]
    else:
        code2 = code.rstrip() + ' F' + fmtF(F)
    if com:
        return code2.rstrip() + ' ' + com + nl
    return code2 + nl

def set_S(text, S):
    code, com = split_comment(text.rstrip('\r\n'))
    nl = text[len(text.rstrip('\r\n')):] or '\n'
    Ss = ('%.2f' % S).rstrip('0').rstrip('.')
    if re.search(r'\sS[-+]?(?:\d+\.?\d*|\.\d+)', ' ' + code):
        code2 = re.sub(r'(\s)S[-+]?(?:\d+\.?\d*|\.\d+)', lambda m: m.group(1) + 'S' + Ss, ' ' + code, count=1)[1:]
    else:
        code2 = code.rstrip() + ' S' + Ss
    return (code2.rstrip() + (' ' + com if com else '')) + nl


def emit(opt, progress=None):
    g = opt.g; G = g.lines
    feeds = {}; fanpol = {}
    for k, ev in enumerate(opt.opt):
        a = opt.L[k]['a']
        for j, F in enumerate(ev.feeds):
            if F is not None and abs(F - G[a + j].effF) > 0.5:
                feeds[a + j] = F
        fanpol[k] = ev.fanpol
    accplan = {i: A for i, A in getattr(opt, 'accplan', {}).items()
               if 0 <= G[i].layer < opt.nl and getattr(opt.opt[G[i].layer], 'acc', False)}
    out = []
    out_F = None; out_acc = None; out_w = None; orig_acc = None
    base_fan = 0.0; out_fan = 0.0; boosted = False
    stats = {'f_changed': 0, 'fan_changed': 0, 'fan_inserted': 0, 'f_inserted': 0, 'acc_inserted': 0, 'acc_raised': 0,
             'acc_restored': 0, 'acc_moves': 0}
    # emission order
    seq = list(range(0, g.body_start))
    for k in range(opt.nl):
        a, b = g.layer_range(k)
        seq += opt.order.get(k, list(range(a, b)))
    seq += list(range(g.body_end, len(G)))
    reordered_layers = set(opt.order.keys())
    prev_opt = False
    nseq = max(1, len(seq))
    for cnt, i in enumerate(seq):
        if progress is not None and (cnt & 32767) == 0:
            progress('emit', cnt / nseq)
        ln = G[i]
        ins = opt.inserts_before.get(i)
        # restore modal state on entering a protected / non-optimisable stretch
        if prev_opt and not ln.opt:
            if boosted:
                out.append('M106 S%s\n' % ('%.2f' % base_fan).rstrip('0').rstrip('.')); stats['fan_inserted'] += 1
                boosted = False; out_fan = base_fan
            if ln.kind == 'motion' and ln.f is None and out_F is not None and abs(out_F - ln.effF) > 0.5:
                out.append('G1 F%s\n' % fmtF(ln.effF)); out_F = ln.effF; stats['f_inserted'] += 1
        # raised acceleration never leaks into another feature or into a protected (AMS / tool-change / timelapse) block
        if out_acc is not None and orig_acc is not None and abs(out_acc - orig_acc) > 0.5 and \
                (not ln.opt or ln.text.startswith('; FEATURE:') or ln.text.startswith('; CHANGE_LAYER')):
            out.append('M204 S%d\n' % int(round(orig_acc))); out_acc = orig_acc; stats['acc_restored'] += 1
        if ins:
            for t in ins:
                out.append(t)
                w = parse_words(split_comment(t)[0][2:])
                if 'F' in w: out_F = w['F']
        text = ln.text
        if ln.kind == 'motion':
            want = feeds.get(i, ln.effF)
            if ln.opt:
                wantA = accplan.get(i)
                tgtA = wantA if wantA is not None else ln.accel
                if wantA is not None: stats['acc_moves'] += 1
                if tgtA is not None and out_acc is not None and abs(tgtA - out_acc) > 0.5:
                    out.append('M204 S%d\n' % int(round(tgtA))); out_acc = tgtA
                    stats['acc_raised' if wantA is not None else ('acc_inserted' if ln.layer in reordered_layers else 'acc_restored')] += 1
            if ln.opt and ln.layer in reordered_layers:
                if ln.is_ext and out_w is not None and abs(ln.width - out_w) > 1e-4:
                    out.append('; LINE_WIDTH: %g\n' % ln.width); out_w = ln.width
            if ln.opt:
                bS = opt.boost.get(i)
                if bS is not None and out_fan < bS - 0.5:
                    out.append('M106 S%s\n' % ('%.2f' % bS).rstrip('0').rstrip('.')); out_fan = bS; boosted = True
                    stats['fan_inserted'] += 1
                elif bS is None and boosted and ln.is_ext:
                    out.append('M106 S%s\n' % ('%.2f' % base_fan).rstrip('0').rstrip('.')); out_fan = base_fan
                    boosted = False; stats['fan_inserted'] += 1
            if ln.f is not None:
                if abs(want - ln.f) > 0.5:
                    text = set_F(text, want); stats['f_changed'] += 1
                out_F = want
            elif ln.x is not None and (ln.length > 0 or ln.e is not None):
                if out_F is None or abs(out_F - want) > 0.5:
                    if ln.opt:
                        text = set_F(text, want); stats['f_changed'] += 1
                    else:
                        out.append('G1 F%s\n' % fmtF(want)); stats['f_inserted'] += 1
                    out_F = want
        # standalone "G1 Fxxx" lines are parsed as motion with no XY (length 0, no E)
        if ln.kind == 'motion' and ln.f is not None and ln.length <= 1e-9 and ln.e is None and \
                (ln.w is not None and set(ln.w.keys()) <= {'F'}):
            nxtF = None
            # find next motion line in the original order within the same layer and use its planned feed
            for q in range(i + 1, min(i + 40, len(G))):
                if G[q].kind == 'motion' and not (G[q].w is not None and set(G[q].w.keys()) <= {'F'}):
                    if abs(G[q].effF - ln.f) < 0.5 and q in feeds and G[q].opt:
                        nxtF = feeds[q]
                    break
            if nxtF is not None:
                text = set_F(ln.text, nxtF); out_F = nxtF; stats['f_changed'] += 1
        if ln.kind == 'fan':
            orig = ln.w.get('S', 255.0) if ln.w else 0.0
            newS = orig
            if ln.layer >= 0 and _fan_editable(ln, G):
                newS = opt.fan_value(orig, fanpol.get(ln.layer), ln.layer)
            if abs(newS - orig) > 0.5 and ln.cmd == 'M106':
                text = set_S(text, newS); stats['fan_changed'] += 1
            base_fan = newS; out_fan = newS; boosted = False
        if ln.kind == 'accel':
            out_acc = ln.accel if ln.accel is not None else (ln.w.get('S', ln.w.get('P')) if ln.w else out_acc)
            orig_acc = out_acc
        if 'LINE_WIDTH:' in text and text.startswith(';'):
            try: out_w = float(text.split(':', 1)[1])
            except ValueError: pass
        out.append(text)
        prev_opt = ln.opt
    return ''.join(out), stats


def _fan_editable(ln, G):
    """Part-fan commands in the print body that are not inside protected blocks."""
    return ln.layer >= 0 and not ln.prot


def rewrite_m73(orig_g, new_text, kin, progress=None):
    """Scale remaining-time (R) of M73 progress lines in the print body by our new/old time ratio."""
    ng = GcodeFile(new_text, progress=(lambda k, f=0.0, d='': progress('m73', f)) if progress else None)
    def rem_list(g):
        d, _ = estimate_times(g.lines, Kinematics(g))
        tot = sum(d); acc = 0.0; res = []
        for ln, t in zip(g.lines, d):
            if ln.layer >= 0 and ln.text.startswith('M73 P') and ' R' in ln.text:
                res.append((ln.i, tot - acc))
            acc += t
        return res, tot
    ro, to = rem_list(orig_g); rn, tn = rem_list(ng)
    if len(ro) != len(rn): return new_text, 0
    lines = ng.raw_lines[:]; n = 0
    for (io, remo), (inew, remn) in zip(ro, rn):
        w = parse_words(split_comment(orig_g.lines[io].text)[0][3:])
        if 'R' not in w or remo <= 0: continue
        R = w['R'] * remn / remo
        Rn = int(round(R))
        if Rn != int(w['R']):
            t = lines[inew]
            lines[inew] = re.sub(r'(\sR)\d+', lambda m: m.group(1) + str(Rn), t, count=1); n += 1
    return ''.join(lines), n


def validate(orig_g, new_text, opt, progress=None):
    """Returns (errors, metrics). Any error => do not use the output."""
    errs = []
    pv = progress or (lambda k, f=0.0, d='': None)
    try:
        ng = GcodeFile(new_text, progress=lambda k, f=0.0, d='': pv('verify', 0.4 * f))
    except Exception as ex:
        return ['output does not parse: %s' % ex], {}
    m = {}
    if len(ng.layer_starts) != len(orig_g.layer_starts):
        errs.append('layer count changed %d -> %d' % (len(orig_g.layer_starts), len(ng.layer_starts)))
    pre_o = orig_g.raw_lines[:orig_g.body_start]; pre_n = ng.raw_lines[:ng.body_start]
    if pre_o != pre_n: errs.append('start G-code / header changed')
    post_o = orig_g.raw_lines[orig_g.body_end:]; post_n = ng.raw_lines[ng.body_end:]
    if post_o != post_n: errs.append('end G-code changed')
    if orig_g.protected_signature() != ng.protected_signature():
        errs.append('protected blocks (timelapse/filament-change/firmware) changed')
    temp_o = [l.text for l in orig_g.lines if l.cmd in ('M104', 'M109', 'M140', 'M190', 'M141', 'M191')]
    temp_n = [l.text for l in ng.lines if l.cmd in ('M104', 'M109', 'M140', 'M190', 'M141', 'M191')]
    if temp_o != temp_n: errs.append('temperature commands changed')
    tot_dE = 0.0; max_layer_dE = 0.0; tot_E = 0.0
    fmax = 0.0; ratio_min = 9; ratio_max = 0; vol_viol = 0
    kin = Kinematics(orig_g)
    nlv = max(1, min(len(ng.layer_starts), len(orig_g.layer_starts)))
    for k in range(min(len(ng.layer_starts), len(orig_g.layer_starts))):
        pv('verify', 0.4 + 0.5 * k / nlv)
        a, b = orig_g.layer_range(k); c, d = ng.layer_range(k)
        eo = sum(l.e for l in orig_g.lines[a:b] if l.is_ext)
        en = sum(l.e for l in ng.lines[c:d] if l.is_ext)
        ao = sum(l.e for l in orig_g.lines[a:b] if l.e is not None)
        an = sum(l.e for l in ng.lines[c:d] if l.e is not None)
        tot_E += eo
        max_layer_dE = max(max_layer_dE, abs(eo - en), abs(ao - an))
        so = sorted((round(l.x, 3), round(l.y, 3), round(l.x0, 3), round(l.y0, 3), l.e) for l in orig_g.lines[a:b] if l.is_ext)
        sn = sorted((round(l.x, 3), round(l.y, 3), round(l.x0, 3), round(l.y0, 3), l.e) for l in ng.lines[c:d] if l.is_ext)
        if so != sn:
            errs.append('layer %d: set of extrusion moves changed' % (k + 1)); break
        for l in ng.lines[c:d]:
            if l.is_ext:
                if abs(l.r_before) > 2e-3:
                    errs.append('layer %d line %d: extruding while retracted (%.3f)' % (k + 1, l.i + 1, l.r_before)); break
                fmax = max(fmax, l.effF)
                if opt.max_vol:
                    vol = l.e * opt.fil_area / l.length * l.effF / 60
                    if vol > opt.max_vol * 1.0001 + 1e-9: vol_viol += 1
        if errs: break
    # per-segment feed ratio (matched by geometry so it also works after re-ordering)
    if not errs:
        key = lambda l: (l.layer, round(l.x, 3), round(l.y, 3), round(l.x0, 3), round(l.y0, 3), l.e)
        fo = {}; ao = {}
        for l in orig_g.lines:
            if l.is_ext and l.layer >= 0:
                fo.setdefault(key(l), []).append(l.effF); ao.setdefault(key(l), []).append(l.accel)
        from optimizer import ACCEL_FEATURES, ACCEL_MIN_LAYER
        feats = ACCEL_FEATURES.get(opt.st.goal, set()); acc_bad = 0; acc_up = 0
        for l in ng.lines:
            if l.is_ext and l.layer >= 0:
                lst = fo.get(key(l))
                if not lst: continue
                oa = ao[key(l)][0]
                if oa is not None and l.accel is not None and abs(l.accel - oa) > 0.5:
                    if l.feature in feats and l.layer >= ACCEL_MIN_LAYER and oa < l.accel <= kin.amax + 0.5:
                        acc_up += 1
                    else:
                        acc_bad += 1
                r = l.effF / lst[0]
                ratio_min = min(ratio_min, r); ratio_max = max(ratio_max, r)
        m['feed_ratio_min'] = round(ratio_min, 3); m['feed_ratio_max'] = round(ratio_max, 3)
        if ratio_max > opt.st.max_speedup + 1e-3: errs.append('feed raised beyond limit (%.3f)' % ratio_max)
        m['accel_raised_moves'] = acc_up
        if acc_bad: errs.append('acceleration changed on %d protected/visible extrusion moves' % acc_bad)
    if max_layer_dE > 1e-6: errs.append('extrusion per layer changed (max diff %.6f mm)' % max_layer_dE)
    if fmax > kin.vmax_xy * 60 + 1: errs.append('feedrate above machine limit')
    fans = [l.w.get('S', 0) for l in ng.lines if l.kind == 'fan' and l.cmd == 'M106' and l.layer >= 0]
    if fans and max(fans) > 255: errs.append('fan > 100%')
    # flow: only flag if output has MORE over-limit segments than the slicer's original
    vol_viol_o = 0
    if opt.max_vol:
        for l in orig_g.lines:
            if l.is_ext and l.layer >= 0 and l.e * opt.fil_area / l.length * l.effF / 60 > opt.max_vol * 1.0001: vol_viol_o += 1
        if vol_viol > vol_viol_o: errs.append('volumetric flow limit exceeded on %d segments' % (vol_viol - vol_viol_o))
    m.update({'layers': len(ng.layer_starts), 'total_extrusion_mm': round(tot_E, 4), 'max_layer_E_diff': max_layer_dE,
              'max_feed_mm_s': round(fmax / 60, 1), 'vol_over_limit_orig': vol_viol_o, 'vol_over_limit_new': vol_viol})
    return errs, m
