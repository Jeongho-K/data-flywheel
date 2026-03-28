"""Data-Centric Active Learning Demo.

Runs 10 rounds of the data cleaning loop:
  1. CleanVision image quality check -> remove bad images
  2. Train model (short epochs, MLflow tracking)
  3. CleanLab label quality check -> remove bad labels
  4. Log metrics, create Prefect artifacts
  5. Repeat

Demonstrates that removing bad data (even though total data decreases)
leads to progressive improvement in model accuracy.

Usage:
    # Ensure services are running: make up && make seed
    # Prepare noisy data first:
    #   python examples/image_classification/prepare_noisy_data.py
    # Then run:
    python scripts/run_active_learning_demo.py

    # Or with custom settings:
    python scripts/run_active_learning_demo.py --rounds 5 --epochs 3
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import mlflow
import mlflow.pytorch
import numpy as np
import torch
from mlflow import MlflowClient
from mlflow.models import infer_signature
from prefect import flow, task
from prefect.artifacts import create_markdown_artifact, create_table_artifact
from torch.utils.data import DataLoader
from torchvision.datasets import ImageFolder

from src.data.preprocessing.transforms import get_eval_transforms, get_train_transforms
from src.data.validation.label_validator import validate_labels
from src.training.models.classifier import create_classifier
from src.training.trainers.classification_trainer import _run_epoch, resolve_device

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@task(name="clean-images")
def clean_images_task(data_dir: str, round_num: int) -> dict[str, Any]:
    """Run CleanVision and remove problematic images.

    Args:
        data_dir: Path to dataset directory.
        round_num: Current Active Learning round number.

    Returns:
        Dict with cleaning results.
    """
    from cleanvision import Imagelab

    from src.data.validation.image_validator import validate_image_dataset

    train_dir = Path(data_dir) / "train"
    report = validate_image_dataset(train_dir)

    before_count = sum(1 for _ in train_dir.rglob("*.png"))

    imagelab = Imagelab(data_path=str(train_dir))
    imagelab.find_issues()

    issues_df = imagelab.issues
    issue_cols = [c for c in issues_df.columns if c.startswith("is_") and c.endswith("_issue")]
    has_issue = issues_df[issue_cols].any(axis=1)
    problematic = issues_df[has_issue].index.tolist()

    removed_count = 0
    for img_path in problematic:
        p = Path(img_path)
        if p.exists():
            p.unlink()
            removed_count += 1

    after_count = sum(1 for _ in train_dir.rglob("*.png"))

    result = {
        "round": round_num,
        "before_count": before_count,
        "removed_images": removed_count,
        "after_count": after_count,
        "health_score": report.health_score,
        "issues_found": report.issues_found,
    }

    markdown = f"""## Round {round_num}: Image Cleaning
