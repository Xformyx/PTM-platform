# PTM-platform 코드 리뷰 및 버그 분석 보고서

**작성일**: 2026-03-13

---

## Part 1: 수정 파일별 코드 검증 결과

### 1.1 검증 요약

| 파일 | 변경 내용 | 검증 결과 |
|------|-----------|-----------|
| `api-server/app/api/health.py` | Container Status/Logs API, KST 변환 | **정상** |
| `api-server/app/api/orders.py` | `md_report_path` config 전달 | **정상** |
| `api-server/app/api/rag.py` | PATCH `is_active` 토글 API | **정상** |
| `api-server/pyproject.toml` | `docker>=7.0.0` 의존성 추가 | **정상** |
| `docker-compose.yml` | `extra_hosts`, Docker 소켓 마운트 | **정상** |
| `docs/02-build-and-run.md` | Cytoscape 트러블슈팅 안내 | **정상** |
| `frontend/src/components/RerunOptionsModal.tsx` | Rerun 모달 UI/동작 수정 | **정상** |
| `frontend/src/pages/LlmConfig.tsx` | LLM 설정 확장 | **정상** |
| `frontend/src/pages/OrderCreate.tsx` | Order 생성 플로우 수정 | **정상** |
| `frontend/src/pages/OrderDetail.tsx` | Order 상세 UI 수정 | **정상** |
| `frontend/src/pages/RagManagement.tsx` | `is_active` 토글 스위치 추가 | **정상** |
| `frontend/src/pages/SystemMonitor.tsx` | Container Status/Logs 섹션 추가 | **정상** |
| `workers/preprocessing/tasks.py` | 설정/환경 변수 소규모 수정 | **정상** |
| `workers/rag_enrichment/tasks.py` | config 전달 방식 수정 | **정상** |
| `workers/report_generation/core/graph.py` | `format_citations`에 network section 포함 | **정상** |
| `workers/report_generation/core/nodes/network_node.py` | Cytoscape 재시도, 절대경로, ptm_only 모드 | **버그 2건 발견** |
| `workers/report_generation/core/rag_retriever.py` | `_resolve_existing_collections()` 추가 | **정상** |

### 1.2 전체적 평가

대부분의 수정 사항은 올바르게 구현되어 있습니다. Container Status/Logs API, RAG is_active 토글, Cytoscape 재시도 로직, `_resolve_existing_collections` 등은 잘 설계되었습니다.

---

## Part 2: 발견된 버그 (Critical 2건)

### 버그 1 (Critical): `network_results`가 LangGraph State에 전달되지 않음

**증상**: `writer_node.py`에서 `state.get("network_results", {})`가 항상 빈 dict `{}`를 반환하여, v98 structured protein data가 생성되지 않고 anti-hallucination 기능이 작동하지 않음.

**원인**: `network_node.py`의 `run_network_analysis()`가 `"network_results"` 키를 반환하지만, `graph.py`의 `ReportState(TypedDict)`에 `network_results` 필드가 **정의되어 있지 않습니다**.

```python
# graph.py - ReportState에 network_results가 없음!
class ReportState(TypedDict, total=False):
    ...
    network_analysis: dict      # ← 이것만 있음
    # network_results: dict     # ← 이것이 없음!
    ...
```

**LangGraph의 동작**: TypedDict에 정의되지 않은 키는 노드 반환값에 포함되어도 **state에 저장되지 않고 무시**됩니다. 이것을 실제 테스트로 확인했습니다:

```python
# 테스트 결과
def node1(state):
    return {'a': 'hello', 'extra_key': 'world'}  # extra_key는 TypedDict에 없음

def node2(state):
    val = state.get('extra_key', 'NOT FOUND')
    print(f'extra_key in node2: {val}')  # 출력: "NOT FOUND"
```

