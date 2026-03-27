"""Integration tests for the Phase 5 serving /metrics endpoint."""

from __future__ import annotations

import httpx


class TestMetricsEndpoint:
    """Verify that the FastAPI /metrics endpoint is functional."""

    def test_metrics_returns_200(self, api_base_url: str) -> None:
        """GET /metrics must return HTTP 200.

        Args:
            api_base_url: Base URL fixture for the serving API.
        """
        response = httpx.get(f"{api_base_url}/metrics", timeout=5)
        assert response.status_code == 200

    def test_metrics_contains_http_request(self, api_base_url: str) -> None:
        """GET /metrics response body must contain the http_request metric family.

        Args:
            api_base_url: Base URL fixture for the serving API.
        """
        response = httpx.get(f"{api_base_url}/metrics", timeout=5)
        assert "http_request" in response.text

    def test_metrics_content_type(self, api_base_url: str) -> None:
        """GET /metrics Content-Type must be text/plain or openmetrics.

        Args:
            api_base_url: Base URL fixture for the serving API.
        """
        response = httpx.get(f"{api_base_url}/metrics", timeout=5)
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "openmetrics" in content_type

    def test_metrics_contains_custom_counters(self, api_base_url: str) -> None:
        """GET /metrics response body must contain custom prediction counters.

        Checks for either prediction_class_total or prediction_confidence,
        both of which are registered by the monitoring layer.

        Args:
            api_base_url: Base URL fixture for the serving API.
        """
        response = httpx.get(f"{api_base_url}/metrics", timeout=5)
        body = response.text
        assert "prediction_class_total" in body or "prediction_confidence" in body
