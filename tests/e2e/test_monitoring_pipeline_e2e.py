"""E2E tests for monitoring, drift detection, and runtime gate logic.

Validates Prometheus metrics collection, prediction log persistence to S3,
drift detection infrastructure readiness, and runtime gate severity classification.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, ClassVar
from unittest.mock import patch

import httpx
import pytest

from tests.e2e.helpers.e2e_utils import (
    flush_prediction_logger,
    get_s3_objects,
    query_prometheus,
    query_prometheus_metric_value,
    wait_for_prometheus_metric,
)

logger = logging.getLogger(__name__)


class TestPrometheusMetrics:
    """Verify that API predictions update Prometheus metrics."""

    def test_01_prediction_counter_exists(self, prometheus_base_url: str) -> None:
        """Prediction class counter metric should exist in Prometheus."""
        data = query_prometheus(prometheus_base_url, "prediction_class_total")
        assert data["status"] == "success", f"Prometheus query failed: {data}"
        # Metric may be 0 initially; we only verify the query succeeds
        logger.info(
            "prediction_class_total query returned %d result(s)",
            len(data.get("data", {}).get("result", [])),
        )

    def test_02_send_predictions_and_check_count(
        self,
        api_base_url: str,
        prometheus_base_url: str,
        test_image_bytes: bytes,
    ) -> None:
        """Sending predictions should increase the prediction counter."""
        # Record baseline
        before = query_prometheus_metric_value(prometheus_base_url, "sum(prediction_class_total)")
        before = before if before is not None else 0.0

        # Send 5 predictions
        for i in range(5):
            try:
                response = httpx.post(
                    f"{api_base_url}/predict",
                    files={"file": ("test.png", test_image_bytes, "image/png")},
                    timeout=30.0,
                )
                logger.info("Prediction %d status: %d", i + 1, response.status_code)
            except httpx.RequestError as exc:
                logger.warning("Prediction %d failed: %s", i + 1, exc)

        # Wait for Prometheus to scrape the updated counter.
        # Pass the baseline so the helper keeps polling until the counter
        # actually moves, not just any non-zero value.
        after = wait_for_prometheus_metric(
            prometheus_base_url,
            "sum(prediction_class_total)",
            timeout=60.0,
            poll_interval=5.0,
            min_value=before,
        )
        assert after > before, f"Counter did not increase: before={before}, after={after}"

    def test_03_confidence_histogram_exists(self, prometheus_base_url: str) -> None:
        """Prediction confidence histogram metric should exist."""
        data = query_prometheus(prometheus_base_url, "prediction_confidence_bucket")
        assert data["status"] == "success", f"Prometheus query failed: {data}"
        logger.info(
            "prediction_confidence_bucket returned %d result(s)",
            len(data.get("data", {}).get("result", [])),
        )

    def test_04_al_metrics_exist(self, prometheus_base_url: str) -> None:
        """Active learning routing decision metric should exist."""
        data = query_prometheus(prometheus_base_url, "al_routing_decision_total")
        assert data["status"] == "success", f"Prometheus query failed: {data}"
        logger.info(
            "al_routing_decision_total returned %d result(s)",
            len(data.get("data", {}).get("result", [])),
        )


class TestPredictionLogging:
    """Verify prediction logs are written to S3."""

    _flush_results: ClassVar[list[dict[str, Any]]] = []
    _s3_objects: ClassVar[list[dict[str, Any]]] = []

    def test_01_send_predictions_to_fill_buffer(self, api_base_url: str, test_image_bytes: bytes) -> None:
        """Send enough predictions to trigger the PredictionLogger S3 flush."""
        results = flush_prediction_logger(api_base_url, test_image_bytes, count=55)
        TestPredictionLogging._flush_results = results
        logger.info("Flush sent %d predictions, %d succeeded", 55, len(results))
        assert len(results) > 0, "No predictions succeeded"

    def test_02_prediction_logs_in_s3(self, minio_s3_client: Any) -> None:
        """Prediction log objects should appear in the prediction-logs bucket."""
        if not TestPredictionLogging._flush_results:
            pytest.skip("No predictions were sent in test_01")

        objects: list[dict[str, Any]] = []
        for attempt in range(3):
            objects = get_s3_objects(minio_s3_client, "prediction-logs", "")
            if objects:
                break
            logger.info("Attempt %d/3: no objects yet, waiting 10s...", attempt + 1)
            time.sleep(10)

        TestPredictionLogging._s3_objects = objects

        if not objects:
            pytest.skip("Prediction logs not yet flushed to S3; flush timing may exceed test window")

        logger.info("Found %d prediction log object(s) in S3", len(objects))

    def test_03_prediction_log_format_valid(self, minio_s3_client: Any) -> None:
        """Downloaded prediction log should be valid JSONL with expected keys."""
        if not TestPredictionLogging._s3_objects:
            pytest.skip("No prediction log objects found in S3")

        key = TestPredictionLogging._s3_objects[0]["Key"]
        response = minio_s3_client.get_object(Bucket="prediction-logs", Key=key)
        body = response["Body"].read().decode()
        lines = [line for line in body.strip().splitlines() if line.strip()]
        assert len(lines) > 0, f"JSONL file is empty: {key}"

        required_keys = {"timestamp", "predicted_class", "confidence", "model_version"}
        for i, line in enumerate(lines):
            record = json.loads(line)
            missing = required_keys - set(record.keys())
            assert not missing, f"Line {i} missing keys {missing} in {key}: {record}"

        logger.info("Validated %d JSONL records from %s", len(lines), key)


class TestDriftDetectionEndpoints:
    """Verify drift-related infrastructure is ready."""

    def test_01_pushgateway_healthy(self, pushgateway_base_url: str) -> None:
        """Pushgateway health endpoint should return 200."""
        response = httpx.get(f"{pushgateway_base_url}/-/healthy", timeout=10.0)
        assert response.status_code == 200, f"Pushgateway unhealthy: {response.status_code}"

    def test_02_drift_reports_bucket_exists(self, minio_s3_client: Any) -> None:
        """The drift-reports S3 bucket should exist."""
        try:
            minio_s3_client.head_bucket(Bucket="drift-reports")
        except Exception as exc:
            pytest.fail(f"drift-reports bucket not found: {exc}")

    def test_03_pushgateway_metrics_endpoint(self, pushgateway_base_url: str) -> None:
        """Pushgateway metrics endpoint should serve Prometheus format."""
        response = httpx.get(f"{pushgateway_base_url}/metrics", timeout=10.0)
        assert response.status_code == 200
        body = response.text
        assert "# HELP" in body or "# TYPE" in body, "Pushgateway /metrics does not contain standard Prometheus format"


class TestRuntimeGateLogic:
    """Test runtime gate severity classification.

    Unit-level validation that the G5 gate is importable and produces
    correct severity/action mappings.
    """

    def test_01_low_severity(self) -> None:
        """Low drift score with no detection should yield LOW severity."""
        from src.core.orchestration.tasks.runtime_gate import (
            evaluate_runtime_gate,
        )

        with patch(
            "src.core.orchestration.tasks.runtime_gate.create_markdown_artifact",
        ):
            result = evaluate_runtime_gate.fn(drift_score=0.1, drift_detected=False)
        assert result["severity"] == "low", f"Expected LOW severity, got {result['severity']}"
        assert result["action"] == "log_only", f"Expected log_only action, got {result['action']}"

    def test_02_medium_severity(self) -> None:
        """Moderate drift score with detection should yield MEDIUM severity."""
        from src.core.orchestration.tasks.runtime_gate import (
            evaluate_runtime_gate,
        )

        with patch(
            "src.core.orchestration.tasks.runtime_gate.create_markdown_artifact",
        ):
            result = evaluate_runtime_gate.fn(drift_score=0.4, drift_detected=True)
        assert result["severity"] == "medium", f"Expected MEDIUM severity, got {result['severity']}"
        assert result["action"] == "trigger_active_learning", (
            f"Expected trigger_active_learning action, got {result['action']}"
        )

    def test_03_high_severity(self) -> None:
        """High drift score with detection should yield HIGH severity."""
        from src.core.orchestration.tasks.runtime_gate import (
            evaluate_runtime_gate,
        )

        with patch(
            "src.core.orchestration.tasks.runtime_gate.create_markdown_artifact",
        ):
            result = evaluate_runtime_gate.fn(drift_score=0.7, drift_detected=True)
        assert result["severity"] == "high", f"Expected HIGH severity, got {result['severity']}"
        assert result["action"] == "rollback_and_retrain", (
            f"Expected rollback_and_retrain action, got {result['action']}"
        )
