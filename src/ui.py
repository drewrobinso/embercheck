"""Small dark progress window + results card (tkinter only, no extra dependencies).

Colours follow Bambu Studio's dark theme: dark greys with Bambu green (#00AE42)."""
import os, sys, time, json, threading, queue, webbrowser, re, html as _html

BG = '#1f2023'        # window
CARD = '#2a2b2f'      # panels
LINE = '#3a3b40'
FG = '#e8e8e8'
DIM = '#9a9ca3'
GREEN = '#00AE42'
GREEN_HI = '#14c45a'
AMBER = '#f0a020'
RED = '#e5484d'
TRACK = '#3b3d42'


def _font_family():
    return 'Segoe UI' if sys.platform == 'win32' else 'DejaVu Sans'


def _win_tweaks(root):
    """Dark title bar on Windows 10/11 (no effect elsewhere) + app icon."""
    if sys.platform != 'win32':
        return
    try:
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))  # PyInstaller puts data in _internal
        for ico in (os.path.join(base, 'icon.ico'), os.path.join(base, '..', 'packaging', 'icon.ico')):
            if os.path.exists(ico):
                root.iconbitmap(ico); break
    except Exception:
        pass
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def _dpi_aware():
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def _round_rect(cv, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
           x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


class RoundButton:
    def __init__(self, parent, text, command, primary=False, width=150, height=34, font=None, bg=BG):
        import tkinter as tk
        self.cmd = command; self.primary = primary
        self.cv = tk.Canvas(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0, cursor='hand2')
        self.base = GREEN if primary else CARD
        self.hover = GREEN_HI if primary else LINE
        self.shape = _round_rect(self.cv, 1, 1, width - 1, height - 1, 9, fill=self.base,
                                 outline='' if primary else LINE)
        self.label = self.cv.create_text(width / 2, height / 2, text=text, fill='#ffffff' if primary else FG, font=font)
        self.cv.bind('<Enter>', lambda e: self.cv.itemconfig(self.shape, fill=self.hover))
        self.cv.bind('<Leave>', lambda e: self.cv.itemconfig(self.shape, fill=self.base))
        self.cv.bind('<Button-1>', lambda e: self.cmd())

    def set_text(self, t):
        self.cv.itemconfig(self.label, text=t)

    def pack(self, **kw):
        self.cv.pack(**kw); return self


class ProgressBar:
    def __init__(self, parent, width=380, height=10):
        import tkinter as tk
        self.w, self.h = width, height
        self.cv = tk.Canvas(parent, width=width, height=height, bg=BG, highlightthickness=0, bd=0)
        _round_rect(self.cv, 0, 0, width, height, height / 2, fill=TRACK, outline='')
        self.bar = None; self.set(0.0)

    def set(self, frac):
        if self.bar is not None:
            self.cv.delete(self.bar)
        x1 = max(self.h, self.w * max(0.0, min(1.0, frac)))
        self.bar = _round_rect(self.cv, 0, 0, x1, self.h, self.h / 2, fill=GREEN, outline='')


def _center(root, w, h, pos=None):
    root.update_idletasks()
    if pos:
        x, y = pos
    else:
        x = (root.winfo_screenwidth() - w) // 2; y = (root.winfo_screenheight() - h) // 2
    root.geometry('%dx%d+%d+%d' % (w, h, x, y))


STAGE_ORDER = ['Parsing G-code', 'Thermal analysis', 'Optimizing', 'Verifying', 'Writing']


class ProgressWindow:
    """Run `work(progress_cb, cancel_flag)` in a worker thread while showing progress.
    Returns (result, error, cancelled, window_position)."""
    W, H = 460, 200

    def __init__(self, title_file=''):
        self.title_file = title_file

    def run(self, work):
        import tkinter as tk
        _dpi_aware()
        self.q = queue.Queue(); self.cancel = threading.Event(); self.out = {}
        root = self.root = tk.Tk()
        root.title('Print Optimizer'); root.configure(bg=BG); root.resizable(False, False)
        root.attributes('-topmost', True)
        _center(root, self.W, self.H)
        ff = _font_family()
        f_title = (ff, 13, 'bold'); f_txt = (ff, 10); f_small = (ff, 9)
        top = tk.Frame(root, bg=BG); top.pack(fill='x', padx=22, pady=(18, 0))
        dot = tk.Canvas(top, width=12, height=12, bg=BG, highlightthickness=0); dot.pack(side='left', pady=(3, 0))
        dot.create_oval(1, 1, 11, 11, fill=GREEN, outline='')
        tk.Label(top, text='Print Optimizer', bg=BG, fg=FG, font=f_title).pack(side='left', padx=(8, 0))
        self.pct = tk.Label(top, text='0%', bg=BG, fg=GREEN, font=f_title); self.pct.pack(side='right')
        self.sub = tk.Label(root, text=self.title_file, bg=BG, fg=DIM, font=f_small, anchor='w')
        self.sub.pack(fill='x', padx=22, pady=(2, 10))
        self.bar = ProgressBar(root, width=self.W - 44); self.bar.cv.pack(padx=22)
        mid = tk.Frame(root, bg=BG); mid.pack(fill='x', padx=22, pady=(10, 0))
        self.stage = tk.Label(mid, text='Starting…', bg=BG, fg=FG, font=f_txt, anchor='w'); self.stage.pack(side='left')
        self.elapsed = tk.Label(mid, text='0:00', bg=BG, fg=DIM, font=f_small); self.elapsed.pack(side='right')
        self.steps = tk.Label(root, text=self._steps_text(None), bg=BG, fg=DIM, font=(ff, 8), anchor='w')
        self.steps.pack(fill='x', padx=22, pady=(4, 0))
        bot = tk.Frame(root, bg=BG); bot.pack(fill='x', padx=22, pady=(12, 14), side='bottom')
        self.btn = RoundButton(bot, 'Cancel', self._cancel, width=110, height=30, font=f_txt).pack(side='right')
        tk.Label(bot, text='Cancel keeps the original G-code', bg=BG, fg=DIM, font=f_small).pack(side='left')
        root.protocol('WM_DELETE_WINDOW', self._cancel)
        _win_tweaks(root)
        self.t0 = time.time()

        def worker():
            try:
                self.out['result'] = work(lambda label, frac, detail='': self.q.put((label, frac, detail)), self.cancel.is_set)
            except BaseException as ex:  # noqa
                self.out['error'] = ex
            self.q.put(None)
        threading.Thread(target=worker, daemon=True).start()
        root.after(50, self._poll)
        root.mainloop()
        pos = self.out.get('pos')
        try:
            root.destroy()
        except Exception:
            pass
        return self.out.get('result'), self.out.get('error'), self.cancel.is_set(), pos

    def _steps_text(self, cur):
        short = ['Parse', 'Thermal', 'Optimize', 'Verify', 'Write']
        if cur not in STAGE_ORDER:
            return '   ›   '.join(short)
        i = STAGE_ORDER.index(cur)
        return '   ›   '.join(('✓ ' + s) if j < i else (('● ' + s) if j == i else s) for j, s in enumerate(short))

    def _poll(self):
        done = False
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    done = True; break
                label, frac, detail = item
                self.bar.set(frac); self.pct.config(text='%d%%' % int(frac * 100))
                self.stage.config(text=label + ('  ·  ' + detail if detail else ''))
                self.steps.config(text=self._steps_text(label))
        except queue.Empty:
            pass
        s = int(time.time() - self.t0)
        self.elapsed.config(text='%d:%02d' % divmod(s, 60))
        if done:
            self.out['pos'] = (self.root.winfo_x(), self.root.winfo_y())
            self.root.quit(); return
        self.root.after(60, self._poll)

    def _cancel(self):
        if not self.cancel.is_set():
            self.cancel.set()
            self.stage.config(text='Cancelling… original G-code will be kept')
            self.btn.set_text('Cancelling…')


# ----------------------------------------------------------------------------------- results card
def _strip(s):
    s = re.sub(r'<[^>]+>', '', s)
    return _html.unescape(s)


def show_summary(path, auto_close=60, pos=None):
    import tkinter as tk
    _dpi_aware()
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    root = tk.Tk(); root.title('Print Optimizer'); root.configure(bg=BG); root.resizable(False, False)
    W, H = 460, 470
    if pos:
        pos = (max(0, pos[0] - 10), max(0, pos[1] - 120))
    _center(root, W, H, pos)
    root.attributes('-topmost', True)
    root.after(1500, lambda: root.attributes('-topmost', False))
    ff = _font_family()
    f_title = (ff, 13, 'bold'); f_big = (ff, 18, 'bold'); f_txt = (ff, 10); f_small = (ff, 9); f_bold = (ff, 10, 'bold')
    status = d.get('status', 'optimized')
    col, label = {'optimized': (GREEN, 'Optimized'), 'nochange': (DIM, 'No changes needed'),
                  'failed': (AMBER, 'Check failed — G-code left unchanged'),
                  'dryrun': (DIM, 'Report only (dry run)')}.get(status, (DIM, status))
    top = tk.Frame(root, bg=BG); top.pack(fill='x', padx=22, pady=(18, 0))
    dot = tk.Canvas(top, width=12, height=12, bg=BG, highlightthickness=0); dot.pack(side='left', pady=(3, 0))
    dot.create_oval(1, 1, 11, 11, fill=col, outline='')
    tk.Label(top, text=label, bg=BG, fg=FG, font=f_title).pack(side='left', padx=(8, 0))
    tk.Label(root, text=d.get('name', ''), bg=BG, fg=DIM, font=f_small, anchor='w').pack(fill='x', padx=22, pady=(2, 10))

    # stat tiles
    grid = tk.Frame(root, bg=BG)
    if 'dt_pct' in d:   # no stats when the run crashed before analysis finished
        grid.pack(fill='x', padx=18)
    dt = d.get('dt_pct', 0.0)
    tiles = [
        ('Print time', '%+.1f%%' % dt, GREEN if dt < -0.05 else (FG if abs(dt) <= 0.05 else AMBER)),
        ('Hot layers', '%d → %d' % (d.get('hot_before', 0), d.get('hot_after', 0)), GREEN if d.get('hot_after', 0) < d.get('hot_before', 0) else FG),
        ('Cold layers', '%d → %d' % (d.get('cold_before', 0), d.get('cold_after', 0)), GREEN if d.get('cold_after', 0) < d.get('cold_before', 0) else FG),
        ('Overhangs slowed', str(d.get('overhang_adjusted', 0)), FG),
        ('Open-air travels', str(d.get('open_air', 0)), FG),
        ('Un-retracted', str(d.get('open_air_unretracted', 0)), AMBER if d.get('open_air_unretracted', 0) else FG),
    ]
    for i, (k, v, c) in enumerate(tiles):
        cell = tk.Frame(grid, bg=BG); cell.grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky='nsew')
        cv = tk.Canvas(cell, width=134, height=58, bg=BG, highlightthickness=0); cv.pack()
        _round_rect(cv, 1, 1, 133, 57, 10, fill=CARD, outline='')
        cv.create_text(12, 17, text=k, fill=DIM, font=f_small, anchor='w')
        cv.create_text(12, 39, text=v, fill=c, font=(ff, 14, 'bold'), anchor='w')
    if d.get('bambu_time'):
        tk.Label(root, text='Slicer estimate %s · time change is from the optimizer\'s motion model' % d['bambu_time'],
                 bg=BG, fg=DIM, font=f_small, anchor='w', justify='left', wraplength=W - 44).pack(fill='x', padx=22, pady=(4, 0))
    if status == 'failed' and d.get('errors'):
        tk.Label(root, text='Reason: ' + '; '.join(d['errors'])[:160], bg=BG, fg=AMBER, font=f_small, anchor='w',
                 justify='left', wraplength=W - 44).pack(fill='x', padx=22, pady=(6, 0))
    tk.Label(root, text='Details' if status == 'failed' else 'Recommendations', bg=BG, fg=FG, font=f_bold, anchor='w').pack(fill='x', padx=22, pady=(12, 4))
    recs = d.get('recommendations') or []
    box = tk.Frame(root, bg=BG); box.pack(fill='both', expand=True, padx=22)
    for area, text in recs[:3]:
        row = tk.Frame(box, bg=BG); row.pack(fill='x', pady=2)
        tk.Label(row, text='●', bg=BG, fg=GREEN, font=f_small).pack(side='left', anchor='n', padx=(0, 6))
        t = _strip(text)
        if len(t) > 170: t = t[:167].rsplit(' ', 1)[0] + '…'
        tk.Label(row, text='%s: %s' % (area, t), bg=BG, fg=FG, font=f_small, justify='left', anchor='w',
                 wraplength=W - 70).pack(side='left', fill='x')
    bot = tk.Frame(root, bg=BG); bot.pack(fill='x', padx=22, pady=(8, 16), side='bottom')
    cd = tk.Label(bot, text='', bg=BG, fg=DIM, font=f_small); cd.pack(side='left')
    state = {'left': auto_close, 'active': auto_close > 0}

    def close():
        root.destroy()

    def open_report():
        rp = d.get('report')
        if not (rp and os.path.exists(rp)):
            rp = d.get('log_dir')
        if rp and os.path.exists(rp):
            if sys.platform == 'win32':
                os.startfile(rp)  # noqa
            else:
                webbrowser.open('file://' + os.path.abspath(rp))
        state['active'] = False; cd.config(text='')

    RoundButton(bot, 'Close', close, width=90, height=32, font=f_txt).pack(side='right')
    tk.Frame(bot, bg=BG, width=8).pack(side='right')
    RoundButton(bot, 'Open full report' if d.get('report') else 'Open log folder', open_report, primary=True, width=150, height=32, font=f_bold).pack(side='right')

    def stop_timer(_e=None):
        if state['active']:
            state['active'] = False; cd.config(text='')
    root.bind('<Button-1>', stop_timer, add='+'); root.bind('<Key>', stop_timer, add='+')

    def tick():
        if not state['active']:
            return
        if state['left'] <= 0:
            close(); return
        cd.config(text='Closes in %ds' % state['left'])
        state['left'] -= 1
        root.after(1000, tick)
    tick()
    root.protocol('WM_DELETE_WINDOW', close)
    _win_tweaks(root)
    root.mainloop()
