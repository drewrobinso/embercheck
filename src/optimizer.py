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
        self.margin = None              # deg C safety margin inside window (None -> goal default)
        self.accel = True               # speed-aware acceleration on internal features
        self.time_budget = 'goal'       # max print-time increase as a fraction; 'goal' -> goal default, None = no limit
        self.__dict__.update({k: v for k, v in kw.items() if v is not None})
        if self.max_speedup is None:
            self.max_speedup = {'quality': 1.0, 'balanced': 1.25, 'speed': 1.5}[self.goal]
        if self.margin is None:
            self.margin = 5.0 if self.goal == 'quality' else 3.0
        if self.time_budget == 'none':
            self.time_budget = None
        if self.time_budget == 'goal':
            # speed: never slower than the slicer; balanced: at most +2 %; quality: no limit
            self.time_budget = {'speed': 0.0, 'balanced': 0.02, 'quality': None}[self.goal]


# Speed-aware acceleration (M204) per Bambu ;FEATURE: type. Visible / delicate features (outer wall, overhangs,
# bridges, top surface, first layers) always keep the slicer's acceleration.
ACCEL_FEATURES = {'speed': {'Sparse infill', 'Internal solid infill', 'Inner wall'},
                  'balanced': {'Sparse infill', 'Internal solid infill', 'Inner wall'},
                  'quality': {'Sparse infill', 'Internal solid infill'}}
ACCEL_FACTOR = {'speed': None, 'balanced': 1.5, 'quality': 1.2}   # None -> up to the machine maximum
ACCEL_MIN_LAYER = 3


