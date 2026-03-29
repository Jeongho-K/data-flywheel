"""E2E tests for the serving layer.

Tests API endpoints through both direct API and Nginx reverse proxy.
"""

from __future__ import annotations

import json
import urllib.request


class TestAPIEndpoints:
    """Verify API endpoints respond correctly."""

    def test_health_returns_model_status(self, api_base_url) -> None:
        """Health endpoint should return model_loaded boolean."""
        response = urllib.request.urlopen(f"{api_base_url}/health")
        data = json.loads(response.read())
        assert isinstance(data["model_loaded"], bool)

    def test_metrics_endpoint_exposes_prometheus(self, api_base_url) -> None:
        """Metrics endpoint should return Prometheus format."""
        response = urllib.request.urlopen(f"{api_base_url}/metrics")
        body = response.read().decode()
        # Prometheus metrics always contain HELP and TYPE lines
        assert "# HELP" in body
        assert "# TYPE" in body


class TestNginxProxy:
    """Verify Nginx correctly proxies to the API."""

    def test_nginx_proxies_health(self, nginx_base_url) -> None:
        """Nginx should proxy /health to the API."""
        response = urllib.request.urlopen(f"{nginx_base_url}/health")
        data = json.loads(response.read())
        assert "model_loaded" in data

    def test_nginx_security_headers(self, nginx_base_url) -> None:
        """Nginx should include security headers."""
        response = urllib.request.urlopen(f"{nginx_base_url}/health")
        headers = dict(response.headers)
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"


class TestGrafanaDashboard:
    """Verify Grafana dashboards are provisioned."""

    def test_mlops_dashboard_exists(self, grafana_base_url) -> None:
        """The MLOps overview dashboard should be provisioned."""
        req = urllib.request.Request(f"{grafana_base_url}/api/search?query=MLOps")
        req.add_header("Authorization", "Basic YWRtaW46YWRtaW4=")  # admin:admin
        response = urllib.request.urlopen(req)
        data = json.loads(response.read())
        # At least one dashboard should exist
        assert len(data) > 0, "No dashboards found matching 'MLOps'"
