"""run_preprocessing must not rebind pandas inside the task.

구현 대상: 운영 버그 수정. 측정 경로의 식은 바꾸지 않는다.
사전등록: 해당 없음.
해석 한계: 이 검사는 이름 바인딩만 본다. 전처리 수치를 재계산하지 않는다.
주장 금지: 이 수정으로 kinase 귀속 또는 정량 정확도가 바뀌었다고 서술하지 않는다.

`import pandas as pd` inside run_preprocessing makes pd local to the whole
function. Insulin_Signaling_V3_260929_Codex_Astra_bundle_1 failed with
UnboundLocalError because condition_map was already set, so that import
never ran, and the later pd.read_csv saw an unbound local.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TASKS = Path(__file__).resolve().parents[1] / "preprocessing" / "tasks.py"


def test_run_preprocessing_does_not_rebind_pandas():
    tree = ast.parse(_TASKS.read_text())
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_preprocessing"
    ]
    assert len(functions) == 1
    rebound = []
    for node in ast.walk(functions[0]):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname == "pd":
                    rebound.append(node.lineno)
    assert rebound == []
