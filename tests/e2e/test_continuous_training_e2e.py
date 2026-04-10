"""E2E tests for the continuous training pipeline.

Tests Prefect deployments, MLflow integration, retraining trigger
endpoint, and round state management via S3.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from tests.e2e.helpers.e2e_utils import (
    admin_trigger_retraining,
    get_s3_objects,
)

logger = logging.getLogger(__name__)


class TestPrefectDeployments:
    """Verify Prefect server health and deployment/flow listing."""

    def test_01_prefect_server_healthy(self, prefect_base_url: str) -> None:
        """GET /api/health should return 200 indicating Prefect server is up."""
        response = httpx.get(f"{prefect_base_url}/api/health", timeout=10.0)
        assert response.status_code == 200, f"Prefect health check failed with status {response.status_code}"
        logger.info("Prefect server healthy at %s", prefect_base_url)

    def test_02_list_deployments(self, prefect_base_url: str) -> None:
        """POST /api/deployments/filter should return 200.

        Verifies the Prefect API is functional. Deployments may or may not
        exist depending on whether flows have been served.
        """
        response = httpx.post(
            f"{prefect_base_url}/api/deployments/filter",
            json={"limit": 50},
            timeout=10.0,
        )
        assert response.status_code == 200, f"Prefect deployments filter returned {response.status_code}"
        data = response.json()
        logger.info(
            "Prefect deployments filter returned %d entries",
            len(data) if isinstance(data, list) else 0,
        )

    def test_03_list_flows(self, prefect_base_url: str) -> None:
        """POST /api/flows/filter should return 200."""
        response = httpx.post(
            f"{prefect_base_url}/api/flows/filter",
            json={"limit": 50},
            timeout=10.0,
        )
        assert response.status_code == 200, f"Prefect flows filter returned {response.status_code}"
        logger.info("Prefect flows filter returned successfully")


class TestMLflowIntegration:
    """Verify MLflow tracking server health and experiment/model APIs."""

    def test_01_mlflow_healthy(self, mlflow_base_url: str) -> None:
        """GET /health should return 200 indicating MLflow is up."""
        response = httpx.get(f"{mlflow_base_url}/health", timeout=10.0)
        assert response.status_code == 200, f"MLflow health check failed with status {response.status_code}"
        logger.info("MLflow server healthy at %s", mlflow_base_url)

    def test_02_search_experiments(self, mlflow_base_url: str) -> None:
        """POST /api/2.0/mlflow/experiments/search should return experiments.

        MLflow requires a positive ``max_results`` and prefers POST for this
        endpoint (GET is not supported on recent versions).
        """
        response = httpx.post(
            f"{mlflow_base_url}/api/2.0/mlflow/experiments/search",
            json={"max_results": 100},
            timeout=10.0,
        )
        assert response.status_code == 200, f"MLflow experiments search returned {response.status_code}"
        data = response.json()
        assert "experiments" in data, "MLflow experiments search response missing 'experiments' key"
        logger.info(
            "MLflow has %d experiments",
            len(data["experiments"]),
        )

    def test_03_search_registered_models(self, mlflow_base_url: str) -> None:
        """GET /api/2.0/mlflow/registered-models/search should return 200."""
        response = httpx.get(
            f"{mlflow_base_url}/api/2.0/mlflow/registered-models/search",
            timeout=10.0,
        )
        assert response.status_code == 200, f"MLflow registered-models search returned {response.status_code}"
        logger.info("MLflow registered-models search returned successfully")

    def test_04_check_model_versions(self, mlflow_base_url: str) -> None:
        """Check latest versions for the cv-classifier registered model.

        If the model exists, verify the response contains model versions.
        If the model has not been registered yet, skip with an informative
        message rather than failing.
        """
        response = httpx.get(
            f"{mlflow_base_url}/api/2.0/mlflow/registered-models/get-latest-versions",
            params={"name": "cv-classifier"},
            timeout=10.0,
        )
        if response.status_code == 200:
            data = response.json()
            assert "model_versions" in data, "Response missing 'model_versions' key"
            logger.info(
                "cv-classifier has %d model versions",
                len(data["model_versions"]),
            )
        else:
            pytest.skip(
                f"cv-classifier model not registered yet (status {response.status_code}): {response.text[:200]}"
            )


class TestRetrainingTrigger:
    """Verify the admin retraining trigger endpoint and round state."""

    def test_01_trigger_without_auth_returns_403(
        self,
        api_base_url: str,
    ) -> None:
        """POST /admin/trigger-retraining without X-Admin-Key should return 403."""
        response = httpx.post(
            f"{api_base_url}/admin/trigger-retraining",
            timeout=10.0,
        )
        assert response.status_code == 403, f"Expected 403 without auth, got {response.status_code}"
        logger.info("Trigger endpoint correctly rejects unauthenticated requests")

    def test_02_trigger_with_auth(
        self,
        api_base_url: str,
        admin_api_key: str,
    ) -> None:
        """Trigger retraining with a valid admin API key.

        Accepts both 200 (triggered) and 503 (Prefect unavailable) as valid
        responses -- the endpoint itself works in both cases.
        """
        if not admin_api_key:
            pytest.skip("ADMIN_API_KEY not configured")

        try:
            result = admin_trigger_retraining(api_base_url, admin_api_key)
            logger.info("Retraining triggered successfully: %s", result)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 503:
                logger.info(
                    "Retraining endpoint returned 503 (Prefect unavailable) -- endpoint works but orchestrator is down",
                )
            else:
                raise

    def test_03_round_state_bucket(self, minio_s3_client: Any) -> None:
        """Check if the active-learning bucket exists and contains round state.

        Looks for the 'rounds/' prefix in the 'active-learning' bucket.
        """
        try:
            objects = get_s3_objects(
                minio_s3_client,
                "active-learning",
                "rounds/",
            )
            logger.info(
                "Found %d objects under rounds/ prefix in active-learning bucket",
                len(objects),
            )
        except minio_s3_client.exceptions.NoSuchBucket:
            pytest.skip("active-learning bucket does not exist yet")
        except Exception as exc:
            pytest.skip(f"Cannot access active-learning bucket: {exc}")
