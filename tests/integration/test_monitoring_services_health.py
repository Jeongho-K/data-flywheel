"""Integration tests for Phase 6 monitoring service health endpoints."""

from __future__ import annotations

import httpx


class TestPrometheusHealth:
    """Verify that the Prometheus instance is reachable and healthy."""

    def test_prometheus_healthy(self, prometheus_base_url: str) -> None:
        """GET /-/healthy must return HTTP 200.

        Args:
            prometheus_base_url: Base URL fixture for Prometheus.
        """
        response = httpx.get(f"{prometheus_base_url}/-/healthy", timeout=5)
        assert response.status_code == 200

    def test_prometheus_ready(self, prometheus_base_url: str) -> None:
        """GET /-/ready must return HTTP 200.

        Args:
            prometheus_base_url: Base URL fixture for Prometheus.
        """
        response = httpx.get(f"{prometheus_base_url}/-/ready", timeout=5)
        assert response.status_code == 200


class TestGrafanaHealth:
    """Verify that the Grafana instance is reachable and reports a healthy database."""

    def test_grafana_health(self, grafana_base_url: str) -> None:
        """GET /api/health must return HTTP 200 with database=ok.

        Args:
            grafana_base_url: Base URL fixture for Grafana.
        """
        response = httpx.get(f"{grafana_base_url}/api/health", timeout=5)
        assert response.status_code == 200
        body = response.json()
        assert body.get("database") == "ok"


class TestPushgatewayHealth:
    """Verify that the Prometheus Pushgateway is reachable and healthy."""

    def test_pushgateway_healthy(self, pushgateway_base_url: str) -> None:
        """GET /-/healthy must return HTTP 200.

        Args:
            pushgateway_base_url: Base URL fixture for the Pushgateway.
        """
        response = httpx.get(f"{pushgateway_base_url}/-/healthy", timeout=5)
        assert response.status_code == 200
