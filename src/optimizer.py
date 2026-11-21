"""Analysis + optimisation engine (thermal model, speed/fan plan, overhangs, travel, stringing)."""
import math
from gcode_model import (GcodeFile, Kinematics, estimate_times, FEATURES_SPEEDUP, FEATURES_SLOWDOWN,
                         FEATURES_REORDER, WALLS, split_comment, parse_words)
import materials as M

try:
    import numpy as np
    import shapely
    from shapely import STRtree
    HAVE_GEOM = True
    GEOM_ERROR = None
except Exception as _ex:  # pragma: no cover
    HAVE_GEOM = False
    GEOM_ERROR = '%s: %s' % (type(_ex).__name__, _ex)


HOLE_FILL_MM2 = 30.0   # holes smaller than this (sparse-infill cells) count as solid support


def fill_small_holes(poly, max_area):
    if not hasattr(poly, 'interiors') or not poly.interiors:
        return poly
    from shapely.geometry import Polygon
    keep = [r for r in poly.interiors if Polygon(r).area >= max_area]
    return Polygon(poly.exterior, keep)


class Settings:
    def __init__(self, **kw):
        self.goal = 'balanced'          # quality | balanced | speed
        self.max_speedup = None         # None -> goal default
        self.min_scale = 0.5            # never slower than 50 % of the slicer's speed (thermal)
        self.skip_layers = 2            # never touch the first N layers' speeds
        self.chamber = None             # deg C, None -> from config / 35 enclosed
        self.material = None            # override filament type
        self.speed = True
        self.fan = True
        self.overhang = True
        self.bridge_fan = True
        self.reorder = False
        self.fix_strings = False
        self.m73 = True
        self.margin = 3.0               # deg C safety margin inside window
        self.__dict__.update({k: v for k, v in kw.items() if v is not None})
        if self.max_speedup is None:
            self.max_speedup = {'quality': 1.0, 'balanced': 1.25, 'speed': 1.5}[self.goal]


class LayerEval:
    __slots__ = ('time', 'Tmax', 'Tmin', 'Tmean', 'cold_frac', 'hot_frac', 'isl', 'feeds', 'fanpol', 's',
                 'tstart', 'fan_avg')


