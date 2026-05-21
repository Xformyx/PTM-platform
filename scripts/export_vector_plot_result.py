#!/usr/bin/env python3
"""
export_vector_plot_result.py
────────────────────────────────────────────────────────────────────────────────
PTM Platform — Vector Plot + Receptor Inference 결과 내보내기 스크립트

사용법:
  python export_vector_plot_result.py --order_id 42 --top_n 30
  python export_vector_plot_result.py --order_id 42 --lock_receptor
  python export_vector_plot_result.py --order_id 42 --force_refresh --top_n 50

출력:
  results/<ORDER_CODE>_<ptm_type>_top<N>_<timestamp>.json

의존성:
  pip install requests  (표준 라이브러리 외 유일한 의존성)

설정:
  환경변수 또는 스크립트 내 BASE_URL / TOKEN 수정
────────────────────────────────────────────────────────────────────────────────
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' 패키지가 필요합니다. pip install requests")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# 설정 — 환경변수 우선, 없으면 기본값
# ═══════════════════════════════════════════════════════════════════════════════
BASE_URL = os.environ.get("PTM_API_URL", "http://localhost:8000/api")
TOKEN = os.environ.get("PTM_API_TOKEN", "")  # JWT 토큰 (로그인 후 획득)
OUTPUT_DIR = os.environ.get("PTM_EXPORT_DIR", "results")


def get_auth_headers() -> dict:
    """인증 헤더 생성. TOKEN이 비어있으면 쿠키 기반 인증 시도."""
    if TOKEN:
        return {"Authorization": f"Bearer {TOKEN}"}
    return {}


def fetch_order_info(order_id: int) -> dict:
    """Order 기본 정보 조회 (order_code, ptm_type, analysis_context 등)."""
    url = f"{BASE_URL}/orders/{order_id}"
    resp = requests.get(url, headers=get_auth_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_vector_plot_data(
    order_id: int,
    top_n: int | None = None,
    lock_receptor: bool = False,
    force_refresh: bool = False,
) -> dict:
    """vector-plot-data 엔드포인트 호출."""
    url = f"{BASE_URL}/orders/{order_id}/vector-plot-data"
    params = {}
    if lock_receptor:
        params["lock_receptor"] = "true"
    if force_refresh:
        params["force_refresh"] = "true"

    resp = requests.get(url, headers=get_auth_headers(), params=params, timeout=120)
    resp.raise_for_status()
    return resp.json()


def build_export(
    order_info: dict,
    vector_plot_response: dict,
    args: argparse.Namespace,
) -> dict:
    """내보내기용 구조화된 JSON 생성."""
    now = datetime.now()

    # Receptor inference 상세 분석
    receptors = vector_plot_response.get("inferred_receptors", [])
    source_breakdown = {"literature": [], "reactome": [], "e3_ligase_db": [],
                        "ubiquitylation_db_client": [], "treatment_context": [],
                        "treatment_context_uniprot": []}
    for rec in receptors:
        src = rec.get("source", "unknown")
        if src in source_breakdown:
            source_breakdown[src].append(rec.get("name", ""))
        else:
            source_breakdown.setdefault(src, []).append(rec.get("name", ""))

    # Top N PTMs 요약
    top_n_ptms = vector_plot_response.get("top_n_ptms", [])
    protein_classes = {}
    for ptm in top_n_ptms:
        pc = ptm.get("protein_class", "unknown")
        protein_classes[pc] = protein_classes.get(pc, 0) + 1

    export = {
        # ── 메타 정보 ──
        "meta": {
            "export_timestamp": now.isoformat(),
            "export_timestamp_readable": now.strftime("%Y-%m-%d %H:%M:%S"),
            "script_version": "1.0.0",
            "api_base_url": BASE_URL,
            "call_params": {
                "order_id": args.order_id,
                "top_n": args.top_n,
                "lock_receptor": args.lock_receptor,
                "force_refresh": args.force_refresh,
            },
        },

        # ── Order 정보 ──
        "order": {
            "id": order_info.get("id"),
            "order_code": order_info.get("order_code", ""),
            "ptm_type": order_info.get("ptm_type", ""),
            "status": order_info.get("status", ""),
            "treatment": (order_info.get("analysis_context") or {}).get("treatment", ""),
            "cell_line": (order_info.get("analysis_context") or {}).get("cell_line", ""),
            "species": order_info.get("species", ""),
            "top_n_setting": vector_plot_response.get("top_n_setting"),
            "suggested_n": vector_plot_response.get("suggested_n"),
            "data_source": vector_plot_response.get("source", ""),
        },

        # ── Receptor Inference 결과 ──
        "receptor_inference": {
            "total_count": len(receptors),
            "source_breakdown": {k: len(v) for k, v in source_breakdown.items() if v},
            "source_details": {k: v for k, v in source_breakdown.items() if v},
            "receptors": receptors,
        },

        # ── Top N PTMs ──
        "top_n_ptms": {
            "count": len(top_n_ptms),
            "protein_class_distribution": protein_classes,
            "items": top_n_ptms,
        },

        # ── Vector Data 통계 ──
        "vector_data_stats": _compute_vector_stats(vector_plot_response.get("vector_data", [])),

        # ── 원본 응답 (전체) ──
        "raw_response": vector_plot_response,
    }

    return export


def _compute_vector_stats(vector_data: list) -> dict:
    """Vector data에서 기본 통계 계산."""
    if not vector_data:
        return {"total_rows": 0}

    conditions = set()
    genes = set()
    fc_values = []

    for row in vector_data:
        conditions.add(row.get("condition", ""))
        genes.add(row.get("gene", ""))
        fc = row.get("ptm_relative_log2fc", 0)
        if fc != 0:
            fc_values.append(fc)

    stats = {
        "total_rows": len(vector_data),
        "unique_genes": len(genes),
        "conditions": sorted(conditions - {""}),
        "condition_count": len(conditions - {""}),
    }

    if fc_values:
        import statistics
        stats["fc_stats"] = {
            "min": round(min(fc_values), 4),
            "max": round(max(fc_values), 4),
            "mean": round(statistics.mean(fc_values), 4),
            "median": round(statistics.median(fc_values), 4),
            "stdev": round(statistics.stdev(fc_values), 4) if len(fc_values) > 1 else 0,
            "count_nonzero": len(fc_values),
        }

    return stats


def save_export(export: dict, order_info: dict, args: argparse.Namespace) -> Path:
    """결과를 JSON 파일로 저장."""
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    order_code = order_info.get("order_code", f"order_{args.order_id}")
    ptm_type = order_info.get("ptm_type", "unknown")
    ptm_short = "phos" if "phospho" in ptm_type.lower() else "ubi"
    top_n = export["order"]["top_n_setting"] or args.top_n or "auto"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = f"{order_code}_{ptm_short}_top{top_n}_{timestamp}.json"
    filepath = out_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2, default=str)

    return filepath


def print_summary(export: dict, filepath: Path):
    """콘솔에 요약 출력."""
    meta = export["meta"]
    order = export["order"]
    ri = export["receptor_inference"]
    ptms = export["top_n_ptms"]
    stats = export["vector_data_stats"]

    print("\n" + "═" * 70)
    print("  PTM Vector Plot Result Export")
    print("═" * 70)
    print(f"  시각: {meta['export_timestamp_readable']}")
    print(f"  Order: {order['order_code']} (ID: {order['id']})")
    print(f"  PTM Type: {order['ptm_type']}")
    print(f"  Treatment: {order['treatment'] or '(없음)'}")
    print(f"  Cell Line: {order['cell_line'] or '(없음)'}")
    print(f"  Top N: {order['top_n_setting']} (suggested: {order['suggested_n']})")
    print("─" * 70)
    print(f"  📊 Vector Data: {stats['total_rows']} rows, "
          f"{stats.get('unique_genes', 0)} genes, "
          f"{stats.get('condition_count', 0)} conditions")
    if "fc_stats" in stats:
        fc = stats["fc_stats"]
        print(f"     Log2FC range: [{fc['min']}, {fc['max']}], "
              f"mean={fc['mean']}, stdev={fc['stdev']}")
    print(f"  🧬 Top N PTMs: {ptms['count']} sites")
    if ptms["protein_class_distribution"]:
        for cls, cnt in sorted(ptms["protein_class_distribution"].items(),
                               key=lambda x: -x[1]):
            print(f"     • {cls}: {cnt}")
    print(f"  🎯 Receptors: {ri['total_count']} inferred")
    if ri["source_breakdown"]:
        for src, cnt in sorted(ri["source_breakdown"].items(), key=lambda x: -x[1]):
            names = ri["source_details"].get(src, [])
            preview = ", ".join(names[:3])
            suffix = f" +{len(names)-3}" if len(names) > 3 else ""
            print(f"     • {src}: {cnt} ({preview}{suffix})")
    print("─" * 70)
    print(f"  💾 저장: {filepath}")
    print(f"     크기: {filepath.stat().st_size / 1024:.1f} KB")
    print("═" * 70)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="PTM Platform vector-plot-data 결과를 JSON으로 내보내기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 기본 호출 (현재 설정된 top_n 사용)
  python export_vector_plot_result.py --order_id 42

  # top_n 지정하여 호출
  python export_vector_plot_result.py --order_id 42 --top_n 30

  # Receptor 결과 고정 (캐시된 값 사용)
  python export_vector_plot_result.py --order_id 42 --lock_receptor

  # 강제 재계산 (캐시 무시)
  python export_vector_plot_result.py --order_id 42 --force_refresh

  # 반복 비교 (3회 연속 호출)
  python export_vector_plot_result.py --order_id 42 --repeat 3

환경변수:
  PTM_API_URL    API 기본 URL (기본: http://localhost:8000/api)
  PTM_API_TOKEN  JWT 인증 토큰
  PTM_EXPORT_DIR 출력 디렉토리 (기본: results/)
        """,
    )
    parser.add_argument("--order_id", type=int, required=True, help="Order ID")
    parser.add_argument("--top_n", type=int, default=None,
                        help="Top N PTM 수 (미지정 시 서버 설정 사용)")
    parser.add_argument("--lock_receptor", action="store_true",
                        help="저장된 receptor 결과를 고정 (재계산 안 함)")
    parser.add_argument("--force_refresh", action="store_true",
                        help="캐시 무시하고 receptor 강제 재계산")
    parser.add_argument("--repeat", type=int, default=1,
                        help="반복 호출 횟수 (결과 변동 비교용, 기본: 1)")
    parser.add_argument("--base_url", type=str, default=None,
                        help="API 기본 URL 오버라이드")
    parser.add_argument("--token", type=str, default=None,
                        help="JWT 토큰 오버라이드")
    parser.add_argument("--output_dir", type=str, default=None,
                        help="출력 디렉토리 오버라이드")
    parser.add_argument("--no_raw", action="store_true",
                        help="raw_response (전체 vector_data) 제외하여 파일 크기 축소")
    parser.add_argument("--quiet", action="store_true",
                        help="요약 출력 생략")

    args = parser.parse_args()

    # 오버라이드 적용
    global BASE_URL, TOKEN, OUTPUT_DIR
    if args.base_url:
        BASE_URL = args.base_url
    if args.token:
        TOKEN = args.token
    if args.output_dir:
        OUTPUT_DIR = args.output_dir

    # ── 실행 ──
    print(f"\n🔄 Order {args.order_id} 정보 조회 중...")
    try:
        order_info = fetch_order_info(args.order_id)
    except requests.HTTPError as e:
        print(f"❌ Order 조회 실패: {e}")
        print(f"   URL: {BASE_URL}/orders/{args.order_id}")
        print(f"   인증 토큰이 설정되었는지 확인하세요.")
        sys.exit(1)
    except requests.ConnectionError:
        print(f"❌ 서버 연결 실패: {BASE_URL}")
        print(f"   서버가 실행 중인지 확인하세요.")
        sys.exit(1)

    print(f"   ✓ Order: {order_info.get('order_code')} ({order_info.get('ptm_type')})")

    saved_files = []
    for i in range(args.repeat):
        if args.repeat > 1:
            print(f"\n🔄 [{i+1}/{args.repeat}] vector-plot-data 호출 중...")
        else:
            print(f"\n🔄 vector-plot-data 호출 중...")

        try:
            vp_data = fetch_vector_plot_data(
                order_id=args.order_id,
                top_n=args.top_n,
                lock_receptor=args.lock_receptor,
                force_refresh=args.force_refresh,
            )
        except requests.HTTPError as e:
            print(f"❌ vector-plot-data 호출 실패: {e}")
            sys.exit(1)

        export = build_export(order_info, vp_data, args)

        # --no_raw 옵션: 대용량 vector_data 제외
        if args.no_raw:
            export.pop("raw_response", None)

        filepath = save_export(export, order_info, args)
        saved_files.append(filepath)

        if not args.quiet:
            print_summary(export, filepath)

    # 반복 호출 시 diff 요약
    if args.repeat > 1 and len(saved_files) > 1:
        print("\n" + "═" * 70)
        print("  반복 호출 비교 요약")
        print("═" * 70)
        receptor_sets = []
        for fp in saved_files:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            recs = [r["name"] for r in data.get("receptor_inference", {}).get("receptors", [])]
            receptor_sets.append(set(recs))
            print(f"  {fp.name}: {len(recs)} receptors")

        # 변동 분석
        all_same = all(s == receptor_sets[0] for s in receptor_sets)
        if all_same:
            print("\n  ✅ 모든 호출에서 receptor 결과 동일 (안정적)")
        else:
            common = receptor_sets[0]
            for s in receptor_sets[1:]:
                common &= s
            all_union = set()
            for s in receptor_sets:
                all_union |= s
            variable = all_union - common
            print(f"\n  ⚠️  결과 변동 감지!")
            print(f"     공통: {len(common)} receptors")
            print(f"     변동: {len(variable)} receptors: {sorted(variable)}")
        print("═" * 70)
        print()

    print(f"✅ 완료! {len(saved_files)}개 파일 저장됨: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
