"""Self-contained HTML report (inline SVG, no internet needed)."""
import html, math, datetime
from gcode_model import estimate_times

def _mb(n):
    return '%.1f MB' % (n / 1e6)


def fmt_t(s):
    s = int(round(s)); h, r = divmod(s, 3600); m, sec = divmod(r, 60)
    return ('%dh %02dm %02ds' % (h, m, sec)) if h else ('%dm %02ds' % (m, sec))

def color(T, lo, hi):
    # blue (cold) -> green (ideal) -> red (hot)
    if T is None: return '#888'
    mid = (lo + hi) / 2
    if T <= mid:
        f = max(0.0, min(1.0, (T - (lo - 15)) / (mid - (lo - 15))))
        r, g, b = int(40 + 20 * f), int(90 + 150 * f), int(230 - 170 * f)
    else:
        f = max(0.0, min(1.0, (T - mid) / ((hi + 10) - mid)))
        r, g, b = int(60 + 190 * f), int(240 - 190 * f), int(60 - 20 * f)
    return '#%02x%02x%02x' % (r, g, b)

def line_chart(series, w=900, h=260, ylab='', band=None, hlines=(), title=''):
    xs = [x for s in series for x, _ in s['pts']]; ys = [y for s in series for _, y in s['pts'] if y is not None]
    if band: ys += list(band)
    ys += [v for v, _ in hlines]
    if not xs or not ys: return '<p>(no data)</p>'
    x0, x1 = min(xs), max(xs) or 1; y0, y1 = min(ys), max(ys)
    pad = (y1 - y0) * 0.08 or 1; y0 = (y0 - pad) if (y0 - pad) > 0 or y0 < 0 else 0; y1 += pad
    L, R, T, B = 55, 10, 25, 30
    X = lambda x: L + (x - x0) / ((x1 - x0) or 1) * (w - L - R)
    Y = lambda y: T + (1 - (y - y0) / ((y1 - y0) or 1)) * (h - T - B)
    o = ['<svg viewBox="0 0 %d %d" class="chart">' % (w, h), '<text x="%d" y="16" class="ct">%s</text>' % (L, html.escape(title))]
    if band:
        o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#2e7d3222"/>' % (L, Y(band[1]), w - L - R, Y(band[0]) - Y(band[1])))
    for k in range(6):
        yv = y0 + (y1 - y0) * k / 5
        o.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#ddd"/><text x="%d" y="%.1f" class="ax" text-anchor="end">%.0f</text>' % (L, w - R, Y(yv), Y(yv), L - 4, Y(yv) + 4, yv))
    for k in range(6):
        xv = x0 + (x1 - x0) * k / 5
        o.append('<text x="%.1f" y="%d" class="ax" text-anchor="middle">%.0f</text>' % (X(xv), h - 10, xv))
    for v, lab in hlines:
        o.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#c62828" stroke-dasharray="4 3"/><text x="%d" y="%.1f" class="ax" fill="#c62828">%s</text>' % (L, w - R, Y(v), Y(v), w - R - 120, Y(v) - 3, html.escape(lab)))
    for s in series:
        pts = ' '.join('%.1f,%.1f' % (X(x), Y(y)) for x, y in s['pts'] if y is not None)
        o.append('<polyline fill="none" stroke="%s" stroke-width="%s" %s points="%s"/>' % (s['color'], s.get('w', 1.5), 'stroke-dasharray="5 3"' if s.get('dash') else '', pts))
    lx = L + 10
    for s in series:
        o.append('<rect x="%d" y="%d" width="14" height="3" fill="%s"/><text x="%d" y="%d" class="ax">%s</text>' % (lx, h - T - B + 10, s['color'], lx + 18, h - T - B + 14, html.escape(s['name'])))
        lx += 30 + 7 * len(s['name'])
    o.append('<text x="12" y="%d" class="ax" transform="rotate(-90 12 %d)">%s</text></svg>' % (h // 2, h // 2, html.escape(ylab)))
    return ''.join(o)

def side_heatmap(opt, evs, title, w=430, h=330):
    lo, hi = opt.mat['t_low'], opt.mat['t_high']
    xs = [ii['xmin'] for d in opt.L for ii in d['islands']] + [ii['xmax'] for d in opt.L for ii in d['islands']]
    if not xs: return ''
    x0, x1 = min(xs), max(xs); z1 = max(opt.g.layer_z) or 1
    L, R, T, B = 35, 10, 22, 22
    sx = (w - L - R) / ((x1 - x0) or 1); sz = (h - T - B) / z1
    s = min(sx, sz)
    o = ['<svg viewBox="0 0 %d %d" class="hm"><text x="%d" y="15" class="ct">%s</text>' % (w, h, L, html.escape(title))]
    for k, d in enumerate(opt.L):
        z = opt.g.layer_z[k]; lh = max(opt.g.layer_h[k], 0.05)
        for ii, iv in zip(d['islands'], evs[k].isl):
            T_ = iv[3]
            o.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="%s"><title>layer %d  T=%s</title></rect>' % (
                L + (ii['xmin'] - x0) * s, h - B - z * s, max((ii['xmax'] - ii['xmin']) * s, 0.5), max(lh * s, 0.6), color(T_, lo, hi), k + 1,
                ('%.0f C' % T_) if T_ is not None else 'n/a'))
    o.append('<text x="%d" y="%d" class="ax">X (mm) &#8594; side view, colour = predicted interlayer temp</text>' % (L, h - 5))
    o.append('</svg>')
    return ''.join(o)

