"""Base classifier interface for ZanderMCP."""

from abc import ABC, abstractmethod
from typing import Dict, Any
import numpy as np


class BaseClassifier(ABC):
    """Abstract base class for all classifiers."""

    def __init__(self, name: str, version: str = "1.0"):
        """
        Initialize classifier.

        Args:
            name: Classifier name
            version: Classifier version
        """
        self.name = name
        self.version = version

    @abstractmethod
    async def predict(self, eeg_data: np.ndarray, **kwargs) -> Dict[str, Any]:
        """
        Make a prediction from EEG data.

        Args:
            eeg_data: EEG data array of shape (n_channels, n_samples)
            **kwargs: Additional parameters for prediction

        Returns:
            Dictionary with prediction results, must include:
            - workload: float (0-1 or similar range)
            - confidence: float (0-1)
            - features: dict of extracted features (optional)
            - metadata: dict of additional info (optional)
        """
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """
        Get classifier metadata and configuration.

        Returns:
            Dictionary with classifier information
        """
        pass

    def get_info(self) -> Dict[str, Any]:
        """Get basic classifier information."""
        return {
            "name": self.name,
            "version": self.version,
            "type": self.__class__.__name__,
        }
