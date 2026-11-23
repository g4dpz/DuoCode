# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 The DuoCode authors (see NOTICE)
# SPDX header check (task 2.2, R19.2). Used by the CI Repository hygiene job and by check C43.
# Rule: the two header lines from NOTICE are the first two lines of the file, each a comment
# (#, //, --, or * inside a block comment). A #! line may come first, and a lone /* or /** opener
# may come before the header.
import os,re,subprocess,sys

PATTERNS=['*.ts','*.tsx','*.js','*.jsx','*.mjs','*.cjs','*.go','*.sql','*.py','*.sh','*Dockerfile','*Dockerfile.*']
LEAD=r'^\s*(?:#|//|--|\*)\s*'
SPDX=re.compile(LEAD+r'SPDX-License-Identifier: AGPL-3\.0-only\s*$')
COPY=re.compile(LEAD+r'Copyright \(C\) \d{4}(?:-\d{4})? The DuoCode authors \(see NOTICE\)\s*$')

def has_header(text):
    lines=text.replace('\r\n','\n').split('\n')
    i=0
    if lines and lines[0].startswith('#!'): i=1
    if i<len(lines) and re.fullmatch(r'\s*/\*\*?\s*',lines[i]): i+=1
    return i+1<len(lines) and bool(SPDX.match(lines[i])) and bool(COPY.match(lines[i+1]))

def source_files(root):
    r=subprocess.run(['git','-C',root,'ls-files','-z','--cached','--',*PATTERNS],capture_output=True)
    if r.returncode!=0:
        raise RuntimeError(f'git ls-files failed (exit {r.returncode}): {r.stderr.decode(errors="replace").strip()[:100]}')
    return [p for p in r.stdout.decode('utf-8',errors='surrogateescape').split('\0') if p]

def missing(root):
    out=[]
    for f in source_files(root):
        with open(os.path.join(root,f),encoding='utf-8',errors='replace') as fh:
            if not has_header(fh.read(4096)): out.append(f)
    return out

if __name__=='__main__':
    root=sys.argv[1] if len(sys.argv)>1 else '.'
    try:
        files=source_files(root); bad=missing(root)
    except Exception as e:
        print(f'SPDX check could not run: {e}'); sys.exit(2)
    if bad:
        print('Missing SPDX header (the two NOTICE lines as the first comment lines):'); [print('  '+f) for f in bad]; sys.exit(1)
    print(f'SPDX headers present on {len(files)} source files')
