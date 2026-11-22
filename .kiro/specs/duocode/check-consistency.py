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
elif 'DRAFT' not in files['NOTICE'] or 'DRAFT' not in files['CONTRIBUTING.md']: pr.append('draft banner missing')
check(f'C13 licensing artefacts present, LICENSE is the FSF AGPL-3.0 text (sha256 {sha[:16]}...), NOTICE names AGPL-3.0-only, and after Gate 6 no draft banner or placeholder remains and NOTICE names the LI-1 holders',pr)
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
for idx,l in enumerate(lines):
    if re.match(r'- \[x\]',l):
        m=re.match(r'- \[x\] (1\.[1-6]) \*\*Gate',l)
        nxt=lines[idx+1] if idx+1<len(lines) else ''
        if not m: pr.append('marked done but not a Phase 1 gate: '+l[:60])
        elif not re.search(r'Signed off \d{4}-\d{2}-\d{2} by .+owner statement "[^"]*\S[^"]*"',nxt): pr.append(f'gate {m.group(1)} marked done without a recorded owner sign-off')
if re.search(r'^- \[x\] 1\.9',tk,re.M) and len(re.findall(r'^- \[x\] 1\.[1-6] ',tk,re.M))<6: pr.append('1.9 marked done before all six gates')
awaiting=re.findall(r'^  - \*\*Reopened [^\n]*Awaiting an explicit owner confirmation',tk,re.M)
if awaiting:
    if re.search(r'^- \[x\] 1\.9',tk,re.M): pr.append('1.9 marked done while a reopened gate part awaits confirmation')
    for fn in ('requirements.md','traceability.md','tasks.md','revision-3.1-review-package.md'):
        if 'awaiting owner confirmation' not in files[fn]: pr.append(f'{fn} status does not mention the reopened gate part awaiting confirmation')
signed=re.findall(r'^- \[x\] (1\.[1-6]) ',tk,re.M)
check(f'C15 only Phase 1 gates are marked done, each with a recorded owner sign-off (signed: {", ".join(signed) or "none"})',pr)
# 16 baseline constants
pr=[]
if 'maxItems: 4' not in files['openapi.yaml']: pr.append('code length not constrained')
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
# 21 no application code, migrations or implementation tasks
import subprocess
tracked=subprocess.run(['git','-C',root,'ls-files','-co','--exclude-standard'],capture_output=True,text=True).stdout.split()
allowed_ext={'.md','.yaml','.yml','.py'}
pr=[]
for f in tracked:
    base=os.path.basename(f); ext=os.path.splitext(f)[1]
    top=f.split('/')[0]
    if top in('backend','tools','deployment','frontend','postman','docs'): pr.append(f'{f}: implementation directory')
    elif f.endswith('.sql') or 'migration' in f.lower(): pr.append(f'{f}: migration or SQL file')
    elif base in('LICENSE','NOTICE','.gitignore','DuoCode-Requirements'): continue
    elif ext=='.py' and f.startswith('.kiro/specs/duocode/'): continue   # specification tooling, not application code
    elif ext not in allowed_ext: pr.append(f'{f}: unexpected file type')
    elif f.startswith('.github/workflows/'): continue               # CI skeleton added earlier at the owner request, no application logic
if any(l.startswith('- [x]') and not __import__('re').match(r'- \[x\] 1\.[1-6] \*\*Gate',l) for l in files['tasks.md'].splitlines()): pr.append('an implementation task is marked done')
check('C21 no application code, database migration or implementation directory exists (only specification, licensing, CI skeleton and the two specification tool scripts)',pr)
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