**영향 범위**:
- `writer_node.py` 라인 105-115: `network_results`가 항상 `{}`이므로 `build_structured_protein_data_for_llm()`이 빈 데이터를 받아 `("", [], [])` 반환
- v98 anti-hallucination directive가 비어 있어 LLM에 전달되지 않음
- `validate_llm_output_against_data()`에서 `v98_protein_names`가 빈 리스트이므로 검증 건너뜀

**수정**: `ReportState`에 `network_results: dict` 추가

```python
# graph.py 수정
class ReportState(TypedDict, total=False):
    ...
    network_analysis: dict
    network_results: dict          # ← 추가
    ...
```

---

### 버그 2 (Critical): Cytoscape export 경로 불일치 — Docker 내부 경로 vs 호스트 경로

**증상**: Cytoscape가 연결되어 네트워크를 생성하지만, 이미지 파일이 실제로 저장되지 않거나 비어 있음.

**원인**: `_save_network_png()` (라인 700-731)에서 `p4c.export_image(filename=str(png_file), ...)`를 호출할 때:

```
Docker 컨테이너 내부 경로: /app/data/outputs/ORDER_CODE/PTM_Signaling_Network.png
호스트 머신 실제 경로:     ./data/outputs/ORDER_CODE/PTM_Signaling_Network.png
```

`py4cytoscape.export_image()`는 Cytoscape Desktop의 CyREST API를 호출합니다. Cytoscape Desktop은 **호스트 머신**에서 실행되므로, `/app/data/outputs/...` 경로는 호스트에 존재하지 않습니다. 따라서:

1. Cytoscape가 해당 경로에 파일을 쓰려고 시도하지만 실패하거나
2. 호스트의 `/app/data/outputs/...` 경로에 파일을 생성하지만, Docker 컨테이너의 `./data/outputs/...`와 매핑되지 않음

**수정 방안 A (권장)**: CyREST API를 직접 호출하여 이미지를 바이너리로 받아 컨테이너 내부에서 직접 저장

```python
def _save_network_png(p4c, network_suid: int, network_name: str, output_dir: str) -> Optional[str]:
    """Export network as 300dpi PNG via CyREST direct download."""
    try:
        import requests
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        png_file = output_path / f"{network_name}.png"

        p4c.fit_content(network=network_suid)
        time.sleep(0.5)

        # 방법 1: CyREST API 직접 호출로 이미지 바이너리 수신
        base_url = _cytoscape_base_url()
        # 현재 뷰의 PNG를 직접 다운로드
        view_url = f"{base_url}/networks/{network_suid}/views/first.png?h=2400"
        resp = requests.get(view_url, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 1000:
            with open(png_file, "wb") as f:
                f.write(resp.content)
            logger.info(f"Network PNG saved via CyREST direct: {png_file} ({len(resp.content)} bytes)")
            return str(png_file)

        # 방법 2: fallback - export_image with host path mapping
        host_output_dir = os.getenv("HOST_DATA_DIR", "")
        if host_output_dir:
            host_png = Path(host_output_dir) / "outputs" / Path(output_dir).name / f"{network_name}.png"
            p4c.export_image(filename=str(host_png), type="PNG", resolution=300,
                           network=network_suid, overwrite_file=True)
            time.sleep(1)
            if png_file.exists() and png_file.stat().st_size > 1000:
                return str(png_file)

        logger.warning(f"PNG export: both methods failed for {network_name}")
        return None
    except Exception as e:
        logger.warning(f"PNG export failed: {e}")
        return None
```

**수정 방안 B**: `docker-compose.yml`에 `HOST_DATA_DIR` 환경 변수 추가하여 호스트 경로 매핑

```yaml
celery-worker-report:
  environment:
    HOST_DATA_DIR: ${HOST_DATA_DIR:-/path/to/project/data}
```

---

### 버그 2-b (Minor): `generate_network_figure_section`에서 절대 경로 사용 시 Markdown 렌더링 실패

