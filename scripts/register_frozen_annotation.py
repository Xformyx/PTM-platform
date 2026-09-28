"""Register a checked, content-addressed annotation snapshot without network access."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

from ptm_shared.report_compatible_extensions import file_digest
from ptm_shared.annotation_registry import inspect_snapshot,RegistryError,adapted_metadata


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--audit-dir',type=Path,required=True)
    p.add_argument('--sha256',required=True)
    p.add_argument('--reference-root',type=Path,required=True)
    p.add_argument('--recover-incomplete',action='store_true',help='Preserve an invalid existing registration under a hidden recovery name and atomically install the checked replacement')
    args=p.parse_args()
    if file_digest(args.snapshot)!=args.sha256:
        p.error('Snapshot SHA-256 mismatch')
    metadata=json.loads((args.audit_dir/'annotation_metadata.json').read_text())
    if metadata.get('database_sha256')!=args.sha256:
        p.error('Annotation metadata SHA-256 mismatch')
    root=args.reference_root/'frozen_annotations'; target=root/args.sha256
    if target.exists():
        try:
            checked=inspect_snapshot(root,args.sha256)
        except RegistryError:
            if not args.recover_incomplete:p.error('Registration is incomplete/invalid; review it, then retry with --recover-incomplete to preserve and replace it')
        else:
            print(json.dumps({k:v for k,v in checked.items() if k not in {'snapshot_path','reference_dir','metadata'}},indent=2));return
    root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.register-',dir=root) as temporary:
        staged=Path(temporary)/args.sha256;staged.mkdir()
        shutil.copyfile(args.snapshot,staged/'snapshot.tsv')
        metadata=adapted_metadata(metadata,args.sha256)
        names=set(metadata.get('required_files',[]))|{'manual_primary_source_audit.tsv','pmid_16914728.json','pmid_42644392.json'}
        hashes={}
        for name in names:
            if Path(name).name!=name:p.error('Audit file names must be local basenames')
            source=args.audit_dir/name
            if source.is_file():
                shutil.copyfile(source,staged/name);hashes[name]=file_digest(staged/name)
        metadata['file_sha256']={**metadata.get('file_sha256',{}),**hashes}
        (staged/'annotation_metadata.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False))
        inspect_snapshot(Path(temporary),args.sha256)
        if target.exists():
            try:inspect_snapshot(root,args.sha256)
            except RegistryError:target.rename(root/('.incomplete-'+args.sha256+'-'+uuid4().hex))
            else:p.error('A valid immutable snapshot was concurrently registered; retry to use it')
        staged.rename(target)
    checked=inspect_snapshot(root,args.sha256)
    print(json.dumps({k:v for k,v in checked.items() if k not in {'snapshot_path','reference_dir','metadata'}},indent=2))


if __name__=='__main__':main()
