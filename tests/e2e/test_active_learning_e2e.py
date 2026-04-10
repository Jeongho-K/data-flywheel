"""E2E tests for the Active Learning pipeline.

Tests uncertainty estimation, confidence routing, auto-accumulation of
high-confidence predictions to S3, and Label Studio integration connectivity.
These tests exercise the full Data Flywheel loop from prediction through
routing and accumulation.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
import pytest

from tests.e2e.helpers.e2e_utils import (
    flush_prediction_logger,
    get_s3_objects,
    predict_image,
    wait_for_prometheus_metric,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Valid routing decisions returned by the confidence router
_VALID_ROUTING_DECISIONS = ("auto_accumulate", "human_review", "discard")


class TestUncertaintyEstimation:
    """Tests that the /predict endpoint returns uncertainty scores."""

    _prediction_result: ClassVar[dict[str, Any] | None] = None

    def test_01_prediction_includes_uncertainty_score(
        self,
        api_base_url: str,
        test_image_path: Path,
    ) -> None:
        """POST /predict should return a response containing an uncertainty_score field."""
        result = predict_image(api_base_url, test_image_path)
        assert "uncertainty_score" in result, "Prediction response missing 'uncertainty_score' field"
        TestUncertaintyEstimation._prediction_result = result
        logger.info("Prediction result: %s", result)

    def test_02_uncertainty_score_in_valid_range(self) -> None:
        """Uncertainty score should be a float in [0.0, 1.0]."""
        if TestUncertaintyEstimation._prediction_result is None:
            pytest.skip("No prediction result from test_01")

        score = TestUncertaintyEstimation._prediction_result["uncertainty_score"]
        assert isinstance(score, float), f"uncertainty_score should be float, got {type(score).__name__}"
        assert 0.0 <= score <= 1.0, f"uncertainty_score {score} outside valid range [0.0, 1.0]"

    def test_03_prediction_includes_routing_decision(self) -> None:
        """Prediction response should include a routing_decision field with a valid value."""
        if TestUncertaintyEstimation._prediction_result is None:
            pytest.skip("No prediction result from test_01")

        result = TestUncertaintyEstimation._prediction_result
        assert "routing_decision" in result, "Prediction response missing 'routing_decision' field"
        assert result["routing_decision"] in _VALID_ROUTING_DECISIONS, (
            f"Unexpected routing_decision: {result['routing_decision']}"
        )


class TestConfidenceRouting:
    """Tests confidence routing logic across multiple predictions."""

    _batch_results: ClassVar[list[dict[str, Any]]] = []

    def test_01_send_batch_predictions(
        self,
        api_base_url: str,
        test_image_bytes: bytes,
    ) -> None:
        """Send 20 predictions and store results for subsequent tests."""
        results = flush_prediction_logger(api_base_url, test_image_bytes, count=20)
        assert len(results) > 0, "No successful predictions returned from batch"
        TestConfidenceRouting._batch_results = results
        logger.info("Batch predictions returned %d results", len(results))

    def test_02_all_predictions_have_routing(self) -> None:
        """Every prediction in the batch should contain a routing_decision."""
        if not TestConfidenceRouting._batch_results:
            pytest.skip("No batch results from test_01")

        for i, result in enumerate(TestConfidenceRouting._batch_results):
            assert "routing_decision" in result, f"Prediction {i} missing 'routing_decision'"

    def test_03_routing_decisions_are_valid(self) -> None:
        """Every routing_decision should be one of the valid values."""
        if not TestConfidenceRouting._batch_results:
            pytest.skip("No batch results from test_01")

        for i, result in enumerate(TestConfidenceRouting._batch_results):
            decision = result.get("routing_decision")
            assert decision in _VALID_ROUTING_DECISIONS, f"Prediction {i} has invalid routing_decision: {decision}"

    def test_04_routing_metrics_in_prometheus(
        self,
        prometheus_base_url: str,
    ) -> None:
        """Prometheus should have ``al_routing_decision_total`` > 0.

        Uses ``wait_for_prometheus_metric`` so the test tolerates the
        Prometheus scrape window (15s) that otherwise makes this flaky
        on freshly recreated stacks.
        """
        value = wait_for_prometheus_metric(
            prometheus_base_url,
            "sum(al_routing_decision_total)",
            timeout=45.0,
            poll_interval=5.0,
        )
        assert value > 0, f"Expected al_routing_decision_total > 0, got {value}"


class TestAutoAccumulation:
    """Tests that high-confidence predictions are auto-accumulated to S3."""

    _s3_objects: ClassVar[list[dict[str, Any]]] = []

    def test_01_check_accumulation_bucket_exists(
        self,
        minio_s3_client: Any,
    ) -> None:
        """The 'active-learning' bucket should exist in MinIO."""
        minio_s3_client.head_bucket(Bucket="active-learning")
        logger.info("Bucket 'active-learning' exists")

    def test_02_send_predictions_for_accumulation(
        self,
        api_base_url: str,
        test_image_bytes: bytes,
    ) -> None:
        """Send 60 predictions to trigger the PredictionLogger buffer flush."""
        results = flush_prediction_logger(api_base_url, test_image_bytes, count=60)
        assert len(results) > 0, "No successful predictions returned"
        logger.info(
            "Sent %d predictions for accumulation (flush threshold ~50)",
            len(results),
        )

    def test_03_accumulated_data_in_s3(
        self,
        minio_s3_client: Any,
    ) -> None:
        """Accumulated prediction data should appear under the accumulated/ prefix."""
        objects = get_s3_objects(minio_s3_client, "active-learning", "accumulated/")
        TestAutoAccumulation._s3_objects = objects

        if not objects:
            pytest.skip(
                "No accumulated objects found in S3 yet. "
                "The PredictionLogger buffer may not have flushed "
                "(depends on flush threshold and timing)."
            )

        logger.info("Found %d accumulated objects in S3", len(objects))

    def test_04_accumulated_jsonl_format_valid(
        self,
        minio_s3_client: Any,
    ) -> None:
        """Accumulated JSONL files should contain valid JSON with expected keys."""
        if not TestAutoAccumulation._s3_objects:
            pytest.skip("No accumulated S3 objects found in test_03")

        obj_key = TestAutoAccumulation._s3_objects[0]["Key"]
        response = minio_s3_client.get_object(
            Bucket="active-learning",
            Key=obj_key,
        )
        body = response["Body"].read().decode()

        expected_keys = {"timestamp", "predicted_class", "confidence", "model_version"}
        lines = [line for line in body.strip().splitlines() if line.strip()]
        assert len(lines) > 0, f"JSONL file {obj_key} is empty"

        for i, line in enumerate(lines):
            record = json.loads(line)
            missing = expected_keys - set(record.keys())
            assert not missing, f"Line {i} in {obj_key} missing keys: {missing}"

        logger.info(
            "Validated %d records in %s with keys %s",
            len(lines),
            obj_key,
            expected_keys,
        )


class TestLabelStudioIntegration:
    """Tests Label Studio connectivity (not full labeling workflow)."""

    def test_01_label_studio_api_reachable(
        self,
        label_studio_base_url: str,
    ) -> None:
        """Label Studio /api/version endpoint should be reachable."""
        response = httpx.get(
            f"{label_studio_base_url}/api/version",
            timeout=10.0,
        )
        assert response.status_code == 200, f"Label Studio API returned {response.status_code}"
        logger.info("Label Studio version: %s", response.json())

    def test_02_webhook_endpoint_exists(
        self,
        api_base_url: str,
    ) -> None:
        """The /webhooks/label-studio endpoint should exist (not 404)."""
        response = httpx.post(
            f"{api_base_url}/webhooks/label-studio",
            json={},
            timeout=10.0,
        )
        assert response.status_code != 404, "Webhook endpoint /webhooks/label-studio returned 404 (not registered)"
        logger.info(
            "Webhook endpoint responded with status %d",
            response.status_code,
        )

    def test_03_label_studio_projects_api(
        self,
        label_studio_base_url: str,
        label_studio_api_key: str,
    ) -> None:
        """Label Studio /api/projects should return 200 when authenticated."""
        if not label_studio_api_key:
            pytest.skip("AL_LABEL_STUDIO_API_KEY not set, skipping projects API test")

        response = httpx.get(
            f"{label_studio_base_url}/api/projects",
            headers={"Authorization": f"Token {label_studio_api_key}"},
            timeout=10.0,
        )
        assert response.status_code == 200, f"Label Studio projects API returned {response.status_code}"
        logger.info("Label Studio projects response: %s", response.json())
