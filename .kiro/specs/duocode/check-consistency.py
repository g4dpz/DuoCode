# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 The DuoCode authors (see NOTICE)
# Specification consistency checks (not application code). Run: python3 .kiro/specs/duocode/check-consistency.py
# Task 2.7 in tasks.md turns this into the TS-DOC CI job.
import re,glob,os,yaml,hashlib,sys
import pathlib
root=str(pathlib.Path(__file__).resolve().parents[3])+'/'
d=root+'.kiro/specs/duocode/'
files={os.path.basename(f):open(f).read() for f in sorted(glob.glob(d+'*.md'))}
files['README.md']=open(root+'README.md').read()
files['CONTRIBUTING.md']=open(root+'CONTRIBUTING.md').read()
files['NOTICE']=open(root+'NOTICE').read()
files['openapi.yaml']=open(root+'openapi/openapi.yaml').read()
files['copilot-instructions.md']=open(root+'.github/copilot-instructions.md').read()
spec=[k for k in files if k.endswith('.md') and k not in('README.md','CONTRIBUTING.md')]
results=[]  # (name, ok, detail)
def check(name,problems):
    results.append((name,not problems,sorted(set(problems))))
# 1 requirements in traceability
tr=files['traceability.md']; req=files['requirements.md']
reqnums=[int(x) for x in re.findall(r'^### R(\d+):',req,re.M)]
check('C01 every requirement R1..R21 defined and in traceability matrix',[f'R{i} missing' for i in range(1,22) if i not in reqnums or not re.search(rf'^\| R{i} \|',tr,re.M)]+([] if reqnums==list(range(1,22)) else ['requirement numbering not 1..21']))
# 2 criterion refs
counts={}
for m in re.finditer(r'^### R(\d+):.*?(?=^### R|^## )',req,re.M|re.S):
    counts[int(m.group(1))]=len(re.findall(r'^\d+\. ',m.group(0),re.M))
pr=[]
for fn,t in files.items():
    for m in re.finditer(r'\bR(\d+)\.(\d+)\b',t):
        r,c=int(m.group(1)),int(m.group(2))
        if r not in counts or c>counts[r]: pr.append(f'{fn}: R{r}.{c} does not exist')
check('C02 every R<n>.<m> criterion reference exists',pr)
# 3 TS groups and conc
ts=files['test-strategy.md']
defined=set(re.findall(r'\| (TS-[A-Z]+) \|\s*$',ts,re.M))|set(re.findall(r'\| (TS-[A-Z]+)\s*\|',ts))
defined={g for g in defined if re.fullmatch(r'TS-[A-Z]+',g)}
conc_def=set(int(x) for x in re.findall(r'^\| TS-CONC-(\d+) \|',ts,re.M))
pr=[]
for fn,t in files.items():
    for g in set(re.findall(r'TS-[A-Z]+\b(?!-\d)',t)):
        if g not in defined: pr.append(f'{fn}: {g} not defined')
    for n in set(re.findall(r'TS-CONC-(\d+)',t)):
        if int(n) not in conc_def: pr.append(f'{fn}: TS-CONC-{n} not defined')
check(f'C03 every TS group and TS-CONC id referenced is defined ({len(defined)} groups, {len(conc_def)} concurrency scenarios)',pr)
# 4 decision ids
reg=req
ids={}
for k in ('ND','C','CL','RD','OD','CR','CH','OI','LI'):
    nums=[int(x) for x in re.findall(rf'^\| {k}-(\d+) \|',req,re.M)]
    ids[k]=max(nums) if nums else 0   # the register is the source of truth; any reference above it is unknown
pr=[]
for fn,t in files.items():
    for k,mx in ids.items():
        for n in set(re.findall(rf'(?<![A-Za-z]){k}-(\d+)\b',t)):
            if int(n)<1 or int(n)>mx: pr.append(f'{fn}: {k}-{n} unknown')
for k,mx in ids.items():
    for n in range(1,mx+1):
        if not re.search(rf'\| {k}-{n}\b',reg): pr.append(f'{k}-{n} not in decision register')
check('C04 every decision ID is defined in the register and none is unknown',pr)
# 5 stale terms
stale={r'\bQ(1[0-3]|[1-9])\b':'revision 2 Q-ids',r'`?tok:':'old tok: scopes',r'rematch_of':'old rematch_of column',r'revision-3-review-package':'old review package name',r'5-minute block|5 minutes block':'old auth-fail block', r'UNIQUE \(rematch_of\)':'old constraint',r'Sent from my iPhone':'email signature'}
pr=[]
for fn,t in files.items():
    if fn=='revision-3.1-review-package.md': continue
    for pat,desc in stale.items():
        if re.search(pat,t): pr.append(f'{fn}: {desc}')
check('C05 no stale revision 2/3 identifiers or the email signature in the specification, README or licensing files',pr)
# 6 section refs
def headings(t): return set(re.findall(r'^#{2,3} (\d+(?:\.\d+)?[a-z]?)[\. ]',t,re.M))
H={k:headings(v) for k,v in files.items()}
pat=re.compile(r'`?(design|deployment|security-assessment|database-schema|state-machine|test-strategy)\.md`?,? (?:sections?|section) ([\d\.]+[a-z]?(?:(?:, | and | to )[\d\.]+[a-z]?)*)')
pr=[]
for fn,t in files.items():
    for m in pat.finditer(t):
        doc=m.group(1)+'.md'
        for num in re.findall(r'\d+(?:\.\d+)?[a-z]?',m.group(2)):
            if num not in H[doc]: pr.append(f'{fn}: {doc} section {num} missing')
check('C06 every "<file>.md section N" reference resolves to a heading',pr)
# 7 openapi vs design table
oa=yaml.safe_load(files['openapi.yaml'])
ops={}
for path,item in oa['paths'].items():
    for meth,op in item.items():
        if meth in('get','post','put','delete','patch'): ops[(meth.upper(),path)]=op['operationId']
design=files['design.md']
tbl=re.search(r'\| Operation \| Method and path \| Credential \|.*?\n\n',design,re.S).group(0)
rows=re.findall(r'\| [^|]+ \| `(GET|POST|PUT|DELETE) ([^`]+)` \|',tbl)
pr=[]
dset={(m,p) for m,p in rows}
for k in ops:
    if k not in dset: pr.append(f'OpenAPI {k} missing in design.md table')
for k in dset:
    if k not in ops: pr.append(f'design.md {k} missing in OpenAPI')
check(f'C07 design.md API table matches OpenAPI paths and methods ({len(ops)} operations)',pr)
# 8 error codes
enum=set(oa['components']['schemas']['ErrorCode']['enum'])
fam=re.compile(r'\b(INVALID_[A-Z_]+|GAME_[A-Z_]+|ATTEMPTS_EXHAUSTED|ALREADY_SOLVED|CODE_ALREADY_SET|IDEMPOTENCY_CONFLICT|REMATCH_ALREADY_CREATED|RATE_LIMITED|SERVICE_UNAVAILABLE|INTERNAL_ERROR)\b')
pr=[]
for fn,t in files.items():
    for c in set(fam.findall(t)):
        if c not in enum: pr.append(f'{fn}: {c} not in OpenAPI ErrorCode')
