"""EmberCheck stamp: a comment block near the top of the optimized G-code that says what EmberCheck did, plus the SHA-256 of the
rest of the file, so anyone can check that the file Bambu Studio prints/exports is exactly the one EmberCheck wrote.

Placement: directly after Bambu's '; HEADER_BLOCK_END' line (before the thumbnail/config blocks), or at the top if a
file has no header block. Only ';' comment lines, ASCII, < 200 characters each: printers ignore them, and Bambu's
header block, thumbnails and config block are left byte-identical.

body_sha256 = SHA-256 of the UTF-8 file with the block (from '; EMBERCHECK_BLOCK_START' to '; EMBERCHECK_BLOCK_END', both
lines with their line endings) removed. Check: EmberCheck.exe --check-stamp file.gcode(.3mf)  /  docs/verify.md."""
import hashlib, re, zipfile

BEGIN = '; EMBERCHECK_BLOCK_START'
END = '; EMBERCHECK_BLOCK_END'
_BLOCK_RE = re.compile(r'^; EMBERCHECK_BLOCK_START[^\n]*\n(?:.*\n)*?; EMBERCHECK_BLOCK_END[^\n]*(?:\r?\n|$)', re.M)


def strip(text):
    """(text without the EmberCheck block, block text or None)."""
    m = _BLOCK_RE.search(text)
    if not m:
        return text, None
    return text[:m.start()] + text[m.end():], m.group(0)


def body_sha256(text_without_block):
    return hashlib.sha256(text_without_block.encode('utf-8', errors='surrogateescape')).hexdigest()


def _ascii(s):
    s = (s.replace('\u2192', '->').replace('\u2212', '-').replace('\u2013', '-').replace('\u2014', '-')
          .replace('&rarr;', '->').replace('&sup2;', '2').replace('&sup3;', '3'))
    s = re.sub(r'<[^>]+>', '', s)
    return s.encode('ascii', 'replace').decode('ascii').replace('\r', ' ').replace('\n', ' ')[:190]


def insert(text, lines):
    """Insert the block (lines = text lines without the leading '; ') and return the stamped text.
    An existing EmberCheck block is replaced."""
    text, _ = strip(text)
    h = body_sha256(text)
    nl = '\r\n' if '\r\n' in text[:2000] else '\n'
    body = [BEGIN] + ['; ' + _ascii(l) for l in lines] + ['; body_sha256: ' + h, END]
    block = nl.join(body) + nl
    m = re.search(r'^; HEADER_BLOCK_END[^\n]*\n', text, re.M)
    pos = m.end() if m and m.start() < 20000 else 0
    return text[:pos] + block + text[pos:]


def fields(block):
    out = {}
    for ln in (block or '').splitlines():
        mm = re.match(r';\s*([a-z_0-9 ]+?):\s*(.*)$', ln)
        if mm:
            out.setdefault(mm.group(1).strip(), mm.group(2).strip())
    return out


def check_text(text):
    """(ok, message) for one G-code text."""
    rest, block = strip(text)
    if block is None:
        return False, 'No EmberCheck stamp found: this G-code was not written by EmberCheck 1.4.2+ (or the stamp was removed).'
    f = fields(block)
    want = f.get('body_sha256', '')
    got = body_sha256(rest)
    first = next((l[2:] for l in block.splitlines()[1:] if l.startswith('; ')), 'EmberCheck')
    if want and want == got:
        return True, 'Stamp OK - %s. The G-code is exactly what it wrote (body SHA-256 %s...).%s' % (
            first, got[:16], (' Print time: %s.' % f['print time']) if f.get('print time') else '')
    return False, ('Stamp found (%s) but the G-code was changed after it was written (body SHA-256 %s... expected %s...).'
                   % (first, got[:16], want[:16]))


def check_file(path):
    if path.lower().endswith('.3mf'):
        msgs = []; ok = True
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if re.match(r'Metadata/plate_\d+\.gcode$', n)]
            if not names:
                return False, 'No sliced G-code (Metadata/plate_N.gcode) in %s.' % path
            for n in names:
                data = z.read(n)
                o, m = check_text(data.decode('utf-8', errors='surrogateescape'))
                md5n = n + '.md5'
                if md5n in z.namelist():
                    if z.read(md5n).decode('ascii', 'replace').strip().upper() != hashlib.md5(data).hexdigest().upper():
                        o = False; m += ' The plate MD5 in the 3MF does not match its G-code.'
                ok = ok and o; msgs.append('%s: %s' % (n, m))
        return ok, '\n'.join(msgs)
    with open(path, 'r', encoding='utf-8', errors='surrogateescape', newline='') as f:
        return check_text(f.read())
