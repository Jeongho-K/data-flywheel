"""Integration tests for prediction logging storage and graceful degradation."""

from __future__ import annotations

import httpx
import pytest


class TestBucketExistence:
    """Verify that required MinIO buckets exist after seeding."""

    def test_prediction_logs_bucket_exists(self, minio_s3_client) -> None:  # noqa: ANN001
        """The prediction-logs bucket must be present in MinIO.

        Args:
            minio_s3_client: Session-scoped boto3 S3 client fixture.
        """
        response = minio_s3_client.list_buckets()
        bucket_names = [b["Name"] for b in response.get("Buckets", [])]
        assert "prediction-logs" in bucket_names

    def test_drift_reports_bucket_exists(self, minio_s3_client) -> None:  # noqa: ANN001
        """The drift-reports bucket must be present in MinIO.

        Args:
            minio_s3_client: Session-scoped boto3 S3 client fixture.
        """
        response = minio_s3_client.list_buckets()
        bucket_names = [b["Name"] for b in response.get("Buckets", [])]
        assert "drift-reports" in bucket_names


class TestGracefulDegradation:
    """Verify that the serving API degrades gracefully when no model is loaded."""

    def test_predict_503_without_model(self, api_base_url: str) -> None:
        """POST /predict must return 503 when the health endpoint reports model_loaded=false.

        The test is skipped if the model is already loaded so it does not
        produce a false failure in environments where a model is present.

        Args:
            api_base_url: Base URL fixture for the serving API.
        """
        health_response = httpx.get(f"{api_base_url}/health", timeout=5)
        assert health_response.status_code == 200

        health_data = health_response.json()
        if health_data.get("model_loaded", False):
            pytest.skip("Model is loaded; graceful-degradation path is not reachable.")

        # Minimal multipart/form-data request with a 1×1 white PNG.
        _1x1_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        predict_response = httpx.post(
            f"{api_base_url}/predict",
            files={"file": ("test.png", _1x1_png, "image/png")},
            timeout=5,
        )
        assert predict_response.status_code == 503
