"""Self-contained test for src/bambu_presets.py: "<layer>mm <printer> EmberCheck <Goal>" naming, multi-account folders,
migration of 1.0/1.1 "... - Optimized" and 1.2-1.4 "... AI <Goal>" presets (marked / legacy, synced / unsynced,
user tweaks carried over), repointing PrintOptimizer.exe -> EmberCheck.exe, multi-printer selection, pruning, uninstall.
Run: python test/test_presets.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import bambu_presets as bp

OLD = '0.20mm Standard @BBL H2S - Optimized'
H2S = 'Bambu Lab H2S 0.4 nozzle'


def w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def sysproc(d, name, printers, inst='true'):
    w(os.path.join(d, 'system', 'BBL', 'process', name + '.json'),
      {'name': name, 'setting_id': 'GP' + name[:4], 'instantiation': inst, 'compatible_printers': printers})


def main():
    d = tempfile.mkdtemp(); app = tempfile.mkdtemp(); bk = os.path.join(app, 'bk'); q = lambda m: None
    w(os.path.join(d, 'system', 'BBL.json'), {'version': '02.09.00.74'})
    w(os.path.join(d, 'system', 'BBL', 'machine', H2S + '.json'), {'printer_model': 'Bambu Lab H2S', 'default_print_profile': '0.20mm Standard @BBL H2S'})
    for n in ('0.16mm Standard @BBL H2S', '0.20mm Standard @BBL H2S', '0.24mm Standard @BBL H2S', '0.08mm High Quality @BBL H2S',
              '0.12mm High Quality @BBL H2S', '0.20mm Strength @BBL H2S'):
        sysproc(d, n, [H2S])
    sysproc(d, 'fdm_process_common', [H2S], inst='false')
    w(os.path.join(d, 'BambuStudio.conf'), {'app': {'preset_folder': '2132877600', 'sync_user_preset': True}, 'models': [{'model': 'Bambu Lab H2S', 'nozzle_diameter': '0.4', 'vendor': 'BBL'}]})

    expected = ['%s H2S EmberCheck %s' % (l, g) for l in ('0.16mm', '0.20mm', '0.24mm') for g in ('Balanced', 'Speed', 'Quality')]
    names = [x[0] for x in bp.plan(d, os.path.join(d, 'system'))]
    assert names == expected, names

    acct = os.path.join(d, 'user', '2132877600', 'process'); dflt = os.path.join(d, 'user', 'default', 'process')
    # 1.1.x account preset: legacy (no marker, python.exe ...bambu_optimizer.py), cloud-synced
    w(os.path.join(acct, OLD + '.json'), {'name': OLD, 'inherits': '0.20mm Standard @BBL H2S', 'version': '02.09.00.74',
                                          'post_process': ['"C:\\Py\\python.exe" "C:\\BambuPrintOptimizer\\bambu_optimizer.py" --goal balanced']})
    w(os.path.join(acct, OLD + '.info'), 'sync_info = \nuser_id = 2132877600\nsetting_id = PPUS1\nbase_id = GP158\nupdated_time = 1\n')
    # 1.1.x default-folder preset: marked, not synced
    w(os.path.join(dflt, OLD + '.json'), {'name': OLD, 'description': bp.MARK, 'post_process': ['"C:\\X\\PrintOptimizer.exe" --goal balanced'], 'version': '1'})
    # unrelated user presets
    other = os.path.join(d, 'user', '777', 'process', OLD + '.json'); w(other, {'name': OLD, 'post_process': ['C:\\other.exe']})
    clash = os.path.join(acct, '0.24mm H2S EmberCheck Speed.json'); w(clash, {'name': '0.24mm H2S EmberCheck Speed', 'post_process': []})
    mine = os.path.join(acct, 'My fine.json'); w(mine, {'name': 'My fine'})

    cmd = '"C:\\K\\EmberCheck.exe" --goal {goal}'
    written = bp.install(cmd, d, os.path.join(app, 'm.json'), log=q, backup_dir=bk)
    assert len(written) == 9 * 3 - 1, len(written)             # 9 x (2132877600, 777, default) minus the user's clash
    j = json.load(open(os.path.join(acct, '0.16mm H2S EmberCheck Quality.json')))
    assert j['inherits'] == '0.16mm Standard @BBL H2S' and j['post_process'] == ['"C:\\K\\EmberCheck.exe" --goal quality'] and bp.MARK in j['description']
    assert json.load(open(clash))['post_process'] == []        # user's own same-named preset untouched
    # migration: synced legacy -> cleared (kept, marked for upload); unsynced marked -> deleted; unrelated untouched
    o = json.load(open(os.path.join(acct, OLD + '.json'))); oi = bp._read_info(os.path.join(acct, OLD + '.info'))
    assert o['post_process'] == [] and 'Replaced by' in o['description'] and oi['setting_id'] == 'PPUS1' and oi['sync_info'] == 'update'
    assert not os.path.exists(os.path.join(dflt, OLD + '.json'))
    assert json.load(open(other))['post_process'] == ['C:\\other.exe']
    assert len(os.listdir(os.path.join(bk, '2132877600'))) == 2 and len(os.listdir(os.path.join(bk, 'default'))) == 1

    # re-install over itself keeps cloud ids of synced new presets
    p = os.path.join(acct, '0.20mm H2S EmberCheck Balanced.info')
    bp._write_info(p, {'sync_info': '', 'user_id': '2132877600', 'setting_id': 'PPUS9', 'base_id': 'GP0.20', 'updated_time': '5'})
    bp.install(cmd, d, os.path.join(app, 'm.json'), log=q, backup_dir=bk)
    assert bp._read_info(p)['setting_id'] == 'PPUS9' and bp._read_info(p)['sync_info'] == 'update'

    bp.remove(d, os.path.join(app, 'm.json'), log=q)
    assert not os.path.exists(os.path.join(dflt, '0.20mm H2S EmberCheck Balanced.json'))       # unsynced: deleted
    assert not os.path.exists(os.path.join(acct, '0.16mm H2S EmberCheck Speed.json'))
    j = json.load(open(os.path.join(acct, '0.20mm H2S EmberCheck Balanced.json')))            # synced: cleared, kept
    assert j['post_process'] == [] and bp.MARK not in j['description']
    assert os.path.exists(other) and os.path.exists(mine) and os.path.exists(clash)
    print('test_presets: OK (%d presets for H2S 0.4: %s)' % (len(expected), ', '.join(expected)))


def real_conf_case():
    """Andrew's real layout: conf with '# MD5 checksum' trailer, printer only in presets.machine, no "models",
    app.sync_user_preset false, empty user/*/machine folders, a marked 1.1.x preset in the account folder that
    had a cloud id. Expect: 9 presets in each folder, the old preset DELETED (sync off), no access code in logs."""
    d = tempfile.mkdtemp(); app = tempfile.mkdtemp(); logs = []
    w(os.path.join(d, 'system', 'BBL.json'), {'version': '02.09.00.74'})
    w(os.path.join(d, 'system', 'BBL', 'machine', H2S + '.json'), {'printer_model': 'Bambu Lab H2S', 'default_print_profile': '0.20mm Standard @BBL H2S'})
    for n in ('0.16mm Standard @BBL H2S', '0.20mm Standard @BBL H2S', '0.24mm Standard @BBL H2S', '0.12mm High Quality @BBL H2S'):
        sysproc(d, n, [H2S])
    conf = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'BambuStudio.conf'), encoding='utf-8').read()
    w(os.path.join(d, 'BambuStudio.conf'), conf)
    try:
        json.loads(conf); raise AssertionError('fixture should not be plain JSON')
    except ValueError:
        pass
    for uid in ('default', '2132877600'):
        os.makedirs(os.path.join(d, 'user', uid, 'machine'), exist_ok=True)      # exist, but empty
    acct = os.path.join(d, 'user', '2132877600', 'process')
    w(os.path.join(acct, OLD + '.json'), {'name': OLD, 'description': bp.MARK, 'post_process': ['"C:\\X\\PrintOptimizer.exe" --goal balanced']})
    w(os.path.join(acct, OLD + '.info'), 'sync_info = \nuser_id = 2132877600\nsetting_id = PPUS1\nbase_id = GP158\nupdated_time = 1\n')

    c = bp.load_conf(d)
    assert c['presets']['machine'] == H2S and c['app']['preset_folder'] == '2132877600' and not bp.sync_enabled(c)
    assert bp.installed_printers(d, os.path.join(d, 'system')) == [H2S]
    st = {}
    written = bp.install('"C:\\K\\EmberCheck.exe" --goal {goal}', d, os.path.join(app, 'm.json'), log=logs.append,
                         backup_dir=os.path.join(app, 'bk'), stats=st)
    assert st['status'] == 'ok' and len(written) == 18, (st.get('status'), len(written))
    assert not os.path.exists(os.path.join(acct, OLD + '.json')) and not os.path.exists(os.path.join(acct, OLD + '.info'))
    assert st['removed'] and not st['cleared']
    text = bp.status_text(st)
    assert 'Added 9 EmberCheck presets for H2S' in text and 'delete them in Bambu Studio' not in text, text
    assert not any('SECRET' in m for m in logs) and 'SECRET' not in text
    # uninstall with sync off: everything of ours deleted, even with a cloud id
    bp._write_info(os.path.join(acct, '0.20mm H2S EmberCheck Balanced.info'), {'setting_id': 'PPUS9', 'updated_time': '1'})
    bp.remove(d, os.path.join(app, 'm.json'), log=logs.append)
    assert not [f for f in os.listdir(acct) if f.endswith('.json')], os.listdir(acct)
    # nothing detectable -> clear "noprinter" status, no files
    w(os.path.join(d, 'BambuStudio.conf'), '{"app": {"preset_folder": ""}}\n# MD5 checksum 00\n')
    st2 = {}
    assert bp.install('x {goal}', d, None, log=logs.append, stats=st2) == [] and st2['status'] == 'noprinter'
    assert 'No Bambu Lab printer was selected or found' in bp.status_text(st2)
    print('test_presets real-conf case: OK')


MODELS = {   # synthetic system profiles: model -> (short, process tag, nozzles)
    'Bambu Lab X1 Carbon': ('X1C', 'X1C', ('0.2', '0.4', '0.6', '0.8')),
    'Bambu Lab P1S': ('P1S', 'P1P', ('0.4', '0.6')),
    'Bambu Lab A1 mini': ('A1 mini', 'A1M', ('0.4',)),
    'Bambu Lab H2S': ('H2S', 'H2S', ('0.4',)),
}


def synth(d):
    w(os.path.join(d, 'system', 'BBL.json'), {'version': '02.09.01.70',
      'machine_model_list': [{'name': m} for m in ('Bambu Lab X1 Carbon', 'Bambu Lab P1S', 'Bambu Lab A1 mini', 'Bambu Lab H2S')]})
    for model, (_, tag, nozzles) in MODELS.items():
        for nz in nozzles:
            mach = '%s %s nozzle' % (model, nz)
            dl = {'0.2': '0.10', '0.4': '0.20', '0.6': '0.30', '0.8': '0.40'}[nz]
            suf = '' if nz == '0.4' else ' %s nozzle' % nz
            w(os.path.join(d, 'system', 'BBL', 'machine', mach + '.json'),
              {'name': mach, 'printer_model': model, 'default_print_profile': '%smm Standard @BBL %s%s' % (dl, tag, suf)})
            base = float(dl)
            for lh in (base - 0.04, base, base + 0.04):
                sysproc(d, '%.2fmm Standard @BBL %s%s' % (lh, tag, suf), [mach])
    os.makedirs(os.path.join(d, 'user', 'default', 'process'), exist_ok=True)


def multi_printer_case():
    """X1C (4 nozzles), P1S (2), A1 mini, H2S: names, inherits, compatible_printers per nozzle; --printers parsing;
    detection from the conf; pruning when a printer is deselected; 1.2-1.4 'AI' preset tweaks carried over;
    a user's own preset that calls PrintOptimizer.exe is repointed to EmberCheck.exe."""
    d = tempfile.mkdtemp(); app = tempfile.mkdtemp(); q = lambda m: None
    synth(d); sysd = os.path.join(d, 'system')
    assert [m for m, _, _ in bp.available_models(sysd)] == list(MODELS)
    assert bp.resolve_models('x1c; P1S,a1 mini;Bambu Lab H2S;nonsense', sysd) == list(MODELS)
    # conf: X1C + A1 mini set up in Bambu Studio (contains an access code that must never be logged)
    w(os.path.join(d, 'BambuStudio.conf'), json.dumps({'app': {'preset_folder': ''}, 'access_code': {'X': 'SECRET123'},
      'models': [{'model': 'Bambu Lab X1 Carbon', 'nozzle_diameter': '0.4;0.6', 'vendor': 'BBL'},
                 {'model': 'Bambu Lab A1 mini', 'nozzle_diameter': '0.4', 'vendor': 'BBL'}]}) + '\n# MD5 checksum 00\n')
    det = set(bp.model_of(n, sysd) for n in bp.installed_printers(d, sysd))
    assert det == {'Bambu Lab X1 Carbon', 'Bambu Lab A1 mini'}, det
    pdir = os.path.join(d, 'user', 'default', 'process')
    # 1.4 "AI" preset with a user tweak, and the user's own preset calling the 1.x exe
    w(os.path.join(pdir, '0.20mm H2S AI Balanced.json'), {'name': '0.20mm H2S AI Balanced', 'inherits': '0.20mm Standard @BBL H2S',
      'description': 'Created by Bambu Print Optimizer', 'post_process': ['"C:\\Old\\PrintOptimizer.exe" --goal balanced'],
      'wall_loops': '4', 'setting_id': 'PPUSold'})
    w(os.path.join(pdir, 'My PETG.json'), {'name': 'My PETG', 'post_process': ['"C:\\Users\\a\\AppData\\Local\\Programs\\PrintOptimizer\\PrintOptimizer.exe" --goal quality --no-accel']})
    logs = []; st = {}
    cmd = '"C:\\Users\\a\\AppData\\Local\\Programs\\EmberCheck\\EmberCheck.exe" --goal {goal}'
    written = bp.install(cmd, d, os.path.join(app, 'm.json'), log=logs.append, backup_dir=os.path.join(app, 'bk'), stats=st,
                         models=bp.resolve_models('X1C;P1S;A1 mini;H2S', sysd))
    names = sorted(os.path.basename(x)[:-5] for x in written)
    # 3 layer heights x 3 goals per machine preset: X1C 4 + P1S 2 + A1 mini 1 + H2S 1 = 8 machines
    assert len(written) == 8 * 9, len(written)
    for n, parent, mach in (('0.20mm X1C EmberCheck Balanced', '0.20mm Standard @BBL X1C', 'Bambu Lab X1 Carbon 0.4 nozzle'),
                            ('0.30mm X1C 0.6 EmberCheck Speed', '0.30mm Standard @BBL X1C 0.6 nozzle', 'Bambu Lab X1 Carbon 0.6 nozzle'),
                            ('0.10mm X1C 0.2 EmberCheck Quality', '0.10mm Standard @BBL X1C 0.2 nozzle', 'Bambu Lab X1 Carbon 0.2 nozzle'),
                            ('0.44mm X1C 0.8 EmberCheck Balanced', '0.44mm Standard @BBL X1C 0.8 nozzle', 'Bambu Lab X1 Carbon 0.8 nozzle'),
                            ('0.20mm P1S EmberCheck Balanced', '0.20mm Standard @BBL P1P', 'Bambu Lab P1S 0.4 nozzle'),
                            ('0.16mm A1 mini EmberCheck Quality', '0.16mm Standard @BBL A1M', 'Bambu Lab A1 mini 0.4 nozzle'),
                            ('0.24mm H2S EmberCheck Speed', '0.24mm Standard @BBL H2S', 'Bambu Lab H2S 0.4 nozzle')):
        assert n in names, (n, names[:12])
        j = json.load(open(os.path.join(pdir, n + '.json')))
        assert j['inherits'] == parent and j['compatible_printers'] == [mach], (n, j['inherits'], j['compatible_printers'])
        assert j['post_process'][0].startswith('"C:\\Users\\a\\AppData\\Local\\Programs\\EmberCheck\\EmberCheck.exe" --goal ') and bp.MARK in j['description']
    # AI preset retired, tweak carried over to the EmberCheck preset (without the old cloud id)
    assert not os.path.exists(os.path.join(pdir, '0.20mm H2S AI Balanced.json'))
    k = json.load(open(os.path.join(pdir, '0.20mm H2S EmberCheck Balanced.json')))
    assert k['wall_loops'] == '4' and 'setting_id' not in k and k['post_process'] == ['"C:\\Users\\a\\AppData\\Local\\Programs\\EmberCheck\\EmberCheck.exe" --goal balanced']
    assert os.path.join(pdir, '0.20mm H2S EmberCheck Balanced.json') in st['migrated']
    # user's own preset repointed, arguments kept
    assert json.load(open(os.path.join(pdir, 'My PETG.json')))['post_process'] == ['"C:\\Users\\a\\AppData\\Local\\Programs\\EmberCheck\\EmberCheck.exe" --goal quality --no-accel']
    assert len(st['repointed']) == 1
    text = bp.status_text(st)
    assert 'Added 72 EmberCheck presets' in text and 'X1C' in text and 'A1 mini' in text and 'EmberCheck.exe' in text, text
    assert not any('SECRET123' in m for m in logs) and 'SECRET123' not in text
    assert json.load(open(os.path.join(app, 'm.json')))['models'] == list(MODELS)
    # deselect P1S and H2S -> their EmberCheck presets are retired (unsynced: deleted)
    st = {}
    bp.install(cmd, d, os.path.join(app, 'm.json'), log=q, stats=st, models=['Bambu Lab X1 Carbon', 'Bambu Lab A1 mini'])
    left = sorted(f[:-5] for f in os.listdir(pdir) if f.endswith('.json') and ' EmberCheck ' in f)
    assert len(left) == 5 * 9 and not any(' P1S ' in x or ' H2S ' in x for x in left), left
    assert len(st['pruned']) == 3 * 9
    # default (no selection) = printers set up in Bambu Studio: all X1C nozzles in the conf? the conf lists X1C + A1 mini
    st = {}
    bp.install(cmd, d, None, log=q, stats=st)
    assert st['status'] == 'ok' and all(('X1C' in n or 'A1 mini' in n) for n in st['names']), st['names'][:5]
    # repoint-only (installer with the presets task unchecked)
    w(os.path.join(pdir, 'Old2.json'), {'name': 'Old2', 'post_process': ['C:\\PO\\PrintOptimizer.exe --goal speed']})
    ch = bp.repoint_all(cmd, d, None, q)
    assert ch == [os.path.join(pdir, 'Old2.json')] and json.load(open(ch[0]))['post_process'] == ['"C:\\Users\\a\\AppData\\Local\\Programs\\EmberCheck\\EmberCheck.exe" --goal speed']
    print('test_presets multi-printer case: OK (X1C 0.2/0.4/0.6/0.8, P1S 0.4/0.6, A1 mini, H2S: %d presets; prune, AI migration, repoint)' % len(written))


def real_profiles_case():
    """Bambu Studio 02.09 system profiles (if present on this box): every model gets presets inheriting a real
    system process preset that is compatible with that exact machine preset."""
    sysd = os.environ.get('EMBERCHECK_SYSDIR', '/workspace/winbuild/prefix/drive_c/users/box/AppData/Roaming/BambuStudio/system')
    if not os.path.exists(os.path.join(sysd, 'BBL.json')):
        print('test_presets real-profiles case: skipped (no system profiles)'); return
    d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, 'user', 'default', 'process'))
    os.symlink(sysd, os.path.join(d, 'system'))
    avail = bp.available_models(sysd)
    assert len(avail) >= 14, [m for m, _, _ in avail]
    sel = bp.resolve_models('X1C;P1S;A1 mini;H2S', sysd)
    assert sel == ['Bambu Lab X1 Carbon', 'Bambu Lab P1S', 'Bambu Lab A1 mini', 'Bambu Lab H2S'], sel
    todo = bp.plan(d, sysd, [m for m, _, _ in avail])
    per = {}
    for name, parent, goal, base_id, mach in todo:
        pj = json.load(open(os.path.join(sysd, 'BBL', 'process', parent + '.json')))
        assert mach in pj.get('compatible_printers', []), (name, parent, mach)
        per.setdefault(bp.model_of(mach, sysd), set()).add(mach)
    missing = [m for m, _, ns in avail if m not in per]
    assert not missing, missing
    ex = [t[0] for t in todo if t[0] in ('0.20mm X1C EmberCheck Balanced', '0.20mm P1S EmberCheck Balanced', '0.20mm A1 mini EmberCheck Balanced', '0.20mm H2S EmberCheck Balanced')]
    assert len(ex) == 4, ex
    print('test_presets real-profiles case: OK (%d models, %d machine presets, %d presets, e.g. %s)' % (
        len(per), sum(len(v) for v in per.values()), len(todo), ', '.join(ex)))


if __name__ == '__main__':
    main()
    real_conf_case()
    multi_printer_case()
    real_profiles_case()
