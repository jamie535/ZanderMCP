"""Historical MCP tools for querying database records.

These tools provide access to historical predictions, sessions,
and events stored in the PostgreSQL database.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from uuid import UUID
import logging

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import DatabaseManager
from database.models import Prediction, Session, Event, FeatureVector

logger = logging.getLogger(__name__)


class HistoryTools:
    """MCP tools for historical data queries."""

    def __init__(self, db_manager: DatabaseManager):
        """Initialize history tools.

        Args:
            db_manager: Database manager
        """
        self.db = db_manager

    async def query_workload_history(
        self,
        minutes: int = 10,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query workload predictions from database.

        Args:
            minutes: Number of minutes to look back
            user_id: Optional filter by user
            session_id: Optional filter by session

        Returns:
            Dictionary with workload history
        """
        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=minutes)

            async with self.db.session() as session:
                # Build query
                query = select(Prediction).where(
                    Prediction.timestamp >= start_time,
                    Prediction.timestamp <= end_time
                )

                if user_id:
                    query = query.where(Prediction.user_id == user_id)

                if session_id:
                    query = query.where(Prediction.session_id == UUID(session_id))

                query = query.order_by(Prediction.timestamp.asc())

                result = await session.execute(query)
                predictions = result.scalars().all()

                if not predictions:
                    return {
                        "error": "No predictions found in time range",
                        "samples": [],
                        "statistics": {},
                    }

                # Extract data
                samples = []
                workload_values = []

                for pred in predictions:
                    samples.append({
                        "timestamp": pred.timestamp.isoformat(),
                        "workload": pred.workload,
                        "confidence": pred.confidence,
                        "attention": pred.attention,
                        "classifier": pred.classifier_name,
                        "session_id": str(pred.session_id),
                    })
                    if pred.workload is not None:
                        workload_values.append(pred.workload)

                # Calculate statistics
                statistics = {}
                if workload_values:
                    statistics = {
                        "count": len(workload_values),
                        "mean": sum(workload_values) / len(workload_values),
                        "min": min(workload_values),
                        "max": max(workload_values),
                        "median": sorted(workload_values)[len(workload_values) // 2],
                    }

                return {
                    "time_range_minutes": minutes,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "samples": samples,
                    "statistics": statistics,
                }

        except Exception as e:
            logger.error(f"Error querying workload history: {e}", exc_info=True)
            return {
                "error": str(e),
                "samples": [],
                "statistics": {},
            }

    async def get_session_summary(
        self,
        session_id: str,
    ) -> Dict[str, Any]:
        """Get summary statistics for a session.

        Args:
            session_id: Session UUID

        Returns:
            Dictionary with session summary
        """
        try:
            session_uuid = UUID(session_id)

            async with self.db.session() as session:
                # Get session info
                session_query = select(Session).where(Session.session_id == session_uuid)
                session_result = await session.execute(session_query)
                session_record = session_result.scalar_one_or_none()

                if not session_record:
                    return {
                        "error": f"Session {session_id} not found",
                        "session_info": {},
                        "statistics": {},
                    }

                # Get prediction statistics
                pred_stats_query = select(
                    func.count(Prediction.id).label("count"),
                    func.avg(Prediction.workload).label("avg_workload"),
                    func.min(Prediction.workload).label("min_workload"),
                    func.max(Prediction.workload).label("max_workload"),
                    func.min(Prediction.timestamp).label("first_prediction"),
                    func.max(Prediction.timestamp).label("last_prediction"),
                ).where(Prediction.session_id == session_uuid)

                stats_result = await session.execute(pred_stats_query)
                stats = stats_result.one()

                # Get event count
                event_count_query = select(func.count(Event.event_id)).where(
                    Event.session_id == session_uuid
                )
                event_result = await session.execute(event_count_query)
                event_count = event_result.scalar()

                # Calculate duration
                duration = None
                if session_record.end_time:
                    duration = (session_record.end_time - session_record.start_time).total_seconds()
                elif stats.first_prediction:
                    duration = (datetime.utcnow() - session_record.start_time).total_seconds()

                return {
                    "session_info": {
                        "session_id": str(session_record.session_id),
                        "user_id": session_record.user_id,
                        "start_time": session_record.start_time.isoformat(),
                        "end_time": session_record.end_time.isoformat() if session_record.end_time else None,
                        "duration_seconds": duration,
                        "notes": session_record.notes,
                        "is_active": session_record.end_time is None,
                    },
                    "statistics": {
                        "total_predictions": stats.count,
                        "avg_workload": float(stats.avg_workload) if stats.avg_workload else None,
                        "min_workload": float(stats.min_workload) if stats.min_workload else None,
                        "max_workload": float(stats.max_workload) if stats.max_workload else None,
                        "first_prediction": stats.first_prediction.isoformat() if stats.first_prediction else None,
                        "last_prediction": stats.last_prediction.isoformat() if stats.last_prediction else None,
                        "total_events": event_count,
                    },
                }

        except Exception as e:
            logger.error(f"Error getting session summary: {e}", exc_info=True)
            return {
                "error": str(e),
                "session_info": {},
                "statistics": {},
            }

    async def analyze_cognitive_patterns(
        self,
        start: str,
        end: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze cognitive patterns over a time range.

        Args:
            start: Start time (ISO format)
            end: End time (ISO format)
            user_id: Optional filter by user

        Returns:
            Dictionary with pattern analysis
        """
        try:
            start_time = datetime.fromisoformat(start)
            end_time = datetime.fromisoformat(end)

            async with self.db.session() as session:
                # Build query
                query = select(Prediction).where(
                    Prediction.timestamp >= start_time,
                    Prediction.timestamp <= end_time
                )

                if user_id:
                    query = query.where(Prediction.user_id == user_id)

                query = query.order_by(Prediction.timestamp.asc())

                result = await session.execute(query)
                predictions = result.scalars().all()

                if not predictions:
                    return {
                        "error": "No predictions in time range",
                        "patterns": {},
                    }

                # Extract workload values
                workload_values = [p.workload for p in predictions if p.workload is not None]

                if not workload_values:
                    return {
                        "error": "No workload data available",
                        "patterns": {},
                    }

                # Analyze patterns
                patterns = await self._analyze_patterns(workload_values, predictions)

                return {
                    "time_range": {
                        "start": start_time.isoformat(),
                        "end": end_time.isoformat(),
                        "duration_hours": (end_time - start_time).total_seconds() / 3600,
                    },
                    "sample_count": len(predictions),
                    "patterns": patterns,
                }

        except Exception as e:
            logger.error(f"Error analyzing patterns: {e}", exc_info=True)
            return {
                "error": str(e),
                "patterns": {},
            }

    async def get_recent_events(
        self,
        limit: int = 10,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get recent annotated events.

        Args:
            limit: Maximum number of events to return
            user_id: Optional filter by user (via session)
            session_id: Optional filter by session

        Returns:
            Dictionary with recent events
        """
        try:
            async with self.db.session() as db_session:
                query = select(Event).order_by(desc(Event.timestamp)).limit(limit)

                if session_id:
                    query = query.where(Event.session_id == UUID(session_id))

                result = await db_session.execute(query)
                events = result.scalars().all()

                events_list = []
                for event in events:
                    events_list.append({
                        "event_id": str(event.event_id),
                        "session_id": str(event.session_id),
                        "timestamp": event.timestamp.isoformat(),
                        "label": event.label,
                        "notes": event.notes,
                        "metadata": event.event_metadata,
                    })

                return {
                    "events": events_list,
                    "count": len(events_list),
                }

        except Exception as e:
            logger.error(f"Error getting recent events: {e}", exc_info=True)
            return {
                "error": str(e),
                "events": [],
                "count": 0,
            }

    async def get_user_sessions(
        self,
        user_id: str,
        limit: int = 10,
        include_active: bool = True,
    ) -> Dict[str, Any]:
        """Get recent sessions for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of sessions
            include_active: Include sessions without end_time

        Returns:
            Dictionary with sessions list
        """
        try:
            async with self.db.session() as session:
                query = select(Session).where(Session.user_id == user_id)

                if not include_active:
                    query = query.where(Session.end_time.is_not(None))

                query = query.order_by(desc(Session.start_time)).limit(limit)

                result = await session.execute(query)
                sessions = result.scalars().all()

                sessions_list = []
                for sess in sessions:
                    duration = None
                    if sess.end_time:
                        duration = (sess.end_time - sess.start_time).total_seconds()
                    elif include_active:
                        duration = (datetime.utcnow() - sess.start_time).total_seconds()

                    sessions_list.append({
                        "session_id": str(sess.session_id),
                        "start_time": sess.start_time.isoformat(),
                        "end_time": sess.end_time.isoformat() if sess.end_time else None,
                        "duration_seconds": duration,
                        "total_samples": sess.total_samples,
                        "notes": sess.notes,
                        "is_active": sess.end_time is None,
                    })

                return {
                    "user_id": user_id,
                    "sessions": sessions_list,
                    "count": len(sessions_list),
                }

        except Exception as e:
            logger.error(f"Error getting user sessions: {e}", exc_info=True)
            return {
                "error": str(e),
                "sessions": [],
                "count": 0,
            }

    async def _analyze_patterns(
        self,
        workload_values: List[float],
        predictions: List[Prediction],
    ) -> Dict[str, Any]:
        """Analyze patterns in workload data.

        Args:
            workload_values: List of workload values
            predictions: List of prediction records

        Returns:
            Dictionary with pattern analysis
        """
        # Calculate basic statistics
        mean_workload = sum(workload_values) / len(workload_values)
        min_workload = min(workload_values)
        max_workload = max(workload_values)

        # Detect periods of high/low load
        high_load_periods = []
        low_load_periods = []

        high_load_threshold = 0.7
        low_load_threshold = 0.3

        current_high_start = None
        current_low_start = None

        for pred in predictions:
            if pred.workload is None:
                continue

            # High load detection
            if pred.workload >= high_load_threshold:
                if current_high_start is None:
                    current_high_start = pred.timestamp
            else:
                if current_high_start is not None:
                    high_load_periods.append({
                        "start": current_high_start.isoformat(),
                        "end": pred.timestamp.isoformat(),
                        "duration_seconds": (pred.timestamp - current_high_start).total_seconds(),
                    })
                    current_high_start = None

            # Low load detection
            if pred.workload <= low_load_threshold:
                if current_low_start is None:
                    current_low_start = pred.timestamp
            else:
                if current_low_start is not None:
                    low_load_periods.append({
                        "start": current_low_start.isoformat(),
                        "end": pred.timestamp.isoformat(),
                        "duration_seconds": (pred.timestamp - current_low_start).total_seconds(),
                    })
                    current_low_start = None

        # Calculate trend
        if len(workload_values) > 1:
            first_quarter = workload_values[:len(workload_values)//4]
            last_quarter = workload_values[-len(workload_values)//4:]

            if first_quarter and last_quarter:
                first_avg = sum(first_quarter) / len(first_quarter)
                last_avg = sum(last_quarter) / len(last_quarter)
                trend_direction = "increasing" if last_avg > first_avg else "decreasing"
                trend_magnitude = abs(last_avg - first_avg)
            else:
                trend_direction = "unknown"
                trend_magnitude = 0.0
        else:
            trend_direction = "insufficient_data"
            trend_magnitude = 0.0

        return {
            "overall": {
                "mean_workload": mean_workload,
                "min_workload": min_workload,
                "max_workload": max_workload,
                "workload_range": max_workload - min_workload,
            },
            "trend": {
                "direction": trend_direction,
                "magnitude": trend_magnitude,
            },
            "high_load_periods": {
                "count": len(high_load_periods),
                "periods": high_load_periods[:5],  # Return up to 5 periods
            },
            "low_load_periods": {
                "count": len(low_load_periods),
                "periods": low_load_periods[:5],
            },
        }
