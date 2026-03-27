"""Shared fixtures for integration tests."""

from __future__ import annotations

import os

import boto3
import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-mark every collected test in this package as integration.

    Args:
        items: List of collected pytest items.
    """
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


# ---------------------------------------------------------------------------
# URL fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Return the base URL for the serving API.

    Returns:
        Base URL string derived from the API_PORT environment variable.
    """
    port = os.environ.get("API_PORT", "8000")
    return f"http://localhost:{port}"


@pytest.fixture(scope="session")
def prometheus_base_url() -> str:
    """Return the base URL for the Prometheus instance.

    Returns:
        Base URL string derived from the PROMETHEUS_PORT environment variable.
    """
    port = os.environ.get("PROMETHEUS_PORT", "9090")
    return f"http://localhost:{port}"


@pytest.fixture(scope="session")
def grafana_base_url() -> str:
    """Return the base URL for the Grafana instance.

    Returns:
        Base URL string derived from the GRAFANA_PORT environment variable.
    """
    port = os.environ.get("GRAFANA_PORT", "3000")
    return f"http://localhost:{port}"


@pytest.fixture(scope="session")
def pushgateway_base_url() -> str:
    """Return the base URL for the Prometheus Pushgateway.

    Returns:
        Base URL string derived from the PUSHGATEWAY_PORT environment variable.
    """
    port = os.environ.get("PUSHGATEWAY_PORT", "9091")
    return f"http://localhost:{port}"


# ---------------------------------------------------------------------------
# Storage fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def minio_s3_client() -> boto3.client:  # type: ignore[type-arg]
    """Return a boto3 S3 client configured for the local MinIO instance.

    Reads credentials and endpoint from environment variables, falling back
    to the defaults defined in .env.example.

    Returns:
        Configured boto3 S3 client pointing at MinIO.
    """
    endpoint_url = os.environ.get(
        "MLFLOW_S3_ENDPOINT_URL",
        f"http://localhost:{os.environ.get('MINIO_API_PORT', '9000')}",
    )
    access_key = os.environ.get("MINIO_ROOT_USER", "minioadmin")
    secret_key = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin123")

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