class Optimizer:
    def __init__(self, g: GcodeFile, st: Settings, log=print, progress=None):
        self.g, self.st, self.log = g, st, log
        self.kin = Kinematics(g)
        ft = st.material or g.cfg('filament_type', 'PLA', num=False)
        self.filament_type = ft
        self.mat_name, self.mat_guess = M.resolve(ft)
        self.mat = dict(M.MATERIALS[self.mat_name])
        self.T_noz = g.cfg('nozzle_temperature', 220) or 220
        self.T_bed = self._bed_temp()
        ch = g.cfg('chamber_temperatures', 0) or 0
        enclosed = 'H2' in (g.config.get('printer_model', '')) or 'X1' in g.config.get('printer_model', '') \
            or 'P1S' in g.config.get('printer_model', '') or 'P2S' in g.config.get('printer_model', '')
        self.T_env = st.chamber if st.chamber is not None else max(ch, 35.0 if enclosed else 25.0)
        self.fil_area = math.pi * ((g.cfg('filament_diameter', 1.75) or 1.75) / 2) ** 2
        self.max_vol = g.cfg('filament_max_volumetric_speed', 0) or 0
        self.fan_max_cfg = g.cfg('fan_max_speed', 100) or 100
        self.fan_min_cfg = g.cfg('fan_min_speed', 0) or 0
        self.ov_fan_cfg = g.cfg('overhang_fan_speed', 100) or 100
        self.close_fan_layers = int(g.cfg('close_fan_the_first_x_layers', 1) or 1)
        self.min_layer_time = g.cfg('slow_down_layer_time', 0) or 0
        self.ret_len = g.cfg('retraction_length', 0.8) or 0.8
        self.ret_speed = g.cfg('retraction_speed', 30) or 30
        self.deret_speed = g.cfg('deretraction_speed', 0) or self.ret_speed
        # fan ceiling for layer cooling (never above what the slicer itself would use for overhangs)
        self.fan_cap_pct = max(self.fan_max_cfg, min(self.mat['fan_cap'], self.ov_fan_cfg))
        self.boost_pct = self.ov_fan_cfg
        self.nl = len(g.layer_starts)
        self.ovf = {}         # line idx -> capped feed (overhang)
        self.ov_info = {}     # line idx -> overhang fraction
        self.boost = {}       # line idx -> fan S value to boost to
        self.inserts_before = {}
        self.order = {}       # layer -> list of original indices
        self.notes = []
        self.progress = progress or (lambda key, frac=0.0, detail='': None)

    def _bed_temp(self):
        for ln in self.g.lines[:self.g.body_start]:
            if ln.cmd in ('M140', 'M190'):
                w = parse_words(split_comment(ln.text)[0][4:])
                if w.get('S', 0) > 0: return w['S']
        return 60.0

    # ------------------------------------------------------------ geometry
    def build_geometry(self):
        g = self.g
        self.L = []  # per layer dict
        prev = None
        for k in range(self.nl):
            self.progress('geom', k / max(1, self.nl), 'layer %d/%d' % (k + 1, self.nl))
            a, b = g.layer_range(k)
            lines = g.lines[a:b]
            exts = [ln for ln in lines if ln.is_ext]
            d = {'a': a, 'b': b, 'lines': lines, 'exts': exts, 'region': None, 'islands': [], 'ov': []}
            if HAVE_GEOM and exts:
                co = np.array([[[l.x0, l.y0], [l.x, l.y]] for l in exts])
                ls = shapely.linestrings(co)
                bufs = shapely.buffer(ls, np.array([max(l.width, 0.1) / 2 for l in exts]), quad_segs=2)
                region = shapely.union_all(bufs).simplify(0.02)
                polys = [fill_small_holes(p, HOLE_FILL_MM2) for p in getattr(region, 'geoms', [region]) if p.area > 0.01]
                region = shapely.union_all(polys) if polys else region
                d['region'] = region
                tree = STRtree(polys)
                mids = shapely.points((co[:, 0, :] + co[:, 1, :]) / 2)
                pairs = tree.query(mids, predicate='intersects')
                owner = [-1] * len(exts)
                for pi, ti in zip(pairs[0], pairs[1]):
                    if owner[pi] < 0: owner[pi] = int(ti)
                missing = [i for i, o in enumerate(owner) if o < 0]
                if missing:
                    near = tree.query_nearest(mids[missing])
                    for qi, ti in zip(near[0], near[1]): owner[missing[qi]] = int(ti)
                isl = []
                for j, p in enumerate(polys):
                    bx = p.bounds
                    isl.append({'poly': p, 'area': p.area, 'segs': [], 'cx': (bx[0] + bx[2]) / 2,
                                'xmin': bx[0], 'xmax': bx[2], 'ymin': bx[1], 'ymax': bx[3], 'over': []})
                for i, o in enumerate(owner): isl[o]['segs'].append(exts[i].i - a)
                d['islands'] = isl
                if prev is not None and prev['islands']:
                    ptree = STRtree([q['poly'] for q in prev['islands']])
                    for j, ii in enumerate(isl):
                        for t in ptree.query(ii['poly'], predicate='intersects'):
                            ar = ii['poly'].intersection(prev['islands'][int(t)]['poly']).area
                            if ar > 1e-3: ii['over'].append((int(t), ar))
            elif exts:  # no shapely: whole layer = one island, full overlap
                xs = [l.x for l in exts]; ys = [l.y for l in exts]
                area = sum(l.length * l.width for l in exts)
                d['islands'] = [{'poly': None, 'area': area, 'segs': [l.i - a for l in exts], 'cx': (min(xs) + max(xs)) / 2,
                                 'xmin': min(xs), 'xmax': max(xs), 'ymin': min(ys), 'ymax': max(ys),
                                 'over': [(0, area)] if prev is not None and prev['islands'] else []}]
            self.L.append(d)
            prev = d

    # ------------------------------------------------------------ overhangs / bridges
    def detect_overhangs(self):
        if not HAVE_GEOM: return
        g = self.g
        sp = {2: g.cfg('overhang_2_4_speed', 0), 3: g.cfg('overhang_3_4_speed', 0), 4: g.cfg('overhang_4_4_speed', 0)}
        dflt = {2: None, 3: 30.0, 4: 15.0}
        self.ov_stats = {'checked': 0, 'b2': 0, 'b3': 0, 'b4': 0, 'slowed': 0, 'labelled_overhang_lines': 0,
                         'bridge_low_fan': 0, 'bridge_lines': 0, 'boosted': 0}
        boost_S = round(self.boost_pct * 2.55, 2)
        boost_ok = self.st.overhang and self.st.fan
        for k in range(1, self.nl):
            self.progress('overhang', k / max(1, self.nl), 'layer %d/%d' % (k + 1, self.nl))
            d = self.L[k]; prev = self.L[k - 1]['region']
            for ln in d['exts']:
                if ln.feature == 'Overhang wall': self.ov_stats['labelled_overhang_lines'] += 1
                if ln.feature == 'Bridge':
                    self.ov_stats['bridge_lines'] += 1
                    if ln.fan < boost_S * 0.9 and ln.opt:
                        self.ov_stats['bridge_low_fan'] += 1
                        if self.st.bridge_fan and self.mat_name in ('PLA', 'PETG', 'TPU') and k >= self.close_fan_layers:
                            self.boost[ln.i] = boost_S
            if prev is None: continue
            walls = [ln for ln in d['exts'] if ln.feature in WALLS and ln.opt]
            if not walls: continue
            pts = []; owner = []
            for wi, ln in enumerate(walls):
                n = max(1, int(ln.length / 1.0))
                for s in range(n):
                    t = (s + 0.5) / n
                    pts.append((ln.x0 + (ln.x - ln.x0) * t, ln.y0 + (ln.y - ln.y0) * t)); owner.append(wi)
            P = np.array(pts)
            inside = shapely.contains_xy(prev, P[:, 0], P[:, 1])
            dist = shapely.distance(shapely.points(P), prev.boundary)
            acc = [[0.0, 0] for _ in walls]
            for pi in range(len(P)):
                w = walls[owner[pi]].width or 0.4
                ov = (w / 2 - dist[pi]) / w if inside[pi] else (w / 2 + dist[pi]) / w
                ov = min(1.0, max(0.0, ov))
                acc[owner[pi]][0] += ov; acc[owner[pi]][1] += 1
            for wi, ln in enumerate(walls):
                self.ov_stats['checked'] += 1
                ov = acc[wi][0] / max(1, acc[wi][1])
                if ov < 0.25: continue
                bucket = 2 if ov < 0.5 else (3 if ov < 0.75 else 4)
                self.ov_stats['b%d' % bucket] += 1
                self.ov_info[ln.i] = ov
                if not self.st.overhang or bucket == 2: continue   # 25-50 %: report only
                F = ln.effF
                v = sp[bucket] if sp[bucket] else None
                if v is None:
                    v = dflt[bucket] if dflt[bucket] else F / 60.0 * 0.7
                    if bucket == 3: v = min(v, F / 60.0 * 0.5)
                    if bucket == 4: v = min(v, F / 60.0 * 0.35)
                target = max(10.0 * 60, v * 60)
                if target < F - 1:
                    self.ovf[ln.i] = target; self.ov_stats['slowed'] += 1
                if boost_ok and k >= self.close_fan_layers and ln.fan < boost_S:
                    if self.mat_name in ('PLA', 'PETG', 'TPU') or bucket >= 3:
                        self.boost[ln.i] = boost_S
        self.ov_stats['boosted'] = len(self.boost)

    # ------------------------------------------------------------ feeds
    def flow_cap_F(self, ln):
        if not self.max_vol or not ln.is_ext or ln.length <= 0: return 1e12
        mm3_per_mm = ln.e * self.fil_area / ln.length
        if mm3_per_mm <= 0: return 1e12
        return self.max_vol * 0.95 / mm3_per_mm * 60.0

    def compute_run_caps(self):
        """One flow cap per continuous extrusion run (same feature + same slicer F), so we emit one F per run
        instead of a different F on every segment (keeps pressure advance / flow steady)."""
        self.runcap = {}
        run = []; key = None
        def flush():
            if run:
                c = min(self.flow_cap_F(l) for l in run)
                for l in run: self.runcap[l.i] = c
        for ln in self.g.lines[self.g.body_start:self.g.body_end]:
            if ln.kind != 'motion': continue
            if ln.is_ext:
                k = (ln.feature, ln.effF, ln.layer)
                if k != key: flush(); run = []; key = k
                run.append(ln)
            else:
                flush(); run = []; key = None
        flush()

    def feed(self, ln, s):
        F = ln.effF
        if not (ln.opt and ln.is_ext) or ln.layer < self.st.skip_layers:
            return F
        tgt = F
        if self.st.speed:
            if s > 1.0 and ln.feature in FEATURES_SPEEDUP:
                cap = min(max(F, self.runcap.get(ln.i, self.flow_cap_F(ln))), self.kin.vmax_xy * 60)
                tgt = min(F * s, cap)
                tgt = max(tgt, F)
            elif s < 1.0 and ln.feature in FEATURES_SLOWDOWN:
                floor = max((self.g.cfg('slow_down_min_speed', 10) or 10) * 60, 600)
                tgt = max(F * s, min(F, floor))
        if ln.i in self.ovf: tgt = min(tgt, self.ovf[ln.i])
        return tgt

    def fan_value(self, orig, pol, layer):
        """pol: None | ('raise', S) | ('lower', factor, floorS)"""
        if pol is None or orig <= 0 or layer < self.close_fan_layers or not self.st.fan:
            return orig
        if pol[0] == 'raise':
            return max(orig, min(pol[1], self.fan_cap_pct * 2.55))
        if pol[0] == 'lower':
            if orig >= self.ov_fan_cfg * 2.55 - 1:  # overhang/bridge fan commands are left alone
                return orig
            return max(orig * pol[1], pol[2])
        return orig

    # ------------------------------------------------------------ thermal
    def eval_layer(self, k, s, fanpol, prev_state, tstart):
        d = self.L[k]; lines = d['lines']
        feeds = [self.feed(ln, s) if ln.kind == 'motion' else None for ln in lines]
        durs, _ = estimate_times(lines, self.kin, feed_of=lambda ln: feeds[ln.i - d['a']])
        n = len(lines); t = tstart; starts = [0.0] * n
        fan_t = 0.0; tt = 0.0
        for i in range(n):
            starts[i] = t; t += durs[i]
            if lines[i].kind == 'motion' and durs[i] > 0:
                fv = self.boost.get(lines[i].i) or self.fan_value(lines[i].fan, fanpol, k)
                fan_t += fv / 255.0 * durs[i]; tt += durs[i]
        ev = LayerEval(); ev.time = t - tstart; ev.s = s; ev.fanpol = fanpol; ev.tstart = tstart; ev.feeds = feeds
        fan_avg = fan_t / tt if tt > 0 else 0.0
        ev.fan_avg = fan_avg
        tau = self.mat['tau_still'] / (1.0 + M.K_FAN * fan_avg)
        Tb = self.T_env + M.BEAD_FRAC * (self.T_noz - self.T_env)
        isl_out = []
        for ii in d['islands']:
            if ii['segs']:
                ts = [starts[j] for j in ii['segs']]; te = [starts[j] + durs[j] for j in ii['segs']]
                t0, t1 = min(ts), max(te)
            else:
                t0 = t1 = tstart
            tmid = (t0 + t1) / 2
            Tin = None
            if k == 0:
                Tin = self.T_bed
            elif ii['over'] and prev_state:
                wsum = 0.0; acc = 0.0
                for (j, ar) in ii['over']:
                    pj = prev_state[j]
                    dt = max(0.0, t0 - pj[1]) + (tmid - t0) * 0.5
                    Ts = self.T_env + (pj[0] - self.T_env) * math.exp(-dt / pj[2])
                    acc += Ts * ar; wsum += ar
                Tin = acc / wsum if wsum > 0 else None
            Tend = M.DEPOSIT_MIX * Tb + (1 - M.DEPOSIT_MIX) * (Tin if Tin is not None else self.T_env)
            isl_out.append((Tend, tmid, tau, Tin, ii['area']))
        ev.isl = isl_out
        vals = [(x[3], x[4]) for x in isl_out if x[3] is not None]
        if vals:
            ev.Tmax = max(v for v, _ in vals); ev.Tmin = min(v for v, _ in vals)
            A = sum(a for _, a in vals)
            ev.Tmean = sum(v * a for v, a in vals) / A
            ev.cold_frac = sum(a for v, a in vals if v < self.mat['t_low']) / A
            ev.hot_frac = sum(a for v, a in vals if v > self.mat['t_high']) / A
        else:
            ev.Tmax = ev.Tmin = ev.Tmean = None; ev.cold_frac = ev.hot_frac = 0.0
        return ev

    def run_chain(self, chooser, key='opt'):
        prev = None; t = 0.0; out = []
        for k in range(self.nl):
            self.progress(key, k / max(1, self.nl), 'layer %d/%d' % (k + 1, self.nl))
            ev = chooser(k, prev, t)
            out.append(ev)
            prev = [(x[0], x[1], x[2]) for x in ev.isl]
            t += ev.time
        return out

    def baseline(self):
        save = self.ovf, self.boost
        self.ovf, self.boost = {}, {}
        self.base = self.run_chain(lambda k, p, t: self.eval_layer(k, 1.0, None, p, t), key='baseline')
        self.ovf, self.boost = save
        return self.base

    def optimise(self):
        st = self.st; mat = self.mat
        hi = mat['t_high'] - st.margin; lo = mat['t_low'] + st.margin
        grid_up = [round(1.0 + 0.05 * i, 2) for i in range(1, int(round((st.max_speedup - 1.0) / 0.05)) + 1)]
        grid_dn = [round(1.0 - 0.05 * i, 2) for i in range(1, int(round((1.0 - st.min_scale) / 0.05)) + 1)]
        raiseS = self.fan_cap_pct * 2.55
        lower = ('lower', 0.5, self.fan_min_cfg * 2.55)
        self.decisions = []

        def nxt_T(k, e, t):
            if k + 1 >= self.nl: return -1e9
            en = self.eval_layer(k + 1, 1.0, None, [(x[0], x[1], x[2]) for x in e.isl], t + e.time)
            return en.Tmax if en.Tmax is not None else -1e9

        def choose(k, prev, t):
            e1 = self.eval_layer(k, 1.0, None, prev, t)
            if k < st.skip_layers or e1.Tmax is None:
                self.decisions.append('keep'); return e1
            ok_hot = lambda e: e.Tmax <= hi and nxt_T(k, e, t) <= hi
            n1 = nxt_T(k, e1, t)
            if e1.Tmax > mat['t_high'] or n1 > mat['t_high']:
                for pol in ([None, ('raise', raiseS)] if st.fan else [None]):
                    for s in ([1.0] if pol else []) + (grid_dn if st.speed else []):
                        e = self.eval_layer(k, s, pol, prev, t)
                        if ok_hot(e):
                            self.decisions.append('hot->s%.2f%s' % (s, ' fan+' if pol else '')); return e
                e = self.eval_layer(k, st.min_scale if st.speed else 1.0, ('raise', raiseS) if st.fan else None, prev, t)
                self.decisions.append('hot-residual'); return e
            if mat['cold_matters'] and e1.cold_frac >= 0.25:
                best = e1
                for pol in ([None, lower] if st.fan else [None]):
                    for s in [1.0] + (grid_up if st.speed else []):
                        if s == 1.0 and pol is None: continue
                        e = self.eval_layer(k, s, pol, prev, t)
                        if e.Tmax > hi or (self.min_layer_time and e.time < min(self.min_layer_time, e1.time) - 1e-6):
                            continue
                        if s > 1.0 and nxt_T(k, e, t) > hi: continue
                        if e.cold_frac < 0.25:
                            self.decisions.append('cold->s%.2f%s' % (s, ' fan-' if pol else '')); return e
                        if (e.Tmean or 0) > (best.Tmean or 0): best = e
                self.decisions.append('cold-residual'); return best
            if st.speed and grid_up and e1.Tmax < hi and n1 < hi:
                floor_t = min(e1.time, self.min_layer_time) if self.min_layer_time else 0
                if self.min_layer_time and e1.time < self.min_layer_time * 1.05:
                    self.decisions.append('keep(min-layer-time)'); return e1
                lo_i, hi_i, best = 0, len(grid_up) - 1, None
                while lo_i <= hi_i:
                    mid = (lo_i + hi_i) // 2
                    e = self.eval_layer(k, grid_up[mid], None, prev, t)
                    if e.Tmax <= hi and e.time >= floor_t - 1e-6 and nxt_T(k, e, t) <= hi:
                        best = e; lo_i = mid + 1
                    else:
                        hi_i = mid - 1
                if best is not None and best.time < e1.time - 0.05:
                    self.decisions.append('speed s%.2f' % best.s); return best
            self.decisions.append('keep'); return e1
        self.opt = self.run_chain(choose, key='opt')
        return self.opt

    # ------------------------------------------------------------ travel & stringing
    def analyse_travel(self):
        g = self.g
        self.travel = {'moves': 0, 'length': 0.0, 'open_air': 0, 'open_air_len': 0.0, 'open_air_unretracted': 0,
                       'inside_retracted': 0, 'inside_lifted': 0, 'fixed': 0, 'flags': []}
        if not HAVE_GEOM: return
        for k in range(self.nl):
            self.progress('travel', k / max(1, self.nl))
            d = self.L[k]; reg = d['region']
            trav = [ln for ln in d['lines'] if ln.is_travel and ln.opt]
            if not trav or reg is None: continue
            co = np.array([[[l.x0, l.y0], [l.x, l.y]] for l in trav])
            outside = shapely.length(shapely.difference(shapely.linestrings(co), reg))
            lines = d['lines']; a = d['a']
            for ln, out in zip(trav, outside):
                if ln.layer < 0: continue
                self.travel['moves'] += 1; self.travel['length'] += ln.length
                retracted = ln.r_before < -0.05
                lifted = (ln.z is not None and abs(ln.z - g.layer_z[k]) > 0.05)
                if out >= 1.0:
                    self.travel['open_air'] += 1; self.travel['open_air_len'] += float(out)
                    if not retracted:
                        self.travel['open_air_unretracted'] += 1
                        if len(self.travel['flags']) < 400:
                            self.travel['flags'].append((k + 1, ln.i + 1, round(float(out), 1), ln.feature))
                        if self.st.fix_strings and out >= 2.0 and ln.opt:
                            self._fix_string(ln, lines, a)
                elif out < 0.05 and retracted:
                    self.travel['inside_retracted'] += 1
                    if lifted: self.travel['inside_lifted'] += 1

    def _fix_string(self, ln, lines, a):
        j = ln.i - a + 1
        while j < len(lines):
            q = lines[j]
            if q.kind == 'motion' and q.e is not None:
                if not q.is_ext or not q.opt: return  # existing retraction logic - leave alone
                break
            if not q.opt and q.kind == 'motion': return
            j += 1
        else:
            return
        L = self.ret_len
        self.inserts_before.setdefault(ln.i, []).append('G1 E-%.3f F%d ; PO anti-string retract\n' % (L, self.ret_speed * 60))
        self.inserts_before.setdefault(lines[j].i, []).append('G1 E%.3f F%d ; PO anti-string unretract\n' % (L, self.deret_speed * 60))
        self.travel['fixed'] += 1

    # ------------------------------------------------------------ reorder (TSP within feature runs)
    def plan_reorder(self):
        self.reorder_stats = {'runs': 0, 'chunks': 0, 'reordered_runs': 0, 'travel_before': 0.0, 'travel_after': 0.0}
        for k in range(self.nl):
            self.progress('reorder', k / max(1, self.nl))
            d = self.L[k]; lines = d['lines']; a = d['a']
            order = list(range(a, d['b']))
            changed = False
            # split into barrier-free regions
            regions = []; cur = []
            for ln in lines:
                ok = (ln.opt or (ln.in_wipe and not ln.prot and ln.layer >= 0) or (ln.text.startswith('; WIPE_') and not ln.prot)) and ln.feature in FEATURES_REORDER and ln.i not in self.inserts_before and (
                    ln.kind in ('motion', 'accel') or ln.cmd == 'G17' or
                    (ln.kind == 'other' and not ln.cmd and any(x in ln.text for x in ('LINE_WIDTH', 'WIPE_START', 'WIPE_END'))))
                if ok and cur and lines[cur[-1] - a].feature != ln.feature: ok_split = True
                else: ok_split = False
                if ok and not ok_split:
                    cur.append(ln.i)
                else:
                    if cur: regions.append(cur)
                    cur = [ln.i] if ok else []
            if cur: regions.append(cur)
            G = self.g.lines
            for reg in regions:
                bounds = []
                for p, i in enumerate(reg):
                    if G[i].is_travel:
                        q = p - 1
                        while q >= 0 and G[reg[q]].e is None: q -= 1
                        bnd = q + 1
                        if not bounds or bounds[-1] < bnd: bounds.append(bnd)
                if not bounds: continue
                chunks = []
                edges = [0] + bounds + [len(reg)]
                edges = sorted(set(edges))
                for x0, x1 in zip(edges[:-1], edges[1:]):
                    chunks.append(reg[x0:x1])
                if len(chunks) < 3: continue
                st_s = lambda c: round(G[c[0]].r_before, 3)
                st_e = lambda c: round(G[c[-1] + 1].r_before, 3) if c[-1] + 1 < len(G) else None
                R = st_s(chunks[1])
                # merge chunks so every movable unit starts and ends in the same (retracted) state and extrudes
                merged = [chunks[0]]
                curc = None
                for c in chunks[1:]:
                    curc = c if curc is None else curc + c
                    lns = [G[i] for i in curc]
                    if st_s(curc) == R and st_e(curc) == R and any(l.is_ext for l in lns) and any(l.is_travel for l in lns):
                        merged.append(curc); curc = None
                tail = curc  # leftover (e.g. last chunk that ends un-retracted before the next feature) stays last
                if any(st_s(c) != R for c in merged[1:]): continue
                head, movable = merged[0], merged[1:]
                if tail is None and movable:
                    # the last unit stays last: whatever follows the run (barrier, next feature, a G-code
                    # line that continues from the current nozzle position) must see the same position
                    tail = movable.pop()
                if len(movable) < 2: continue
                info = []
                for c in movable:
                    lns = [G[i] for i in c]
                    tr = next(l for l in lns if l.is_travel)
                    mot = [l for l in lns if l.kind == 'motion' and l.x is not None]
                    info.append(((tr.x, tr.y), (mot[-1].x, mot[-1].y)))
                hm = [G[i] for i in head if G[i].kind == 'motion']
                if not hm: continue
                start = (hm[-1].x, hm[-1].y)
                nxt = None
                if tail:
                    trt = next((l for l in (G[i] for i in tail) if l.is_travel), None)
                    if trt is not None: nxt = (trt.x, trt.y)
                for ln in ([] if nxt else G[reg[-1] + 1:d['b']]):
                    if ln.kind == 'motion' and ln.length > 1e-9 and ln.x is not None:
                        nxt = (ln.x, ln.y); break
                n = len(info)
                self.reorder_stats['runs'] += 1; self.reorder_stats['chunks'] += n
                def cost(seq):
                    p = start; c = 0.0
                    for s_ in seq:
                        c += math.dist(p, info[s_][0]); p = info[s_][1]
                    if nxt: c += math.dist(p, nxt)
                    return c
                orig = list(range(n)); c0 = cost(orig)
                # nearest neighbour
                left = set(orig); p = start; seq = []
                while left:
                    j = min(left, key=lambda q: math.dist(p, info[q][0]))
                    seq.append(j); left.discard(j); p = info[j][1]
                best, cb = (seq, cost(seq))
                if cb > c0: best, cb = orig, c0
                if n <= 80:
                    improved = True; it = 0
                    while improved and it < 20:
                        improved = False; it += 1
                        for i in range(n - 1):
                            for j in range(i + 1, n):
                                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                                cc = cost(cand)
                                if cc < cb - 1e-6: best, cb, improved = cand, cc, True
                self.reorder_stats['travel_before'] += c0
                if cb < c0 - 1.0 and cb < c0 * 0.98:
                    self.reorder_stats['travel_after'] += cb
                    self.reorder_stats['reordered_runs'] += 1
                    if self.st.reorder:
                        newidx = list(head) + [i for s_ in best for i in movable[s_]] + (list(tail) if tail else [])
                        pos = order.index(reg[0])
                        order[pos:pos + len(reg)] = newidx
                        changed = True
                else:
                    self.reorder_stats['travel_after'] += c0
            if changed: self.order[k] = order

    # ------------------------------------------------------------ run everything
    def run(self):
        self.build_geometry()
        self.detect_overhangs()
        self.compute_run_caps()
        self.baseline()
        self.optimise()
        self.analyse_travel()
        self.plan_reorder()
        return self
