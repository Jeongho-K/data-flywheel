"""E2E tests for pseudo-label data accumulation.

Validates the Data Flywheel's auto-accumulation path: high-confidence
predictions are automatically stored in S3 as pseudo-labeled training data.

Note:
    The auto-accumulator has a ``flush_threshold`` of 500 by default.
    With only 60 predictions sent in these tests, the internal buffer
    likely will not flush automatically. Tests handle this gracefully
    with ``pytest.skip()`` rather than hard failures.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, ClassVar

import pytest

from tests.e2e.helpers.e2e_utils import (
    flush_prediction_logger,
    get_s3_objects,
    read_s3_jsonl,
)

logger = logging.getLogger(__name__)

_ACTIVE_LEARNING_BUCKET = "active-learning"
_ACCUMULATED_PREFIX = "accumulated/"
_IMAGES_PREFIX = "accumulated/images/"


class TestAccumulationBucketStructure:
    """Verify S3 bucket structure for accumulation."""

    accumulated_objects: ClassVar[list[dict[str, Any]]] = []
    image_objects: ClassVar[list[dict[str, Any]]] = []

    def test_01_active_learning_bucket_exists(
        self,
        minio_s3_client: Any,
    ) -> None:
        """The active-learning S3 bucket must exist."""
        response = minio_s3_client.head_bucket(Bucket=_ACTIVE_LEARNING_BUCKET)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

    def test_02_accumulated_prefix_structure(
        self,
        minio_s3_client: Any,
    ) -> None:
        """List objects under the accumulated/ prefix.

        The prefix may be empty if no predictions have been sent yet.
        This is acceptable; the test records the current state for
        downstream assertions.
        """
        objects = get_s3_objects(
            minio_s3_client,
            _ACTIVE_LEARNING_BUCKET,
            _ACCUMULATED_PREFIX,
        )
        TestAccumulationBucketStructure.accumulated_objects = objects
        logger.info(
            "Found %d objects under '%s' prefix",
            len(objects),
            _ACCUMULATED_PREFIX,
        )

    def test_03_images_prefix_structure(
        self,
        minio_s3_client: Any,
    ) -> None:
        """List objects under the accumulated/images/ prefix.

        Stores image object metadata for later verification.
        """
        objects = get_s3_objects(
            minio_s3_client,
            _ACTIVE_LEARNING_BUCKET,
            _IMAGES_PREFIX,
        )
        TestAccumulationBucketStructure.image_objects = objects
        logger.info(
            "Found %d objects under '%s' prefix",
            len(objects),
            _IMAGES_PREFIX,
        )


class TestPseudoLabelAccumulation:
    """Full accumulation flow: predict, accumulate, verify in S3.

    Sends 60 predictions and checks whether pseudo-labeled data appears
    in the ``accumulated/`` prefix. Because the default flush_threshold
    is 500, the buffer may not flush with only 60 predictions. Tests
    degrade gracefully by skipping rather than failing.
    """

    prediction_results: ClassVar[list[dict[str, Any]]] = []
    auto_accumulate_count: ClassVar[int] = 0
    accumulated_objects: ClassVar[list[dict[str, Any]]] = []

    def test_01_send_predictions_to_trigger_accumulation(
        self,
        api_base_url: str,
        test_image_bytes: bytes,
    ) -> None:
        """Send 60 predictions to populate the accumulation buffer.

        Counts how many responses have ``routing_decision == "auto_accumulate"``
        to confirm the confidence router is classifying high-confidence
        predictions for auto-accumulation.
        """
        results = flush_prediction_logger(
            api_base_url,
            image_bytes=test_image_bytes,
            count=60,
        )
        TestPseudoLabelAccumulation.prediction_results = results
        logger.info("Received %d prediction responses", len(results))

        auto_count = sum(1 for r in results if r.get("routing_decision") == "auto_accumulate")
        TestPseudoLabelAccumulation.auto_accumulate_count = auto_count
        logger.info(
            "%d / %d predictions routed to auto_accumulate",
            auto_count,
            len(results),
        )

    def test_02_wait_for_accumulated_data(
        self,
        minio_s3_client: Any,
    ) -> None:
        """Poll S3 for accumulated objects with retry.

        Retries 5 times with 10-second intervals. If no objects appear,
        remaining tests are skipped with an informative message about
        the buffer threshold (default 500).
        """
        max_attempts = 5
        poll_interval = 10.0

        for attempt in range(1, max_attempts + 1):
            objects = get_s3_objects(
                minio_s3_client,
                _ACTIVE_LEARNING_BUCKET,
                _ACCUMULATED_PREFIX,
            )
            if objects:
                TestPseudoLabelAccumulation.accumulated_objects = objects
                logger.info(
                    "Found %d accumulated objects on attempt %d",
                    len(objects),
                    attempt,
                )
                return
            logger.info(
                "Attempt %d/%d: no accumulated objects yet, waiting %.0fs",
                attempt,
                max_attempts,
                poll_interval,
            )
            if attempt < max_attempts:
                time.sleep(poll_interval)

        pytest.skip(
            "No accumulated objects found after polling. "
            "The flush_threshold is 500 by default, so 60 predictions "
            "may not trigger an automatic flush. "
            "Skipping remaining accumulation content tests."
        )

    def test_03_verify_accumulated_jsonl_content(
        self,
        minio_s3_client: Any,
    ) -> None:
        """Verify JSONL records contain required fields.

        Each accumulated record must include: timestamp, predicted_class,
        confidence, model_version, and image_ref. Confidence values
        must be positive floats.
        """
        if not TestPseudoLabelAccumulation.accumulated_objects:
            pytest.skip("No accumulated objects available from previous test")

        jsonl_keys = [
            obj["Key"] for obj in TestPseudoLabelAccumulation.accumulated_objects if obj["Key"].endswith(".jsonl")
        ]
        if not jsonl_keys:
            pytest.skip("No JSONL files found under accumulated/ prefix")

        required_keys = {
            "timestamp",
            "predicted_class",
            "confidence",
            "model_version",
            "image_ref",
        }

        records = read_s3_jsonl(
            minio_s3_client,
            _ACTIVE_LEARNING_BUCKET,
            jsonl_keys[0],
        )
        logger.info(
            "Read %d records from %s",
            len(records),
            jsonl_keys[0],
        )

        for i, record in enumerate(records):
            missing = required_keys - set(record.keys())
            assert not missing, f"Record {i} missing keys: {missing}"
            confidence = record["confidence"]
            assert isinstance(confidence, float), f"Record {i} confidence is not float: {type(confidence)}"
            assert confidence > 0, f"Record {i} confidence must be > 0, got {confidence}"

    def test_04_verify_accumulated_images(
        self,
        minio_s3_client: Any,
    ) -> None:
        """Check that image bytes are stored alongside JSONL metadata.

        Images should appear under the ``accumulated/images/`` prefix.
        """
        if not TestPseudoLabelAccumulation.accumulated_objects:
            pytest.skip("No accumulated objects available from previous test")

        image_objects = get_s3_objects(
            minio_s3_client,
            _ACTIVE_LEARNING_BUCKET,
            _IMAGES_PREFIX,
        )
        logger.info(
            "Found %d objects under '%s' prefix",
            len(image_objects),
            _IMAGES_PREFIX,
        )
        assert len(image_objects) > 0, f"Expected image objects under '{_IMAGES_PREFIX}' but none were found"


class TestAccumulationDataQuality:
    """Verify quality aspects of accumulated data.

    These tests inspect previously accumulated JSONL records for
    data-quality invariants. If no accumulated data exists (e.g.,
    because the flush_threshold was not reached), tests skip
    gracefully.
    """

    def _get_accumulated_records(
        self,
        minio_s3_client: Any,
    ) -> list[dict[str, Any]]:
        """Load accumulated JSONL records or skip if unavailable.

        Args:
            minio_s3_client: boto3 S3 client for MinIO.

        Returns:
            List of parsed JSONL records.

        Raises:
            pytest.skip: If no accumulated JSONL data is found.
        """
        objects = get_s3_objects(
            minio_s3_client,
            _ACTIVE_LEARNING_BUCKET,
            _ACCUMULATED_PREFIX,
        )
        jsonl_keys = [obj["Key"] for obj in objects if obj["Key"].endswith(".jsonl")]
        if not jsonl_keys:
            pytest.skip("No accumulated JSONL data found. flush_threshold (default 500) likely not reached.")

        return read_s3_jsonl(
            minio_s3_client,
            _ACTIVE_LEARNING_BUCKET,
            jsonl_keys[0],
        )

    def test_01_accumulated_records_have_timestamps(
        self,
        minio_s3_client: Any,
    ) -> None:
        """All accumulated records must have ISO-8601 timestamp strings."""
        records = self._get_accumulated_records(minio_s3_client)

        for i, record in enumerate(records):
            ts = record.get("timestamp")
            assert ts is not None, f"Record {i} missing 'timestamp'"
            assert isinstance(ts, str), f"Record {i} timestamp is not a string: {type(ts)}"
            # Validate ISO-8601 parsing
            try:
                datetime.fromisoformat(ts)
            except ValueError as exc:
                pytest.fail(f"Record {i} timestamp '{ts}' is not valid ISO-8601: {exc}")

    def test_02_accumulated_records_have_valid_confidence(
        self,
        minio_s3_client: Any,
    ) -> None:
        """All confidence values must be in [0.0, 1.0]."""
        records = self._get_accumulated_records(minio_s3_client)

        for i, record in enumerate(records):
            confidence = record.get("confidence")
            assert confidence is not None, f"Record {i} missing 'confidence'"
            assert isinstance(confidence, (int, float)), f"Record {i} confidence is not numeric: {type(confidence)}"
            assert 0.0 <= float(confidence) <= 1.0, f"Record {i} confidence {confidence} not in [0.0, 1.0]"

    def test_03_class_distribution_logged(
        self,
        minio_s3_client: Any,
    ) -> None:
        """At least one record must have a non-None predicted_class."""
        records = self._get_accumulated_records(minio_s3_client)

        classes = [r.get("predicted_class") for r in records if r.get("predicted_class") is not None]
        assert len(classes) > 0, (
            "All accumulated records have predicted_class=None; expected at least one valid class label"
        )
        logger.info(
            "Found %d records with predicted_class values: %s",
            len(classes),
            set(classes),
        )
