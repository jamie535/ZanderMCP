"""Real-time MCP tools for querying current cognitive state.

These tools provide low-latency access to the latest predictions
from the in-memory stream buffer.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import logging

from ingestion.stream_buffer import SessionBufferManager

logger = logging.getLogger(__name__)


class RealtimeTools:
    """MCP tools for real-time cognitive state queries."""

    def __init__(self, buffer_manager: SessionBufferManager):
        """Initialize realtime tools.

        Args:
            buffer_manager: Stream buffer manager
        """
        self.buffer_manager = buffer_manager

    async def get_current_cognitive_load(
        self,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get the latest cognitive load prediction.

        This is the primary real-time query - returns the most recent
        workload prediction with confidence and trend.

        Args:
            user_id: Optional user identifier (uses latest if not specified)

        Returns:
            Dictionary with:
            - workload: float (0-1 or similar scale)
            - confidence: float (0-1)
            - timestamp: ISO timestamp
            - trend: "increasing" | "decreasing" | "stable"
            - session_id: UUID string
        """
        try:
            # Get all active sessions
            session_ids = await self.buffer_manager.get_active_sessions()

            if not session_ids:
                return {
                    "error": "No active sessions",
                    "workload": None,
                    "confidence": None,
                    "timestamp": None,
                    "trend": None,
                }

            # If user_id specified, find their session
            if user_id:
                # Find session for this user
                latest_prediction = None
                for session_id in session_ids:
                    buffer = await self.buffer_manager.get_buffer(session_id)
                    sample = await buffer.get_latest(user_id=user_id)
                    if sample and sample.get("sample_type") == "prediction":
                        latest_prediction = sample
                        break
            else:
                # Get latest prediction from any session
                latest_prediction = None
                latest_time = None

                for session_id in session_ids:
                    buffer = await self.buffer_manager.get_buffer(session_id)
                    sample = await buffer.get_latest()

                    if sample and sample.get("sample_type") == "prediction":
                        if latest_time is None or sample["timestamp"] > latest_time:
                            latest_prediction = sample
                            latest_time = sample["timestamp"]

            if not latest_prediction:
                return {
                    "error": "No predictions available yet",
                    "workload": None,
                    "confidence": None,
                    "timestamp": None,
                    "trend": None,
                }

            # Extract prediction data
            data = latest_prediction["data"]
            workload = data.get("workload")
            confidence = data.get("confidence")
            timestamp = latest_prediction["timestamp"]

            # Calculate trend (compare with previous predictions)
            trend = await self._calculate_trend(
                latest_prediction["session_id"],
                latest_prediction["user_id"],
                workload
            )

            return {
                "workload": workload,
                "confidence": confidence,
                "timestamp": timestamp.isoformat(),
                "trend": trend,
                "session_id": str(latest_prediction["session_id"]),
                "user_id": latest_prediction["user_id"],
            }

        except Exception as e:
            logger.error(f"Error getting cognitive load: {e}", exc_info=True)
            return {
                "error": str(e),
                "workload": None,
                "confidence": None,
                "timestamp": None,
                "trend": None,
            }

    async def get_cognitive_state(
        self,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get interpreted cognitive state with recommendations.

        Provides a human-readable interpretation of the cognitive state
        with actionable recommendations.

        Args:
            user_id: Optional user identifier

        Returns:
            Dictionary with:
            - state: "focused" | "moderate" | "high_load" | "overloaded"
            - workload: float
            - intensity: "low" | "medium" | "high" | "very_high"
            - duration: seconds in current state
            - recommendations: list of suggestions
        """
        try:
            # Get current load
            load_data = await self.get_current_cognitive_load(user_id)

            if load_data.get("error"):
                return {
                    "error": load_data["error"],
                    "state": None,
                    "workload": None,
                    "intensity": None,
                    "duration": None,
                    "recommendations": [],
                }

            workload = load_data["workload"]
            trend = load_data["trend"]

            # Interpret workload level
            if workload < 0.3:
                state = "focused"
                intensity = "low"
                recommendations = [
                    "Good time for complex or challenging tasks",
                    "Cognitive capacity available for learning new concepts"
                ]
            elif workload < 0.5:
                state = "moderate"
                intensity = "medium"
                recommendations = [
                    "Maintain current pace",
                    "Good balance of engagement and capacity"
                ]
            elif workload < 0.7:
                state = "high_load"
                intensity = "high"
                recommendations = [
                    "Consider taking a short break soon",
                    "Switch to less demanding tasks if possible",
                    "Stay hydrated"
                ]
            else:
                state = "overloaded"
                intensity = "very_high"
                recommendations = [
                    "Take a break as soon as possible",
                    "Step away from screen for 5-10 minutes",
                    "Practice deep breathing or stretching",
                    "Avoid starting new complex tasks"
                ]

            # Adjust recommendations based on trend
            if trend == "increasing" and workload > 0.5:
                recommendations.insert(0, f"⚠️ Cognitive load is {trend} - monitor closely")
            elif trend == "decreasing" and workload > 0.6:
                recommendations.insert(0, "Cognitive load decreasing - good progress")

            # Calculate duration in state (estimate from recent samples)
            duration = await self._estimate_state_duration(
                load_data.get("session_id"),
                load_data.get("user_id"),
                workload
            )

            return {
                "state": state,
                "workload": workload,
                "confidence": load_data["confidence"],
                "intensity": intensity,
                "duration_seconds": duration,
                "trend": trend,
                "recommendations": recommendations,
                "timestamp": load_data["timestamp"],
            }

        except Exception as e:
            logger.error(f"Error getting cognitive state: {e}", exc_info=True)
            return {
                "error": str(e),
                "state": None,
                "workload": None,
                "intensity": None,
                "duration": None,
                "recommendations": [],
            }

    async def get_workload_trend(
        self,
        minutes: int = 5,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get workload trend over recent time period.

        Args:
            minutes: Number of minutes to look back
            user_id: Optional user identifier

        Returns:
            Dictionary with trend information
        """
        try:
            session_ids = await self.buffer_manager.get_active_sessions()

            if not session_ids:
                return {
                    "error": "No active sessions",
                    "samples": [],
                    "trend": None,
                }

            # Collect predictions from last N minutes
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=minutes)

            all_predictions = []

            for session_id in session_ids:
                buffer = await self.buffer_manager.get_buffer(session_id)
                samples = await buffer.get_range(start_time, end_time, user_id=user_id)

                predictions = [
                    s for s in samples
                    if s.get("sample_type") == "prediction"
                ]
                all_predictions.extend(predictions)

            if not all_predictions:
                return {
                    "error": "No predictions in time range",
                    "samples": [],
                    "trend": None,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                }

            # Sort by timestamp
            all_predictions.sort(key=lambda x: x["timestamp"])

            # Extract workload values
            workload_values = [p["data"].get("workload") for p in all_predictions]
            timestamps = [p["timestamp"].isoformat() for p in all_predictions]

            # Calculate statistics
            avg_workload = sum(workload_values) / len(workload_values)
            min_workload = min(workload_values)
            max_workload = max(workload_values)

            # Simple trend detection (compare first half to second half)
            mid_point = len(workload_values) // 2
            if mid_point > 0:
                first_half_avg = sum(workload_values[:mid_point]) / mid_point
                second_half_avg = sum(workload_values[mid_point:]) / (len(workload_values) - mid_point)

                diff = second_half_avg - first_half_avg
                if diff > 0.1:
                    trend = "increasing"
                elif diff < -0.1:
                    trend = "decreasing"
                else:
                    trend = "stable"
            else:
                trend = "insufficient_data"

            return {
                "samples_count": len(all_predictions),
                "time_range_minutes": minutes,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "avg_workload": avg_workload,
                "min_workload": min_workload,
                "max_workload": max_workload,
                "trend": trend,
                "workload_values": workload_values,
                "timestamps": timestamps,
            }

        except Exception as e:
            logger.error(f"Error getting workload trend: {e}", exc_info=True)
            return {
                "error": str(e),
                "samples": [],
                "trend": None,
            }

    async def get_buffer_status(self) -> Dict[str, Any]:
        """Get current buffer status and statistics.

        Returns:
            Dictionary with buffer statistics
        """
        try:
            stats = await self.buffer_manager.get_all_stats()

            session_stats = []
            for session_id, session_stat in stats.items():
                session_stats.append({
                    "session_id": str(session_id),
                    **session_stat
                })

            return {
                "active_sessions": len(stats),
                "sessions": session_stats,
            }

        except Exception as e:
            logger.error(f"Error getting buffer status: {e}", exc_info=True)
            return {
                "error": str(e),
                "active_sessions": 0,
                "sessions": [],
            }

    async def _calculate_trend(
        self,
        session_id: str,
        user_id: str,
        current_workload: float
    ) -> str:
        """Calculate workload trend from recent samples.

        Args:
            session_id: Session UUID
            user_id: User identifier
            current_workload: Current workload value

        Returns:
            "increasing" | "decreasing" | "stable" | "unknown"
        """
        try:
            buffer = await self.buffer_manager.get_buffer(session_id)

            # Get last 5 predictions
            samples = await buffer.get_last_n(
                n=5,
                user_id=user_id,
                sample_type="prediction"
            )

            if len(samples) < 3:
                return "unknown"

            # Extract workload values
            workloads = [s["data"].get("workload") for s in samples]

            # Compare recent average to current
            avg_recent = sum(workloads[:-1]) / (len(workloads) - 1)

            diff = current_workload - avg_recent

            if diff > 0.05:
                return "increasing"
            elif diff < -0.05:
                return "decreasing"
            else:
                return "stable"

        except Exception as e:
            logger.error(f"Error calculating trend: {e}")
            return "unknown"

    async def _estimate_state_duration(
        self,
        session_id: str,
        user_id: str,
        current_workload: float
    ) -> float:
        """Estimate how long the current state has persisted.

        Args:
            session_id: Session UUID
            user_id: User identifier
            current_workload: Current workload value

        Returns:
            Duration in seconds
        """
        try:
            buffer = await self.buffer_manager.get_buffer(session_id)

            # Get recent predictions
            samples = await buffer.get_last_n(
                n=20,
                user_id=user_id,
                sample_type="prediction"
            )

            if len(samples) < 2:
                return 0.0

            # Determine current state range
            if current_workload < 0.3:
                state_range = (0, 0.3)
            elif current_workload < 0.5:
                state_range = (0.3, 0.5)
            elif current_workload < 0.7:
                state_range = (0.5, 0.7)
            else:
                state_range = (0.7, 1.0)

            # Find when we entered this state
            state_start_time = samples[0]["timestamp"]

            for i, sample in enumerate(samples):
                workload = sample["data"].get("workload")
                if not (state_range[0] <= workload < state_range[1]):
                    # Found transition point
                    if i > 0:
                        state_start_time = samples[i-1]["timestamp"]
                    break

            # Calculate duration
            current_time = samples[-1]["timestamp"]
            duration = (current_time - state_start_time).total_seconds()

            return duration

        except Exception as e:
            logger.error(f"Error estimating state duration: {e}")
            return 0.0
