"""In-memory buffer for real-time EEG stream data.

This module provides thread-safe buffers for storing the latest samples
from each active session, enabling low-latency real-time queries.
"""

import asyncio
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID
import numpy as np


class StreamBuffer:
    """Thread-safe circular buffer for real-time stream data.

    Stores the latest N samples for quick access by MCP tools.
    Uses collections.deque for O(1) append and automatic size limiting.
    """

    def __init__(self, maxlen: int = 1000):
        """Initialize stream buffer.

        Args:
            maxlen: Maximum number of samples to store (oldest are dropped)
        """
        self.maxlen = maxlen
        self._buffer: deque = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def add_sample(
        self,
        timestamp: datetime,
        data: np.ndarray | Dict[str, Any],
        session_id: UUID,
        user_id: str,
        sample_type: str = "raw",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Add a sample to the buffer.

        Args:
            timestamp: Sample timestamp
            data: EEG data array or feature dictionary
            session_id: Session UUID
            user_id: User identifier
            sample_type: Type of data ("raw", "features", "prediction")
            metadata: Optional additional metadata
        """
        async with self._lock:
            sample = {
                "timestamp": timestamp,
                "data": data,
                "session_id": session_id,
                "user_id": user_id,
                "sample_type": sample_type,
                "metadata": metadata or {},
            }
            self._buffer.append(sample)

    async def get_latest(self, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get the most recent sample.

        Args:
            user_id: Optional filter by user_id

        Returns:
            Latest sample dict or None if buffer is empty
        """
        async with self._lock:
            if not self._buffer:
                return None

            if user_id is None:
                return self._buffer[-1]

            # Search backwards for latest sample from this user
            for sample in reversed(self._buffer):
                if sample["user_id"] == user_id:
                    return sample

            return None

    async def get_last_n(
        self,
        n: int,
        user_id: Optional[str] = None,
        sample_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get the last N samples.

        Args:
            n: Number of samples to retrieve
            user_id: Optional filter by user_id
            sample_type: Optional filter by sample type

        Returns:
            List of sample dicts (newest first)
        """
        async with self._lock:
            if not self._buffer:
                return []

            # Filter samples
            filtered = self._buffer
            if user_id is not None:
                filtered = [s for s in filtered if s["user_id"] == user_id]
            if sample_type is not None:
                filtered = [s for s in filtered if s["sample_type"] == sample_type]

            # Return last n samples (newest first)
            return list(reversed(filtered))[-n:][::-1]

    async def get_range(
        self,
        start_time: datetime,
        end_time: datetime,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get samples within a time range.

        Args:
            start_time: Start of time range
            end_time: End of time range
            user_id: Optional filter by user_id

        Returns:
            List of samples in time range (oldest first)
        """
        async with self._lock:
            if not self._buffer:
                return []

            samples = []
            for sample in self._buffer:
                if start_time <= sample["timestamp"] <= end_time:
                    if user_id is None or sample["user_id"] == user_id:
                        samples.append(sample)

            return samples

    async def clear(self, user_id: Optional[str] = None):
        """Clear the buffer.

        Args:
            user_id: Optional - only clear samples for this user
        """
        async with self._lock:
            if user_id is None:
                self._buffer.clear()
            else:
                # Remove only samples from this user
                self._buffer = deque(
                    (s for s in self._buffer if s["user_id"] != user_id),
                    maxlen=self.maxlen
                )

    async def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics.

        Returns:
            Dictionary with buffer stats
        """
        async with self._lock:
            if not self._buffer:
                return {
                    "total_samples": 0,
                    "unique_users": 0,
                    "unique_sessions": 0,
                    "oldest_timestamp": None,
                    "newest_timestamp": None,
                }

            user_ids = set(s["user_id"] for s in self._buffer)
            session_ids = set(s["session_id"] for s in self._buffer)

            return {
                "total_samples": len(self._buffer),
                "unique_users": len(user_ids),
                "unique_sessions": len(session_ids),
                "oldest_timestamp": self._buffer[0]["timestamp"],
                "newest_timestamp": self._buffer[-1]["timestamp"],
                "buffer_capacity": self.maxlen,
                "buffer_usage_percent": (len(self._buffer) / self.maxlen) * 100,
            }


class SessionBufferManager:
    """Manages separate buffers for each active session.

    This allows independent buffers per user/session for better isolation
    and easier session management.
    """

    def __init__(self, default_buffer_size: int = 1000):
        """Initialize session buffer manager.

        Args:
            default_buffer_size: Default size for new session buffers
        """
        self.default_buffer_size = default_buffer_size
        self._buffers: Dict[UUID, StreamBuffer] = {}
        self._lock = asyncio.Lock()

    async def get_buffer(self, session_id: UUID) -> StreamBuffer:
        """Get or create a buffer for a session.

        Args:
            session_id: Session UUID

        Returns:
            StreamBuffer for this session
        """
        async with self._lock:
            if session_id not in self._buffers:
                self._buffers[session_id] = StreamBuffer(maxlen=self.default_buffer_size)
            return self._buffers[session_id]

    async def add_sample(
        self,
        session_id: UUID,
        timestamp: datetime,
        data: np.ndarray | Dict[str, Any],
        user_id: str,
        sample_type: str = "raw",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Add a sample to a session's buffer.

        Args:
            session_id: Session UUID
            timestamp: Sample timestamp
            data: EEG data or features
            user_id: User identifier
            sample_type: Type of data
            metadata: Optional metadata
        """
        buffer = await self.get_buffer(session_id)
        await buffer.add_sample(timestamp, data, session_id, user_id, sample_type, metadata)

    async def remove_session(self, session_id: UUID):
        """Remove a session's buffer (e.g., when session ends).

        Args:
            session_id: Session UUID to remove
        """
        async with self._lock:
            if session_id in self._buffers:
                del self._buffers[session_id]

    async def get_active_sessions(self) -> List[UUID]:
        """Get list of active session IDs.

        Returns:
            List of session UUIDs with active buffers
        """
        async with self._lock:
            return list(self._buffers.keys())

    async def get_all_stats(self) -> Dict[UUID, Dict[str, Any]]:
        """Get statistics for all session buffers.

        Returns:
            Dictionary mapping session_id to stats dict
        """
        async with self._lock:
            stats = {}
            for session_id, buffer in self._buffers.items():
                stats[session_id] = await buffer.get_stats()
            return stats

    async def clear_all(self):
        """Clear all session buffers."""
        async with self._lock:
            for buffer in self._buffers.values():
                await buffer.clear()


# Global instance (will be initialized by server.py)
_global_buffer_manager: Optional[SessionBufferManager] = None


def get_buffer_manager() -> SessionBufferManager:
    """Get the global buffer manager instance.

    Returns:
        Global SessionBufferManager instance

    Raises:
        RuntimeError: If buffer manager not initialized
    """
    if _global_buffer_manager is None:
        raise RuntimeError("Buffer manager not initialized. Call init_buffer_manager() first.")
    return _global_buffer_manager


def init_buffer_manager(default_buffer_size: int = 1000) -> SessionBufferManager:
    """Initialize the global buffer manager.

    Args:
        default_buffer_size: Default size for session buffers

    Returns:
        Initialized SessionBufferManager
    """
    global _global_buffer_manager
    _global_buffer_manager = SessionBufferManager(default_buffer_size)
    return _global_buffer_manager
