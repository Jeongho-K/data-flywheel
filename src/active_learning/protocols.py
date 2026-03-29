"""Domain-agnostic protocols for Active Learning components.

These protocols define the contracts that domain-specific implementations
(CV, NLP, Tabular) must satisfy. The framework orchestrates the flow;
plugins provide the implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class UncertaintyEstimator(Protocol):
    """Measures prediction uncertainty.

    Domain-specific implementations compute uncertainty from model outputs.
    Higher scores indicate greater uncertainty.
    """

    def estimate(self, predictions: list[list[float]]) -> list[float]:
        """Compute uncertainty scores from model predictions.

        Args:
            predictions: Model output in domain-specific format.
                For CV: list of softmax probability vectors.

        Returns:
            Uncertainty scores in [0.0, 1.0], one per prediction.
        """
        ...


@runtime_checkable
class SampleSelector(Protocol):
    """Selects samples for human labeling from uncertain predictions.

    Implements query strategies such as top-K uncertainty, diversity
    sampling, or hybrid approaches.
    """

    def select(self, uncertainties: list[float], budget: int) -> list[int]:
        """Select indices of samples to send for labeling.

        Args:
            uncertainties: Uncertainty scores per sample.
            budget: Maximum number of samples to select.

        Returns:
            Indices of selected samples, ordered by priority.
        """
        ...