class LayerEval:
    __slots__ = ('time', 'Tmax', 'Tmin', 'Tmean', 'cold_frac', 'hot_frac', 'isl', 'feeds', 'fanpol', 's',
                 'tstart', 'fan_avg', 'acc')


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
                if not self.st.overhang or (bucket == 2 and self.st.goal != 'quality'): continue   # 25-50 %: quality only
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

    def plan_accel(self):
        """line idx -> raised M204 acceleration for internal features (only used on layers whose plan has acc=True).
        Travels/retracts between two raised extrusions of the same feature run at the same original accel are raised
        too, so we do not toggle M204 around every hop; anything the slicer set differently (short-travel 250 mm/s2,
        protected AMS/tool-change blocks, other features) keeps its own value."""
        self.accplan = {}
        self.acc_target_max = 0
        if not (self.st.accel and self.st.speed): return
        feats = ACCEL_FEATURES[self.st.goal]; fac = ACCEL_FACTOR[self.st.goal]; amax = self.kin.amax
        def target(a):
            t = amax if fac is None else min(amax, a * fac)
            return t if t > a + 1 else None
        for k in range(ACCEL_MIN_LAYER, self.nl):
            pend = []; last = None   # last = (feature, orig accel, target) of the previous raised extrusion
            for ln in self.L[k]['lines']:
                if ln.kind != 'motion': continue
                if not ln.opt or ln.layer < 0 or not ln.accel:
                    pend = []; last = None; continue
                if ln.is_ext:
                    t = target(ln.accel) if ln.feature in feats else None
                    if t is not None:
                        if last is not None and last[0] == ln.feature and last[1] == ln.accel:
                            for q in pend: self.accplan[q] = t
                        self.accplan[ln.i] = t; last = (ln.feature, ln.accel, t)
                        self.acc_target_max = max(self.acc_target_max, t)
                    else:
                        last = None
                    pend = []
                elif last is not None and ln.feature == last[0] and ln.accel == last[1]:
                    pend.append(ln.i)
                else:
                    pend = []; last = None

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
    def _acc_of(self, acc):
        if not acc or not self.accplan: return None
        ap = self.accplan
        return lambda ln: ap.get(ln.i, ln.accel)

    def eval_layer(self, k, s, fanpol, prev_state, tstart, acc=False):
        d = self.L[k]; lines = d['lines']
        feeds = [self.feed(ln, s) if ln.kind == 'motion' else None for ln in lines]
        durs, _ = estimate_times(lines, self.kin, feed_of=lambda ln: feeds[ln.i - d['a']], accel_of=self._acc_of(acc))
        n = len(lines); t = tstart; starts = [0.0] * n
        fan_t = 0.0; tt = 0.0
        for i in range(n):
            starts[i] = t; t += durs[i]
            if lines[i].kind == 'motion' and durs[i] > 0:
                fv = self.boost.get(lines[i].i) or self.fan_value(lines[i].fan, fanpol, k)
                fan_t += fv / 255.0 * durs[i]; tt += durs[i]
        ev = LayerEval(); ev.time = t - tstart; ev.s = s; ev.fanpol = fanpol; ev.tstart = tstart; ev.feeds = feeds
        ev.acc = bool(acc and self.accplan)
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
        use_acc = bool(self.accplan)
        mlt = self.min_layer_time
        self.decisions = []

        def nxt_T(k, e, t):
            if k + 1 >= self.nl: return -1e9
            en = self.eval_layer(k + 1, 1.0, None, [(x[0], x[1], x[2]) for x in e.isl], t + e.time)
            return en.Tmax if en.Tmax is not None else -1e9

        def done(e, dec):
            self.decisions.append(dec + (' acc+' if e.acc else '')); return e

        def choose(k, prev, t):
            e1 = self.eval_layer(k, 1.0, None, prev, t)
            if k < st.skip_layers or e1.Tmax is None:
                return done(e1, 'keep')
            ok_hot = lambda e: e.Tmax <= hi and nxt_T(k, e, t) <= hi
            n1 = nxt_T(k, e1, t)
            if e1.Tmax > mat['t_high'] or n1 > mat['t_high']:
                # hot: never raise acceleration here. speed/balanced try the free fix (more fan, same speed) first.
                if st.goal != 'quality' and st.fan:
                    e = self.eval_layer(k, 1.0, ('raise', raiseS), prev, t)
                    if ok_hot(e): return done(e, 'hot->s1.00 fan+')
                for pol in ([None, ('raise', raiseS)] if st.fan else [None]):
                    for s in ([1.0] if pol else []) + (grid_dn if st.speed else []):
                        e = self.eval_layer(k, s, pol, prev, t)
                        if ok_hot(e):
                            return done(e, 'hot->s%.2f%s' % (s, ' fan+' if pol else ''))
                e = self.eval_layer(k, st.min_scale if st.speed else 1.0, ('raise', raiseS) if st.fan else None, prev, t)
                return done(e, 'hot-residual')
            if mat['cold_matters'] and e1.cold_frac >= 0.25:
                best = e1
                for pol in ([None, lower] if st.fan else [None]):
                    for s in [1.0] + (grid_up if st.speed else []):
                        if s == 1.0 and pol is None and not use_acc: continue
                        e = self.eval_layer(k, s, pol, prev, t, use_acc)
                        if e.Tmax > hi or (mlt and e.time < min(mlt, e1.time) - 1e-6):
                            continue
                        if (s > 1.0 or e.acc) and nxt_T(k, e, t) > hi: continue
                        if e.cold_frac < 0.25:
                            return done(e, 'cold->s%.2f%s' % (s, ' fan-' if pol else ''))
                        if (e.Tmean or 0) > (best.Tmean or 0): best = e
                return done(best, 'cold-residual')
            floor_t = min(e1.time, mlt) if mlt else 0
            base_e = e1
            if use_acc and e1.Tmax < hi and n1 < hi:
                ea = self.eval_layer(k, 1.0, None, prev, t, True)
                if ea.Tmax <= hi and ea.time >= floor_t - 1e-6 and nxt_T(k, ea, t) <= hi:
                    base_e = ea
            if st.speed and grid_up and e1.Tmax < hi and n1 < hi:
                if mlt and e1.time < mlt * 1.05:
                    return done(base_e, 'keep(min-layer-time)')
                lo_i, hi_i, best = 0, len(grid_up) - 1, None
                while lo_i <= hi_i:
                    mid = (lo_i + hi_i) // 2
                    e = self.eval_layer(k, grid_up[mid], None, prev, t, base_e.acc)
                    if e.Tmax <= hi and e.time >= floor_t - 1e-6 and nxt_T(k, e, t) <= hi:
                        best = e; lo_i = mid + 1
                    else:
                        hi_i = mid - 1
                if best is not None and best.time < base_e.time - 0.05:
                    return done(best, 'speed s%.2f' % best.s)
            return done(base_e, 'keep')
        self.opt = self.run_chain(choose, key='opt')
        return self.opt

    def rechain(self):
        """Re-evaluate the thermal chain with the current per-layer choices (speed scale, fan policy, accel)."""
        ch = [(e.s, e.fanpol, e.acc) for e in self.opt]
        self.opt = self.run_chain(lambda k, p, t: self.eval_layer(k, ch[k][0], ch[k][1], p, t, ch[k][2]), key='budget')

    def enforce_budget(self, frac, extra_s=0.0):
        """Keep the modelled print time <= original * (1 + frac). Pays first with everything that is already faster
        (speed-ups, acceleration, fan-only fixes), then drops the lowest-value slowdowns: cooling slowdowns with the
        smallest predicted overheat per second first, then unmarked-overhang slowdowns (25-50 %, 50-75 %, >75 %).
        Fan changes stay (they cost no time). Returns seconds still over (0 when met)."""
        if frac is None: return 0.0
        bs = getattr(self, 'budget_stats', None) or {'kept_hot_layers': 0, 'dropped_overhangs': 0, 'rounds': 0}
        self.budget_stats = bs
        B = sum(e.time for e in self.base)
        target = B * (1.0 + frac) - 0.001 * B - extra_s
        thigh = self.mat['t_high']
        for _ in range(30):
            T = sum(e.time for e in self.opt)
            D = T - target
            bs['over_s'] = max(0.0, D)
            if D <= 0: return 0.0
            bs['rounds'] += 1
            cands = []
            for k, e in enumerate(self.opt):
                if e.s < 1.0 - 1e-9:
                    prev = [(x[0], x[1], x[2]) for x in self.opt[k - 1].isl] if k else None
                    e1 = self.eval_layer(k, 1.0, e.fanpol, prev, e.tstart, e.acc)
                    saved = e.time - e1.time
                    if saved <= 1e-6: continue
                    nb = self.base[k + 1].Tmax if k + 1 < self.nl and self.base[k + 1].Tmax is not None else -1e9
                    excess = max(0.5, max(self.base[k].Tmax or -1e9, nb) - thigh)
                    cands.append((0, excess / saved, saved, k))
            if not cands:
                # second phase: unmarked-overhang slowdowns, least overhanging first
                byk = {}
                for i in self.ovf:
                    byk.setdefault(self.g.lines[i].layer, []).append(i)
                for k, idx in byk.items():
                    if k < 0 or k >= self.nl: continue
                    e = self.opt[k]
                    keep = {i: self.ovf.pop(i) for i in idx}
                    prev = [(x[0], x[1], x[2]) for x in self.opt[k - 1].isl] if k else None
                    e1 = self.eval_layer(k, e.s, e.fanpol, prev, e.tstart, e.acc)
                    self.ovf.update(keep)
                    saved = e.time - e1.time
                    if saved <= 1e-6: continue
                    ovm = sum(self.ov_info.get(i, 0.5) for i in idx) / len(idx)
                    cands.append((1, ovm * len(idx) / saved, saved, k))
            if not cands:
                return D
            cands.sort(key=lambda c: (c[0], c[1]))
            got = 0.0
            for phase, _v, saved, k in cands:
                e = self.opt[k]
                if phase == 0:
                    e.s = 1.0; bs['kept_hot_layers'] += 1
                    self.decisions[k] = 'hot-kept(time budget)' + (' fan+' if e.fanpol else '') + (' acc+' if e.acc else '')
                else:
                    idx = [i for i in self.ovf if self.g.lines[i].layer == k]
                    for i in idx: self.ovf.pop(i, None)
                    bs['dropped_overhangs'] += len(idx)
                got += saved
                if got >= D * 1.05: break
            self.rechain()
        return max(0.0, sum(e.time for e in self.opt) - target)

    def accel_savings(self):
        """Seconds saved by the raised accelerations alone (same feeds, original M204)."""
        tot = 0.0; layers = 0
        for k, e in enumerate(self.opt):
            if not e.acc: continue
            d = self.L[k]; lines = d['lines']
            fo = lambda ln, d=d, e=e: e.feeds[ln.i - d['a']]
            t0 = sum(estimate_times(lines, self.kin, feed_of=fo)[0])
            t1 = sum(estimate_times(lines, self.kin, feed_of=fo, accel_of=self._acc_of(True))[0])
            tot += t0 - t1; layers += 1
        self.acc_saved = tot; self.acc_layers = layers
        return tot

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
        self.plan_accel()
        self.baseline()
        self.optimise()
        self.budget_stats = {'kept_hot_layers': 0, 'dropped_overhangs': 0, 'rounds': 0, 'over_s': 0.0}
        if self.st.time_budget is not None:
            self.enforce_budget(self.st.time_budget)
        self.accel_savings()
        self.analyse_travel()
        self.plan_reorder()
        return self
