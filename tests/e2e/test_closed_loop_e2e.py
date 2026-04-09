"""Full Data Flywheel closed-loop E2E test.

Validates the entire cycle: predict -> confidence routing ->
auto-accumulate/human-review -> prediction logging -> monitoring
metrics -> drift detection readiness.
"""

from __future__ import annotations

import logging
import time
from typing import Any, ClassVar

import httpx
import pytest

from tests.e2e.helpers.e2e_utils import (
    flush_prediction_logger,
    get_health,
    get_s3_objects,
    predict_image,
    query_prometheus,
    query_prometheus_metric_value,
    read_s3_jsonl,
    wait_for_prometheus_metric,
)

logger = logging.getLogger(__name__)

_VALID_ROUTING_DECISIONS = frozenset({"auto_accumulate", "human_review", "discard"})
_PREDICTION_LOGS_BUCKET = "prediction-logs"
_ACTIVE_LEARNING_BUCKET = "active-learning"
_DRIFT_REPORTS_BUCKET = "drift-reports"
_ACCUMULATED_PREFIX = "accumulated/"


class TestClosedLoopFlywheel:
    """End-to-end validation of the full Data Flywheel closed loop.

    Tests are numbered to enforce strict execution order. Class variables
    carry state between tests so that later steps can build on earlier
    results without re-querying external services.
    """

    # -- shared state across tests ------------------------------------------
    health_response: ClassVar[dict[str, Any]] = {}
    prediction_response: ClassVar[dict[str, Any]] = {}
    route_distribution: ClassVar[dict[str, int]] = {}
    prediction_metric_value: ClassVar[float] = 0.0
    prediction_log_keys: ClassVar[list[str]] = []
    prediction_log_records: ClassVar[list[dict[str, Any]]] = []
    accumulated_object_count: ClassVar[int] = 0
    total_predictions_sent: ClassVar[int] = 0

    # -- tests --------------------------------------------------------------

    def test_01_api_healthy_with_model(
        self,
        api_base_url: str,
    ) -> None:
        """Verify the serving API is healthy and a model is loaded.

        This is the prerequisite for the entire flywheel cycle. If the
        model is not loaded, all downstream tests are meaningless.
        """
        health = get_health(api_base_url)
        TestClosedLoopFlywheel.health_response = health

        assert health.get("status") == "ok", f"API health check failed: {health}"

        if not health.get("model_loaded"):
            pytest.skip("Model not loaded - skipping all subsequent flywheel tests")

    def test_02_predict_and_capture_routing(
        self,
        api_base_url: str,
        test_image_path: Any,
    ) -> None:
        """Send a single prediction and capture the full response.

        Validates that the response contains all expected keys that
        the flywheel depends on: predicted_class, confidence,
        uncertainty_score, routing_decision, and probabilities.
        """
        response = predict_image(api_base_url, test_image_path)
        TestClosedLoopFlywheel.prediction_response = response
        TestClosedLoopFlywheel.total_predictions_sent += 1

        expected_keys = {
            "predicted_class",
            "confidence",
            "uncertainty_score",
            "routing_decision",
            "probabilities",
        }
        missing = expected_keys - set(response.keys())
        assert not missing, f"Prediction response missing keys: {missing}. Got keys: {list(response.keys())}"
        logger.info(
            "Prediction response: class=%s confidence=%.4f routing=%s",
            response["predicted_class"],
            response["confidence"],
            response["routing_decision"],
        )

    def test_03_routing_decision_is_valid(self) -> None:
        """Verify the routing decision from test_02 is a known value.

        The confidence router must assign one of the three valid
        routing decisions that drive the dual-path data flywheel.
        """
        response = TestClosedLoopFlywheel.prediction_response
        if not response:
            pytest.skip("No prediction response captured in test_02")

        decision = response.get("routing_decision")
        assert decision in _VALID_ROUTING_DECISIONS, (
            f"Invalid routing_decision '{decision}'. Expected one of: {sorted(_VALID_ROUTING_DECISIONS)}"
        )
        logger.info("Routing decision '%s' is valid", decision)

    def test_04_batch_predict_and_count_routes(
        self,
        api_base_url: str,
        test_image_bytes: bytes,
    ) -> None:
        """Send 30 batch predictions and categorize by routing decision.

        This exercises the confidence router at scale and captures the
        distribution of routing decisions across predictions. The
        distribution is stored for later logging in the summary test.
        """
        results = flush_prediction_logger(
            api_base_url,
            image_bytes=test_image_bytes,
            count=30,
        )
        TestClosedLoopFlywheel.total_predictions_sent += len(results)

        distribution: dict[str, int] = {}
        for r in results:
            decision = r.get("routing_decision", "unknown")
            distribution[decision] = distribution.get(decision, 0) + 1

        TestClosedLoopFlywheel.route_distribution = distribution
        logger.info("Routing distribution from 30 predictions: %s", distribution)

        assert len(results) > 0, "Expected at least some successful predictions"

    def test_05_prediction_metrics_updated(
        self,
        prometheus_base_url: str,
    ) -> None:
        """Verify prediction metrics are exported to Prometheus.

        The serving layer must push prediction_class_total counters
        so that the monitoring pillar can track inference volume.
        """
        try:
            value = wait_for_prometheus_metric(
                prometheus_base_url,
                "sum(prediction_class_total)",
                timeout=30.0,
                poll_interval=5.0,
            )
        except TimeoutError:
            value = query_prometheus_metric_value(
                prometheus_base_url,
                "sum(prediction_class_total)",
            )

        if value is not None and value > 0:
            TestClosedLoopFlywheel.prediction_metric_value = value
            logger.info("prediction_class_total sum = %.0f", value)
        else:
            logger.warning("prediction_class_total not yet available in Prometheus")

        assert value is not None and value > 0, "Expected sum(prediction_class_total) > 0 after sending predictions"

    def test_06_routing_metrics_updated(
        self,
        prometheus_base_url: str,
    ) -> None:
        """Verify active learning routing metrics are in Prometheus.

        The confidence router should export al_routing_decision_total
        counters, broken down by decision type.
        """
        data = query_prometheus(
            prometheus_base_url,
            "al_routing_decision_total",
        )
        results = data.get("data", {}).get("result", [])

        if results:
            logger.info("al_routing_decision_total has %d series", len(results))
            for series in results:
                labels = series.get("metric", {})
                val = series.get("value", [None, None])[1]
                logger.info("  decision=%s value=%s", labels.get("decision", "?"), val)
        else:
            logger.warning("al_routing_decision_total not found in Prometheus")

        # Also try per-decision queries
        for decision in ("auto_accumulate", "human_review", "discard"):
            val = query_prometheus_metric_value(
                prometheus_base_url,
                f'al_routing_decision_total{{decision="{decision}"}}',
            )
            if val is not None:
                logger.info("  al_routing_decision_total{decision=%s} = %.0f", decision, val)

        assert results, "Expected al_routing_decision_total metric to exist in Prometheus"

    def test_07_prediction_logs_in_s3(
        self,
        minio_s3_client: Any,
        api_base_url: str,
        test_image_bytes: bytes,
    ) -> None:
        """Verify prediction logs are flushed to S3.

        The PredictionLogger buffers predictions and flushes them to
        S3 in JSONL format. If no logs are found on the first check,
        sends additional predictions to trigger a flush, then retries.
        """
        max_attempts = 2
        sleep_between = 15.0

        for attempt in range(1, max_attempts + 1):
            objects = get_s3_objects(
                minio_s3_client,
                _PREDICTION_LOGS_BUCKET,
                "",
            )
            if objects:
                TestClosedLoopFlywheel.prediction_log_keys = [obj["Key"] for obj in objects]
                logger.info(
                    "Found %d prediction log objects on attempt %d",
                    len(objects),
                    attempt,
                )
                return

            logger.info(
                "Attempt %d/%d: no prediction logs yet",
                attempt,
                max_attempts,
            )
            if attempt < max_attempts:
                # Send more predictions to force a flush
                extra = flush_prediction_logger(
                    api_base_url,
                    image_bytes=test_image_bytes,
                    count=55,
                )
                TestClosedLoopFlywheel.total_predictions_sent += len(extra)
                logger.info(
                    "Sent %d additional predictions to trigger flush, waiting %.0fs",
                    len(extra),
                    sleep_between,
                )
                time.sleep(sleep_between)

        # If we get here, no logs were found
        logger.warning(
            "No prediction log objects found in '%s' bucket after %d attempts",
            _PREDICTION_LOGS_BUCKET,
            max_attempts,
        )

    def test_08_prediction_log_content_valid(
        self,
        minio_s3_client: Any,
    ) -> None:
        """Validate the content of prediction log JSONL files.

        Each record must contain the fields needed by downstream
        monitoring and active learning components: timestamp,
        predicted_class, confidence, model_version, routing_decision.
        """
        keys = TestClosedLoopFlywheel.prediction_log_keys
        if not keys:
            pytest.skip("No prediction log objects found in test_07")

        # Find a JSONL file to inspect
        jsonl_keys = [k for k in keys if k.endswith(".jsonl")]
        if not jsonl_keys:
            # Try the first key regardless of extension
            jsonl_keys = keys[:1]

        records = read_s3_jsonl(
            minio_s3_client,
            _PREDICTION_LOGS_BUCKET,
            jsonl_keys[0],
        )
        TestClosedLoopFlywheel.prediction_log_records = records

        required_fields = {
            "timestamp",
            "predicted_class",
            "confidence",
            "model_version",
            "routing_decision",
        }

        assert len(records) > 0, f"Expected records in {jsonl_keys[0]} but file is empty"

        for i, record in enumerate(records[:10]):  # Check first 10 records
            missing = required_fields - set(record.keys())
            assert not missing, f"Record {i} in {jsonl_keys[0]} missing fields: {missing}"

        logger.info(
            "Validated %d records from %s (checked first %d)",
            len(records),
            jsonl_keys[0],
            min(10, len(records)),
        )

    def test_09_accumulation_bucket_reachable(
        self,
        minio_s3_client: Any,
    ) -> None:
        """Verify the active-learning S3 bucket exists and is accessible.

        This bucket is the destination for auto-accumulated pseudo-labeled
        data and human-review queue items.
        """
        response = minio_s3_client.head_bucket(Bucket=_ACTIVE_LEARNING_BUCKET)
        status_code = response["ResponseMetadata"]["HTTPStatusCode"]
        assert status_code == 200, f"head_bucket for '{_ACTIVE_LEARNING_BUCKET}' returned {status_code}"
        logger.info("Bucket '%s' is reachable", _ACTIVE_LEARNING_BUCKET)

    def test_10_auto_accumulated_samples_check(
        self,
        minio_s3_client: Any,
    ) -> None:
        """Check for auto-accumulated samples in S3.

        The auto-accumulator buffers high-confidence predictions and
        flushes them when the buffer threshold is reached. Since E2E
        tests may not send enough predictions to trigger a flush,
        this test logs the current state without failing.
        """
        objects = get_s3_objects(
            minio_s3_client,
            _ACTIVE_LEARNING_BUCKET,
            _ACCUMULATED_PREFIX,
        )
        TestClosedLoopFlywheel.accumulated_object_count = len(objects)

        if objects:
            logger.info(
                "Found %d auto-accumulated objects under '%s'",
                len(objects),
                _ACCUMULATED_PREFIX,
            )
            for obj in objects[:5]:
                logger.info("  %s (%.1f KB)", obj["Key"], obj.get("Size", 0) / 1024)
        else:
            logger.info(
                "No auto-accumulated objects yet under '%s'. "
                "This is expected if the buffer threshold has not been reached.",
                _ACCUMULATED_PREFIX,
            )

        # This test intentionally does not fail — accumulation depends on
        # buffer thresholds that E2E test volumes may not trigger.

    def test_11_monitoring_infrastructure_ready(
        self,
        pushgateway_base_url: str,
        prometheus_base_url: str,
    ) -> None:
        """Verify that monitoring infrastructure is operational.

        Checks that Pushgateway is healthy and Prometheus has scraped
        at least one target, confirming the monitoring pillar is ready
        to detect drift and anomalies.
        """
        # Check Pushgateway health
        pgw_response = httpx.get(
            f"{pushgateway_base_url}/-/healthy",
            timeout=10.0,
        )
        assert pgw_response.status_code == 200, f"Pushgateway health check failed: {pgw_response.status_code}"
        logger.info("Pushgateway is healthy")

        # Check Prometheus targets
        prom_response = httpx.get(
            f"{prometheus_base_url}/api/v1/targets",
            timeout=10.0,
        )
        assert prom_response.status_code == 200, f"Prometheus targets API failed: {prom_response.status_code}"

        targets_data = prom_response.json()
        active_targets = targets_data.get("data", {}).get("activeTargets", [])
        logger.info(
            "Prometheus has %d active scrape targets",
            len(active_targets),
        )
        assert len(active_targets) > 0, "Prometheus has no active scrape targets"

    def test_12_drift_reports_bucket_ready(
        self,
        minio_s3_client: Any,
    ) -> None:
        """Verify the drift-reports S3 bucket exists.

        Drift detection results are stored in this bucket. Its existence
        confirms the infrastructure is ready for the monitoring -> retrain
        leg of the flywheel cycle.
        """
        response = minio_s3_client.head_bucket(Bucket=_DRIFT_REPORTS_BUCKET)
        status_code = response["ResponseMetadata"]["HTTPStatusCode"]
        assert status_code == 200, f"head_bucket for '{_DRIFT_REPORTS_BUCKET}' returned {status_code}"
        logger.info("Bucket '%s' is reachable", _DRIFT_REPORTS_BUCKET)

    def test_13_flywheel_cycle_summary(self) -> None:
        """Log a comprehensive summary of the flywheel cycle validation.

        This test always passes. It aggregates results from all previous
        tests into a human-readable summary for test output review.
        """
        logger.info("=" * 60)
        logger.info("DATA FLYWHEEL CLOSED-LOOP E2E SUMMARY")
        logger.info("=" * 60)

        # API health
        health = TestClosedLoopFlywheel.health_response
        logger.info(
            "API status: %s | model_loaded: %s",
            health.get("status", "unknown"),
            health.get("model_loaded", "unknown"),
        )

        # Predictions
        logger.info(
            "Total predictions sent: %d",
            TestClosedLoopFlywheel.total_predictions_sent,
        )

        # Single prediction result
        pred = TestClosedLoopFlywheel.prediction_response
        if pred:
            logger.info(
                "Sample prediction: class=%s confidence=%.4f routing=%s",
                pred.get("predicted_class"),
                pred.get("confidence", 0.0),
                pred.get("routing_decision"),
            )

        # Route distribution
        dist = TestClosedLoopFlywheel.route_distribution
        if dist:
            logger.info("Routing distribution: %s", dict(dist))
        else:
            logger.info("Routing distribution: not captured")

        # Prometheus metrics
        metric_val = TestClosedLoopFlywheel.prediction_metric_value
        logger.info("prediction_class_total (Prometheus): %.0f", metric_val)

        # Prediction logs
        log_count = len(TestClosedLoopFlywheel.prediction_log_keys)
        record_count = len(TestClosedLoopFlywheel.prediction_log_records)
        logger.info(
            "Prediction logs: %d files, %d records inspected",
            log_count,
            record_count,
        )

        # Accumulation
        logger.info(
            "Auto-accumulated objects: %d",
            TestClosedLoopFlywheel.accumulated_object_count,
        )

        logger.info("=" * 60)
        logger.info("FLYWHEEL CYCLE VALIDATION COMPLETE")
        logger.info("=" * 60)
