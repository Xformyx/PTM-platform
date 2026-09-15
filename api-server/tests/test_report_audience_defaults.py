import ast
from pathlib import Path


def _normalize_report_options_for_test():
    """Load the route helper without importing database-bound API modules."""
    source = Path(__file__).parents[1] / "app/api/orders.py"
    tree = ast.parse(source.read_text())
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_normalize_report_options"
    )
    namespace = {"HTTPException": RuntimeError}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["_normalize_report_options"]


def test_empty_user_report_options_default_to_researcher_shadow_manuscript():
    normalized = _normalize_report_options_for_test()({"output_format": "md"})
    config = normalized["report_config"]
    assert config["report_audience"] == "researcher_manuscript"
    assert config["reader_authoring_mode"] == "shadow"
    assert config["technical_audit_delivery"] == "separate_sidecar"


def test_explicit_technical_audit_request_remains_technical():
    normalized = _normalize_report_options_for_test()({
        "report_config": {
            "report_audience": "technical_audit",
            "reader_authoring_mode": "legacy",
            "technical_audit_delivery": "embedded_technical_report",
        },
    })
    config = normalized["report_config"]
    assert config["report_audience"] == "technical_audit"
    assert config["reader_authoring_mode"] == "legacy"
    assert config["technical_audit_delivery"] == "embedded_technical_report"
