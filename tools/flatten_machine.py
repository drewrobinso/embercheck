import json,glob,os,sys
root=sys.argv[1]; name=sys.argv[2]; out=sys.argv[3]
idx={}
for f in glob.glob(os.path.join(root,'machine','*.json')):
    d=json.load(open(f)); idx[d.get('name')]=d
def res(n):
    d=idx[n]; base=res(d['inherits']) if d.get('inherits') else {}
    m=dict(base)
    for inc in d.get('include',[]):
        m.update({k:v for k,v in idx[inc].items() if k not in('name','type','from','instantiation')})
    m.update({k:v for k,v in d.items() if k!='include'}); return m
d=res(name); d.pop('inherits',None); d.pop('include',None)
json.dump(d,open(out,'w'),indent=1); print(len(d['machine_start_gcode']), d['layer_change_gcode'][:40])
