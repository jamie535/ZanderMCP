"""
Preprocessing functions for EEG data.

Ported from bci-direct project.
"""

import numpy as np
from scipy import signal


def filter_eeg_data(
    eeg_data: np.ndarray, sfreq: float, low_cutoff=1.0, high_cutoff=40.0
) -> np.ndarray:
    """
    Bandpass filter EEG data using 4th order Butterworth filter.

    Args:
        eeg_data: EEG data array of shape (n_channels, n_samples)
        sfreq: Sampling frequency in Hz
        low_cutoff: Low cutoff frequency in Hz (default: 1.0)
        high_cutoff: High cutoff frequency in Hz (default: 40.0)

    Returns:
        Filtered EEG data with same shape as input
    """
    nyq = 0.5 * sfreq
    low = low_cutoff / nyq
    high = high_cutoff / nyq
    b, a = signal.butter(4, [low, high], btype="band")

    filtered = np.zeros_like(eeg_data)
    for i in range(eeg_data.shape[0]):
        filtered[i, :] = signal.filtfilt(b, a, eeg_data[i, :])
    return filtered


def compute_psd(
    eeg_data: np.ndarray,
    sfreq: float,
    window_size_sec: float = 4.0,
    overlap_sec: float = 2.0
):
    """
    Compute power spectral density using windowed FFT with Hanning window.

    Args:
        eeg_data: Filtered EEG data of shape (n_channels, n_samples)
        sfreq: Sampling frequency in Hz
        window_size_sec: Window size in seconds (default: 4.0)
        overlap_sec: Overlap between windows in seconds (default: 2.0)

    Returns:
        Tuple of (freqs, psd) where:
        - freqs: frequency bins (n_freqs,)
        - psd: power spectral density (n_channels, n_freqs, n_windows)
    """
    n_channels = eeg_data.shape[0]
    window_length = int(window_size_sec * sfreq)
    overlap_length = int(overlap_sec * sfreq)
    step = window_length - overlap_length
    n_windows = (eeg_data.shape[1] - overlap_length) // step

    win = signal.windows.hann(window_length)
    freqs = np.fft.rfftfreq(window_length, 1 / sfreq)
    n_freqs = len(freqs)
    psd = np.zeros((n_channels, n_freqs, n_windows))

    for ch in range(n_channels):
        for w in range(n_windows):
            start = w * step
            end = start + window_length
            if end <= eeg_data.shape[1]:
                data_win = eeg_data[ch, start:end] * win
                fft_data = np.fft.rfft(data_win)
                psd[ch, :, w] = np.log10(np.abs(fft_data) ** 2 / window_length)

    return freqs, psd


def extract_band_power(freqs: np.ndarray, psd: np.ndarray, bands: dict):
    """
    Extract band power for defined frequency bands using Simpson integration.

    Args:
        freqs: Frequency bins from compute_psd
        psd: Power spectral density from compute_psd
        bands: Dictionary of band name -> (fmin, fmax) tuples
               e.g., {"theta": (4, 8), "alpha": (8, 13)}

    Returns:
        Dictionary of band name -> power array (n_channels, n_windows)
    """
    from scipy.integrate import simpson

    n_channels, _, n_windows = psd.shape
    band_powers = {}

    for band, (fmin, fmax) in bands.items():
        idx = (freqs >= fmin) & (freqs <= fmax)
        arr = np.zeros((n_channels, n_windows))
        for ch in range(n_channels):
            for w in range(n_windows):
                arr[ch, w] = simpson(psd[ch, idx, w], freqs[idx])
        band_powers[band] = arr

    return band_powers