def legend(lo, hi):
    cells = ''.join('<span style="background:%s"></span>' % color(t, lo, hi) for t in range(int(lo - 15), int(hi + 12), 3))
    return '<div class="lg">%d&deg;C (too cold) %s %d&deg;C (too hot) &nbsp; window %d&ndash;%d&deg;C</div>' % (lo - 15, cells, hi + 10, lo, hi)

def time_breakdown(opt):
    g = opt.g
    body = g.lines[g.body_start:g.body_end]
    d, sp = estimate_times(body, opt.kin)
    cat = {'Extrusion (cruise)': 0.0, 'Extrusion accel/decel loss': 0.0, 'Travel': 0.0, 'Retract / Z / lift': 0.0, 'Dwell / waits': 0.0}
    flow_lim = 0.0; ext_t = 0.0
    for ln, t, v in zip(body, d, sp):
        if ln.kind == 'motion':
            if ln.is_ext:
                cruise = ln.length / v if v > 0 else t
                cat['Extrusion (cruise)'] += min(cruise, t); cat['Extrusion accel/decel loss'] += max(0.0, t - cruise)
                ext_t += t
                if opt.flow_cap_F(ln) <= ln.effF * 1.02: flow_lim += t
            elif ln.is_travel: cat['Travel'] += t
            else: cat['Retract / Z / lift'] += t
        elif t: cat['Dwell / waits'] += t
    return cat, flow_lim, ext_t

def _layer_list(ks, n=8):
    ks = list(ks); s = ', '.join(str(k) for k in ks[:n])
    return s + (' and %d more' % (len(ks) - n) if len(ks) > n else '')


