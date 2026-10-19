"""Preview or atomically import reviewed actual sales into the existing retailer reference file."""
import argparse,json,os,tempfile
from pathlib import Path
from app.marketplaces.sold_import import reference
from app.deal_references import load,_BIND

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('file',type=Path);p.add_argument('--apply',action='store_true')
    p.add_argument('--references',type=Path,default=Path(os.getenv('LOTUS_DEAL_REFERENCES_FILE','/app/app/deal-references.json')))
    a=p.parse_args()
    try:
        if a.file.stat().st_size>2_000_000:raise ValueError('INPUT_TOO_LARGE')
        ref=reference(json.loads(a.file.read_text()))
        if a.apply:
            import fcntl
            a.references.parent.mkdir(parents=True,exist_ok=True)
            with a.references.with_suffix(a.references.suffix+'.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                existing=load(a.references)
                same=lambda r: r.get('import_method')==ref['import_method'] and r.get('marketplace')==ref['marketplace'] and all(r.get(k)==ref[k] for k in _BIND)
                # Replace this importer’s previous benchmark only; preserve other references.
                rows=[r for r in existing if not same(r)]+[ref]
                fd,tmp=tempfile.mkstemp(dir=a.references.parent,prefix='.lotus-market-',suffix='.json')
                try:
                    with os.fdopen(fd,'w') as f:json.dump(rows,f,indent=2);f.flush();os.fsync(f.fileno())
                    load(tmp)
                    if a.references.exists():
                        backup=a.references.with_name(a.references.name+'.backup-'+__import__('uuid').uuid4().hex[:8])
                        with backup.open('x') as f:f.write(a.references.read_text())
                    os.replace(tmp,a.references)
                finally:
                    if os.path.exists(tmp):os.unlink(tmp)
        print(json.dumps({'state':'IMPORTED' if a.apply else 'PREVIEW','reference':ref,'alerts_sent':0,
            'note':'Applies to exact retailer product only; does not enable a marketplace listing worker. Persist this reference file across deployments.'},indent=2))
        return 0
    except (ValueError,TypeError,KeyError,OSError,ArithmeticError) as e:
        print(json.dumps({'state':'IMPORT_FAILED','error_type':type(e).__name__,'alerts_sent':0}));return 1
if __name__=='__main__':raise SystemExit(main())
