"""Device resolution utilities for PyTorch."""

from __future__ import annotations

import logging

import torch

logger = logging.getLogger(__name__)


def resolve_device(device_str: str) -> torch.device:
    """Resolve device string to torch.device.

    Args:
        device_str: "auto", "cpu", "cuda", or "mps".

    Returns:
        Resolved torch.device.

    Raises:
        RuntimeError: If explicitly requested device is not available.
    """
    if device_str == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        logger.warning(
            "No GPU detected (CUDA/MPS unavailable). Falling back to CPU. Training will be significantly slower."
        )
        return torch.device("cpu")

    device = torch.device(device_str)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            f"Device '{device_str}' requested but CUDA is not available. Use --device auto or --device cpu."
        )
    if device.type == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError(
            f"Device '{device_str}' requested but MPS is not available. Use --device auto or --device cpu."
        )
    return device
