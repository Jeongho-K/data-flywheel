"""Prepare noisy dataset for Active Learning demonstration.

Downloads CIFAR-10 and creates a dataset with intentional data quality issues:
- Label noise (~15-20%): Random label swaps
- Blurry images (~5-10%): Gaussian blur applied
- Dark images (~5%): Extreme brightness reduction
- Duplicate images (~5%): Same image copied with different names
- Odd-sized images (~3%): Resized to abnormal dimensions

The corruption metadata is saved as JSON for later verification of
detection accuracy by CleanVision and CleanLab.

Usage:
    python examples/image_classification/prepare_noisy_data.py
"""

from __future__ import annotations

import json
import logging
import random
import shutil
from pathlib import Path

from PIL import Image, ImageFilter
from torchvision.datasets import CIFAR10

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CIFAR10_CLASSES = [
    "airplane",
    "automobile",
    "bird",
    "cat",
    "deer",
    "dog",
    "frog",
    "horse",
    "ship",
    "truck",
]

# Dataset size: 500 per class for train, 100 per class for val = 6,000 total
TRAIN_PER_CLASS = 500
VAL_PER_CLASS = 100

# Corruption ratios (applied to train set only)
LABEL_NOISE_RATIO = 0.18  # ~18% of train images get wrong labels
BLUR_RATIO = 0.08         # ~8% get Gaussian blur
DARK_RATIO = 0.05         # ~5% get extreme darkening
DUPLICATE_RATIO = 0.05    # ~5% are duplicates
ODD_SIZE_RATIO = 0.03     # ~3% get abnormal dimensions

RANDOM_SEED = 42


def prepare_noisy_dataset(output_dir: str | Path = "data/raw/cifar10-noisy") -> Path:
    """Download CIFAR-10 and create a noisy dataset for Active Learning demo.

    Args:
        output_dir: Where to save the organized dataset.

    Returns:
        Path to the created dataset directory.
    """
    output_dir = Path(output_dir)
    if output_dir.exists():
        logger.info("Removing existing dataset at %s", output_dir)
        shutil.rmtree(output_dir)

    random.seed(RANDOM_SEED)

    logger.info("Downloading CIFAR-10...")
    try:
        train_dataset = CIFAR10(root="/tmp/cifar10", train=True, download=True)
        val_dataset = CIFAR10(root="/tmp/cifar10", train=False, download=True)
    except (OSError, RuntimeError) as e:
        raise RuntimeError(f"Failed to download CIFAR-10: {e}") from e

    # Save clean validation set (no corruption)
    logger.info("Saving clean validation set...")
    _save_subset(val_dataset, output_dir / "val", VAL_PER_CLASS)

    # Save train set with corruption
    logger.info("Saving train set with intentional corruption...")
    corruption_log = _save_noisy_train(train_dataset, output_dir / "train", TRAIN_PER_CLASS)

    # Save corruption metadata
    metadata_path = output_dir / "corruption_metadata.json"
    metadata = {
        "seed": RANDOM_SEED,
        "train_per_class": TRAIN_PER_CLASS,
        "val_per_class": VAL_PER_CLASS,
        "total_train": TRAIN_PER_CLASS * len(CIFAR10_CLASSES),
        "total_val": VAL_PER_CLASS * len(CIFAR10_CLASSES),
        "corruption_ratios": {
            "label_noise": LABEL_NOISE_RATIO,
            "blur": BLUR_RATIO,
            "dark": DARK_RATIO,
            "duplicate": DUPLICATE_RATIO,
            "odd_size": ODD_SIZE_RATIO,
        },
        "corruption_counts": {
            "label_noise": len(corruption_log["label_noise"]),
            "blur": len(corruption_log["blur"]),
            "dark": len(corruption_log["dark"]),
            "duplicate": len(corruption_log["duplicate"]),
            "odd_size": len(corruption_log["odd_size"]),
        },
        "corrupted_files": corruption_log,
    }
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    total_corrupted = sum(metadata["corruption_counts"].values())
    total_train = TRAIN_PER_CLASS * len(CIFAR10_CLASSES)
    logger.info(
        "Noisy dataset created: %d train + %d val images at %s",
        total_train,
        VAL_PER_CLASS * len(CIFAR10_CLASSES),
        output_dir,
    )
    logger.info(
        "Corruption summary: %d/%d images corrupted (%.1f%%)",
        total_corrupted,
        total_train,
        100 * total_corrupted / total_train,
    )
    for ctype, count in metadata["corruption_counts"].items():
        logger.info("  %s: %d images", ctype, count)

    return output_dir