check(f'C08 every error code named anywhere exists in the OpenAPI ErrorCode enum ({len(enum)} codes)',pr)
# 9 states
gs=set(oa['components']['schemas']['GameState']['enum'])
ddl=re.search(r"```sql\n(.*?)```",files['database-schema.md'],re.S).group(1)
dbst=set(re.findall(r"'([A-Z_]+)'",re.search(r"CREATE TYPE game_state AS ENUM\s*\((.*?)\);",ddl,re.S).group(1)))
sm=files['state-machine.md']
smst=set(re.findall(r'^\| `([A-Z_]+)` \| (?:Created|Both|Both players|Both joined)',sm,re.M))
pr=[]
if gs!=dbst: pr.append(f'OpenAPI GameState {sorted(gs)} != DB enum {sorted(dbst)}')
for st in gs:
    if f'`{st}`' not in sm: pr.append(f'state {st} missing in state-machine.md')
check('C09 game states agree between OpenAPI, database enum and state machine',pr)
# 10 table.column
tables=dict()
for m in re.finditer(r'CREATE TABLE (\w+) \((.*?)\n\);',ddl,re.S):
    cols=set(re.findall(r'^\s+(\w+)\s+(?:uuid|bigserial|bigint|smallint|text|boolean|bytea|timestamptz|jsonb|double precision|integer|game_state|credential_type)\b',m.group(2),re.M))
    tables[m.group(1)]=cols
pr=[]
for fn in spec:
    if fn=='revision-3.1-review-package.md': continue  # change notes name removed columns on purpose
    for m in re.finditer(r'`(\w+)\.(\w+)`',files[fn]):
        t,c=m.group(1),m.group(2)
        if t in tables and c not in tables[t]: pr.append(f'{fn}: {t}.{c} not a column')
check(f'C10 every `table.column` reference names a real column ({len(tables)} tables in the DDL)',pr)
# 11 config keys
cfgsec=design[design.index('## 13. Configuration'):design.index('## 14.')]
cfg=set(re.findall(r'^\| `([A-Z][A-Z0-9_]+)` \|',cfgsec,re.M))
pr=[]
allowed={'CODE_KEYRING_FILE','DATABASE_URL'}|cfg
for fn in spec:
    for k in set(re.findall(r'`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`',files[fn])):
        if k.startswith(('TS_','INVALID_','GAME_')): continue
        if k in enum or k in {'READ_ONLY','SPDX','SOURCE_DATE_EPOCH'}: continue  # SOURCE_DATE_EPOCH is a build variable, not application configuration
        if re.fullmatch(r'(WAITING_FOR_PLAYER|WAITING_FOR_CODES|PLAYER_[12]_WINS|DRAW|ACTIVE|COMPLETED|EXPIRED|NOT_STARTED|IN_PROGRESS|SOLVED|EXHAUSTED|DECRYPT_ONLY|ROTATED|SUPERSEDED|ROTATION_SIDE_EFFECT|REVOKED|CONSUMED|LIVE|ACCESS|INVITATION|REMATCH|EXPIRED_PENDING|ROTATION_OVERDUE|WARNING|STAGED)',k): continue
        if k not in allowed and not k.startswith(('RATE_LIMIT_','TTL_')) : pr.append(f'{fn}: {k} not in configuration table')
check(f'C11 every configuration key named in the specification is in design.md section 13 ({len(cfg)} keys)',pr)
# 12 deployment scopes vs design
dep=files['deployment.md']
scopes_dep=set(re.findall(r'^\| `((?:ip|pl):[a-z]+)` \|',dep,re.M))
scopes_des=set(re.findall(r'`((?:ip|pl):[a-z]+)`',design))
check('C12 rate-limit scopes agree between design.md and deployment.md',[f'{x} only in one' for x in scopes_dep^scopes_des])
# 13 licence
lic=open(root+'LICENSE','rb').read()
sha=hashlib.sha256(lic).hexdigest()
pr=[]
if sha!='0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0': pr.append('LICENSE checksum differs from FSF text recorded')
if b'GNU AFFERO GENERAL PUBLIC LICENSE' not in lic or b'Version 3, 19 November 2007' not in lic: pr.append('LICENSE header wrong')
if 'AGPL-3.0-only' not in files['NOTICE']: pr.append('NOTICE lacks AGPL-3.0-only')
GATE6_SHA={'NOTICE':'da4743ec575a99ea6009598f032976c6476676745febc95fd0a5f36a89b3aadf','CONTRIBUTING.md':'7fe3f313c4bae45b842340d8157848dbcdae72a96b47deffeb5e5cac8354756f'}   # as approved at Gate 6 (merge ea26b6f)
for fn,h in GATE6_SHA.items():
    if hashlib.sha256(open(root+fn,'rb').read()).hexdigest()!=h: pr.append(f'{fn} differs from the version approved at Gate 6 (a change reopens Gate 6)')
g6=bool(re.search(r'^- \[x\] 1\.6 ',files['tasks.md'],re.M))
if g6:
    # after Gate 6: no draft banner and no placeholders; NOTICE names exactly the LI-1 holders
    for fn in ('NOTICE','CONTRIBUTING.md'):
        if 'DRAFT' in files[fn]: pr.append(f'{fn} still carries the draft banner after Gate 6')
        if re.search(r'\[(LI-\d|COPYRIGHT HOLDER)',files[fn]): pr.append(f'{fn} still has a placeholder after Gate 6')
    li1=re.search(r'^\| LI-1 \|[^|]*\|[^|]*\| ([^|]*?)\. No affiliation shown \|',req,re.M)
    holders=re.findall(r'^Copyright \(C\) \d{4} (.+)$',files['NOTICE'],re.M)
    if not li1: pr.append('requirements.md LI-1 has no recorded answer')
    elif set(holders)!=set(x.strip() for x in li1.group(1).split(' and ')): pr.append(f'NOTICE holders {holders} differ from LI-1 ({li1.group(1)})')
    if 'LI-3' not in files['CONTRIBUTING.md']: pr.append('CONTRIBUTING.md does not record the outstanding legal review LI-3')
check(f'C13 licensing artefacts present, LICENSE is the FSF AGPL-3.0 text (sha256 {sha[:16]}...), NOTICE and CONTRIBUTING.md match the Gate 6 versions, NOTICE names AGPL-3.0-only, and no draft banner or placeholder remains',pr)
# 14 workflows yaml
pr=[]
for f in glob.glob(root+'.github/workflows/*.yml'):
    try: yaml.safe_load(open(f))
    except Exception as e: pr.append(f'{f}: {e}')
check('C14 GitHub workflow files parse as YAML',pr)
# 15 gate sign-offs: only Phase 1 gates may be marked done, each with a recorded owner sign-off; nothing else
pr=[]
tk=files['tasks.md']
lines=tk.splitlines()
DONE=re.compile(r'^\s*- \*\*Done \d{4}-\d{2}-\d{2}\.?\*\*',re.M)
SIGNED=re.compile(r'Signed off \d{4}-\d{2}-\d{2} by .+owner statement "[^"]*\S[^"]*"')
def entry_of(idx):
    out=[]
    for x in lines[idx+1:]:
        if x.startswith('- [') or x.startswith('#'): break
        out.append(x)
    return '\n'.join(out)
for idx,l in enumerate(lines):
    if re.match(r'- \[x\]',l):
        m=re.match(r'- \[x\] (1\.[1-6]) \*\*Gate|- \[x\] (1\.9) \*\*Phase 1 sign-off',l)
        ent=entry_of(idx)
        mp=re.match(r'- \[x\] (\d+)\.\d+[a-z]? ',l)
        if mp and int(mp.group(1))>=2:
            tid=l.split()[2]
            if not re.search(r'^- \[x\] 1\.9 ',tk,re.M): pr.append(f'task {tid} marked done before Phase 1 sign-off (1.9)')
            elif re.search(r'\*\*Gate|\*\*Phase \d+ sign-off',l):
                if not SIGNED.search(ent): pr.append(f'task {tid} (a gate) marked done without a recorded owner sign-off')
            elif not DONE.search(ent): pr.append(f'task {tid} marked done without a dated record (- **Done YYYY-MM-DD**)')
            continue
        if re.match(r'- \[x\] 1\.[78] ',l):
            if not DONE.search(ent): pr.append(f'{l[6:9]} marked done without a dated record (- **Done YYYY-MM-DD**)')
            continue
        if not m: pr.append('marked done but not a Phase 1 gate: '+l[:60])
        elif not SIGNED.search(ent): pr.append(f'task {m.group(1) or m.group(2)} marked done without a recorded owner sign-off')