| Metric | Value |
|--------|-------|
| Images Before | {before_count} |
| Images Removed | {removed_count} |
| Images After | {after_count} |
| Health Score | {report.health_score:.3f} |
"""
    create_markdown_artifact(key=f"image-clean-round-{round_num}", markdown=markdown)

    logger.info("Round %d image cleaning: removed %d/%d images", round_num, removed_count, before_count)
    return result


@task(name="train-round")
def train_round_task(
    data_dir: str,
    round_num: int,
    model_name: str,
    num_classes: int,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    experiment_name: str,
    mlflow_tracking_uri: str,
    registered_model_name: str,
    image_size: int = 224,
) -> dict[str, Any]:
    """Train model for one Active Learning round.

    Args:
        data_dir: Path to dataset directory.
        round_num: Current round number.
        model_name: Architecture name.
        num_classes: Number of classes.
        epochs: Training epochs per round.
        batch_size: Batch size.
        learning_rate: Learning rate.
        experiment_name: MLflow experiment name.
        mlflow_tracking_uri: MLflow URI.
        registered_model_name: Model registry name.
        image_size: Input image size.

    Returns:
        Dict with training metrics and model info.
    """
    device = resolve_device("auto")
    train_dir = Path(data_dir) / "train"
    val_dir = Path(data_dir) / "val"

    train_dataset = ImageFolder(str(train_dir), transform=get_train_transforms(image_size))
    val_dataset = ImageFolder(str(val_dir), transform=get_eval_transforms(image_size))

    pin_memory = device.type == "cuda"
    train_loader = DataLoader(
        train_dataset, batch_size=batch_size, shuffle=True, num_workers=0, pin_memory=pin_memory,
    )
    val_loader = DataLoader(
        val_dataset, batch_size=batch_size, shuffle=False, num_workers=0, pin_memory=pin_memory,
    )

    model = create_classifier(model_name, num_classes, pretrained=True)
    model = model.to(device)
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=1e-4)

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    mlflow.set_experiment(experiment_name)
    mlflow.pytorch.autolog(log_models=False, log_every_n_epoch=None)

    best_val_acc = 0.0
    model_version = None
    with mlflow.start_run(run_name=f"round-{round_num}") as run:
        mlflow.log_params({
            "round": round_num,
            "model_name": model_name,
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "train_samples": len(train_dataset),
            "val_samples": len(val_dataset),
            "device": str(device),
        })

        for epoch in range(epochs):
            train_loss, train_acc = _run_epoch(
                model, train_loader, criterion, optimizer, device, training=True,
            )
            val_loss, val_acc = _run_epoch(
                model, val_loader, criterion, None, device, training=False,
            )

            mlflow.log_metrics({
                "train_loss": train_loss,
                "train_accuracy": train_acc,
                "val_loss": val_loss,
                "val_accuracy": val_acc,
            }, step=epoch)

            if val_acc > best_val_acc:
                best_val_acc = val_acc

        mlflow.log_metrics({
            "best_val_accuracy": best_val_acc,
            "round_number": round_num,
            "train_data_count": len(train_dataset),
        })

        # Log model with signature
        model.eval()
        sample_input = torch.randn(1, 3, image_size, image_size)
        with torch.no_grad():
            sample_output = model(sample_input.to(device))
        signature = infer_signature(sample_input.numpy(), sample_output.cpu().numpy())

        model_info = mlflow.pytorch.log_model(
            model,
            name="model",
            signature=signature,
            input_example=sample_input.numpy(),
            registered_model_name=registered_model_name,
        )

        if model_info.registered_model_version:
            model_version = model_info.registered_model_version
            client = MlflowClient()
            client.set_registered_model_alias(
                registered_model_name, "challenger", model_version,
            )

        run_id = run.info.run_id

    return {
        "round": round_num,
        "best_val_accuracy": best_val_acc,
        "train_samples": len(train_dataset),
        "val_samples": len(val_dataset),
        "run_id": run_id,
        "model_version": model_version,
    }


@task(name="clean-labels")
def clean_labels_task(
    data_dir: str,
    round_num: int,
    mlflow_tracking_uri: str,
    registered_model_name: str,
    num_classes: int,
    image_size: int = 224,
    max_remove_per_round: int = 100,
) -> dict[str, Any]:
    """Run CleanLab and remove likely mislabeled images.

    Args:
        data_dir: Path to dataset directory.
        round_num: Current round number.
        mlflow_tracking_uri: MLflow URI.
        registered_model_name: Model name in registry.
        num_classes: Number of classes.
        image_size: Input image size.
        max_remove_per_round: Maximum images to remove per round.

    Returns:
        Dict with label cleaning results.
    """
    device = resolve_device("auto")

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    model_uri = f"models:/{registered_model_name}@challenger"
    model = mlflow.pytorch.load_model(model_uri)
    model = model.to(device)
    model.eval()

    train_dir = Path(data_dir) / "train"
    dataset = ImageFolder(str(train_dir), transform=get_eval_transforms(image_size))
    loader = DataLoader(dataset, batch_size=64, shuffle=False, num_workers=0)

    all_labels: list[int] = []
    all_probs: list[np.ndarray] = []

    with torch.no_grad():
        for images, targets in loader:
            outputs = model(images.to(device))
            probs = torch.softmax(outputs, dim=1)
            all_probs.append(probs.cpu().numpy())
            all_labels.extend(targets.numpy().tolist())

    all_paths = [sample[0] for sample in dataset.samples]
    labels_array = np.array(all_labels)
    pred_probs = np.concatenate(all_probs, axis=0)

    report = validate_labels(labels_array, pred_probs)
    before_count = len(dataset)

    issues_to_remove = report.issue_indices[:max_remove_per_round]
    removed_count = 0
    for idx in issues_to_remove:
        if idx < len(all_paths):
            p = Path(all_paths[idx])
            if p.exists():
                p.unlink()
                removed_count += 1

    after_count = sum(1 for _ in train_dir.rglob("*.png"))

    result = {
        "round": round_num,
        "total_label_issues": report.issues_found,
        "removed_labels": removed_count,
        "before_count": before_count,
        "after_count": after_count,
        "avg_label_quality": report.avg_label_quality,
        "label_issue_rate": report.issues_found / max(before_count, 1),
    }

    markdown = f"""## Round {round_num}: Label Cleaning (CleanLab)
