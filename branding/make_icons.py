#!/usr/bin/env python3
"""EmberCheck app icon: three original concepts, hand-authored as SVG (no third-party marks), rendered to PNG/ICO.

usage:  python3 branding/make_icons.py              # concepts + the default (concept in branding/DEFAULT)
        python3 branding/make_icons.py --default b  # switch the app icon to concept b ("layers") and rebuild
Outputs
  branding/concepts/<id>-<name>/icon.svg, icon_small.svg (16 px variant), icon_<16|24|32>.svg where a concept has size-specific versions, icon_256.png, preview_16_32.png
  branding/concepts/overview.png                           all three side by side
  branding/embercheck.svg, embercheck_small.svg            the chosen concept
  branding/png/embercheck_<size>.png                       16 24 32 48 64 128 256
  packaging/icon.ico                                       exe + installer + shortcuts (all 7 sizes)
  src/assets/embercheck_<16|32|48|256>.png, embercheck.ico Tk iconphoto / iconbitmap for the card and progress window
Needs cairosvg (pip install cairosvg) and Pillow."""
import io, os, struct, sys
import cairosvg
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
SIZES = [16, 24, 32, 48, 64, 128, 256]

# shared shapes (viewBox 0 0 256 256)
FLAME = ('M128 22 C146 62 198 88 198 150 C198 198 166 230 128 230 C90 230 58 198 58 150 C58 114 80 92 96 68 '
         'C100 92 108 106 121 113 C116 82 118 50 128 22 Z')
FLAME_SIMPLE = 'M128 18 C160 66 204 96 204 152 C204 202 170 234 128 234 C86 234 52 202 52 152 C52 96 100 70 128 18 Z'
FLAME2 = ('M128 20 C136 54 170 78 188 108 C202 132 204 156 198 176 C188 210 160 232 128 232 C94 232 64 208 58 172 '
          'C54 146 64 124 80 108 C84 128 94 140 106 146 C100 118 104 72 128 20 Z')
CORE = ('M128 112 C142 134 164 148 164 174 C164 198 148 214 128 214 C108 214 92 198 92 176 C92 158 104 148 112 138 '
        'C116 150 122 156 128 158 C124 140 124 126 128 112 Z')
GRAD = '''<linearGradient id="heat" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#ffd166"/><stop offset="0.45" stop-color="#ff8a1f"/><stop offset="1" stop-color="#d7263d"/></linearGradient>'''
TILE_BG = '''<linearGradient id="tile" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#26272d"/><stop offset="1" stop-color="#141519"/></linearGradient>
<radialGradient id="glow" cx="0.5" cy="0.78" r="0.55"><stop offset="0" stop-color="#ff7a1a" stop-opacity="0.55"/><stop offset="1" stop-color="#ff7a1a" stop-opacity="0"/></radialGradient>'''


def svg(body, defs=''):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">'
            '<defs>%s</defs>%s</svg>' % (defs, body))


def tile(small):
    r = 56 if small else 52
    return ('<rect x="8" y="8" width="240" height="240" rx="%d" fill="url(#tile)"/>' % r +
            ('' if small else '<rect x="8" y="8" width="240" height="240" rx="%d" fill="url(#glow)"/>' % r))


# --- concept a: "flame check" - heat-gradient flame with a check mark cut through it -------------------------------
def concept_a(small=False, size=None):
    if small:   # 16/24 px: no notch, no core, very bold check, tile with no glow
        body = (tile(True) + '<path d="%s" fill="url(#heat)"/>' % FLAME2 +
                '<path d="M78 150 L116 188 L182 112" fill="none" stroke="#fff4e0" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>')
    else:
        body = (tile(False) + '<path d="%s" fill="url(#heat)"/>' % FLAME +
                '<path d="%s" fill="#ffd98a" opacity="0.55"/>' % CORE +
                '<path d="M86 160 L118 192 L176 126" fill="none" stroke="#7a1020" stroke-width="24" stroke-linecap="round" stroke-linejoin="round" opacity="0.45"/>'
                '<path d="M86 156 L118 188 L176 122" fill="none" stroke="#fff4e0" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>')
    return svg(body, GRAD + TILE_BG)