def recommendations(opt, summary):
    g = opt.g; c = g.cfg; recs = []
    mat = opt.mat_name
    hot = summary['hot_before']; cold = summary['cold_before']
    goal = summary.get('goal'); left = summary.get('hot_after', 0)
    if goal in ('speed', 'balanced') and left and summary.get('budget_kept_hot'):
        recs.append(('Goal', '%s goal keeps print time %s, so %d layers predicted too hot were left as they are (layers %s). Use the <b>%s</b> preset for this print to fix them, or apply the cooling settings below.' % (
            goal.capitalize(), 'at or below the original' if goal == 'speed' else 'within +2%', left,
            _layer_list([i + 1 for i, e in enumerate(opt.opt) if e.Tmax is not None and e.Tmax > opt.mat['t_high']]),
            'AI Balanced or AI Quality' if goal == 'speed' else 'AI Quality')))
    if hot:
        need = summary.get('hot_layer_time_needed')
        recs.append(('Cooling / min layer time', 'Bambu Studio &rsaquo; Filament &rsaquo; Cooling: <b>Slow printing down for better layer cooling</b> (slow_down_layer_time) is %gs. %d layers are predicted too hot. Raising it%s, printing 2+ copies at once, or adding a sacrificial "cooling tower" next to small parts fixes this at the source.' % (
            c('slow_down_layer_time', 0), hot, (' to ~%ds' % need) if need else '')))
        if mat in ('PLA', 'PETG', 'TPU') and opt.fan_max_cfg < 80:
            recs.append(('Fan', 'Max fan speed (fan_max_speed) is %g%%. For %s small/hot features, 80-100%% (PLA) or 60-70%% (PETG) helps.' % (opt.fan_max_cfg, mat)))
    if cold and opt.mat['cold_matters']:
        recs.append(('Chamber / cold layers', '%d layers are predicted too cold for %s (weak bonding / warping risk on big layers). Close the door/lid and pre-heat the chamber%s; lower <b>Min fan speed</b> (fan_min_speed, now %g%%) and consider raising <b>fan_cooling_layer_time</b> threshold carefully.' % (
            cold, mat, ' (set Filament &rsaquo; Chamber temperature if your printer heats the chamber)' if c('support_chamber_temp_control', 0) else '', opt.fan_min_cfg)))
    tr = opt.travel
    if tr['moves'] and tr['open_air'] > 0.1 * tr['moves'] and not c('reduce_crossing_wall', 0):
        recs.append(('Stringing / travel', '%d of %d travels (%.0f mm total) cross open air. Enable <b>Avoid crossing wall</b> (Process &rsaquo; Others; reduce_crossing_wall) so travels stay inside the part, which this post-processor cannot safely re-route.' % (tr['open_air'], tr['moves'], tr['open_air_len'])))
    if tr['open_air_unretracted']:
        recs.append(('Retraction', '%d open-air travels happen without retraction. Check Filament &rsaquo; Setting overrides &rsaquo; Retraction (length %g mm) and that "Retract when changing layer"/wipe are on. Use --fix-strings to add retractions here.' % (tr['open_air_unretracted'], opt.ret_len)))
    if tr['inside_lifted'] > 50 and c('z_hop', 0) > 0:
        recs.append(('Z-hop', '%d travels that stay fully inside the part still retract + z-hop (%g mm, %s). If the top surfaces look fine, set <b>Z-hop type</b> to Slope/Spiral and "Z-hop when retracting" only above top surfaces, or reduce z_hop to 0.2-0.4 mm to save time.' % (tr['inside_lifted'], c('z_hop', 0), g.config.get('z_hop_types', '?'))))
    ov = getattr(opt, 'ov_stats', None)
    if ov and (ov['b3'] + ov['b4']) > 0:
        recs.append(('Overhangs', '%d wall segments are >50%% unsupported but not marked as overhangs by the slicer. Keep <b>Detect overhang wall</b> and <b>Slow down for overhang</b> on (currently %s/%s); consider supports or a 45&deg; chamfer for these areas.' % (ov['b3'] + ov['b4'], int(c('detect_overhang_wall', 0)), int(c('enable_overhang_speed', 0)))))
    if ov and ov['bridge_low_fan']:
        recs.append(('Bridges', '%d bridge segments print with less than the overhang fan speed. Raise Filament &rsaquo; Cooling &rsaquo; <b>Overhang/bridge fan</b> (overhang_fan_speed, now %g%%).' % (ov['bridge_low_fan'], opt.ov_fan_cfg)))
    fl = summary.get('flow_limited_share', 0)
    if fl > 0.25:
        recs.append(('Flow limit', '%.0f%% of extrusion time is already at the filament max volumetric speed (%g mm&sup3;/s), so faster motion cannot help there. A High-Flow hotend (the H2S profile lists Direct Drive High Flow variants) with a matching filament profile is the only way to go faster.' % (fl * 100, opt.max_vol)))
    acc = summary.get('accel_share', 0)
    if acc > 0.25:
        recs.append(('Short segments', '%.0f%% of extrusion time is acceleration-limited (many short moves). Larger infill pattern spacing, Gyroid/"Cross hatch" sparse infill, or fewer walls on tiny features give more real speed than higher mm/s settings.' % (acc * 100)))
    rs = getattr(opt, 'reorder_stats', None)
    if rs and rs['travel_before'] and (rs['travel_before'] - rs['travel_after']) > 0.05 * rs['travel_before']:
        recs.append(('Travel order', 'Re-ordering infill islands would cut %.0f mm of travel (%.0f%%). Run with --reorder to apply.' % (rs['travel_before'] - rs['travel_after'], 100 * (1 - rs['travel_after'] / rs['travel_before']))))
    if c('wall_sequence', None, num=False) and 'outer wall/inner wall' in g.config.get('wall_sequence', '') and ov and (ov['b2'] + ov['b3'] + ov['b4']) > 20:
        recs.append(('Wall order', 'Outer-before-inner wall order makes overhangs worse; use inner/outer (or inner-outer-inner) for parts with overhangs.'))
    if not recs:
        recs.append(('Slicer settings', 'Nothing important to change in the slicer for this print.'))
    return recs