if re.search(r'^- \[x\] 1\.9',tk,re.M) and len(re.findall(r'^- \[x\] 1\.[1-6] ',tk,re.M))<6: pr.append('1.9 marked done before all six gates')
if re.search(r'^- \[x\] 1\.9',tk,re.M) and len(re.findall(r'^- \[x\] 1\.[78] ',tk,re.M))<2: pr.append('1.9 marked done before 1.7 and 1.8 are complete')
if not re.search(r'^- \[[ x]\] 1\.9 .*1\.7 and 1\.8 are complete',tk,re.M): pr.append('1.9 does not list 1.7 and 1.8 as prerequisites')
awaiting=re.findall(r'^  - \*\*Reopened [^\n]*Awaiting an explicit owner confirmation',tk,re.M)
if awaiting:
    if re.search(r'^- \[x\] 1\.9',tk,re.M): pr.append('1.9 marked done while a reopened gate part awaits confirmation')
    for fn in ('requirements.md','traceability.md','tasks.md','revision-3.1-review-package.md'):
        if 'awaiting owner confirmation' not in files[fn]: pr.append(f'{fn} status does not mention the reopened gate part awaiting confirmation')
signed=re.findall(r'^- \[x\] (1\.[1-6]) ',tk,re.M)
check(f'C15 every ticked task carries its record (gates and 1.9 an owner statement, 1.7, 1.8 and later phases a dated Done line), and no later-phase task is ticked before 1.9 (signed: {", ".join(signed) or "none"})',pr)
# 16 baseline constants
pr=[]
def oa_resolve(node):
    seen=0
    while isinstance(node,dict) and '$ref' in node and seen<10:
        cur=oa
        for part in node['$ref'].lstrip('#/').split('/'): cur=cur[part]
        node=cur; seen+=1
    return node
if 'Code' not in oa['components']['schemas']: pr.append('schema Code is missing')
else:
    cs=oa_resolve({'$ref':'#/components/schemas/Code'})
    if cs.get('type')!='array' or cs.get('minItems')!=4 or cs.get('maxItems')!=4: pr.append('Code is not an array of exactly 4 items')
    it=oa_resolve(cs.get('items',{}))
    if it.get('type')!='integer' or it.get('minimum')!=1 or it.get('maximum')!=6: pr.append('Code items are not integers from 1 to 6')
check('C16 OpenAPI constrains codes to 4 symbols from 1..6',pr)
# 17 openapi nickname regex vs db regex
oan=oa['components']['schemas']['Nickname']['pattern']
dbn=re.search(r"nickname !~ E'(\[[^']+\])'",ddl).group(1)
oar=re.search(r'\[\^(.*?)\]\+',oan).group(1).replace('\\\\','\\')
dbr=dbn.strip('[]').replace('\\\\','\\')
pr=[] if oar.replace('\\u0000','\\u0001')==dbr else [f'OpenAPI class {oar} vs DB class {dbr}']
check('C17 nickname forbidden character classes agree between OpenAPI and database CHECK (NUL aside)',pr)
# 18 rotation key regex is v4 only
rk=oa['components']['parameters']['RotationIdempotencyKey']['schema']['pattern']
good=re.fullmatch(rk,'3f2b8c1e-5a4d-4c6e-9b7a-1d2e3f4a5b6c') and not re.fullmatch(rk,'3f2b8c1e-5a4d-1c6e-9b7a-1d2e3f4a5b6c') and not re.fullmatch(rk,'3f2b8c1e-5a4d-4c6e-7b7a-1d2e3f4a5b6c')
check('C18 OpenAPI rotation key pattern accepts v4 UUIDs and rejects v1 and wrong-variant values',[] if good else ['pattern wrong'])
# 19 decision register vs traceability decision map
def expand(text):
    out=set()
    for m in re.finditer(r'\b(OD|ND|CL|CR|RD|CH|LI|OI|C)-(\d+)(?: to (?:OD|ND|CL|CR|RD|CH|LI|OI|C)-(\d+))?',text):
        a=int(m.group(2)); b=int(m.group(3)) if m.group(3) else a
        for n in range(a,b+1): out.add(f'{m.group(1)}-{n}')
    return out
regids=set()
for m in re.finditer(r'^\| ((?:OD|ND|CL|CR|RD|CH|LI|OI|C)-\d+) \|',req,re.M): regids.add(m.group(1))
mapsec=tr[tr.index('## 4. Decision to requirement map'):]
mapids=set()
for m in re.finditer(r'^\| ([^|]+) \|',mapsec,re.M): mapids|=expand(m.group(1))
check(f'C19 every decision in the register has a row in the traceability decision map ({len(regids)} decisions)',[f'{x} missing in traceability map' for x in sorted(regids-mapids)]+[f'{x} in map but not in register' for x in sorted(mapids-regids)])
# 20 no stale pending on resolved decisions
pr=[]
for fn in spec:
    if fn=='revision-3.1-review-package.md': continue
    for i,l in enumerate(files[fn].splitlines(),1):
        if re.search(r'\b(?:RD|CH|ND|CR|CL)-\d+',l) and re.search(r'\b[Pp]ending\b',l) and 'Pending** (needs' not in l and 'None of the technical decisions is pending' not in l:
            pr.append(f'{fn}:{i}: {l.strip()[:110]}')
check('C20 no decision recorded as approved in the register is still described as pending elsewhere',pr)
# 21 no application code, migrations or implementation tasks before Phase 1 sign-off (task 1.9)
import subprocess
phase1_signed=bool(re.search(r'^- \[x\] 1\.9 ',files['tasks.md'],re.M))
lsf=subprocess.run(['git','-C',root,'ls-files','-z','--cached'],capture_output=True,text=True)   # tracked files only; untracked build output cannot fail the suite
tracked=[x for x in lsf.stdout.split('\0') if x]
allowed_ext={'.md','.yaml','.yml','.py'}
ext_where={'.ts':('backend/','tools/'),'.json':('backend/','tools/','postman/'),'.lock':('backend/','tools/'),'.go':('deployment/caddy/',),'.mod':('deployment/caddy/',),'.sum':('deployment/caddy/',)} if phase1_signed else {}   # Phase 2 onward, by location
allowed_base={'LICENSE','NOTICE','.gitignore','DuoCode-Requirements','.gitkeep','Dockerfile','.env.example'}
pr=[f'git ls-files failed (exit {lsf.returncode}): {lsf.stderr.strip()[:100]}'] if lsf.returncode!=0 else []
for f in tracked:
    base=os.path.basename(f); ext=os.path.splitext(f)[1]
    top=f.split('/')[0]
    if top=='.agents': continue   # local agent working files, never committed
    if not phase1_signed and top in('backend','tools','deployment','frontend','postman','docs'): pr.append(f'{f}: implementation directory'); continue
    if ext=='.sql' or (not phase1_signed and 'migration' in f.lower()):
        if not (phase1_signed and f.startswith('backend/migrations/')): pr.append(f'{f}: migration or SQL file outside backend/migrations/' if phase1_signed else f'{f}: migration or SQL file')
        continue
    if re.search(r'(?i)keyring|key[-_]ring|secret|^\.env',base) and base!='.env.example' and 'secrets.example/' not in f and not f.startswith('.kiro/'):
        pr.append(f'{f}: key ring, secret or environment file name'); continue
    if base in allowed_base: continue
    if ext in ext_where:
        if not f.startswith(ext_where[ext]): pr.append(f'{f}: {ext} files belong under {", ".join(ext_where[ext])}')
        continue
    if ext=='.py':
        if not f.startswith('.kiro/specs/duocode/'): pr.append(f'{f}: unexpected file type')   # only the specification tool scripts are Python
        continue
    if ext not in allowed_ext: pr.append(f'{f}: unexpected file type')
