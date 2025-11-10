"""Signal processing-based classifier using deterministic EEG metrics."""

from typing import Dict, Any
import numpy as np
import time

from .base import BaseClassifier
from signal_processing.features import (
    estimate_cognitive_workload,
    BANDS_DEFAULT,
    WORKLOAD_WEIGHTS_DEFAULT,
)


class SignalProcessingClassifier(BaseClassifier):
    """
    Deterministic workload classifier based on EEG band power analysis.

    This classifier uses established neuroscience metrics:
    - Frontal theta power
    - Theta/beta ratio in frontal regions
    - Parietal alpha power
    - Frontal theta / parietal alpha ratio

    No machine learning model required - uses direct signal processing.
    """

    def __init__(
        self,
        name: str = "signal_processing",
        version: str = "1.0",
        sfreq: float = 250.0,
        channel_groups: Dict[str, list] = None,
        bands: Dict[str, tuple] = None,
        filter_cutoffs: Dict[str, float] = None,
        psd_config: Dict[str, float] = None,
        metric_weights: Dict[str, float] = None,
    ):
        """
        Initialize signal processing classifier.

        Args:
            name: Classifier name
            version: Classifier version
            sfreq: Sampling frequency in Hz (default: 250)
            channel_groups: Dictionary mapping region names to channel indices
                          e.g., {"frontal": [0, 1], "parietal": [5, 6]}
            bands: Frequency bands (uses BANDS_DEFAULT if None)
            filter_cutoffs: Bandpass filter cutoffs (default: 1-40 Hz)
            psd_config: PSD computation config (default: 4s window, 2s overlap)
            metric_weights: Weights for workload calculation
        """
        super().__init__(name, version)
        self.sfreq = sfreq

        # Default channel groups for standard 10-20 system
        # Indices assume: [F3, F4, C3, Cz, C4, P3, P4]
        self.channel_groups = channel_groups or {
            "frontal": [0, 1],  # F3, F4
            "central": [2, 3, 4],  # C3, Cz, C4
            "parietal": [5, 6],  # P3, P4
        }

        self.bands = bands or BANDS_DEFAULT
        self.filter_cutoffs = filter_cutoffs or {"low": 1.0, "high": 40.0}
        self.psd_config = psd_config or {"window_size": 4.0, "overlap": 2.0}
        self.metric_weights = metric_weights or WORKLOAD_WEIGHTS_DEFAULT

    async def predict(self, eeg_data: np.ndarray, **kwargs) -> Dict[str, Any]:
        """
        Predict cognitive workload from raw EEG data.

        Args:
            eeg_data: Raw EEG data of shape (n_channels, n_samples)
            **kwargs: Additional parameters (unused for this classifier)

        Returns:
            Dictionary with:
            - workload: Mean workload value
            - confidence: Fixed at 1.0 (deterministic)
            - features: Extracted EEG features
            - metadata: Processing information
        """
        start_time = time.time()

        # Run workload estimation pipeline
        workload_array, metrics = estimate_cognitive_workload(
            eeg_data=eeg_data,
            sfreq=self.sfreq,
            channel_groups=self.channel_groups,
            bands=self.bands,
            filter_cutoffs=self.filter_cutoffs,
            psd_config=self.psd_config,
            metric_weights=self.metric_weights,
        )

        # Take mean across windows if multiple windows
        if isinstance(workload_array, np.ndarray):
            workload_value = float(np.mean(workload_array))
        else:
            workload_value = float(workload_array)

        # Convert metrics to serializable format
        features = {}
        for key, value in metrics.items():
            if isinstance(value, np.ndarray):
                features[key] = float(np.mean(value))
            else:
                features[key] = float(value)

        processing_time = (time.time() - start_time) * 1000  # Convert to ms

        return {
            "workload": workload_value,
            "confidence": 1.0,  # Deterministic, so confidence is always 1.0
            "attention": None,  # Not computed by this classifier
            "features": features,
            "metadata": {
                "classifier_type": "signal_processing",
                "processing_time_ms": processing_time,
                "n_channels": eeg_data.shape[0],
                "n_samples": eeg_data.shape[1],
                "duration_sec": eeg_data.shape[1] / self.sfreq,
            },
        }

    def get_metadata(self) -> Dict[str, Any]:
        """Get classifier configuration and metadata."""
        return {
            "name": self.name,
            "version": self.version,
            "type": "signal_processing",
            "description": "Deterministic workload classifier based on EEG band power metrics",
            "config": {
                "sampling_frequency": self.sfreq,
                "channel_groups": self.channel_groups,
                "frequency_bands": self.bands,
                "filter_cutoffs": self.filter_cutoffs,
                "psd_config": self.psd_config,
                "metric_weights": self.metric_weights,
            },
            "outputs": {
                "workload": "Cognitive workload index (higher = more load)",
                "features": "EEG metrics (theta, alpha, beta powers and ratios)",
            },
            "requirements": {
                "min_channels": 7,
                "expected_channels": ["F3", "F4", "C3", "Cz", "C4", "P3", "P4"],
                "sampling_rate": f"{self.sfreq} Hz",
                "min_duration": f"{self.psd_config['window_size']} seconds",
            },
        }