| Metric | Value |
|--------|-------|
| Total Label Issues | {report.issues_found} |
| Labels Removed | {removed_count} |
| Samples Before | {before_count} |
| Samples After | {after_count} |
| Avg Label Quality | {report.avg_label_quality:.3f} |
| Label Issue Rate | {result['label_issue_rate']:.1%} |
"""
    create_markdown_artifact(key=f"label-clean-round-{round_num}", markdown=markdown)

    logger.info(
        "Round %d label cleaning: %d issues found, %d removed",
        round_num, report.issues_found, removed_count,
    )
    return result


@flow(name="active-learning-demo", log_prints=True)
def active_learning_demo(
    data_dir: str = "data/raw/cifar10-noisy",
    rounds: int = 10,
    model_name: str = "resnet18",
    num_classes: int = 10,
    epochs_per_round: int = 3,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    experiment_name: str = "active-learning-demo",
    mlflow_tracking_uri: str = "http://localhost:5050",
    registered_model_name: str = "cifar10-active-learning",
) -> list[dict]:
    """Run Data-Centric Active Learning loop.

    Each round: clean images -> train -> clean labels.

    Args:
        data_dir: Path to noisy dataset.
        rounds: Number of Active Learning rounds.
        model_name: Model architecture.
        num_classes: Number of classes.
        epochs_per_round: Training epochs per round.
        batch_size: Batch size.
        learning_rate: Learning rate.
        experiment_name: MLflow experiment name.
        mlflow_tracking_uri: MLflow URI.
        registered_model_name: Model registry name.

    Returns:
        List of per-round result dictionaries.
    """
    all_results: list[dict] = []
    best_accuracy = 0.0

    for round_num in range(1, rounds + 1):
        logger.info("=" * 60)
        logger.info("ACTIVE LEARNING ROUND %d/%d", round_num, rounds)
        logger.info("=" * 60)

        # Step 1: Clean images
        image_result = clean_images_task(data_dir, round_num)

        # Step 2: Train
        train_result = train_round_task(
            data_dir=data_dir,
            round_num=round_num,
            model_name=model_name,
            num_classes=num_classes,
            epochs=epochs_per_round,
            batch_size=batch_size,
            learning_rate=learning_rate,
            experiment_name=experiment_name,
            mlflow_tracking_uri=mlflow_tracking_uri,
            registered_model_name=registered_model_name,
        )

        # Step 3: Clean labels (skip round 1 to establish baseline)
        label_result: dict = {}
        if round_num > 1:
            label_result = clean_labels_task(
                data_dir=data_dir,
                round_num=round_num,
                mlflow_tracking_uri=mlflow_tracking_uri,
                registered_model_name=registered_model_name,
                num_classes=num_classes,
            )

        # Promote to champion if best accuracy
        if train_result["best_val_accuracy"] > best_accuracy:
            best_accuracy = train_result["best_val_accuracy"]
            if train_result.get("model_version"):
                client = MlflowClient(mlflow_tracking_uri)
                client.set_registered_model_alias(
                    registered_model_name, "champion", train_result["model_version"],
                )
                logger.info(
                    "New champion! Round %d, accuracy=%.4f, version=%s",
                    round_num, best_accuracy, train_result["model_version"],
                )

        round_result = {
            "round": round_num,
            "accuracy": train_result["best_val_accuracy"],
            "train_samples": train_result["train_samples"],
            "images_removed": image_result.get("removed_images", 0),
            "labels_removed": label_result.get("removed_labels", 0),
            "health_score": image_result.get("health_score", 0),
            "label_issue_rate": label_result.get("label_issue_rate", 0),
        }
        all_results.append(round_result)

    # Create summary artifacts
    summary_table = [
        {
            "Round": r["round"],
            "Accuracy": f"{r['accuracy']:.4f}",
            "Train Samples": r["train_samples"],
            "Images Removed": r["images_removed"],
            "Labels Removed": r["labels_removed"],
        }
        for r in all_results
    ]
    create_table_artifact(key="active-learning-summary", table=summary_table)

    first_acc = all_results[0]["accuracy"] if all_results else 0
    last_acc = all_results[-1]["accuracy"] if all_results else 0
    improvement = last_acc - first_acc
    markdown = f"""## Active Learning Summary ({rounds} rounds)
| Metric | Value |
|--------|-------|
| Initial Accuracy | {first_acc:.4f} |
| Final Accuracy | {last_acc:.4f} |
| Improvement | {improvement:+.4f} |
| Best Accuracy | {best_accuracy:.4f} |
| Initial Train Size | {all_results[0]['train_samples'] if all_results else 'N/A'} |
| Final Train Size | {all_results[-1]['train_samples'] if all_results else 'N/A'} |
"""
    create_markdown_artifact(key="active-learning-final-summary", markdown=markdown)

    logger.info(
        "Active Learning complete! %d rounds, accuracy: %.4f -> %.4f (delta %+.4f)",
        rounds, first_acc, last_acc, improvement,
    )

    return all_results


def main() -> None:
    """Parse arguments and run Active Learning demo."""
    parser = argparse.ArgumentParser(description="Data-Centric Active Learning Demo")
    parser.add_argument("--data-dir", default="data/raw/cifar10-noisy", help="Dataset path")
    parser.add_argument("--rounds", type=int, default=10, help="Number of AL rounds")
    parser.add_argument("--epochs", type=int, default=3, help="Epochs per round")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--model", default="resnet18", help="Model architecture")
    parser.add_argument("--mlflow-uri", default="http://localhost:5050", help="MLflow URI")
    parser.add_argument("--experiment", default="active-learning-demo", help="MLflow experiment")
    parser.add_argument("--model-name", default="cifar10-active-learning", help="Registry name")
    args = parser.parse_args()

    active_learning_demo(
        data_dir=args.data_dir,
        rounds=args.rounds,
        model_name=args.model,
        num_classes=10,
        epochs_per_round=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        experiment_name=args.experiment,
        mlflow_tracking_uri=args.mlflow_uri,
        registered_model_name=args.model_name,
    )


if __name__ == "__main__":
    main()
