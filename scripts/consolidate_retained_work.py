"""Preserve both source trees, then prepare an explicit three-way consolidation.

This tool changes only the named new worktree and durable source archive. It
never stages, commits, resets, or changes either original working tree.
"""
from pathlib import Path, PurePosixPath
from collections import Counter
from datetime import datetime, timezone
import hashlib, json, os, stat, subprocess

MAIN=Path('/Users/vishnu/orionviva')
PROTO=Path('/private/tmp/orionviva-sqlite-prototype')
TARGET=Path('/Users/vishnu/orionviva-consolidated')
ARCHIVE=Path('/Users/vishnu/OrionViva-Preservation/2026-11-05-consolidation')
BASE='61d3820af25b2357f8c54f7d2361e907497da824'
HEAD='13a41040029383bba43c6ad323300f7b7f4e6706'
BRANCH='codex/consolidated-sqlite-performance'
INDEX='ced1ce44124ba828467a2c2f866c338d587c1b7ce6e3d7f2ecf6ba3d7284791a'

def sha(data):return hashlib.sha256(data).hexdigest()
def git(root,*args):return subprocess.check_output(['/usr/bin/git','--no-optional-locks','-C',str(root),*args])
def save(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def valid(name):
    p=PurePosixPath(name)
    assert not p.is_absolute() and '..' not in p.parts and '.git' not in p.parts
    return name

def tree(ref):
    answer={}
    for raw in git(MAIN,'ls-tree','-r','-z',ref).split(b'\0'):
        if not raw:continue
        meta,name=raw.split(b'\t',1);mode,kind,oid=meta.decode().split()
        assert kind=='blob' and mode in ('100644','100755')
        answer[valid(name.decode())]=(mode,oid)
    return answer

def working(root):
    answer={};untracked=[]
    for raw in git(root,'ls-files','--stage','-z').split(b'\0'):
        if not raw:continue
        meta,name=raw.split(b'\t',1);mode,oid,stage=meta.decode().split();name=valid(name.decode())
        assert stage=='0' and mode in ('100644','100755')
        q=root/name;assert q.is_file() and not q.is_symlink()
        answer[name]=(mode,q.read_bytes())
    for raw in git(root,'ls-files','--others','--exclude-standard','-z').split(b'\0'):
        if not raw:continue
        name=valid(raw.decode());q=root/name;assert q.is_file() and not q.is_symlink()
        assert Path(name).name not in ('.env','credentials','credentials.json','secrets.json')
        answer[name]=('100755' if q.stat().st_mode&0o111 else '100644',q.read_bytes());untracked.append(name)
    return answer,untracked

def blob_tree(info):return {name:(mode,git(MAIN,'cat-file','blob',oid)) for name,(mode,oid) in info.items()}
def signature(value):return None if value is None else [value[0],sha(value[1])]
def snapshot(label,entries):
    result={}
    for name,(mode,data) in entries.items():
        path=ARCHIVE/'sources'/label/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(path,0o700 if mode=='100755' else 0o600)
        assert sha(path.read_bytes())==sha(data);result[name]={'git_mode':mode,'sha256':sha(data),'bytes':len(data)}
    save(ARCHIVE/(label+'-manifest.json'),result)

def main():
    os.umask(0o077)
    assert git(TARGET,'branch','--show-current').decode().strip()==BRANCH
    assert git(TARGET,'rev-parse','HEAD').decode().strip()==HEAD
    assert sha((MAIN/'.git/index').read_bytes())==INDEX
    assert not ARCHIVE.exists();ARCHIVE.mkdir(mode=0o700)
    old_main_status=git(MAIN,'status','--porcelain=v1','-z','--untracked-files=all')
    old_proto_status=git(PROTO,'status','--porcelain=v1','-z','--untracked-files=all')
    actual_index=(MAIN/'.git/index').read_bytes();(ARCHIVE/'primary-index.before').write_bytes(actual_index)
    retained,main_untracked=working(MAIN);prototype,proto_untracked=working(PROTO)
    assert main_untracked==['Pipfile'] and len(proto_untracked)==18
    # Pipfile is a dependency manifest; reject embedded URL credentials rather
    # than incorporating them into the source branch.
    import re
    assert not re.search(rb'https?://[^/\s:@]+:[^/\s@]+@',retained['Pipfile'][1])
    base=blob_tree(tree(BASE));committed=blob_tree(tree(HEAD))
    for label,entries in [('base',base),('retained-working',retained),('prototype-working',prototype)]:snapshot(label,entries)
    provenance={'base':BASE,'prototype_head':HEAD,'branch':BRANCH,'target':str(TARGET),'primary_index_sha256':INDEX,'main_untracked':main_untracked,'prototype_untracked':proto_untracked,'created_utc':datetime.now(timezone.utc).isoformat(),'scope':'Tracked source plus explicit nonignored untracked work only; vaults/runtime/private documents excluded and preserved at original locations.'}
    save(ARCHIVE/'PROVENANCE.json',provenance)
    decisions=[];results={};counts=Counter()
    for name in sorted(set(base)|set(retained)|set(prototype)):
        o,a,b=base.get(name),retained.get(name),prototype.get(name)
        chosen=None;kind='';unresolved=False
        if a==b:chosen=a;kind='identical-retained-and-prototype'
        elif a==o:chosen=b;kind='prototype-only-change'
        elif b==o:chosen=a;kind='retained-only-change'
        elif a is not None and b is not None:
            mode=a[0] if a[0]==b[0] or o is not None and b[0]==o[0] else b[0]
            textual=True
            for v in [a,b,o]:
                if v is None:continue
                try:v[1].decode('utf-8')
                except UnicodeDecodeError:textual=False
                if b'\0' in v[1]:textual=False
            if textual:
                oa=ARCHIVE/'sources/retained-working'/name;ob=ARCHIVE/'sources/prototype-working'/name
                oo=ARCHIVE/'sources/base'/name
                if o is None:
                    oo=ARCHIVE/'empty-base';oo.touch(exist_ok=True)
                proc=subprocess.run(['/usr/bin/git','merge-file','--diff3','--stdout','-L','retained-main-import','-L','base-61d3820','-L','sample-completion',str(oa),str(oo),str(ob)],capture_output=True)
                assert 0<=proc.returncode<=127
                chosen=(mode,proc.stdout);unresolved=proc.returncode!=0
                kind='text-conflict' if unresolved else 'clean-textual-merge-needs-semantic-review'
            else:chosen=b;kind='binary-conflict-prototype-kept-both-archived';unresolved=True
        else:chosen=b if b is not None else a;kind='modify-delete-conflict-both-archived';unresolved=True
        results[name]=chosen;counts[kind]+=1
        decisions.append({'path':name,'base':signature(o),'retained':signature(a),'prototype':signature(b),'prepared_result':signature(chosen),'decision':kind,'unresolved':unresolved})
    # Check every destination before any source file replacement.
    for name in results:
        p=TARGET/name;expected=committed.get(name)
        assert (p.read_bytes() if p.exists() else None)==(expected[1] if expected is not None else None),name
    assert sha((MAIN/'.git/index').read_bytes())==INDEX
    assert working(MAIN)[0]==retained and working(PROTO)[0]==prototype
    save(ARCHIVE/'PREPARED-COVERAGE.json',{'counts':dict(counts),'paths':decisions})
    for name,value in results.items():
        p=TARGET/name
        if value is None:
            if p.exists():p.unlink()
            continue
        mode,data=value;p.parent.mkdir(parents=True,exist_ok=True)
        temporary=p.with_name(p.name+'.consolidation-next');assert not temporary.exists()
        with temporary.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(temporary,0o755 if mode=='100755' else 0o644);os.replace(temporary,p)
        assert p.read_bytes()==data
    assert git(MAIN,'status','--porcelain=v1','-z','--untracked-files=all')==old_main_status
    assert git(PROTO,'status','--porcelain=v1','-z','--untracked-files=all')==old_proto_status
    assert (MAIN/'.git/index').read_bytes()==actual_index
    report=TARGET/'docs/consolidation/2026-11-05';report.mkdir(parents=True,exist_ok=True)
    save(report/'COVERAGE.json',{'provenance':provenance,'counts':dict(counts),'paths':decisions})
    summary={'status':'THREE_WAY_PREPARATION_COMPLETE_SEMANTIC_REVIEW_REQUIRED','paths':len(decisions),'counts':dict(counts),'unresolved':[v['path'] for v in decisions if v['unresolved']],'primary_index_unchanged':True,'both_original_source_trees_unchanged':True,'source_archive':str(ARCHIVE),'branch':BRANCH,'worktree':str(TARGET),'new_commits':0,'pushes':0}
    save(report/'PREPARATION-RESULT.json',summary);save(ARCHIVE/'PREPARATION-RESULT.json',summary)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
