import json
from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_versioned_dashboard_includes_a_meridian_loki_panel() -> None:
    dashboard = json.loads(
        (ROOT / "observability/grafana/dashboards/meridian-overview.json").read_text()
    )

    log_panels = [
        panel
        for panel in dashboard["panels"]
        if panel.get("datasource", {}).get("type") == "loki"
    ]

    assert len(log_panels) == 1
    assert log_panels[0]["title"] == "Meridian application logs"
    assert 'service_name="meridian-api"' in log_panels[0]["targets"][0]["expr"]

    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {
        "Database pool capacity and saturation",
        "Meridian active-series proxy",
    } <= titles


def test_versioned_dashboard_has_importable_three_signal_datasources() -> None:
    dashboard = json.loads(
        (ROOT / "observability/grafana/dashboards/meridian-overview.json").read_text()
    )

    inputs = {entry["name"]: entry for entry in dashboard["__inputs"]}
    assert set(inputs) == {"DS_PROMETHEUS", "DS_LOKI", "DS_TEMPO"}
    assert inputs["DS_PROMETHEUS"]["pluginId"] == "prometheus"
    assert inputs["DS_LOKI"]["pluginId"] == "loki"
    assert inputs["DS_TEMPO"]["pluginId"] == "tempo"

    trace_panels = [
        panel
        for panel in dashboard["panels"]
        if panel.get("datasource", {}).get("type") == "tempo"
    ]
    assert len(trace_panels) == 1
    assert trace_panels[0]["title"] == "Recent Meridian traces"
    assert (
        'resource.service.name = "meridian-api"'
        in trace_panels[0]["targets"][0]["query"]
    )


def test_versioned_alert_rules_cover_all_immediate_operational_failures() -> None:
    rules = (ROOT / "observability/grafana/provisioning/alert-rules.yaml").read_text()

    for alert in (
        "dependency unavailable",
        "queue backlog",
        "parser failures",
        "generation activation failures",
        "lexical retrieval degradation",
        "hybrid retrieval degradation",
        "retrieval empty shift",
        "API p95 latency regression",
        "Alloy export failures",
    ):
        assert alert in rules

    assert "dashboard_uid: meridian-overview" in rules
    assert "runbook_url:" in rules
    assert "owner: platform" in rules


def test_alloy_config_keeps_the_logs_pipeline_private_and_bounded() -> None:
    alloy_config = (ROOT / "observability/alloy/config.alloy").read_text()

    assert "logs    = [otelcol.processor.memory_limiter.meridian.input]" in alloy_config
    assert "logs    = [otelcol.processor.attributes.safety.input]" in alloy_config
    assert "logs    = [otelcol.processor.filter.safety.input]" in alloy_config
    assert "logs    = [otelcol.processor.batch.meridian.input]" in alloy_config
    assert "logs    = [otelcol.exporter.otlphttp.grafana_cloud.input]" in alloy_config
    assert 'endpoint = "127.0.0.1:4318"' in alloy_config
    assert "queue_size        = 1000" in alloy_config
    assert 'otelcol.processor.filter "safety"' in alloy_config
    assert "Len(body) > 512" in alloy_config
    for forbidden_key in (
        "generation_id",
        "request_id",
        "source_text",
        "provider_response",
        "raw_payload",
    ):
        assert f'key    = "{forbidden_key}"' in alloy_config
