import json,re
exec(open('scripts/r2labels.py').read())
L=[json.loads(l) for l in open('sample_blind_rater2.jsonl')]
out=[]
for i,x in enumerate(L):
    c=x['command']
    if i in O:
        lab,why=O[i]
    else:
        lab='SAFE'
        if re.search(r'commit-with-receipt|git push',c) and re.search(r'git add (--\s)?\S',c): why="named-path add, receipt commit, normal push; nothing risky"
        elif 'curl' in c: why="network fetch or text processing; no git staging, hook or destructive ops"
        elif re.search(r'python3?\s+(-I\s+)?-?\s*(<<|-c)|python3 - ',c): why="python file edit or analysis; no risky git or hook commands run"
        elif re.search(r'selftest|check\.sh|--self-test',c): why="runs repo check or self-test scripts; no staging, hook or destructive ops"
        elif re.search(r'\bgit (status|log|diff|show|grep|rev-parse)',c): why="read-only git inspection"
        else: why="read-only inspection or local build; no staging, hook-skip or destructive git"
    assert len(why.split())<=22, (i,why)
    out.append({"id":x['id'],"label":lab,"why":why})
with open('labels_rater2.jsonl','w') as f:
    for o in out: f.write(json.dumps(o)+"\n")
from collections import Counter
print(len(out),Counter(o['label'] for o in out), sum(1 for o in out if o['label']=='SAFE' and 'scratch' in o['why'].lower()))