# --- concept b: "layers" - flame built from printed layer lines, heat-mapped, with a check badge ---------------------
SMALL_B = 32    # sizes up to this get the simplified, pixel-aligned version; 48+ use the full design


def _stripes(size, period_px, bar_px, first_px, last_px):
    """Layer lines snapped to the pixel grid of the target size (viewBox units = 256 / size per pixel)."""
    u = 256.0 / size
    return ''.join('<rect x="0" y="%.3f" width="256" height="%.3f"/>' % (y * u, bar_px * u)
                   for y in range(first_px, last_px, period_px))


def concept_b(small=False, size=None):
    if size is not None and size <= SMALL_B:
        return concept_b_small(size)
    lines = ''.join('<rect x="0" y="%d" width="256" height="11"/>' % y for y in range(14, 240, 16))
    clip = '<clipPath id="layers">%s</clipPath>' % lines
    badge = ('<circle cx="184" cy="188" r="44" fill="#141519"/><circle cx="184" cy="188" r="34" fill="#fff4e0"/>'
             '<path d="M166 189 L180 203 L203 175" fill="none" stroke="#d7263d" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/>')
    body = tile(False) + '<g clip-path="url(#layers)"><path d="%s" fill="url(#heat)"/></g>' % FLAME2 + badge
    return svg(body, GRAD + TILE_BG + clip)


# 16 px check mark drawn as exact pixels (x, y) so it stays sharp: a 2-px-thick tick inside the badge disc
CHECK16 = '<g fill="#a3122a" shape-rendering="crispEdges">%s</g>' % ''.join(
    '<rect x="%d" y="%d" width="16" height="16"/>' % (x * 16, y * 16)
    for x, y in [(14, 9), (13, 10), (14, 10), (9, 11), (12, 11), (13, 11), (9, 12), (10, 12), (11, 12), (12, 12), (10, 13), (11, 13)])


def concept_b_small(size):
    """16-32 px: fewer, thicker layer lines on the pixel grid (3 px line + 1 px gap at 16; 4 + 1 at 24; 5 + 2 at 32),
    a slightly larger flame, and a bigger, higher-contrast badge. Below 24 px the badge ring is dropped: a solid cream
    disc with a dark-red check sits directly on the red base of the flame."""
    period, bar = {16: (4, 3), 24: (5, 4), 32: (7, 5)}.get(size, (max(4, round(size / 4.5)), max(3, round(size / 6))))
    lines = _stripes(size, period, bar, 1, size)
    clip = '<clipPath id="layers">%s</clipPath>' % lines
    if size < 24:   # 16 px: disc and check snapped to the pixel grid (1 px = 16 units), flame moved up/left to keep it visible
        flame = '<g transform="translate(108 120) scale(1.12) translate(-128 -126)"><path d="%s" fill="url(#heat)"/></g>' % FLAME2
        badge = ('<circle cx="184" cy="184" r="64" fill="#fff4e0"/>'
                 + CHECK16)
    else:
        flame = '<g transform="translate(118 132) scale(1.12) translate(-128 -126)"><path d="%s" fill="url(#heat)"/></g>' % FLAME2
    if size >= 24:
        badge = ('<circle cx="182" cy="184" r="66" fill="#141519"/><circle cx="182" cy="184" r="54" fill="#fff4e0"/>'
                 '<path d="M152 186 L175 209 L212 164" fill="none" stroke="#b5172c" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/>')
    body = tile(True) + '<g clip-path="url(#layers)">%s</g>' % flame + badge
    return svg(body, GRAD + TILE_BG + clip)


