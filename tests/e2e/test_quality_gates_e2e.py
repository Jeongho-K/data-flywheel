"""E2E tests for the 5-gate quality system.

Tests import gate functions directly and exercise them with synthetic
inputs to verify behaviour at each transition point in the pipeline.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# G1: Data Quality Gate
# ---------------------------------------------------------------------------


class TestG1DataQualityGate:
    """Verify the CV data validator is importable and well-structured."""

    def test_01_import_validator(self) -> None:
        """Import validate_image_dataset and verify it is callable."""
        from src.plugins.cv.validator import validate_image_dataset

        assert callable(validate_image_dataset), "validate_image_dataset should be callable"
        logger.info("validate_image_dataset imported successfully")

    def test_02_validation_report_structure(self) -> None:
        """ValidationReport should have expected fields for G1 gate checks."""
        from src.core.protocols import ValidationReport

        report = ValidationReport()
        assert hasattr(report, "total_images"), "Missing field: total_images"
        assert hasattr(report, "issues_found"), "Missing field: issues_found"
        assert hasattr(report, "issue_types"), "Missing field: issue_types"
        assert hasattr(report, "health_score"), "Missing field: health_score"
        logger.info(
            "ValidationReport fields verified: total_images=%d, issues_found=%d, health_score=%.2f",
            report.total_images,
            report.issues_found,
            report.health_score,
        )


# ---------------------------------------------------------------------------
# G2: Training Quality Gate
# ---------------------------------------------------------------------------


class TestG2TrainingQualityGate:
    """Test G2 gate with synthetic training metrics."""

    @staticmethod
    def _check(metrics: dict[str, float]) -> dict[str, Any]:
        """Call check_training_quality outside of Prefect runtime.

        The task is decorated with ``@task``, so we call the underlying
        function via ``.fn()`` to avoid requiring a Prefect flow context.
        """
        from src.core.orchestration.tasks.continuous_training_tasks import (
            check_training_quality,
        )

        with patch(
            "src.core.orchestration.tasks.continuous_training_tasks.create_markdown_artifact",
        ):
            return check_training_quality.fn(metrics=metrics)

    def test_01_passing_metrics(self) -> None:
        """Metrics above thresholds should pass the G2 gate."""
        result = self._check(
            {
                "best_val_accuracy": 0.85,
                "val_loss": 0.4,
                "train_loss": 0.35,
            }
        )
        assert result["passed"] is True, f"G2 should pass: {result['reason']}"
        logger.info("G2 passed with good metrics: %s", result["reason"])

    def test_02_failing_accuracy(self) -> None:
        """Accuracy below the minimum threshold should fail the G2 gate."""
        result = self._check(
            {
                "best_val_accuracy": 0.5,
                "val_loss": 0.8,
                "train_loss": 0.3,
            }
        )
        assert result["passed"] is False, "G2 should fail on low accuracy"
        logger.info("G2 correctly failed on low accuracy: %s", result["reason"])

    def test_03_failing_overfit_gap(self) -> None:
        """Large val_loss - train_loss gap should fail the G2 gate.

        With val_loss=0.9 and train_loss=0.3, the gap is 0.6 which
        exceeds the default max_overfit_gap of 0.15.
        """
        result = self._check(
            {
                "best_val_accuracy": 0.85,
                "val_loss": 0.9,
                "train_loss": 0.3,
            }
        )
        assert result["passed"] is False, "G2 should fail on overfit gap"
        logger.info("G2 correctly failed on overfit gap: %s", result["reason"])


# ---------------------------------------------------------------------------
# G3: Champion Gate
# ---------------------------------------------------------------------------


class TestG3ChampionGate:
    """Test G3 gate import and MLflow integration."""

    def test_01_import_champion_gate(self) -> None:
        """Import check_champion_gate and verify it is callable."""
        from src.core.orchestration.tasks.continuous_training_tasks import (
            check_champion_gate,
        )

        assert callable(check_champion_gate), "check_champion_gate should be callable"
        logger.info("check_champion_gate imported successfully")

    def test_02_champion_gate_with_mlflow(self, mlflow_base_url: str) -> None:
        """Run the champion gate against a live MLflow instance.

        If a champion model exists, verify the result has a 'passed' key.
        If the model is not registered, the function should handle gracefully
        by auto-promoting when no champion exists.
        """
        from src.core.orchestration.tasks.continuous_training_tasks import (
            check_champion_gate,
        )

        with patch(
            "src.core.orchestration.tasks.continuous_training_tasks.create_markdown_artifact",
        ):
            result = check_champion_gate.fn(
                challenger_metrics={"best_val_accuracy": 0.9},
                registered_model_name="cv-classifier",
                mlflow_tracking_uri=mlflow_base_url,
            )

        assert "passed" in result, f"Champion gate result missing 'passed' key: {result}"
        logger.info(
            "G3 champion gate result: passed=%s, reason=%s",
            result["passed"],
            result.get("reason", "N/A"),
        )


# ---------------------------------------------------------------------------
# G4: Canary Gate
# ---------------------------------------------------------------------------


class TestG4CanaryGate:
    """Test G4 canary gate import and Prometheus integration."""

    def test_01_import_canary_gate(self) -> None:
        """Import check_canary_gate and verify it is callable."""
        from src.core.orchestration.tasks.canary_gate import check_canary_gate

        assert callable(check_canary_gate), "check_canary_gate should be callable"
        logger.info("check_canary_gate imported successfully")

    def test_02_canary_gate_with_prometheus(
        self,
        prometheus_base_url: str,
    ) -> None:
        """Run the canary gate against a live Prometheus instance.

        Verify the result contains the expected keys. The canary service
        may not be running, so the gate may report lack of data -- that
        is acceptable.
        """
        from src.core.orchestration.tasks.canary_gate import check_canary_gate

        with patch(
            "src.core.orchestration.tasks.canary_gate.create_markdown_artifact",
        ):
            result = check_canary_gate.fn(
                prometheus_url=prometheus_base_url,
            )

        assert "passed" in result, f"Canary gate missing 'passed': {result}"
        assert "reason" in result, f"Canary gate missing 'reason': {result}"
        assert "metrics" in result, f"Canary gate missing 'metrics': {result}"
        logger.info(
            "G4 canary gate result: passed=%s, reason=%s",
            result["passed"],
            result["reason"],
        )


# ---------------------------------------------------------------------------
# G5: Runtime Gate
# ---------------------------------------------------------------------------


class TestG5RuntimeGate:
    """Test G5 runtime gate with synthetic drift scores."""

    @staticmethod
    def _evaluate(
        drift_score: float,
        drift_detected: bool,
    ) -> dict[str, Any]:
        """Call evaluate_runtime_gate outside of Prefect runtime."""
        from src.core.orchestration.tasks.runtime_gate import (
            evaluate_runtime_gate,
        )

        with patch(
            "src.core.orchestration.tasks.runtime_gate.create_markdown_artifact",
        ):
            return evaluate_runtime_gate.fn(
                drift_score=drift_score,
                drift_detected=drift_detected,
            )

    def test_01_low_drift(self) -> None:
        """Low drift score should yield LOW severity and log_only action."""
        result = self._evaluate(drift_score=0.1, drift_detected=False)
        assert result["severity"] == "low", f"Expected LOW severity, got {result['severity']}"
        assert result["action"] == "log_only", f"Expected log_only action, got {result['action']}"
        logger.info("G5 low drift: %s", result)

    def test_02_medium_drift(self) -> None:
        """Medium drift should yield MEDIUM severity and trigger AL."""
        result = self._evaluate(drift_score=0.45, drift_detected=True)
        assert result["severity"] == "medium", f"Expected MEDIUM severity, got {result['severity']}"
        assert result["action"] == "trigger_active_learning", (
            f"Expected trigger_active_learning, got {result['action']}"
        )
        logger.info("G5 medium drift: %s", result)

    def test_03_high_drift(self) -> None:
        """High drift should yield HIGH severity and rollback_and_retrain."""
        result = self._evaluate(drift_score=0.7, drift_detected=True)
        assert result["severity"] == "high", f"Expected HIGH severity, got {result['severity']}"
        assert result["action"] == "rollback_and_retrain", f"Expected rollback_and_retrain, got {result['action']}"
        logger.info("G5 high drift: %s", result)
