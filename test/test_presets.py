"""Self-contained test for src/bambu_presets.py (multi-account folders, legacy upgrade, cloud-synced uninstall).
Run: python test/test_presets.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import bambu_presets as bp

N = '0.20mm Standard @BBL H2S - Optimized'


def w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def main():
    d = tempfile.mkdtemp(); app = tempfile.mkdtemp()
    w(os.path.join(d, 'system', 'BBL.json'), {'version': '02.09.00.74'})
    w(os.path.join(d, 'system', 'BBL', 'machine', 'Bambu Lab H2S 0.4 nozzle.json'), {'default_print_profile': '0.20mm Standard @BBL H2S'})
    w(os.path.join(d, 'system', 'BBL', 'process', '0.20mm Standard @BBL H2S.json'), {'setting_id': 'GP158'})
    w(os.path.join(d, 'BambuStudio.conf'), {'app': {'preset_folder': '555'}, 'models': [{'model': 'Bambu Lab H2S', 'nozzle_diameter': '0.4', 'vendor': 'BBL'}]})
    acct = os.path.join(d, 'user', '2132877600', 'process')
    w(os.path.join(acct, N + '.json'), {'name': N, 'inherits': '0.20mm Standard @BBL H2S', 'version': '02.09.00.74', 'sparse_infill_density': '25%',
                                        'post_process': ['"C:\\Python312\\python.exe" "C:\\BambuPrintOptimizer\\bambu_optimizer.py" --goal balanced']})
    w(os.path.join(acct, N + '.info'), 'sync_info = \nuser_id = 2132877600\nsetting_id = PPUS1\nbase_id = GP158\nupdated_time = 1\n')
    other = os.path.join(d, 'user', '777', 'process', N + '.json')
    w(other, {'name': N, 'post_process': ['C:\\other.exe'], 'version': '02.09.00.74'})
    mine = os.path.join(acct, 'My fine.json'); w(mine, {'name': 'My fine', 'version': '02.09.00.74'})

    cmd = '"C:\\X\\PrintOptimizer.exe" --goal balanced'
    written = bp.install(cmd, d, os.path.join(app, 'm.json'), log=lambda m: None, backup_dir=os.path.join(app, 'bk'))
    folders = sorted(os.path.basename(os.path.dirname(os.path.dirname(p))) for p in written)
    assert folders == ['2132877600', '555', 'default'], folders                      # all accounts + default + active
    j = json.load(open(os.path.join(acct, N + '.json')))
    assert j['post_process'] == [cmd] and bp.MARK in j['description'] and j['sparse_infill_density'] == '25%'  # legacy upgraded, tweaks kept
    info = bp._read_info(os.path.join(acct, N + '.info'))
    assert info['setting_id'] == 'PPUS1' and info['sync_info'] == 'update' and int(info['updated_time']) > 1  # cloud id kept, upload marked
    assert len(os.listdir(os.path.join(app, 'bk', '2132877600'))) == 2                # backup .json + .info
    assert json.load(open(other))['post_process'] == ['C:\\other.exe']                # unrelated same-name preset untouched

    bp.remove(d, os.path.join(app, 'm.json'), log=lambda m: None)
    assert not os.path.exists(os.path.join(d, 'user', 'default', 'process', N + '.json'))   # unsynced: deleted
    assert not os.path.exists(os.path.join(d, 'user', '555', 'process', N + '.json'))
    j = json.load(open(os.path.join(acct, N + '.json')))
    assert j['post_process'] == [] and bp.MARK not in j['description']               # synced: neutralized, not deleted
    assert os.path.exists(other) and os.path.exists(mine)
    print('test_presets: OK')


if __name__ == '__main__':
    main()