**증상**: `final_report.md`에 Docker 내부 절대 경로(`/app/data/outputs/...`)가 포함되어, 브라우저나 외부 Markdown 뷰어에서 이미지가 표시되지 않음.

**원인**: `network_node.py` 라인 778-779:

```python
img_ref = str(path_obj.resolve()) if path_obj and path_obj.exists() else None
```

이 코드는 컨테이너 내부 절대 경로를 Markdown에 삽입합니다. DOCX 변환은 같은 컨테이너에서 실행되므로 `os.path.isfile()` 체크를 통과하지만, Markdown 파일 자체는 외부에서 열 때 이미지가 깨집니다.

**수정**: 절대 경로 대신 상대 경로를 사용하거나, Base64 인라인 임베딩을 유지

```python
# 상대 경로 사용 (같은 디렉토리에 이미지가 있으므로)
img_ref = path_obj.name if path_obj and path_obj.exists() else None
```

또는 DOCX용으로는 절대 경로를 별도로 유지하고, Markdown에는 상대 경로 사용:

```python
if path_obj and path_obj.exists():
    # Markdown에는 상대 경로 (같은 output 디렉토리 내)
    img_ref = path_obj.name
else:
    # fallback: base64
    base64_img = image_to_base64(img_path) if img_path else None
    img_ref = base64_img
```

---

## Part 3: 수정 코드 제공

### 수정 1: `workers/report_generation/core/graph.py`

`ReportState`에 `network_results` 필드를 추가합니다.

**위치**: `workers/report_generation/core/graph.py` 라인 50 근처

**변경 전**:
```python
    network_analysis: dict
    sections: Dict[str, str]
```

**변경 후**:
```python
    network_analysis: dict
    network_results: dict
    sections: Dict[str, str]
```

### 수정 2: `workers/report_generation/core/nodes/network_node.py`

`_save_network_png` 함수를 CyREST 직접 다운로드 방식으로 변경하고, `generate_network_figure_section`에서 상대 경로를 사용합니다.

**수정 2-A**: `_save_network_png` 함수 (라인 700-731)

**변경 전**:
```python
def _save_network_png(p4c, network_suid: int, network_name: str, output_dir: str) -> Optional[str]:
    """Export network as 300dpi PNG."""
    try:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        png_file = output_path / f"{network_name}.png"

        # Delete existing file to avoid overwrite confirmation dialog
        if png_file.exists():
            try:
                png_file.unlink()
                logger.info(f"Deleted existing file: {png_file}")
            except Exception as del_err:
                logger.warning(f"Could not delete existing file: {del_err}")

        p4c.fit_content(network=network_suid)
        time.sleep(0.5)

        p4c.export_image(
            filename=str(png_file),
            type="PNG",
            resolution=300,
            network=network_suid,
            overwrite_file=True,
        )
        logger.info(f"Network PNG saved: {png_file}")
        return str(png_file)

    except Exception as e:
        logger.warning(f"PNG export failed: {e}")
        return None
```

