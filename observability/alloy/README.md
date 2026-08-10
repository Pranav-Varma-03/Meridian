# Run Grafana Alloy directly on the host

This is a host-native deployment. Install the Grafana Alloy binary through your
operating-system package manager or from Grafana's signed release, then run it
as the same private host service tier as Meridian.

1. Copy `config.alloy` to `/opt/meridian/observability/alloy/config.alloy`.
2. Create `/etc/meridian/grafana-alloy.env` with mode `0600` and with values
   supplied by your secret manager:

   ```env
   GRAFANA_CLOUD_OTLP_ENDPOINT=https://otlp-gateway-<region>.grafana.net/otlp
   GRAFANA_CLOUD_OTLP_AUTHORIZATION=<complete Authorization header value>
   ```

3. Run it directly for a smoke test:

   ```bash
   set -a
   . /etc/meridian/grafana-alloy.env
   set +a
   alloy run /opt/meridian/observability/alloy/config.alloy --server.http.listen-addr=127.0.0.1:12345
   ```

4. On a Linux server, install `meridian-alloy.service` at
   `/etc/systemd/system/meridian-alloy.service`, then run
   `systemctl daemon-reload`, `systemctl enable --now meridian-alloy`, and
   `systemctl status meridian-alloy`.

Alloy receives OTLP only on `127.0.0.1:4317` and `127.0.0.1:4318`; Meridian
must use these local endpoints. Grafana Cloud credentials exist only in the
Alloy host-service environment. The health UI is bound to `127.0.0.1:12345`.