# --- concept c: "heat check" - a bold heat-gradient check mark whose long arm ends in a small flame -------------------
def concept_c(small=False, size=None):
    hg = '''<linearGradient id="heatx" x1="0" y1="1" x2="1" y2="0">
  <stop offset="0" stop-color="#d7263d"/><stop offset="0.55" stop-color="#ff8a1f"/><stop offset="1" stop-color="#ffd166"/></linearGradient>'''
    if small:
        body = (tile(True) +
                '<path d="M58 140 L106 188 L196 82" fill="none" stroke="url(#heatx)" stroke-width="46" stroke-linecap="round" stroke-linejoin="round"/>'
                '<path d="M196 30 C214 56 226 70 226 90 C226 108 212 120 196 120 C180 120 166 108 166 90 C166 70 182 56 196 30 Z" fill="#ffd166"/>')
    else:
        lines = ''.join('<rect x="0" y="%d" width="256" height="3" fill="#000" opacity="0.18"/>' % y for y in range(20, 240, 12))
        body = (tile(False) +
                '<path d="M64 140 L108 184 L190 90" fill="none" stroke="url(#heatx)" stroke-width="38" stroke-linecap="round" stroke-linejoin="round"/>'
                '<path d="M72 136 L108 172 L186 82" fill="none" stroke="#ffe7a8" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" opacity="0.35"/>' +
                '<path d="M192 26 C206 48 222 62 222 84 C222 102 208 116 192 116 C176 116 162 102 162 84 C162 70 170 62 176 52 '
                'C178 62 182 68 188 70 C186 56 186 42 192 26 Z" fill="url(#heat)"/>'
                '<path d="M192 64 C198 74 206 80 206 92 C206 102 200 108 192 108 C184 108 178 102 178 94 C178 86 184 80 192 64 Z" fill="#ffe7a8"/>')
        hg += ('<clipPath id="check"><path d="M64 140 L108 184 L190 90" fill="none" stroke="#000" stroke-width="38" '
               'stroke-linecap="round" stroke-linejoin="round"/></clipPath>')
    return svg(body, GRAD + TILE_BG + hg)


CONCEPTS = [('a', 'flame-check', concept_a), ('b', 'layers', concept_b), ('c', 'heat-check', concept_c)]


def render(svg_text, size):
    return Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg_text.encode(), output_width=size, output_height=size))).convert('RGBA')


def svg_for(fn, s):
    """The design used at s px: concepts may have size-specific small versions (b has 16/24/32 variants)."""
    return fn(s <= 24, size=s)


def icon_images(fn):
    return {s: render(svg_for(fn, s), s) for s in SIZES}


def write_ico(path, imgs):
    """ICO with one PNG-compressed entry per size (Windows Vista+ reads PNG entries at every size)."""
    data = []
    for s in sorted(imgs):
        b = io.BytesIO(); imgs[s].save(b, 'PNG'); data.append((s, b.getvalue()))
    out = io.BytesIO(); out.write(struct.pack('<HHH', 0, 1, len(data)))
    off = 6 + 16 * len(data)
    for s, d in data:
        out.write(struct.pack('<BBBBHHII', s % 256, s % 256, 0, 0, 1, 32, len(d), off)); off += len(d)
    for _, d in data:
        out.write(d)
    with open(path, 'wb') as f:
        f.write(out.getvalue())


def font(sz):
    for f in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def preview_strip(imgs, title):
    """16 and 32 px at real size on dark and light backgrounds, plus 8x / 4x zoom (nearest) to judge the pixels."""
    W, H = 520, 200
    im = Image.new('RGBA', (W, H), '#2b2c31'); d = ImageDraw.Draw(im)
    d.rectangle([0, 100, W, H], fill='#f2f2f2')
    d.text((10, 6), title, fill='#ffffff', font=font(14))
    for row, y in ((0, 40), (1, 140)):
        im.alpha_composite(imgs[16], (16, y)); im.alpha_composite(imgs[24], (42, y - 4)); im.alpha_composite(imgs[32], (76, y - 8))
    z16 = imgs[16].resize((128, 128), Image.NEAREST); z32 = imgs[32].resize((128, 128), Image.NEAREST)
    im.alpha_composite(z16, (240, 36)); im.alpha_composite(z32, (380, 36))
    d.text((240, 168), '16 px x8', fill='#333', font=font(12)); d.text((380, 168), '32 px x4', fill='#333', font=font(12))
    d.text((14, 74), '16 / 24 / 32 on dark', fill='#bbb', font=font(11)); d.text((14, 176), 'on light', fill='#555', font=font(11))
    return im


