"""Load the report graph only when requested; pure retrieval needs no graph runtime."""

def __getattr__(name):
    if name in {"build_report_graph", "ReportState"}:
        from . import graph
        return getattr(graph, name)
    raise AttributeError(name)