if not phase1_signed and any(l.startswith('- [x]') and not __import__('re').match(r'- \[x\] 1\.(?:[1-6] \*\*Gate|[78] |9 \*\*Phase 1 sign-off)',l) for l in files['tasks.md'].splitlines()): pr.append('an implementation task is marked done')
check('C21 no implementation directory before Phase 1 sign-off (task 1.9); SQL only under backend/migrations/ and only after 1.9; every tracked file has an allowed type'+(' (1.9 signed off)' if phase1_signed else ''),pr)
# 23 key usage design consistency (CR-9)
pr=[]
ku=re.search(r"CREATE TABLE key_usage \((.*?)\n\);",ddl,re.S)
if not ku: pr.append('key_usage table missing')
else:
    body=ku.group(1)
    if 'shard' in body: pr.append('key_usage still has a shard column')
    if not re.search(r'key_id\s+smallint PRIMARY KEY',body): pr.append('key_usage is not one row per key')
    m=re.search(r'reserved <= (\d+)',body)
    if not m or int(m.group(1))!=2**30: pr.append('CHECK constant is not 2^30')
    if 'sealed' not in body or 'NOT sealed OR reserved = 1073741824' not in body: pr.append('sealed flag and its CHECK are missing')
dsg=files['design.md']
def cfgval(k):
    m=re.search(r'\| `'+k+r'` \| `(\d+)`',dsg); return int(m.group(1)) if m else None
w,r_,h,b=cfgval('KEY_USAGE_WARN'),cfgval('KEY_USAGE_ROTATE_BY'),cfgval('KEY_USAGE_HARD_STOP'),cfgval('KEY_USAGE_BLOCK')
if (w,r_,h)!=(2**27,2**28,2**30): pr.append(f'threshold defaults {w},{r_},{h} are not 2^27, 2^28, 2^30')
if h is None or b is None: pr.append('KEY_USAGE_HARD_STOP or KEY_USAGE_BLOCK default missing or not numeric')
elif b<1 or h%b!=0: pr.append('hard stop is not a positive multiple of the block')
if 'reserved + $2 <= $3' not in files['database-schema.md']: pr.append('reservation statement guard missing in database-schema.md')
if 'AND NOT sealed' not in files['database-schema.md']: pr.append('reservation statement does not check the sealed flag')
if 'fingerprint bytea NOT NULL UNIQUE' not in files['database-schema.md']: pr.append('key_usage.fingerprint UNIQUE missing')
if 'INSERT INTO key_usage (key_id, fingerprint) VALUES ($1, $2)' not in files['database-schema.md']: pr.append('registration statement lacks the fingerprint')
for fn in ('security-assessment.md','deployment.md','design.md','database-schema.md','requirements.md'):
    if 'STAGED' not in files[fn]: pr.append(f'{fn} does not describe the STAGED ring status')
if 'FOR SHARE' not in files['database-schema.md'] or 'commit-time check' not in files['design.md'] or 'commit-time check' not in files['deployment.md']: pr.append('commit-time check under a share lock missing')
if 'WHERE key_usage.fingerprint = EXCLUDED.fingerprint' not in files['database-schema.md']: pr.append('registration does not reject a mismatched fingerprint')
if 'fingerprintHistory' not in files['deployment.md']: pr.append('restore does not seal from the fingerprint history')
if 'fingerprintHistory' not in files['security-assessment.md']: pr.append('ring fingerprintHistory missing')
if 'AND $2 > 0' not in files['database-schema.md']: pr.append('reservation statement does not reject zero or negative requests')
if 'ON CONFLICT (key_id) DO UPDATE SET reserved = 1073741824, sealed = true' not in files['database-schema.md']: pr.append('seal statement does not insert a missing row')
for term,fn in (('highestKeyId','security-assessment.md'),('highestKeyId','deployment.md'),('KEY_USAGE_REFRESH_SECONDS','design.md'),('known-answer','security-assessment.md'),('claim','design.md')):
    if term not in files[fn]: pr.append(f'{fn} lacks {term}')
if 'KEY_USAGE_REFRESH_SECONDS' not in files['requirements.md']: pr.append('R10.10 does not mention the refresh interval')
if 'SELECT NOT sealed AND fingerprint = $2 AS usable FROM key_usage' not in files['database-schema.md']: pr.append('pre-encryption check statement missing or not bound to the fingerprint')
if 'AND fingerprint = $4' not in files['database-schema.md']: pr.append('reservation statement not bound to the fingerprint')
for fn in ('security-assessment.md','deployment.md','design.md','database-schema.md'):
    if 'sealed' not in files[fn]: pr.append(f'{fn} does not describe sealing')
for fn in ('security-assessment.md','deployment.md','database-schema.md','requirements.md'):
    if 'CR-10' not in files[fn]: pr.append(f'{fn} does not reference CR-10 (key lifecycle after rotation)')
for term in ('Reserved unit','Encryption invocation','Allowance'):
    if term not in files['requirements.md']: pr.append(f'term {term!r} not in requirements glossary')
    if term not in files['database-schema.md']: pr.append(f'term {term!r} not defined in database-schema.md 6.2')
for fn in spec:
    if fn=='revision-3.1-review-package.md': continue
    for i,l in enumerate(files[fn].splitlines(),1):
        if re.search(r'shard',l,re.I) and not re.search(r'replac|draft|old_key_usage|negative control|removed|without shard|With shards|sharding',l,re.I):
            pr.append(f'{fn}:{i}: shard mentioned as current design: {l.strip()[:90]}')
for need in ('keys:seal','TS-CONC-21','TS-CONC-22','TS-CONC-23','TS-CONC-24','TS-CONC-25','TS-CONC-26','TS-CONC-27','TS-CONC-28'):
    if need not in files['test-strategy.md'] and need not in files['deployment.md']: pr.append(f'{need} missing')
if 'RD-14' not in files['requirements.md'] or 'CR-9' not in files['requirements.md']: pr.append('RD-14 or CR-9 missing from the register')
check('C23 key usage design is consistent: one authoritative row per key, CHECK at 2^30, thresholds 2^27 / 2^28 / 2^30, strict statement, terms defined, sharding only mentioned as replaced',pr)
# 24 verify-schema uses the specified statements
vs=open(d+'verify-schema.py').read()
pr=[]
if '(HERE / "database-schema.md")' not in vs: pr.append('verify-schema.py does not read database-schema.md')
for name in ('reserve_sql','register_sql','check_sql','commit_check_sql','report_sql','activation_sql','offline_sql','presence_sql','admission_sql','require_sql','reconcile_sql'):
    m=re.search(r'^\s*'+name+r'\s*=\s*(.+)$',vs,re.M)
    if not m: pr.append(f'{name} is not assigned'); continue
    if not m.group(1).startswith('next(b for b in blocks if'): pr.append(f'{name} is not extracted from the specification SQL blocks: {m.group(1)[:60]}')
    if len(re.findall(r'^\s*'+name+r'\s*=',vs,re.M))!=1: pr.append(f'{name} is assigned more than once')