def _save_noisy_train(
    dataset: CIFAR10,
    train_dir: Path,
    per_class: int,
) -> dict[str, list[dict]]:
    """Save train images with intentional corruption.

    Returns:
        Dictionary mapping corruption type to list of affected file records.
    """
    corruption_log: dict[str, list[dict]] = {
        "label_noise": [],
        "blur": [],
        "dark": [],
        "duplicate": [],
        "odd_size": [],
    }

    # First, collect all images per class
    class_images: dict[int, list[tuple[Image.Image, int]]] = {i: [] for i in range(len(CIFAR10_CLASSES))}
    for img, label in dataset:
        if len(class_images[label]) < per_class:
            class_images[label].append((img, label))
        if all(len(v) >= per_class for v in class_images.values()):
            break

    # Flatten and assign indices
    all_images: list[tuple[Image.Image, int, int]] = []  # (img, label, global_idx)
    idx = 0
    for label in range(len(CIFAR10_CLASSES)):
        for img, lbl in class_images[label]:
            all_images.append((img, lbl, idx))
            idx += 1

    total = len(all_images)
    indices = list(range(total))
    random.shuffle(indices)

    # Assign corruption types to different subsets (no overlap)
    ptr = 0
    label_noise_count = int(total * LABEL_NOISE_RATIO)
    blur_count = int(total * BLUR_RATIO)
    dark_count = int(total * DARK_RATIO)
    odd_size_count = int(total * ODD_SIZE_RATIO)

    label_noise_indices = set(indices[ptr : ptr + label_noise_count])
    ptr += label_noise_count
    blur_indices = set(indices[ptr : ptr + blur_count])
    ptr += blur_count
    dark_indices = set(indices[ptr : ptr + dark_count])
    ptr += dark_count
    odd_size_indices = set(indices[ptr : ptr + odd_size_count])
    ptr += odd_size_count

    # Duplicate: pick from clean images (not already corrupted)
    duplicate_count = int(total * DUPLICATE_RATIO)
    remaining = [i for i in indices[ptr:] if i not in label_noise_indices]
    duplicate_source_indices = set(remaining[:duplicate_count])

    # Save images
    class_counters: dict[str, int] = {name: 0 for name in CIFAR10_CLASSES}

    for img, original_label, global_idx in all_images:
        # Determine effective label (may be corrupted)
        effective_label = original_label

        if global_idx in label_noise_indices:
            # Swap to a random different class
            other_classes = [c for c in range(len(CIFAR10_CLASSES)) if c != original_label]
            effective_label = random.choice(other_classes)
            corruption_log["label_noise"].append({
                "global_idx": global_idx,
                "original_label": CIFAR10_CLASSES[original_label],
                "corrupted_label": CIFAR10_CLASSES[effective_label],
            })

        class_name = CIFAR10_CLASSES[effective_label]
        class_dir = train_dir / class_name
        class_dir.mkdir(parents=True, exist_ok=True)

        count = class_counters[class_name]
        img_path = class_dir / f"{class_name}_{count:04d}.png"
        class_counters[class_name] = count + 1

        # Apply image-level corruption
        processed_img = img

        if global_idx in blur_indices:
            processed_img = img.filter(ImageFilter.GaussianBlur(radius=5))
            corruption_log["blur"].append({
                "file": str(img_path.relative_to(train_dir)),
                "global_idx": global_idx,
            })

        elif global_idx in dark_indices:
            from PIL import ImageEnhance

            processed_img = ImageEnhance.Brightness(img).enhance(0.05)
            corruption_log["dark"].append({
                "file": str(img_path.relative_to(train_dir)),
                "global_idx": global_idx,
            })

        elif global_idx in odd_size_indices:
            processed_img = img.resize((8, 64))  # Abnormal aspect ratio
            corruption_log["odd_size"].append({
                "file": str(img_path.relative_to(train_dir)),
                "global_idx": global_idx,
                "size": (8, 64),
            })

        if not isinstance(processed_img, Image.Image):
            raise TypeError(f"Expected PIL Image, got {type(processed_img)}")
        processed_img.save(img_path)

        # Create duplicate if selected
        if global_idx in duplicate_source_indices:
            dup_count = class_counters[class_name]
            dup_path = class_dir / f"{class_name}_{dup_count:04d}.png"
            class_counters[class_name] = dup_count + 1
            processed_img.save(dup_path)
            corruption_log["duplicate"].append({
                "original_file": str(img_path.relative_to(train_dir)),
                "duplicate_file": str(dup_path.relative_to(train_dir)),
                "global_idx": global_idx,
            })

    return corruption_log


def _save_subset(
    dataset: CIFAR10,
    split_dir: Path,
    per_class: int,
) -> None:
    """Save a limited number of clean images per class to disk."""
    class_counts: dict[int, int] = {}

    for img, label in dataset:
        count = class_counts.get(label, 0)
        if count >= per_class:
            continue

        class_name = CIFAR10_CLASSES[label]
        class_dir = split_dir / class_name
        class_dir.mkdir(parents=True, exist_ok=True)

        img_path = class_dir / f"{class_name}_{count:04d}.png"
        if not isinstance(img, Image.Image):
            raise TypeError(f"Expected PIL Image, got {type(img)} at index {count}")
        img.save(img_path)

        class_counts[label] = count + 1
        if all(class_counts.get(i, 0) >= per_class for i in range(len(CIFAR10_CLASSES))):
            break


if __name__ == "__main__":
    try:
        path = prepare_noisy_dataset()
        logger.info("Done. Noisy dataset at: %s", path)
    except Exception as e:
        logger.error("Failed to prepare noisy dataset: %s", e)
        raise SystemExit(1) from e