def main():
    default = (sys.argv[sys.argv.index('--default') + 1] if '--default' in sys.argv else
               open(os.path.join(HERE, 'DEFAULT')).read().strip() if os.path.exists(os.path.join(HERE, 'DEFAULT')) else 'a').lower()
    cdir = os.path.join(HERE, 'concepts'); os.makedirs(cdir, exist_ok=True)
    overview = Image.new('RGBA', (3 * 300, 360), '#1f2024'); od = ImageDraw.Draw(overview)
    chosen = None
    for i, (cid, name, fn) in enumerate(CONCEPTS):
        d = os.path.join(cdir, '%s-%s' % (cid, name)); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, 'icon.svg'), 'w').write(fn(False)); open(os.path.join(d, 'icon_small.svg'), 'w').write(svg_for(fn, 16))
        for sz in (16, 24, 32):
            f = os.path.join(d, 'icon_%d.svg' % sz)
            if svg_for(fn, sz) != svg_for(fn, 48 if sz == 32 else 16) or sz == 16:
                open(f, 'w').write(svg_for(fn, sz))
            elif os.path.exists(f):
                os.remove(f)
        imgs = icon_images(fn)
        imgs[256].save(os.path.join(d, 'icon_256.png'))
        preview_strip(imgs, 'Concept %s - %s' % (cid.upper(), name)).save(os.path.join(d, 'preview_16_32.png'))
        overview.alpha_composite(imgs[256], (22 + 300 * i, 20))
        overview.alpha_composite(imgs[16], (40 + 300 * i, 300)); overview.alpha_composite(imgs[32], (70 + 300 * i, 292))
        overview.alpha_composite(imgs[48], (116 + 300 * i, 284))
        od.text((180 + 300 * i, 296), '%s  %s%s' % (cid.upper(), name, '  (default)' if cid == default else ''), fill='#ddd', font=font(13))
        if cid == default:
            chosen = (cid, name, fn, imgs)
    overview.save(os.path.join(cdir, 'overview.png'))
    cid, name, fn, imgs = chosen
    open(os.path.join(HERE, 'DEFAULT'), 'w').write(cid + '\n')
    open(os.path.join(HERE, 'embercheck.svg'), 'w').write(fn(False))
    open(os.path.join(HERE, 'embercheck_small.svg'), 'w').write(svg_for(fn, 16))
    for sz in (24, 32):
        f = os.path.join(HERE, 'embercheck_%d.svg' % sz)
        if svg_for(fn, sz) not in (fn(False), svg_for(fn, 16)):
            open(f, 'w').write(svg_for(fn, sz))
        elif os.path.exists(f):
            os.remove(f)
    pdir = os.path.join(HERE, 'png'); os.makedirs(pdir, exist_ok=True)
    for s, im in imgs.items():
        im.save(os.path.join(pdir, 'embercheck_%d.png' % s))
    write_ico(os.path.join(ROOT, 'packaging', 'icon.ico'), imgs)
    adir = os.path.join(ROOT, 'src', 'assets'); os.makedirs(adir, exist_ok=True)
    for s in (16, 20, 24, 32, 40, 48, 64, 256):     # window icons + the in-window logo at each display scale
        (imgs[s] if s in imgs else render(svg_for(fn, s), s)).save(os.path.join(adir, 'embercheck_%d.png' % s))
    write_ico(os.path.join(adir, 'embercheck.ico'), imgs)
    print('default icon: concept %s (%s) -> packaging/icon.ico, src/assets/, branding/png/' % (cid, name))


if __name__ == '__main__':
    main()