m=re.search(r'^\s*seal_sql\s*=\s*(.+)$',vs,re.M)
if not m or not m.group(1).startswith('re.search(') or 'spec_text' not in m.group(1): pr.append('seal_sql is not extracted from the specification text')
for name in ('INSERT INTO key_usage','UPDATE key_usage','SELECT NOT sealed'):
    lits=[l for l in vs.splitlines() if name in l and 'next(b for b in blocks' not in l and 're.search(' not in l and not l.strip().startswith('#') and 'old_key_usage' not in l and 'set_R' not in l and 'INSERT INTO key_usage(key_id, fingerprint, reserved)' not in l]
    for l in lits:
        if 'SET ROLE' in l: continue   # permission probes, not specified statements
        if 'expect_error' in l or 'reserved = -1' in l or 'reserved = 1;' in l or 'reserved = {L + 1}' in l or 'SET sealed = true WHERE key_id = 2' in l: continue
        pr.append(f'hard-coded key_usage statement in verify-schema.py: {l.strip()[:80]}')
check('C24 the schema verification tool takes the reservation, registration and sealing statements from database-schema.md',pr)
# 25 every operation declares the cross-cutting failure responses (CR-22)
pr=[]
for path,item in oa['paths'].items():
    for meth,op in item.items():
        if meth not in ('get','post','put','delete','patch'): continue
        codes=set(op.get('responses',{}))
        for c in ('500','503'):
            if c not in codes: pr.append(f"{op['operationId']} lacks {c}")
        if path.startswith('/admin') and '429' not in codes: pr.append(f"{op['operationId']} lacks 429")
check('C25 every OpenAPI operation declares 500 and 503, and admin operations declare 429',pr)
# 26 the write order of checks includes the claim, the pre-encryption check and the commit-time check (CR-23)
pr=[]
smw=files['state-machine.md']
w=smw[smw.index('### 1.3 Order of checks'):smw.index('### 1.4')]
steps=re.findall(r'^(\d+)\. (.*)$',w,re.M)
def pos(pat):
    for n,t in steps:
        if re.search(pat,t): return int(n)
    return None
pc=pos(r'Encryption claim.*pre-encryption check'); pb=pos(r'^Begin transaction'); pk=pos(r'Commit-time check'); pa=pos(r'^Apply changes'); pm=pos(r'^\*\*Commit\.\*\*')
if None in (pc,pb,pk,pa,pm): pr.append(f'missing step: claim={pc} begin={pb} apply={pa} commit-check={pk} commit={pm}')
elif not (pc<pb<pa<pk<pm): pr.append(f'wrong order: claim={pc} begin={pb} apply={pa} commit-check={pk} commit={pm}')
for n,t in steps:
    if int(n)!=pm and int(n)!=pk and re.search(r'\bcommit(s|ted)?\b',t,re.I) and not re.search(r'commit-time|before `COMMIT`|had already',t,re.I):
        pr.append(f'step {n} commits outside the Commit step: {t[:60]}')
if pm is not None and re.search(r'only for|skips this step',dict(steps)[str(pm)],re.I): pr.append('the Commit step is conditional')
if [int(n) for n,_ in steps]!=list(range(1,len(steps)+1)): pr.append('steps not numbered 1..n')
check('C26 state-machine 1.3 orders claim and pre-encryption check before BEGIN and the commit-time check before COMMIT',pr)
# 27 the security assessment agrees with the approved schema and deployment, and every threat maps to tests (CR-24)
pr=[]
sa=files['security-assessment.md']; ts=files['test-strategy.md']; tk=files['tasks.md']
s33=sa[sa.index('### 3.3a'):sa.index('### 3.4')]
stmt=re.search(r'`UPDATE key_usage SET reserved[^`]*`',s33)
if not stmt or 'fingerprint' not in stmt.group(0): pr.append('3.3a reservation statement lacks the fingerprint condition')
if not re.search(r'AND fingerprint = \$4',files['database-schema.md']): pr.append('database-schema.md reservation statement lacks the fingerprint condition')
rec=sa[sa.index('**Recovery (database restore).**'):sa.index('**Rotation (planned')]
rsteps=dict((int(n),x) for n,x in re.findall(r'^(\d+)\. (.*)$',rec,re.M))
def rstep(pat):
    for n in sorted(rsteps):
        if re.search(pat,rsteps[n],re.I): return n
    return None
rc=rstep(r'deno task cleanup'); rs=rstep(r'start `app` and `cleanup`')
if rc is None or rs is None or not rc<rs: pr.append(f'restore summary: cleanup step {rc} must come before the service start step {rs}')
if 'ABANDONED' not in rec: pr.append('restore summary does not abandon a sealed staged key')
if rs is not None:
    for n in sorted(rsteps):
        if n<rs and re.search(r'\b(start|restart)\b[^.]*\b(services?|instances?|application)\b',rsteps[n],re.I):
            pr.append(f'restore summary step {n} starts services before step {rs}')
if 'rate_limits' not in rec: pr.append('restore summary does not truncate rate_limits')
dep=files['deployment.md']; d61=dep[dep.index('### 6.1'):dep.index('### 6.2')]
dc=re.search(r'^(\d+)\. Run `deno task cleanup`',d61,re.M); ds=re.search(r'^(\d+)\. Start `app` and `cleanup`',d61,re.M)
if not (dc and ds and int(dc.group(1))<int(ds.group(1))): pr.append('deployment.md 6.1: cleanup must come before the service start')
rot=sa[sa.index('**Rotation (planned'):sa.index('### 3.6a')]
if '--expect' not in rot or 'required_key_ids' not in rot: pr.append('rotation summary lacks keys:activate --expect or the admission gate')
s38=sa[sa.index('### 3.8'):sa.index('### 3.9')]
for w in ('presence lock','pre-encryption check','commit-time check'):
    if w not in s38: pr.append(f'3.8 re-encryption does not mention the {w}')
threats=[int(x) for x in re.findall(r'^\| T(\d+) \|',sa[sa.index('## 5. Threats'):sa.index('## 6.')],re.M)]
if threats!=list(range(1,len(threats)+1)): pr.append('threat IDs are not contiguous from T1')
tmax=len(threats)
t18=ts[ts.index('## 18. Threat coverage'):] if '## 18. Threat coverage' in ts else ''
mapped=[int(x) for x in re.findall(r'^\| T(\d+) \|',t18,re.M)]
if mapped!=threats: pr.append(f'test-strategy.md section 18 does not map exactly T1..T{tmax}: missing {sorted(set(threats)-set(mapped))}, extra {sorted(set(mapped)-set(threats))}')
for fn,txt in (('test-strategy.md',ts),('tasks.md',tk)):
    for m in re.finditer(r'\bT1 to T(\d+)\b',txt):
        if int(m.group(1))!=tmax: pr.append(f'{fn} says T1 to T{m.group(1)}, threat table ends at T{tmax}')
if '9.6a' not in sa[sa.index('## 8. Residual'):]: pr.append('the 9.6a concern is not listed as a residual risk')
check('C27 security assessment matches the approved schema and deployment (reservation, restore order, rotation, re-encryption), and every threat maps to test groups',pr)
# 28 the key commands are the same set everywhere (CR-24)
pr=[]
kcmd=r'keys:[a-z]+(?:-[a-z]+)*'
dep=files['deployment.md']
cl=re.search(r'^- Commands: (.*)$',dep[dep.index('### 2.1'):dep.index('## 3.')],re.M)
canon=set(re.findall(kcmd,cl.group(1))) if cl else set()
if not canon: pr.append('deployment.md 2.1 has no Commands list')
used=set()
for fn,txt in files.items():
    if fn.endswith('.md'): used|=set(re.findall(kcmd,txt))
