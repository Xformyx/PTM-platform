"""Register a checked, content-addressed annotation snapshot without network access."""
import argparse
import json
from pathlib import Path
import shutil

from ptm_shared.report_compatible_extensions import file_digest
from ptm_shared.enrichment_free_profile import annotation_snapshot


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--audit-dir',type=Path,required=True)
    p.add_argument('--sha256',required=True)
    p.add_argument('--reference-root',type=Path,required=True)
    args=p.parse_args()
    if file_digest(args.snapshot)!=args.sha256:
        p.error('Snapshot SHA-256 mismatch')
    metadata=json.loads((args.audit_dir/'annotation_metadata.json').read_text())
    if metadata.get('database_sha256')!=args.sha256:
        p.error('Annotation metadata SHA-256 mismatch')
    root=args.reference_root/'frozen_annotations'; target=root/args.sha256
    if target.exists():
        print(json.dumps(annotation_snapshot(root,args.sha256),indent=2)); return
    target.mkdir(parents=True)
    shutil.copyfile(args.snapshot,target/'snapshot.tsv')
    for name in ['annotation_metadata.json','manual_primary_source_audit.tsv','pmid_16914728.json','pmid_42644392.json']:
        source=args.audit_dir/name
        if source.is_file():shutil.copyfile(source,target/name)
    print(json.dumps(annotation_snapshot(root,args.sha256),indent=2))


if __name__=='__main__':main()