**변경 후**:
```python
def _save_network_png(p4c, network_suid: int, network_name: str, output_dir: str) -> Optional[str]:
    """Export network as high-resolution PNG.
    
    Uses CyREST direct image download to avoid Docker/host path mismatch.
    Falls back to export_image with host path mapping if direct download fails.
    """
    try:
        import requests as _requests

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        png_file = output_path / f"{network_name}.png"

        # Delete existing file
        if png_file.exists():
            try:
                png_file.unlink()
            except Exception as del_err:
                logger.warning(f"Could not delete existing file: {del_err}")

        p4c.fit_content(network=network_suid)
        time.sleep(0.5)

        # --- Method 1: CyREST direct image download (Docker-safe) ---
        base_url = _cytoscape_base_url()
        try:
            # Get first view SUID
            views_resp = _requests.get(
                f"{base_url}/networks/{network_suid}/views",
                timeout=10,
            )
            if views_resp.status_code == 200:
                views = views_resp.json()
                view_suid = views[0] if views else None
            else:
                view_suid = None

            if view_suid is not None:
                img_resp = _requests.get(
                    f"{base_url}/networks/{network_suid}/views/{view_suid}/export/png"
                    f"?h=2400",
                    timeout=60,
                )
                if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                    with open(png_file, "wb") as f:
                        f.write(img_resp.content)
                    logger.info(
                        f"Network PNG saved via CyREST direct: {png_file} "
                        f"({len(img_resp.content):,} bytes)"
                    )
                    return str(png_file)
                else:
                    logger.warning(
                        f"CyREST image download returned status={img_resp.status_code}, "
                        f"size={len(img_resp.content) if img_resp.content else 0}"
                    )
        except Exception as direct_err:
            logger.warning(f"CyREST direct download failed: {direct_err}")

        # --- Method 2: Fallback to export_image with host path mapping ---
        host_data_dir = os.getenv("HOST_DATA_DIR", "")
        if host_data_dir:
            # Map container path to host path for Cytoscape Desktop
            order_dir_name = Path(output_dir).name
            host_png = Path(host_data_dir) / "outputs" / order_dir_name / f"{network_name}.png"
            host_png.parent.mkdir(parents=True, exist_ok=True)
            try:
                p4c.export_image(
                    filename=str(host_png),
                    type="PNG",
                    resolution=300,
                    network=network_suid,
                    overwrite_file=True,
                )
                time.sleep(1.5)
                if png_file.exists() and png_file.stat().st_size > 1000:
                    logger.info(f"Network PNG saved via host path mapping: {png_file}")
                    return str(png_file)
            except Exception as host_err:
                logger.warning(f"Host path export failed: {host_err}")

        # --- Method 3: Last resort - try original export_image ---
        try:
            p4c.export_image(
                filename=str(png_file),
                type="PNG",
                resolution=300,
                network=network_suid,
                overwrite_file=True,
            )
            time.sleep(1.5)
            if png_file.exists() and png_file.stat().st_size > 1000:
                logger.info(f"Network PNG saved via export_image: {png_file}")
                return str(png_file)
        except Exception as fallback_err:
            logger.warning(f"export_image fallback failed: {fallback_err}")

        logger.warning(f"All PNG export methods failed for {network_name}")
        return None

    except Exception as e:
        logger.warning(f"PNG export failed: {e}")
        return None
```

**수정 2-B**: `generate_network_figure_section` 함수 (라인 776-782)

**변경 전**:
```python
    for label, img_path in sorted(network_images.items()):
        path_obj = Path(img_path) if img_path else None
        # Use absolute file path for docx conversion (more reliable than base64 for large images)
        img_ref = str(path_obj.resolve()) if path_obj and path_obj.exists() else None
        if not img_ref:
            base64_img = image_to_base64(img_path) if img_path else None
            img_ref = base64_img
```

**변경 후**:
```python
    for label, img_path in sorted(network_images.items()):
        path_obj = Path(img_path) if img_path else None
        # Use relative filename for Markdown (works in both browser and docx conversion)
        # The image file is in the same output directory as final_report.md
        if path_obj and path_obj.exists() and path_obj.stat().st_size > 1000:
            img_ref = path_obj.name  # relative filename (e.g., "PTM_Signaling_Network.png")
        else:
            # Fallback: base64 inline embedding
            base64_img = image_to_base64(img_path) if img_path else None
            img_ref = base64_img
```

### 수정 3: `workers/common/markdown_to_docx.py`

`add_image_to_doc` 함수에서 상대 경로 이미지를 처리할 수 있도록 수정합니다.

**위치**: `workers/common/markdown_to_docx.py` 라인 436 근처

**변경 전**:
```python
        elif os.path.isfile(img_src):
```

**변경 후**:
```python
        elif os.path.isfile(img_src):
            # Local file path (absolute)
```

