"""Shared utilities for non-browser E2E tests.

Re-exports browser helpers that are useful in plain pytest tests,
and adds utilities specific to pipeline/integration E2E scenarios.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from pathlib import Path

    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Re-exports from browser helpers (usable without Playwright)
# ---------------------------------------------------------------------------
from tests.e2e.browser.helpers.api_client import (  # noqa: E402
    get_health,
    get_model_info,
    predict_image,
    query_prometheus,
    trigger_retraining,
)
from tests.e2e.browser.helpers.wait import (  # noqa: E402
    wait_for_condition,
    wait_for_minio_object,
    wait_for_prefect_flow_run,
)

__all__ = [
    "get_health",
    "get_model_info",
    "predict_image",
    "query_prometheus",
    "trigger_retraining",
    "wait_for_condition",
    "wait_for_minio_object",
    "wait_for_prefect_flow_run",
    "get_s3_objects",
    "create_reference_data",
    "generate_test_image",
    "flush_prediction_logger",
    "query_prometheus_metric_value",
    "wait_for_prometheus_metric",
    "read_s3_jsonl",
    "admin_trigger_retraining",
]


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def get_s3_objects(
    s3_client: S3Client,
    bucket: str,
    prefix: str,
    max_keys: int = 1000,
) -> list[dict[str, Any]]:
    """List S3 objects under a given prefix.

    Args:
        s3_client: boto3 S3 client.
        bucket: Bucket name.
        prefix: Object key prefix.
        max_keys: Maximum number of keys to return.

    Returns:
        List of S3 object metadata dicts (Key, Size, LastModified, etc.).
    """
    response = s3_client.list_objects_v2(
        Bucket=bucket,
        Prefix=prefix,
        MaxKeys=max_keys,
    )
    return response.get("Contents", [])


def create_reference_data(
    s3_client: S3Client,
    bucket: str,
    key: str,
    records: list[dict[str, Any]],
) -> None:
    """Upload JSONL reference data to S3 for drift detection.

    Args:
        s3_client: boto3 S3 client.
        bucket: Target bucket.
        key: S3 object key.
        records: List of dicts, each written as a JSON line.
    """
    body = "\n".join(json.dumps(r) for r in records)
    s3_client.put_object(Bucket=bucket, Key=key, Body=body.encode())


def read_s3_jsonl(
    s3_client: S3Client,
    bucket: str,
    key: str,
) -> list[dict[str, Any]]:
    """Read a JSONL file from S3 and return parsed records.

    Args:
        s3_client: boto3 S3 client.
        bucket: Bucket name.
        key: Object key.

    Returns:
        List of parsed JSON dicts.
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read().decode()
    return [json.loads(line) for line in body.strip().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Test image generation
# ---------------------------------------------------------------------------


def generate_test_image(
    width: int = 224,
    height: int = 224,
    color: tuple[int, int, int] = (128, 64, 32),
    fmt: str = "PNG",
) -> bytes:
    """Generate a minimal test image in memory.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        color: RGB fill color.
        fmt: Image format (PNG, JPEG, etc.).

    Returns:
        Raw image bytes.
    """
    import io

    from PIL import Image

    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def save_test_image(path: Path, **kwargs: Any) -> Path:
    """Generate and save a test image to disk.

    Args:
        path: Destination file path.
        **kwargs: Passed to generate_test_image().

    Returns:
        The path written to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(generate_test_image(**kwargs))
    return path


# ---------------------------------------------------------------------------
# Prediction & API helpers
# ---------------------------------------------------------------------------


def flush_prediction_logger(
    api_base_url: str,
    image_bytes: bytes | None = None,
    count: int = 55,
) -> list[dict[str, Any]]:
    """Send rapid predictions to force the PredictionLogger to flush to S3.

    The default flush threshold is 50, so sending 55 predictions should
    trigger at least one flush.

    Args:
        api_base_url: API base URL.
        image_bytes: Image bytes to use; auto-generated if None.
        count: Number of predictions to send.

    Returns:
        List of prediction responses.
    """
    if image_bytes is None:
        image_bytes = generate_test_image()

    results: list[dict[str, Any]] = []
    for _ in range(count):
        try:
            response = httpx.post(
                f"{api_base_url}/predict",
                files={"file": ("test.png", image_bytes, "image/png")},
                timeout=30.0,
            )
            if response.status_code == 200:
                results.append(response.json())
        except httpx.RequestError:
            pass
    return results


def admin_trigger_retraining(
    api_base_url: str,
    admin_api_key: str,
    trigger_source: str = "e2e-test",
) -> dict[str, Any]:
    """Trigger retraining via admin endpoint with API key.

    Args:
        api_base_url: API base URL.
        admin_api_key: Admin API key for authentication.
        trigger_source: Source identifier for the trigger.

    Returns:
        Parsed JSON response.
    """
    response = httpx.post(
        f"{api_base_url}/admin/trigger-retraining",
        headers={"X-Admin-Key": admin_api_key},
        params={"trigger_source": trigger_source},
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Prometheus helpers
# ---------------------------------------------------------------------------


def query_prometheus_metric_value(
    prometheus_base_url: str,
    query: str,
) -> float | None:
    """Execute a PromQL query and return the scalar value.

    Args:
        prometheus_base_url: Prometheus base URL.
        query: PromQL expression.

    Returns:
        Float value if result exists, None otherwise.
    """
    data = query_prometheus(prometheus_base_url, query)
    results = data.get("data", {}).get("result", [])
    if results:
        # Instant query returns [timestamp, value]
        return float(results[0]["value"][1])
    return None


def wait_for_prometheus_metric(
    prometheus_base_url: str,
    query: str,
    timeout: float = 60.0,
    poll_interval: float = 5.0,
) -> float:
    """Poll Prometheus until a metric returns a non-zero value.

    Args:
        prometheus_base_url: Prometheus base URL.
        query: PromQL expression.
        timeout: Maximum wait time in seconds.
        poll_interval: Seconds between polls.

    Returns:
        The metric value.

    Raises:
        TimeoutError: If metric not found within timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = query_prometheus_metric_value(prometheus_base_url, query)
        if value is not None and value > 0:
            return value
        time.sleep(poll_interval)
    msg = f"Metric '{query}' not found or zero within {timeout}s"
    raise TimeoutError(msg)
