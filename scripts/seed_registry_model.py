"""Seed a minimal classifier into MLflow Model Registry.

Registers an untrained `mobilenet_v3_small` with 10 output classes as
`cv-classifier` version 1 so the serving API has something to load on a fresh
environment. Real training flows will later append higher versions.

Usage (from host):
    uv run python scripts/seed_registry_model.py

Env:
    MLFLOW_TRACKING_URI  MLflow tracking server URL (default http://localhost:5050)
    SEED_MODEL_NAME      Registered model name (default cv-classifier)
    SEED_NUM_CLASSES     Output classes (default 10)
    SEED_ARCH            Architecture in SUPPORTED_MODELS (default mobilenet_v3_small)
"""

from __future__ import annotations

import logging
import sys

import mlflow
import mlflow.pytorch
from mlflow import MlflowClient

from src.plugins.cv.models.classifier import create_classifier

# MLflow configures the root logger at import time, which makes a later
# ``logging.basicConfig`` call a silent no-op. Attach our own handler to
# the script logger so operational messages survive.
_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger = logging.getLogger("seed_registry_model")
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False

import os  # noqa: E402  (imported late to keep the logging block together)


def main() -> None:
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5050")
    model_name = os.environ.get("SEED_MODEL_NAME", "cv-classifier")
    num_classes = int(os.environ.get("SEED_NUM_CLASSES", "10"))
    arch = os.environ.get("SEED_ARCH", "mobilenet_v3_small")

    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri)

    try:
        existing = client.get_registered_model(model_name)
        versions = client.search_model_versions(f"name='{model_name}'")
        if versions:
            logger.info(
                "Registered model '%s' already has %d version(s). Skipping seed.",
                existing.name,
                len(versions),
            )
            return
    except Exception:
        logger.info("Registered model '%s' not found — creating seed.", model_name)

    model = create_classifier(model_name=arch, num_classes=num_classes, pretrained=False)

    experiment_name = "seed-bootstrap"
    mlflow.set_experiment(experiment_name)

    version = None
    with mlflow.start_run(run_name=f"seed-{model_name}") as run:
        mlflow.log_param("arch", arch)
        mlflow.log_param("num_classes", num_classes)
        mlflow.log_param("pretrained", False)
        mlflow.log_param("seed", True)

        info = mlflow.pytorch.log_model(
            pytorch_model=model,
            name="model",
            registered_model_name=model_name,
        )
        version = info.registered_model_version
        logger.info("Logged seed model: run_id=%s version=%s", run.info.run_id, version)

    if version is not None:
        client.set_registered_model_alias(name=model_name, alias="champion", version=version)
        logger.info("Set alias '%s@champion' -> version %s", model_name, version)


if __name__ == "__main__":
    main()
