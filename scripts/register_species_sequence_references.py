"""Install the declared species sequence references.

구현 대상: docs/astra_science_upgrade/operations_KO.md «등록된 종별 sequence reference»
사전등록: 2026-10-12. 주문 실행 전. 선언된 파일명만 등록한다.
해석 한계: 설치는 hard link와 sha256 manifest다. 종 폴더의 다른 FASTA는 고르지 않는다.
주장 금지: 등록 파일이 kinase 귀속 정확도를 높인다고 하지 않는다.
"""
import json
import os
from pathlib import Path

from ptm_shared.species_sequence_reference import install_declared_references


def main() -> None:
    root = Path(os.environ.get('REFERENCE_DIR', 'data/reference'))
    installed = install_declared_references(root)
    print(json.dumps({'reference_root': str(root), 'installed': installed}, indent=2))


if __name__ == '__main__':
    main()
