"""
Feature extraction and workload estimation using deterministic EEG metrics.

Ported from bci-direct project.
"""

import numpy as np
from typing import Dict, Tuple

from .preprocessing import filter_eeg_data, compute_psd, extract_band_power


# Default frequency bands
BANDS_DEFAULT = {
    "delta": (1, 4),
    "theta": (4, 8),
    "alpha": (8, 13),
    "beta": (13, 30),
    "gamma": (30, 40),
}

# Default weights for workload calculation
WORKLOAD_WEIGHTS_DEFAULT = {
    "frontal_theta": 0.10,
    "frontal_theta_beta_ratio": 0.45,
    "parietal_alpha": 0.45,
    "frontal_theta_parietal_alpha_ratio": 2.0,
}


def calculate_deterministic_workload(
    band_powers: Dict[str, np.ndarray],
    channel_groups: Dict[str, list],
    metric_weights: Dict[str, float]
) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    """
    Calculate cognitive workload using deterministic EEG metrics.

    This computes workload based on established neuroscience metrics:
    - Frontal theta power (increases with workload)
    - Theta/beta ratio in frontal regions (increases with workload)
    - Parietal alpha power (decreases with workload)
    - Frontal theta / parietal alpha ratio (increases with workload)

    Args:
        band_powers: Dictionary of band name -> power array (n_channels, n_windows)
        channel_groups: Dictionary mapping region names to channel indices
                       e.g., {"frontal": [0, 1], "parietal": [5, 6]}
        metric_weights: Dictionary of metric name -> weight for weighted sum

    Returns:
        Tuple of (workload_index, metrics_dict) where:
        - workload_index: Array of workload values (n_windows,)
        - metrics_dict: Dictionary of computed metrics
    """
    n_windows = band_powers[next(iter(band_powers))].shape[1]

    metrics = {
        "frontal_theta": np.zeros(n_windows),
        "frontal_theta_beta_ratio": np.zeros(n_windows),
        "parietal_alpha": np.zeros(n_windows),
        "frontal_theta_parietal_alpha_ratio": np.zeros(n_windows),
        "workload_index": np.zeros(n_windows),
    }

    # Frontal theta power
    if "frontal" in channel_groups:
        ft = np.mean(
            [np.mean(band_powers["theta"][ch, :]) for ch in channel_groups["frontal"]]
        )
        metrics["frontal_theta"] = ft

    # Theta/beta ratio in frontal regions
    if "frontal" in channel_groups:
        theta = np.mean(
            [band_powers["theta"][ch, :] for ch in channel_groups["frontal"]], axis=0
        )
        beta = np.mean(
            [band_powers["beta"][ch, :] for ch in channel_groups["frontal"]], axis=0
        )
        metrics["frontal_theta_beta_ratio"] = (theta - beta) / 2.0

    # Parietal alpha power
    if "parietal" in channel_groups:
        pa = np.mean(
            [np.mean(band_powers["alpha"][ch, :]) for ch in channel_groups["parietal"]]
        )
        metrics["parietal_alpha"] = pa

    # Frontal theta / parietal alpha ratio
    if "frontal" in channel_groups and "parietal" in channel_groups:
        theta = np.mean(
            [band_powers["theta"][ch, :] for ch in channel_groups["frontal"]], axis=0
        )
        alpha = np.mean(
            [band_powers["alpha"][ch, :] for ch in channel_groups["parietal"]], axis=0
        )
        metrics["frontal_theta_parietal_alpha_ratio"] = (theta - alpha) / 2.0

    # Calculate weighted workload index
    workload_idx = (
        metric_weights.get("frontal_theta", 0) * metrics["frontal_theta"]
        + metric_weights.get("frontal_theta_beta_ratio", 0)
        * metrics["frontal_theta_beta_ratio"]
        + metric_weights.get("parietal_alpha", 0) * (1 - metrics["parietal_alpha"])
        + metric_weights.get("frontal_theta_parietal_alpha_ratio", 0)
        * metrics["frontal_theta_parietal_alpha_ratio"]
    )

    metrics["workload_index"] = workload_idx

    # Return subset of key metrics for reporting
    report_metrics = {
        "frontal_theta": metrics["frontal_theta"],
        "frontal_theta_beta_ratio": metrics["frontal_theta_beta_ratio"],
        "parietal_alpha": metrics["parietal_alpha"],
        "frontal_theta_parietal_alpha_ratio": metrics["frontal_theta_parietal_alpha_ratio"],
        "workload_index": metrics["workload_index"],
    }

    return workload_idx, report_metrics


def estimate_cognitive_workload(
    eeg_data: np.ndarray,
    sfreq: float,
    channel_groups: Dict[str, list],
    bands: Dict[str, Tuple[float, float]] = None,
    filter_cutoffs: Dict[str, float] = None,
    psd_config: Dict[str, float] = None,
    metric_weights: Dict[str, float] = None,
) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    """
    End-to-end cognitive workload estimation pipeline.

    Pipeline: Raw EEG → Bandpass filter → PSD → Band power → Workload metrics

    Args:
        eeg_data: Raw EEG data of shape (n_channels, n_samples)
        sfreq: Sampling frequency in Hz
        channel_groups: Dictionary mapping region names to channel indices
        bands: Frequency bands dictionary (uses BANDS_DEFAULT if None)
        filter_cutoffs: {"low": Hz, "high": Hz} (default: 1-40 Hz)
        psd_config: {"window_size": sec, "overlap": sec} (default: 4s window, 2s overlap)
        metric_weights: Weights for workload calculation (uses WORKLOAD_WEIGHTS_DEFAULT if None)

    Returns:
        Tuple of (workload_index, metrics_dict)
    """
    # Use defaults if not provided
    if bands is None:
        bands = BANDS_DEFAULT
    if filter_cutoffs is None:
        filter_cutoffs = {"low": 1.0, "high": 40.0}
    if psd_config is None:
        psd_config = {"window_size": 4.0, "overlap": 2.0}
    if metric_weights is None:
        metric_weights = WORKLOAD_WEIGHTS_DEFAULT

    # Step 1: Bandpass filter
    filtered = filter_eeg_data(
        eeg_data, sfreq, filter_cutoffs["low"], filter_cutoffs["high"]
    )

    # Step 2: Compute power spectral density
    freqs, psd = compute_psd(
        filtered,
        sfreq,
        window_size_sec=psd_config.get("window_size", 4.0),
        overlap_sec=psd_config.get("overlap", 2.0),
    )

    # Step 3: Extract band power
    band_powers = extract_band_power(freqs, psd, bands)

    # Step 4: Calculate workload from band powers
    return calculate_deterministic_workload(band_powers, channel_groups, metric_weights)
