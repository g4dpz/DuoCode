#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 The DuoCode authors (see NOTICE)
# Committed negative cases for the governance checks (task 2.7, carried over from the PR #19 and #20 reviews).
# Each case copies the tracked files into a throwaway git repository, applies one violation, runs
# check-consistency.py there, and requires the named check to fail with the expected message.
# A clean copy must pass every check. Run: python3 .kiro/specs/duocode/check-consistency-negative.py
import os,re,shutil,subprocess,sys,tempfile

HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=subprocess.run(['git','-C',HERE,'rev-parse','--show-toplevel'],capture_output=True,text=True,check=True).stdout.strip()
CHECKER='.kiro/specs/duocode/check-consistency.py'
TASKS='.kiro/specs/duocode/tasks.md'
HDR='// SPDX-License-Identifier: AGPL-3.0-only\n// Copyright (C) 2026 The DuoCode authors (see NOTICE)\n'

def copy_repo():
    tmp=tempfile.mkdtemp(prefix='duocode-neg-')
    files=subprocess.run(['git','-C',ROOT,'ls-files','-z','--cached'],capture_output=True,check=True).stdout.decode().split('\0')
    for f in filter(None,files):
        src=os.path.join(ROOT,f)
        if not os.path.exists(src): continue   # deleted in the working tree
        dst=os.path.join(tmp,f); os.makedirs(os.path.dirname(dst),exist_ok=True); shutil.copy2(src,dst)
    git(tmp,'init','-q'); git(tmp,'add','-A')
    return tmp

def git(repo,*args): subprocess.run(['git','-C',repo,*args],capture_output=True,check=True)

def run_checker(repo):
    env=dict(os.environ,CHECK_SKIP_REDOCLY='1')
    out=subprocess.run([sys.executable,os.path.join(repo,CHECKER)],capture_output=True,text=True,env=env,cwd=repo).stdout
    fails={}; cur=None
    for line in out.splitlines():
        m=re.match(r'FAIL (C\d+)',line)
        if m: cur=m.group(1); fails[cur]=[]
        elif line.startswith('     - ') and cur: fails[cur].append(line[7:])
        elif not line.startswith('     '): cur=None
    return fails

def edit(repo,path,old,new):
    p=os.path.join(repo,path); t=open(p).read()
    assert old in t,f'{path}: {old!r} not found'
    open(p,'w').write(t.replace(old,new,1)); git(repo,'add',path)

def add(repo,path,text,force=False):
    p=os.path.join(repo,path); os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'w').write(text)
    git(repo,'add',*(['-f'] if force else []),path)

def untick_19(r): edit(r,TASKS,'- [x] 1.9 ','- [ ] 1.9 ')
def first_open_task(r,phase):
    t=open(os.path.join(r,TASKS)).read()
    return re.search(rf'^- \[ \] ({phase}\.\d+[a-z]?) ',t,re.M).group(1)
def tick_without_record(r):
    tid=first_open_task(r,3); edit(r,TASKS,f'- [ ] {tid} ',f'- [x] {tid} ')
def sql_before_19(r): untick_19(r); add(r,'db/0001_init.sql',   # outside backend/, so the directory rule does not mask it
    '-- SPDX-License-Identifier: AGPL-3.0-only\n-- Copyright (C) 2026 The DuoCode authors (see NOTICE)\nSELECT 1;\n')
def sql_outside(r): add(r,'backend/src/schema.sql','-- SPDX-License-Identifier: AGPL-3.0-only\n-- Copyright (C) 2026 The DuoCode authors (see NOTICE)\nSELECT 1;\n')
def keyring_json(r): add(r,'deployment/configuration/keyring.json','{}\n',force=True)
def remove_layout_dir(r):
    git(r,'rm','-q','-r','-f','tools/api-client'); shutil.rmtree(os.path.join(r,'tools/api-client'),ignore_errors=True)
def dir_left_untracked(r): git(r,'rm','-q','--cached','tools/api-client/.gitkeep')
def no_spdx(r): add(r,'backend/src/probe.ts','export const x = 1;\n')
def spdx_as_data(r): add(r,'backend/src/probe.ts','const s = "SPDX-License-Identifier: AGPL-3.0-only";\nconst c = "Copyright (C) 2026 The DuoCode authors (see NOTICE)";\nexport { c, s };\n')
def gitignore_drops_secrets(r): edit(r,'.gitignore','\nsecrets/\n','\n')
def gitignore_hides_placeholder(r):
    p=os.path.join(r,'.gitignore'); open(p,'a').write('.env.example\n'); git(r,'add','.gitignore')
def notice_changed(r): edit(r,'NOTICE','DuoCode','DuoCode ')
def trace_names_missing(r): edit(r,'.kiro/specs/duocode/traceability.md','`design.md`','`design-old.md`')
def bad_cross_ref(r): edit(r,'.kiro/specs/duocode/design.md','## 13. Configuration','## 13. Configuration\n\nSee `deployment.md` 99.9 for details.')

# (name, mutation, check that must fail, substring its message must contain)
CASES=[
    ('a later-phase task is ticked before 1.9', untick_19, 'C15', 'before Phase 1 sign-off'),
    ('an implementation directory exists before 1.9', untick_19, 'C21', 'implementation directory'),
    ('a later-phase task is ticked without a Done record', tick_without_record, 'C15', 'without a dated record'),
    ('an SQL file exists before 1.9', sql_before_19, 'C21', 'migration or SQL file'),
    ('an SQL file lies outside backend/migrations/', sql_outside, 'C21', 'outside backend/migrations/'),
    ('a key ring file name is tracked', keyring_json, 'C21', 'key ring, secret or environment file name'),
    ('a layout directory is missing', remove_layout_dir, 'C42', 'tools/api-client/'),
    ('a layout directory remains with no tracked file', dir_left_untracked, 'C42', 'tools/api-client/'),
    ('a source file has no SPDX header', no_spdx, 'C43', 'backend/src/probe.ts'),
    ('the SPDX header is string data', spdx_as_data, 'C43', 'backend/src/probe.ts'),
    ('.gitignore stops ignoring secrets/', gitignore_drops_secrets, 'C44', 'secrets/x is not ignored'),
    ('.gitignore ignores the .env.example placeholder', gitignore_hides_placeholder, 'C44', '.env.example is ignored'),
    ('NOTICE differs from its Gate 6 version', notice_changed, 'C13', 'NOTICE differs'),
    ('traceability.md names a file that does not exist', trace_names_missing, 'C47', 'design-old.md'),
    ('a cross-reference names a section that does not exist', bad_cross_ref, 'C48', '`deployment.md` 99.9'),
]

def main():
    bad=0
    r=copy_repo()
    try:
        f=run_checker(r)
        print(('PASS' if not f else 'FAIL')+' clean copy passes every check'+('' if not f else f': {sorted(f)}'))
        bad+=bool(f)
    finally: shutil.rmtree(r,ignore_errors=True)
    for name,mutate,check,text in CASES:
        r=copy_repo()
        try:
            mutate(r); f=run_checker(r)
            ok=check in f and any(text in m for m in f[check])
            print(('PASS' if ok else 'FAIL')+f' {check} rejects: {name}'+('' if ok else f' (failed checks: {sorted(f)})'))
            bad+=not ok
        finally: shutil.rmtree(r,ignore_errors=True)
    print(f'\n{len(CASES)+1-bad} of {len(CASES)+1} negative-case checks passed')
    sys.exit(1 if bad else 0)

if __name__=='__main__': main()
