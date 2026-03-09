#!/usr/bin/env python3
"""
ChromaDB Collection Migration Script
=====================================

ptm-chromadb-web에서 추출한 컬렉션 데이터(JSON)를 PTM-platform의 ChromaDB에 import합니다.

사용법:
    python migrate_collection.py <json_file> [--chromadb-path /path/to/chromadb_data]
    python migrate_collection.py <json_file> [--chromadb-host localhost --chromadb-port 8000]

예시:
    # 로컬 PersistentClient 모드 (Mac Studio에서 직접 실행)
    python migrate_collection.py hippocampal_neurons_export.json --chromadb-path ./chromadb_data

    # HTTP Client 모드 (ChromaDB 서버가 별도로 실행 중인 경우)
    python migrate_collection.py hippocampal_neurons_export.json --chromadb-host localhost --chromadb-port 8000

필요 패키지:
    pip install chromadb
"""

import argparse
import json
import sys
from pathlib import Path


def load_export_data(json_path: str) -> dict:
    """JSON 파일에서 컬렉션 데이터를 로드합니다."""
    path = Path(json_path)
    if not path.exists():
        print(f"[ERROR] 파일을 찾을 수 없습니다: {json_path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"[INFO] 로드 완료: {data['collection_name']}")
    print(f"  - 문서 수: {data['count']}")
    print(f"  - Embedding 차원: {data['dimension']}")
    print(f"  - Embedding 모델: {data['embedding_model']}")
    return data


def get_chromadb_client(args):
    """인자에 따라 ChromaDB 클라이언트를 생성합니다."""
    import chromadb

    if args.chromadb_path:
        print(f"[INFO] PersistentClient 모드: {args.chromadb_path}")
        return chromadb.PersistentClient(path=args.chromadb_path)
    elif args.chromadb_host:
        print(f"[INFO] HttpClient 모드: {args.chromadb_host}:{args.chromadb_port}")
        return chromadb.HttpClient(host=args.chromadb_host, port=args.chromadb_port)
    else:
        print("[ERROR] --chromadb-path 또는 --chromadb-host를 지정해주세요.")
        sys.exit(1)


def migrate_collection(client, data: dict, force: bool = False):
    """컬렉션 데이터를 ChromaDB에 import합니다."""
    collection_name = data["collection_name"]

    # 기존 컬렉션 확인
    existing_names = [c.name for c in client.list_collections()]
    if collection_name in existing_names:
        existing = client.get_collection(collection_name)
        existing_count = existing.count()
        if existing_count > 0 and not force:
            print(f"[WARN] '{collection_name}' 컬렉션이 이미 존재합니다 ({existing_count} items).")
            print(f"  --force 옵션을 사용하면 기존 데이터를 삭제하고 다시 import합니다.")
            response = input("  계속하시겠습니까? (y/N): ").strip().lower()
            if response != "y":
                print("[INFO] 마이그레이션을 취소합니다.")
                return
        if existing_count > 0:
            print(f"[INFO] 기존 컬렉션 삭제 중...")
            client.delete_collection(collection_name)

    # 컬렉션 생성
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "l2"},
    )

    # 배치 단위로 데이터 삽입 (ChromaDB 제한: 한 번에 최대 5461개)
    batch_size = 100
    total = len(data["ids"])
    print(f"[INFO] '{collection_name}' 컬렉션에 {total}개 항목을 import합니다...")

    for i in range(0, total, batch_size):
        end = min(i + batch_size, total)
        batch_ids = data["ids"][i:end]
        batch_docs = data["documents"][i:end]
        batch_metas = data["metadatas"][i:end]
        batch_embeds = data["embeddings"][i:end]

        collection.add(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_metas,
            embeddings=batch_embeds,
        )
        print(f"  [{end}/{total}] 완료")

    # 검증
    final_count = collection.count()
    print(f"\n[SUCCESS] 마이그레이션 완료!")
    print(f"  - 컬렉션: {collection_name}")
    print(f"  - Import된 항목 수: {final_count}")
    if final_count == total:
        print(f"  - 검증: OK (원본 {total}개 == import {final_count}개)")
    else:
        print(f"  - [WARN] 검증 실패: 원본 {total}개 != import {final_count}개")


def main():
    parser = argparse.ArgumentParser(
        description="ChromaDB 컬렉션 마이그레이션 스크립트"
    )
    parser.add_argument(
        "json_file",
        help="import할 컬렉션 데이터 JSON 파일 경로",
    )
    parser.add_argument(
        "--chromadb-path",
        help="ChromaDB PersistentClient 데이터 디렉토리 경로 (로컬 모드)",
    )
    parser.add_argument(
        "--chromadb-host",
        help="ChromaDB 서버 호스트 (HTTP 모드)",
        default=None,
    )
    parser.add_argument(
        "--chromadb-port",
        help="ChromaDB 서버 포트 (HTTP 모드)",
        type=int,
        default=8000,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 컬렉션이 있으면 삭제 후 재생성",
    )

    args = parser.parse_args()

    # 데이터 로드
    data = load_export_data(args.json_file)

    # ChromaDB 클라이언트 생성
    client = get_chromadb_client(args)

    # 마이그레이션 실행
    migrate_collection(client, data, force=args.force)


if __name__ == "__main__":
    main()
