import json,sys,os,glob
root=sys.argv[1]; name=sys.argv[2]; kind=sys.argv[3]; out=sys.argv[4]
idx={}
for f in glob.glob(os.path.join(root,kind,'**','*.json'),recursive=True):
    try: d=json.load(open(f))
    except Exception: continue
    if 'name' in d: idx[d['name']]=d
def res(n):
    d=idx[n]; base=res(d['inherits']) if d.get('inherits') else {}
    m=dict(base); m.update(d); return m
d=res(name); d.pop('inherits',None); d['from']='User'; d['is_custom_defined']='1'
pass
json.dump(d,open(out,'w'),indent=1); print(out, d.get('filament_type'), d.get('printer_model'))