이 부분은 현재도 절대 경로를 처리하므로, `generate_network_figure_section`에서 상대 경로(파일명만)를 사용하면 `os.path.isfile("PTM_Signaling_Network.png")`이 `False`를 반환할 수 있습니다.

따라서 `convert_markdown_to_docx` 함수에서 이미지 경로를 resolve하는 로직을 추가해야 합니다:

**위치**: `workers/common/markdown_to_docx.py`의 `convert_report_to_docx` 함수 (라인 675)

**변경 전**:
```python
def convert_report_to_docx(md_file_path: str, output_dir: str = None) -> Optional[str]:
    ...
    try:
        # Read markdown content
        with open(md_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        ...
        # Convert
        convert_markdown_to_docx(md_content, docx_path)
```

**변경 후**:
```python
def convert_report_to_docx(md_file_path: str, output_dir: str = None) -> Optional[str]:
    ...
    try:
        # Read markdown content
        with open(md_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        # Resolve relative image paths to absolute (relative to md file directory)
        md_dir = os.path.dirname(os.path.abspath(md_file_path))
        md_content = _resolve_image_paths(md_content, md_dir)
        ...
        # Convert
        convert_markdown_to_docx(md_content, docx_path)
```

그리고 `_resolve_image_paths` 헬퍼 함수를 추가합니다:

```python
def _resolve_image_paths(md_content: str, base_dir: str) -> str:
    """Resolve relative image paths in Markdown to absolute paths.
    
    Converts ![alt](filename.png) to ![alt](/absolute/path/filename.png)
    when the file exists in base_dir.
    """
    import re
    
    def _resolve_match(match):
        alt = match.group(1)
        src = match.group(2)
        # Skip base64 data URIs and already-absolute paths
        if src.startswith('data:') or src.startswith('/') or src.startswith('http'):
            return match.group(0)
        # Try to resolve relative to base_dir
        abs_path = os.path.join(base_dir, src)
        if os.path.isfile(abs_path):
            return f"![{alt}]({abs_path})"
        return match.group(0)
    
    return re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _resolve_match, md_content)
```

---

## Part 4: 수정 적용 순서

1. **`graph.py`**: `ReportState`에 `network_results: dict` 추가 → **즉시 효과**: writer_node의 v98 anti-hallucination 활성화
2. **`network_node.py`**: `_save_network_png` CyREST 직접 다운로드 방식으로 변경 → **즉시 효과**: Docker 환경에서 Cytoscape 이미지 정상 저장
3. **`network_node.py`**: `generate_network_figure_section`에서 상대 경로 사용 → **즉시 효과**: Markdown에서 이미지 정상 표시
4. **`markdown_to_docx.py`**: 상대 경로 resolve 로직 추가 → **즉시 효과**: DOCX에서 이미지 정상 포함
5. (선택) **`docker-compose.yml`**: `HOST_DATA_DIR` 환경 변수 추가 → CyREST 직접 다운로드 실패 시 fallback용

---

## Part 5: 추가 권장 사항

### 5.1 `ptm_type`도 ReportState에 누락

`writer_node.py` 라인 104에서 `state.get("ptm_type", "phosphorylation")`을 사용하지만, `ReportState`에 `ptm_type` 필드가 없습니다. `initial_state`에도 설정되지 않습니다. 현재는 기본값 `"phosphorylation"`이 사용되므로 큰 문제는 아니지만, Cross-Talk 분석 등에서 다른 PTM 타입을 사용할 경우 문제가 될 수 있습니다.

### 5.2 `enriched_json_path`도 ReportState에 누락 가능성

`context_loader.py`에서 `state.get("enriched_json_path")`를 사용하는데, `ReportState`에는 정의되어 있지 않습니다. 다만 `initial_state`에서 직접 설정하므로 LangGraph 첫 노드에서는 접근 가능합니다. (initial_state는 TypedDict 제약을 받지 않음)