for c in sorted(used-canon): pr.append(f'{c} is used but not in the deployment.md 2.1 command list')
lay=files['design.md']; lay=lay[lay.index('## 3. Repository layout'):lay.index('## 4.')]
for c in sorted(canon-set(re.findall(kcmd,lay))): pr.append(f'design.md section 3 layout does not list {c}')
t92=re.search(r'^- \[[ x]\] 9\.2a .*$',files['tasks.md'],re.M)
for c in sorted(canon-set(re.findall(kcmd,t92.group(0) if t92 else ''))): pr.append(f'tasks.md 9.2a does not list {c}')
check(f'C28 every key command used in the specification is in the deployment.md 2.1 list, the design layout and task 9.2a ({len(canon)} commands)',pr)
# 29 headings quoted by name in requirements.md exist
pr=[]
heads=set(h.strip() for h in re.findall(r'^#{2,4} (.+)$',req,re.M))
for m in re.finditer(r'(?:listed under|see) "([^"]+)"',req):
    q=m.group(1)
    if not any(h==q or h.startswith(q+' (') for h in heads): pr.append(f'requirements.md quotes the heading "{q}", which does not exist')
check('C29 every heading quoted by name in requirements.md exists',pr)
# 30 README layout matches the approved design.md layout (task 1.7), compared as full paths
pr=[]
def tree_paths(txt,inline):
    stack=[]; paths=set()
    def add(p):
        parts=p.split('/')
        for i in range(1,len(parts)):
            paths.add('/'.join(parts[:i])+'/')
        if parts[-1]: paths.add(p)
    for l in txt.splitlines():
        m=re.match(r'^((?:│   |    )*)[├└]── (\S+)(.*)$',l)
        if not m:
            n=re.match(r'^\(([\w./-]+/) holds',l)   # design.md note under the tree, e.g. deployment/caddy/
            if n and inline: add(n.group(1))
            continue
        depth=len(m.group(1))//4; stack=stack[:depth]; tok=m.group(2); full=''.join(stack)+tok
        add(full)
        if tok.endswith('/'):
            stack.append(tok)
            if inline:   # child directories named on a directory line, e.g. postman/ ... environments/
                for x in m.group(3).replace(',',' ').split():
                    if re.fullmatch(r'[\w.-]+/',x): add(full+x)
        elif inline:   # a file entry may carry sibling files and root-relative paths on the same line
            parent=full[:full.rfind('/')+1] if '/' in full else ''
            for x in m.group(3).split():
                if '/' in x: add(x)
                elif re.fullmatch(r'[\w.-]+\.\w+|\.\w+|LICENSE|NOTICE',x): add(parent+x)
    return paths
lay=files['design.md']; lay=lay[lay.index('## 3. Repository layout'):lay.index('## 4.')]
rd=files['README.md']; i0=rd.index('duocode/\n'); rtree=rd[i0:rd.index('\n\n',i0)]
want=tree_paths(lay,True)-{'frontend/'}   # frontend/ is created later; the README says so in prose
have=tree_paths(rtree,False)
for p in sorted(want-have): pr.append(f'README layout lacks {p}')
for p in sorted(have-want): pr.append(f'README layout has {p}, which design.md section 3 does not')
for stale in ('awaiting owner approval','Caddy or Nginx','subject to owner approval'):
    if stale in rd: pr.append(f'README still says "{stale}"')
check(f'C30 the README layout lists exactly the approved design.md layout as full paths ({len(want)} paths) and carries no superseded approval statements',pr)
# 31 invitation error table agrees across documents (task 1.8, A3, B14, C8)
pr=[]
for fn in ('requirements.md','security-assessment.md','state-machine.md','copilot-instructions.md','openapi.yaml'):
    for tok in ('GAME_FULL','INVALID_INVITATION'):
        if tok not in files[fn]: pr.append(f'{fn} does not mention {tok}')
for fn in ('requirements.md','security-assessment.md','state-machine.md','copilot-instructions.md'):
    for i,l in enumerate(files[fn].splitlines(),1):
        if '401 INVALID_CREDENTIALS' in l and re.search(r'invitation',l,re.I) and not re.search(r'GAME_FULL|INVALID_INVITATION|access and rematch|exception',l):
            pr.append(f'{fn}:{i}: a 401 rule mentions invitations without the join exceptions')
jr=oa['paths']['/games/{gameId}/join']['post']['responses']
if '401' in jr: pr.append('joinGame declares 401')
for c in ('404','409'):
    if c not in jr: pr.append(f'joinGame lacks {c}')
check('C31 the join error exceptions (409 GAME_FULL, 404 INVALID_INVITATION, no blanket 401) agree in requirements, security assessment, state machine, copilot instructions and OpenAPI',pr)
# 32 HKDF labels agree (task 1.8, B13)
pr=[]
labels=set()
for fn,t in files.items():
    for l in t.splitlines():
        if 'HKDF' in l: labels|=set(re.findall(r'duocode/[a-z]+/v\d+',l))   # the other duocode/<name>/v1 strings are AAD domain labels
if labels!={'duocode/enc/v1','duocode/mac/v1'}: pr.append(f'HKDF labels in use: {sorted(labels)}')
m1=re.search(r'Guess fingerprint: `HMAC-SHA-256\(HKDF\(key\[kid\], "([^"]+)"\)',files['design.md'])
m2=re.search(r'`(duocode/[a-z]+/v\d+)` for HMAC fingerprints',files['security-assessment.md'])
if not m1 or m1.group(1)!='duocode/mac/v1': pr.append('design.md guess fingerprint does not use duocode/mac/v1')
if not m2 or m2.group(1)!='duocode/mac/v1': pr.append('security-assessment.md fingerprint key does not use duocode/mac/v1')
check('C32 the HKDF labels (lines that mention HKDF) are duocode/enc/v1 and duocode/mac/v1 only, and the guess fingerprint uses duocode/mac/v1 in design.md and security-assessment.md',pr)
# 33 every operation with a gameId path parameter declares 400 (task 1.8, C9)
pr=[]
for path,item in oa['paths'].items():
    if '{gameId}' not in path: continue
    for meth,op in item.items():
        if meth in ('get','post','put','delete','patch') and '400' not in op.get('responses',{}): pr.append(f"{op['operationId']} lacks 400")
check('C33 every OpenAPI operation with a gameId path parameter declares 400',pr)
# 34 CI secret hygiene covers .env.* and exempts only .env.example (task 1.8, B1)
pr=[]
hy=[st.get('run','') for j in yaml.safe_load(open(root+'.github/workflows/ci.yml'))['jobs'].values() for st in j.get('steps',[]) if 'git ls-files' in st.get('run','') and 'secrets/' in st.get('run','')]
hm=re.search(r"grep -E '([^']+)'.*grep -vE '([^']+)'",hy[0]) if hy else None
if not hm: pr.append('the secret-file step of ci.yml was not found')
else:
    flag=lambda n: re.search(hm.group(1),n) and not re.search(hm.group(2),n)
    for n in ('.env','.env.local','.env.production','app/.env.staging','secrets/key.txt','a.pem','.env.example.bak'):
        if not flag(n): pr.append(f'{n} is not flagged')
    if flag('.env.example') or flag('docs/.env.example'): pr.append('.env.example is not exempt')
    if flag('secrets.example/dev.pem') or flag('secrets.example/duocode_ratelimit_key.key'): pr.append('secrets.example/ placeholders are not exempt')
    if not flag('secrets.examples/a.pem'): pr.append('secrets.examples/ must not be exempt')
