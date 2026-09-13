"""Reader mode interpretation used by writer, assembly and final task gates."""
def is_reader_mode(config):
    if isinstance(config, dict):
        config = config.get("reader_authoring_mode") or (config.get("report_config") or {}).get("reader_authoring_mode")
    return str(config or "").strip().lower() in {"shadow", "opt_in_shadow"}
