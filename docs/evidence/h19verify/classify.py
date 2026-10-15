import json,sys,os,glob,importlib.util
os.environ['AGENT_GUARD_ROOT']='/work/repo';os.environ['AGENT_GUARD_UNDO']='0';os.environ.pop('AGENT_GUARD_JUDGE',None)
R=sys.argv[1]
s=importlib.util.spec_from_file_location('gp',R+'/guard.py');g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
out=[]
for f in sorted(glob.glob(os.path.expanduser('~/agent-guard-bench-holdout-19/*_cases.jsonl'))):
    for l in open(f):
        r=json.loads(l); d=g.decide_full(r['command']); v=d['verdict']; o=d.get('origin')
        j='deny' if v in('block','deny') else ('undo' if o=='recoverable' else 'allow')
        out.append(dict(r,judge=j,verdict=v,origin=o,reason=d.get('reason'),dd={k:str(x)[:300] for k,x in d.items()}))
json.dump(out,open('classified.json','w'),indent=1)
import collections
c=collections.Counter((r['expect'],r['judge']) for r in out);print(c,len(out))