check('C34 the CI repository hygiene step flags .env, .env.* and secret files and exempts only .env.example and secrets.example/ placeholders',pr)
# 35 required merge checks include audit and exist as CI jobs (task 1.8, D13)
pr=[]
mm=re.search(r'Merge requires (.*?) to pass',files['test-strategy.md'])
req_jobs=re.findall(r'`([\w-]+)`',mm.group(1)) if mm else []
if 'audit' not in req_jobs: pr.append('test-strategy.md required merge checks omit audit')
cij=yaml.safe_load(open(root+'.github/workflows/ci.yml'))['jobs']
if 'audit' not in cij: pr.append('ci.yml has no audit job')
check('C35 the required merge checks in test-strategy.md include audit and ci.yml defines the audit job',pr)
# 36 pl:rotate replays are exempt everywhere, and R20.3 scopes token buckets to the application layer (task 1.8, RD-16, RD-18)
pr=[]
for fn in spec:
    if fn=='revision-3.1-review-package.md': continue
    for i,l in enumerate(files[fn].splitlines(),1):
        if 'pl:rotate' in l and re.search(r'replay',l,re.I) and not re.search(r'exempt|not charged|never charged|uncharged',l,re.I):
            pr.append(f'{fn}:{i}: pl:rotate and replay without the exemption')
r203=re.search(r'^3\. (EACH application-layer limit.*)$',req[req.index('### R20:'):],re.M)
if not r203 or 'sliding-window' not in r203.group(1) or 'not token buckets' not in r203.group(1): pr.append('R20.3 does not scope token buckets to the application layer')
check('C36 validated pl:rotate replays are described as exempt wherever they are mentioned, and R20.3 limits token buckets to the application layer',pr)
# 37 to 40 PR #17 review follow-ups (RD-21, replay maintenance loop, simulator secrecy scope, twin rotation charging)
pr=[]
ds=files['database-schema.md']; dep=files['deployment.md']
for fn in ('deployment.md','database-schema.md','security-assessment.md','tasks.md'):
    if 'RD-21' not in files[fn] and fn!='tasks.md': pr.append(fn+': no mention of RD-21')
if not re.search(r'^\| RD-21 \|.*expired immediately.*results return an internal error.*keys:verify. accepts',req,re.M): pr.append('requirements.md: RD-21 row missing or incomplete')
for need in ('acceptedLoss','SET expires_at = now()','idempotency_keys i JOIN players','--accepted-loss'):
    if need not in ds: pr.append('database-schema.md: missing '+need)
if '--accepted-loss' not in dep: pr.append('deployment.md: missing --accepted-loss')
if not re.search(r'in progress is expired at once',dep): pr.append('deployment.md 6.2 does not expire in-progress affected games')
if '--accepted-loss' not in files['tasks.md'] or 'RD-21' not in files['tasks.md']: pr.append('tasks.md 9.2a does not define the accepted-loss options')
for i,l in enumerate(files['security-assessment.md'].splitlines(),1):
    if 'abandoned games are left to cleanup' in l: pr.append(f'security-assessment.md:{i}: affected games described without immediate expiry')
check('C37 missing-key recovery (RD-21): decision row, durable record, immediate expiry of in-progress affected games, verifier exclusion list and task 9.2a agree',pr)
pr=[]
if re.search(r'Maintenance statements, run once',ds): pr.append('database-schema.md: replay maintenance still described as run once per cleanup run')
if 'Replay ciphertext maintenance has its own loop' not in ds or 'updates no rows' not in ds: pr.append('database-schema.md: replay maintenance loop not specified')
if 'separate replay-ciphertext loop' not in files['tasks.md']: pr.append('tasks.md 5.11 lacks the replay maintenance loop test')
check('C38 replay ciphertext maintenance in cleanup is its own loop of committed batches that stops when no rows are updated',pr)
pr=[]
for fn in ('simulator-design.md','test-strategy.md','copilot-instructions.md'):
    for i,l in enumerate(files[fn].splitlines(),1):
        if re.search(r"no response[^.|]*opponent'?s guesses",l,re.I) and not re.search(r'except[^.|]*completed `?getResults',l): pr.append(f'{fn}:{i}: opponent guess ban without the completed getResults exception')
if 'except a completed `getResults`' not in files['simulator-design.md']: pr.append('simulator-design.md: secrecy check lacks the completed getResults exception')
check('C39 the simulator ban on opponent guesses and feedback exempts completed getResults',pr)
pr=[]
sm=files['state-machine.md']
for need in ('Charging `pl:rotate` for rotation requests (RD-22','read-only replay check','before `BEGIN`','over-charge of one unit is accepted'):
    if need not in sm: pr.append('state-machine.md: missing '+need)
# C40 scans sentences, not lines: wrapped text is joined, each sentence is judged with the one before it
# (so "It is charged to pl:rotate. The charge is refunded." is caught), and only a negation inside the
# offending sentence itself exempts it.
c40_bad=re.compile(r'refund|credit(?:ed|s)? back|post-?commit|\b(?:after|once|when|as soon as)\b[^.;]{0,40}\bcommit(?:s|ted)?\b|after the (?:commit|rotation)|only checks that|issued after|charged once,? after|charge of a rotation that has',re.I)
c40_ok=re.compile(r'no charge after|none after|\bno refund|\bnot refund|\bnever refund|\bwithout (?:a )?refund|replaces the round-2|round-2 (?:text|charge)|no `pl:rotate` statement runs after|is not charged|never charged',re.I)
def c40_sentences(text):
    out=[];buf=[]
    def flush():
        if buf:
            joined=' '.join(buf);buf.clear()
            out.extend(x for x in re.split(r'(?<=[.;:?!])\s+(?=[A-Z`(\d*])',joined) if x.strip())
    for l in text.splitlines():
        t=l.strip()
        if not t: flush();continue
        if t.startswith(('|','#','- ','* ')) or re.match(r'\d+\. ',t): flush()
        if t.startswith('|'): out.extend(x for x in re.split(r'(?<=[.;?!])\s+(?=[A-Z`(\d*])',t) if x.strip());continue
        buf.append(t)
    flush();return out
def c40_scan(fn,text):
    res=[];prev=''
    for sent in c40_sentences(text):
        if c40_bad.search(sent) and ('pl:rotate' in sent or 'pl:rotate' in prev) and not c40_ok.search(sent): res.append(f'{fn}: post-commit or refund charging wording for pl:rotate: {sent[:90]}')
        prev=sent
    return res
for fn in ('state-machine.md','deployment.md','design.md','requirements.md','security-assessment.md','test-strategy.md','revision-3.1-review-package.md','tasks.md'):
    pr.extend(c40_scan(fn,files[fn]))
if 'Twin rotations' not in files['test-strategy.md'] or 'TS-CONC-30' not in files['test-strategy.md']: pr.append('test-strategy.md: no twin rotation test or TS-CONC-30')
if 'before its transaction' not in dep: pr.append('deployment.md: no pl:rotate charge-before-transaction rule')
check('C40 pl:rotate is charged before the rotation transaction (RD-22), a known replay is found by a read-only check first, and no post-commit charge or refund wording remains',pr)
pr=[]
reqt=files['requirements.md']
for n in ('RD-22','RD-23','RD-24'):
    if not re.search(r'^\| '+n+r' \|.*i accept your recommendations',reqt,re.M): pr.append('requirements.md: '+n+' row missing or without owner statement')
    if not re.search(r'^\| '+n+r' \|',files['traceability.md'],re.M): pr.append('traceability.md: no decision map row '+n)