CSS = '''body{font-family:Segoe UI,Arial,sans-serif;margin:24px;max-width:1000px;color:#222}h1{font-size:22px}h2{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd}
.kpi{display:flex;flex-wrap:wrap;gap:10px}.kpi div{background:#f4f6f8;border-radius:8px;padding:10px 14px;min-width:150px}.kpi b{display:block;font-size:19px}
table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #ddd;padding:3px 8px;text-align:right}th{background:#f4f6f8}td.l,th.l{text-align:left}
.chart{width:100%;height:auto;background:#fff;border:1px solid #eee}.hm{width:49%;height:auto;border:1px solid #eee}.ct{font-size:13px;font-weight:600}.ax{font-size:10px;fill:#555}
.lg span{display:inline-block;width:10px;height:10px}.lg{font-size:12px;margin:4px 0}.warn{background:#fff4e5;padding:8px;border-left:4px solid #f0a020}.ok{background:#e8f5e9;padding:8px;border-left:4px solid #2e7d32}.bad{background:#fdecea;padding:8px;border-left:4px solid #c62828}
small{color:#666}'''

def build(opt, summary, validation, applied, src_name, settings_desc):
    lo, hi = opt.mat['t_low'], opt.mat['t_high']
    base, new = opt.base, opt.opt
    nl = opt.nl
    o = ['<!doctype html><html><head><meta charset="utf-8"><title>Print Optimizer report - %s</title><style>%s</style></head><body>' % (html.escape(src_name), CSS)]
    o.append('<h1>Bambu Print Optimizer report</h1><p><b>%s</b><br><small>%s &middot; generated %s &middot; %s</small></p>' % (
        html.escape(src_name), html.escape(opt.g.config.get('printer_model', 'unknown printer')), datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), html.escape(settings_desc)))
    if validation['errors']:
        o.append('<p class="bad"><b>Optimised G-code was NOT written</b> - safety check failed: %s. Your file is unchanged.</p>' % html.escape('; '.join(validation['errors'])))
    elif not applied:
        o.append('<p class="warn">Report-only (dry run): no changes were written.</p>')
    else:
        o.append('<p class="ok">Optimised G-code written and verified: same layers, same extrusion per layer, start/end/AMS/timelapse blocks untouched.</p>')
    k = summary
    o.append('<div class="kpi">')
    for lab, val in [('Material (model preset)', '%s%s' % (opt.mat_name, ' (guessed)' if opt.mat_guess else '')),
                     ('Chamber assumed', '%g&deg;C' % opt.T_env),
                     ('Slicer time estimate', html.escape(k['bambu_time'] or 'n/a')),
                     ('Our model: before', fmt_t(k['t_before'])), ('Our model: after', fmt_t(k['t_after'])),
                     ('Time change', '%+.1f%% (%s)' % (k['dt_pct'], ('-' if k['t_after'] < k['t_before'] else '+') + fmt_t(abs(k['t_before'] - k['t_after'])))),
                     ('Of which acceleration', '-%s (%.1f%%, %d layers, up to %d mm/s&sup2;)' % (
                         fmt_t(k.get('acc_saved_s', 0.0)), k.get('acc_saved_pct', 0.0), k.get('acc_layers', 0), k.get('acc_target_max', 0))
                      if k.get('acc_saved_s') else 'unchanged'),
                     ('Of which travel order', ('-%s (%.0f mm less travel, %d runs)' % (fmt_t(k.get('travel_saved_s', 0.0)),
                         k.get('travel_saved_mm', 0.0), k.get('reorder_runs', 0))) if k.get('reorder_runs') else 'unchanged'),
                     ('Of which hop/retract skip', ('-%s (%d Z-hops, %d retracts skipped)' % (fmt_t(k.get('hop_saved_s', 0.0)),
                         k.get('hops_skipped', 0), k.get('retracts_skipped', 0))) if k.get('hops_skipped') or k.get('retracts_skipped') else 'unchanged'),
                     ('Arc fitting', ('%d arcs replace %d moves' % (k.get('arcs', 0), k.get('arc_segments', 0))) if k.get('arcs_on')
                      else 'off (%s)' % html.escape(k.get('arcs_note') or 'off')),
                     ('G-code size / M204 lines', '%s &rarr; %s / %d &rarr; %d' % (_mb(k.get('bytes_before', 0)), _mb(k.get('bytes_after', 0)),
                         k.get('m204_before', 0), k.get('m204_after', 0))),
                     ('Goal', html.escape((k.get('goal') or '?').capitalize()) + (
                         ' (limit: not slower)' if k.get('time_budget_pct') == 0 else
                         (' (limit: +%g%%)' % k['time_budget_pct'] if k.get('time_budget_pct') else ' (no time limit)'))),
                     ('Hot layers', '%d &rarr; %d' % (k['hot_before'], k['hot_after'])),
                     ('Cold layers', '%d &rarr; %d%s' % (k['cold_before'], k['cold_after'], '' if opt.mat['cold_matters'] else ' (info)'))]:
        o.append('<div>%s<b>%s</b></div>' % (lab, val))
    o.append('</div><p><small>Temperatures are from a simplified, uncalibrated thermal model (not a physics simulation) - use them to compare layers and before/after, not as measured values. Time values come from our own motion estimate; the printer may differ by a few %.</small></p>')
    xs = list(range(1, nl + 1))
    o.append('<h2>Predicted interlayer temperature</h2>')
    o.append(line_chart([
        {'name': 'hottest island - before', 'color': '#f4a3a3', 'pts': list(zip(xs, [e.Tmax for e in base]))},
        {'name': 'hottest island - after', 'color': '#c62828', 'pts': list(zip(xs, [e.Tmax for e in new])), 'w': 2},
        {'name': 'area average - before', 'color': '#9cc3ee', 'pts': list(zip(xs, [e.Tmean for e in base]))},
        {'name': 'area average - after', 'color': '#1565c0', 'pts': list(zip(xs, [e.Tmean for e in new])), 'w': 2}],
        ylab='deg C', band=(lo, hi), title='Surface temperature when the next layer is laid down (green band = target window)'))
    o.append(legend(lo, hi))
    o.append(side_heatmap(opt, base, 'Heat map - BEFORE') + side_heatmap(opt, new, 'Heat map - AFTER'))
    o.append('<h2>Layer time</h2>')
    hl = [(opt.min_layer_time, 'slicer min layer time')] if opt.min_layer_time else []
    o.append(line_chart([{'name': 'before', 'color': '#aaa', 'pts': list(zip(xs, [e.time for e in base]))},
                         {'name': 'after', 'color': '#2e7d32', 'pts': list(zip(xs, [e.time for e in new])), 'w': 2}],
                        ylab='seconds', hlines=hl, title='Time per layer'))
    # time breakdown
    cat = k['breakdown']; tot = sum(cat.values()) or 1
    o.append('<h2>Where the time goes (original G-code)</h2><table><tr><th class="l">Category</th><th>Time</th><th>Share</th></tr>')
    for a, b in cat.items():
        o.append('<tr><td class="l">%s</td><td>%s</td><td>%.1f%%</td></tr>' % (a, fmt_t(b), 100 * b / tot))
    o.append('</table><p>%.0f%% of extrusion time is already at the filament flow limit (%g mm&sup3;/s) and cannot be sped up.</p>' % (100 * k['flow_limited_share'], opt.max_vol))
    # changes
    o.append('<h2>What was changed</h2><ul>')
    for line in k['changes']: o.append('<li>%s</li>' % line)
    o.append('</ul>')
    flagged = [i for i in range(nl) if (base[i].Tmax is not None and base[i].Tmax > hi) or (opt.mat['cold_matters'] and base[i].cold_frac >= 0.25)
               or (new[i].Tmax is not None and new[i].Tmax > hi)]
    o.append('<h2>Risk layers (%d)</h2>' % len(flagged))
    if flagged:
        o.append('<table><tr><th>Layer</th><th>Z mm</th><th>Tmax before</th><th>Tmax after</th><th>Cold area before</th><th>Layer time before</th><th>after</th><th class="l">Action</th></tr>')
        for i in flagged[:300]:
            o.append('<tr><td>%d</td><td>%.2f</td><td>%s</td><td>%s</td><td>%.0f%%</td><td>%.1fs</td><td>%.1fs</td><td class="l">%s</td></tr>' % (
                i + 1, opt.g.layer_z[i], '%.0f' % base[i].Tmax if base[i].Tmax else '-', '%.0f' % new[i].Tmax if new[i].Tmax else '-',
                100 * base[i].cold_frac, base[i].time, new[i].time, html.escape(opt.decisions[i] + (
                    ' (layer %d below was slowed to give this layer more cooling time)' % i if i > 0 and opt.decisions[i - 1].startswith('hot') else ''))))
        o.append('</table>')
    else:
        o.append('<p>No layer is outside the window.</p>')
    tr = opt.travel
    o.append('<h2>Travel &amp; stringing</h2><table>')
    for a, b in [('Travel moves (XY)', tr['moves']), ('Travel length', '%.0f mm' % tr['length']),
                 ('Travels crossing open air (&ge;1 mm outside the layer)', '%d (%.0f mm in air)' % (tr['open_air'], tr['open_air_len'])),
                 ('&hellip; of those WITHOUT retraction (stringing risk)', tr['open_air_unretracted']),
                 ('Retractions added (--fix-strings)', tr['fixed']),
                 ('Travels fully inside the part that still retract', tr['inside_retracted']),
                 ('&hellip; and also z-hop', tr['inside_lifted'])]:
        o.append('<tr><td class="l">%s</td><td>%s</td></tr>' % (a, b))
    rs = opt.reorder_stats
    o.append('<tr><td class="l">Infill island re-ordering (%d runs, %d islands checked)</td><td>%.0f &rarr; %.0f mm%s</td></tr>' % (
        rs['runs'], rs['chunks'], rs['travel_before'], rs['travel_after'], ' (applied)' if opt.st.reorder and opt.order else ' (not applied; use --reorder)'))
    o.append('</table>')
    if tr['flags']:
        o.append('<details><summary>Un-retracted open-air travels (first %d)</summary><table><tr><th>Layer</th><th>G-code line</th><th>mm in air</th><th class="l">Feature</th></tr>' % len(tr['flags']))
        for f in tr['flags'][:200]: o.append('<tr><td>%d</td><td>%d</td><td>%.1f</td><td class="l">%s</td></tr>' % (f[0], f[1], f[2], html.escape(str(f[3]))))
        o.append('</table></details>')
    ov = getattr(opt, 'ov_stats', None)
    if ov:
        o.append('<h2>Overhangs &amp; bridges</h2><table>')
        for a, b in [('Wall segments checked against the layer below', ov['checked']), ('Slicer-labelled overhang wall moves', ov['labelled_overhang_lines']),
                     ('Extra overhangs found 25-50%', ov['b2']), ('Extra overhangs found 50-75%', ov['b3']), ('Extra overhangs found 75-100%', ov['b4']),
                     ('Segments slowed', ov['slowed']), ('Bridge moves', ov['bridge_lines']), ('Bridge moves below overhang fan speed', ov['bridge_low_fan']),
                     ('Moves with fan boost', ov['boosted'])]:
            o.append('<tr><td class="l">%s</td><td>%s</td></tr>' % (a, b))
        o.append('</table>')
    o.append('<h2>Slicer setting recommendations</h2><table><tr><th class="l">Area</th><th class="l">Suggestion</th></tr>')
    for a, b in recommendations(opt, summary): o.append('<tr><td class="l">%s</td><td class="l">%s</td></tr>' % (a, b))
    o.append('</table>')
    o.append('<h2>Safety checks</h2><table>')
    for a, b in validation['metrics'].items(): o.append('<tr><td class="l">%s</td><td>%s</td></tr>' % (html.escape(str(a)), html.escape(str(b))))
    o.append('<tr><td class="l">errors</td><td>%s</td></tr></table>' % html.escape('; '.join(validation['errors']) or 'none'))
    o.append('<p><small>Model inputs: nozzle %g&deg;C, bed %g&deg;C, chamber %g&deg;C, window %d-%d&deg;C, filament max flow %g mm&sup3;/s, fan cap %g%%.</small></p></body></html>' % (
        opt.T_noz, opt.T_bed, opt.T_env, lo, hi, opt.max_vol, opt.fan_cap_pct))
    return ''.join(o)
