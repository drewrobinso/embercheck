"""Self-contained test for src/bambu_presets.py: "<layer>mm <printer> AI <Goal>" naming, multi-account folders,
migration of 1.x "... - Optimized" presets (marked / legacy, synced / unsynced), uninstall.
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
    w(os.path.join(d, 'BambuStudio.conf'), {'app': {'preset_folder': '2132877600'}, 'models': [{'model': 'Bambu Lab H2S', 'nozzle_diameter': '0.4', 'vendor': 'BBL'}]})

    expected = ['%s H2S AI %s' % (l, g) for l in ('0.16mm', '0.20mm', '0.24mm') for g in ('Balanced', 'Speed', 'Quality')]
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
    clash = os.path.join(acct, '0.24mm H2S AI Speed.json'); w(clash, {'name': '0.24mm H2S AI Speed', 'post_process': []})
    mine = os.path.join(acct, 'My fine.json'); w(mine, {'name': 'My fine'})

    cmd = '"C:\\X\\PrintOptimizer.exe" --goal {goal}'
    written = bp.install(cmd, d, os.path.join(app, 'm.json'), log=q, backup_dir=bk)
    assert len(written) == 9 * 3 - 1, len(written)             # 9 x (2132877600, 777, default) minus the user's clash
    j = json.load(open(os.path.join(acct, '0.16mm H2S AI Quality.json')))
    assert j['inherits'] == '0.16mm Standard @BBL H2S' and j['post_process'] == ['"C:\\X\\PrintOptimizer.exe" --goal quality'] and bp.MARK in j['description']
    assert json.load(open(clash))['post_process'] == []        # user's own same-named preset untouched
    # migration: synced legacy -> cleared (kept, marked for upload); unsynced marked -> deleted; unrelated untouched
    o = json.load(open(os.path.join(acct, OLD + '.json'))); oi = bp._read_info(os.path.join(acct, OLD + '.info'))
    assert o['post_process'] == [] and 'Replaced by' in o['description'] and oi['setting_id'] == 'PPUS1' and oi['sync_info'] == 'update'
    assert not os.path.exists(os.path.join(dflt, OLD + '.json'))
    assert json.load(open(other))['post_process'] == ['C:\\other.exe']
    assert len(os.listdir(os.path.join(bk, '2132877600'))) == 2 and len(os.listdir(os.path.join(bk, 'default'))) == 1

    # re-install over itself keeps cloud ids of synced new presets
    p = os.path.join(acct, '0.20mm H2S AI Balanced.info')
    bp._write_info(p, {'sync_info': '', 'user_id': '2132877600', 'setting_id': 'PPUS9', 'base_id': 'GP0.20', 'updated_time': '5'})
    bp.install(cmd, d, os.path.join(app, 'm.json'), log=q, backup_dir=bk)
    assert bp._read_info(p)['setting_id'] == 'PPUS9' and bp._read_info(p)['sync_info'] == 'update'

    bp.remove(d, os.path.join(app, 'm.json'), log=q)
    assert not os.path.exists(os.path.join(dflt, '0.20mm H2S AI Balanced.json'))       # unsynced: deleted
    assert not os.path.exists(os.path.join(acct, '0.16mm H2S AI Speed.json'))
    j = json.load(open(os.path.join(acct, '0.20mm H2S AI Balanced.json')))            # synced: cleared, kept
    assert j['post_process'] == [] and bp.MARK not in j['description']
    assert os.path.exists(other) and os.path.exists(mine) and os.path.exists(clash)
    print('test_presets: OK (%d presets for H2S 0.4: %s)' % (len(expected), ', '.join(expected)))


if __name__ == '__main__':
    main()