if 'keys:prune-accepted-loss' not in files['tasks.md'] or 'keys:prune-accepted-loss' not in dep or 'keys:prune-accepted-loss' not in files['database-schema.md']: pr.append('keys:prune-accepted-loss not defined in tasks.md, deployment.md and database-schema.md')
if not re.search(r'`reencrypt` skips[^.]*accepted|skipped, as a count only',files['security-assessment.md']+files['database-schema.md']): pr.append('reencrypt skip rule (RD-24) missing')
for g in ('1.1','1.2','1.4','1.5'):
    m=re.search(r'- \[x\] '+re.escape(g)+r' .*?(?=\n- \[)',files['tasks.md'],re.S)
    if not m or 'RD-24' not in m.group(0) and g in ('1.1','1.4','1.5') or not re.search(r'Awaiting an explicit owner confirmation|Re-confirmed \d{4}-\d{2}-\d{2} by .+owner statement',m.group(0)): pr.append('tasks.md '+g+': reopened entry does not cover RD-22 to RD-24')
check('C41 RD-22 to RD-24 are recorded with the owner statement, mapped, and carried into the reopened gate entries (RD-23 prune command, RD-24 reencrypt skip)',pr)
# 42 the design.md section 3 directories exist once task 2.1 is done (R19.1)
pr=[]
if re.search(r'^- \[x\] 2\.1 ',files['tasks.md'],re.M):
    lay42=files['design.md']; lay42=lay42[lay42.index('## 3. Repository layout'):lay42.index('## 4.')]
    cached=[x for x in subprocess.run(['git','-C',root,'ls-files','-z','--cached'],capture_output=True,text=True).stdout.split('\0') if x]
    for d in sorted(p for p in tree_paths(lay42,True) if p.endswith('/') and p!='frontend/'):
        if not os.path.isdir(root+d) or not any(f.startswith(d) for f in cached): pr.append(f'{d} from design.md section 3 does not exist with a tracked file in it')
    if os.path.exists(root+'frontend'): pr.append('frontend/ exists, but design.md section 3 creates it only when browser work starts')
check('C42 once task 2.1 is done, every directory in the design.md section 3 layout exists with a tracked file, and frontend/ does not',pr)
# 43 SPDX headers on source files (task 2.2, R19.2): the shared rule in spdx-headers.py, and the CI step that runs it
import importlib.util as _ilu
sys.dont_write_bytecode=True   # importing spdx-headers.py must not leave __pycache__ behind
_sp=_ilu.spec_from_file_location('spdx_headers',root+'.kiro/specs/duocode/spdx-headers.py'); spdx=_ilu.module_from_spec(_sp); _sp.loader.exec_module(spdx)
pr=[]
try:
    srcs=spdx.source_files(root); pr+= [f'{f}: missing SPDX header (the two NOTICE lines as the first comment lines)' for f in spdx.missing(root)]
except Exception as e:
    srcs=[]; pr.append(str(e))
hyg=yaml.safe_load(open(root+'.github/workflows/ci.yml'))['jobs'].get('repo-hygiene',{})
if not any('spdx-headers.py' in st.get('run','') for st in hyg.get('steps',[])): pr.append('the Repository hygiene job does not run spdx-headers.py')
for bad in ('const s = "SPDX-License-Identifier: AGPL-3.0-only";\n// Copyright (C) 2026 The DuoCode authors (see NOTICE)\n',
            '// Copyright (C) 2026 The DuoCode authors (see NOTICE)\n// SPDX-License-Identifier: AGPL-3.0-only\n',
            '// SPDX-License-Identifier: AGPL-3.0-only\n\n// Copyright (C) 2026 The DuoCode authors (see NOTICE)\n'):
    if spdx.has_header(bad): pr.append('spdx-headers.py accepts a malformed header: '+bad.split(chr(10))[0][:40])
for good in ('#!/usr/bin/env python3\n# SPDX-License-Identifier: AGPL-3.0-only\n# Copyright (C) 2026 The DuoCode authors (see NOTICE)\n',
             '/*\n * SPDX-License-Identifier: AGPL-3.0-only\n * Copyright (C) 2026 The DuoCode authors (see NOTICE)\n */\n',
             '-- SPDX-License-Identifier: AGPL-3.0-only\n-- Copyright (C) 2026-2027 The DuoCode authors (see NOTICE)\n'):
    if not spdx.has_header(good): pr.append('spdx-headers.py rejects a valid header: '+good.split(chr(10))[1][:40])
check(f'C43 every tracked source file carries the two-line SPDX header from NOTICE as its first comment lines, and the Repository hygiene job enforces it ({len(srcs)} files)',pr)
# 44 .gitignore keeps environment, secret and key files out and lets the committed placeholders and the specification in (task 2.2)
pr=[]
def _ignored(path): return subprocess.run(['git','-C',root,'check-ignore','-q','--no-index',path]).returncode==0
if not os.path.exists(root+'.gitignore'): pr.append('.gitignore does not exist')
else:
    for path in ('.env','.env.production','backend/.env.local','secrets/x','a.pem','b.key','deployment/configuration/keyring.json','x/key-ring.json','x/key_ring','backend/coverage/lcov.info','node_modules/x','dist/x','.agents/x','.worktrees/y'):
        if not _ignored(path): pr.append(f'{path} is not ignored')
    for path in ('.env.example','secrets.example/duocode_code_keyring','secrets.example/dev.pem','.kiro/specs/duocode/keyring-format.md','backend/src/main.ts','NOTICE'):
        if _ignored(path): pr.append(f'{path} is ignored but must be committable')
check('C44 .gitignore ignores environment, secret, key and build files and keeps .env.example, secrets.example/ and the specification committable',pr)
# 45 every --allow-env key in backend/deno.json is a configuration key in design.md section 13 (task 2.3)
pr=[]
import json as _json
dj=root+'backend/deno.json'
if os.path.exists(dj):
    sec13=files['design.md'][files['design.md'].index('## 13. Configuration'):files['design.md'].index('## 14.')]
    cfg=set(re.findall(r'^\| `([A-Z][A-Z0-9_]*)`',sec13,re.M))
    tasks=_json.load(open(dj)).get('tasks',{})
    for name,cmd in sorted(tasks.items()):
        for lst in re.findall(r'--allow-env=(\S+)',cmd):
            for k in lst.split(','):
                if k not in cfg: pr.append(f'deno.json task {name}: {k} is not a configuration key in design.md section 13')
        if re.search(r'--allow-env(?!=)',cmd): pr.append(f'deno.json task {name}: --allow-env without a key list')
check('C45 every --allow-env key in backend/deno.json is a configuration key in design.md section 13, and no task has an unrestricted --allow-env',pr)
# 22 OpenAPI lint
import shutil as _sh
if _sh.which('npx'):
    try:
        r=subprocess.run(['npx','--yes','@redocly/cli@1','lint',root+'openapi/openapi.yaml'],capture_output=True,text=True,timeout=120)
        out=r.stdout+r.stderr
        ok=('valid' in out and 'warning' not in out.lower() and r.returncode==0)
        check('C22 OpenAPI lint (Redocly): valid with 0 errors and 0 warnings',[] if ok else [out.strip()[-300:]])
    except Exception as e:
        results.append(('C22 OpenAPI lint (Redocly): SKIPPED ('+str(e)[:60]+')',None,[]))
else:
    results.append(('C22 OpenAPI lint (Redocly): SKIPPED (npx not available)',None,[]))
w=0; sk=0
for name,ok,det in results:
    if ok is None:
        print('SKIP '+name); sk+=1; continue
    print(('PASS ' if ok else 'FAIL ')+name)
    for x in det: print('     -',x)
    w+=0 if ok else 1
print(f'\n{len(results)-w-sk} of {len(results)-sk} checks passed ({sk} skipped)')
sys.exit(1 if w else 0)
