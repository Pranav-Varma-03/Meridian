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


def test_alloy_config_keeps_the_logs_pipeline_private_and_bounded() -> None:
    alloy_config = (ROOT / "observability/alloy/config.alloy").read_text()

    assert "logs    = [otelcol.processor.memory_limiter.meridian.input]" in alloy_config
    assert "logs    = [otelcol.processor.attributes.safety.input]" in alloy_config
    assert "logs    = [otelcol.processor.batch.meridian.input]" in alloy_config
    assert "logs    = [otelcol.exporter.otlphttp.grafana_cloud.input]" in alloy_config
    assert 'endpoint = "127.0.0.1:4318"' in alloy_config
    assert "queue_size        = 1000" in alloy_config
