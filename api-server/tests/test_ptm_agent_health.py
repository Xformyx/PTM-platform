from types import SimpleNamespace

from app.api.health import classify_ptm_agent_payload, _resolve_ptm_agent_health_url


def test_explicit_health_url_wins():
    settings = SimpleNamespace(
        PTM_AGENT_HEALTH_URL="http://host.docker.internal:9100/health/",
        WEBHOOK_URL="http://other:1/webhook/ptm",
    )
    assert _resolve_ptm_agent_health_url(settings) == "http://host.docker.internal:9100/health"


def test_webhook_host_is_used_when_health_url_empty():
    settings = SimpleNamespace(
        PTM_AGENT_HEALTH_URL="",
        WEBHOOK_URL="http://host.docker.internal:9100/webhook/ptm",
    )
    assert _resolve_ptm_agent_health_url(settings) == "http://host.docker.internal:9100/health"


def test_default_health_url():
    settings = SimpleNamespace(PTM_AGENT_HEALTH_URL="", WEBHOOK_URL="")
    assert _resolve_ptm_agent_health_url(settings) == "http://host.docker.internal:9100/health"


def test_ok_payload_with_polling():
    status, parts = classify_ptm_agent_payload({
        "status": "ok",
        "pid": 42,
        "uptime_seconds": 12,
        "telegram_polling": True,
    })
    assert status == "ok"
    assert "polling" in parts
    assert "pid 42" in parts


def test_polling_off_is_error():
    status, parts = classify_ptm_agent_payload({
        "status": "ok",
        "telegram_polling": False,
    })
    assert status == "error"
    assert "telegram polling off" in parts


def test_invalid_body_is_error():
    status, parts = classify_ptm_agent_payload("not-json")
    assert status == "error"
    assert parts == ["invalid health body"]
