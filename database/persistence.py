"""Database persistence layer with batched async writes."""

import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID
from collections import deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Session, Prediction, Event, FeatureVector, StreamSample
from .connection import DatabaseManager


class PersistenceManager:
    """Manages batched writes to database for performance."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        batch_size: int = 50,
        flush_interval: float = 5.0,
    ):
        """Initialize persistence manager.

        Args:
            db_manager: Database manager instance
            batch_size: Number of records to batch before writing
            flush_interval: Time in seconds between automatic flushes
        """
        self.db = db_manager
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        # Buffers for each table
        self.prediction_buffer: deque = deque()
        self.feature_buffer: deque = deque()
        self.stream_buffer: deque = deque()

        # Background task for periodic flushing
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the background flush task."""
        if self._running:
            return

        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def stop(self):
        """Stop the background flush task and flush remaining data."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush
        await self.flush_all()

    async def _periodic_flush(self):
        """Periodically flush buffers to database."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self.flush_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in periodic flush: {e}")

    async def add_prediction(
        self,
        timestamp: datetime,
        session_id: UUID,
        user_id: str,
        classifier_name: str,
        workload: Optional[float] = None,
        attention: Optional[float] = None,
        confidence: Optional[float] = None,
        features: Optional[Dict[str, Any]] = None,
        processing_time_ms: Optional[float] = None,
        classifier_version: Optional[str] = None,
    ):
        """Add a prediction to the buffer.

        Will auto-flush when batch_size is reached.
        """
        prediction = {
            "timestamp": timestamp,
            "session_id": session_id,
            "user_id": user_id,
            "classifier_name": classifier_name,
            "workload": workload,
            "attention": attention,
            "confidence": confidence,
            "features": features,
            "processing_time_ms": processing_time_ms,
            "classifier_version": classifier_version,
        }
        self.prediction_buffer.append(prediction)

        if len(self.prediction_buffer) >= self.batch_size:
            await self.flush_predictions()

    async def add_feature_vector(
        self,
        timestamp: datetime,
        session_id: UUID,
        frontal_theta: Optional[float] = None,
        frontal_beta: Optional[float] = None,
        parietal_alpha: Optional[float] = None,
        theta_beta_ratio: Optional[float] = None,
        theta_alpha_ratio: Optional[float] = None,
        all_features: Optional[Dict[str, Any]] = None,
    ):
        """Add a feature vector to the buffer."""
        feature = {
            "timestamp": timestamp,
            "session_id": session_id,
            "frontal_theta": frontal_theta,
            "frontal_beta": frontal_beta,
            "parietal_alpha": parietal_alpha,
            "theta_beta_ratio": theta_beta_ratio,
            "theta_alpha_ratio": theta_alpha_ratio,
            "all_features": all_features,
        }
        self.feature_buffer.append(feature)

        if len(self.feature_buffer) >= self.batch_size:
            await self.flush_features()

    async def add_stream_sample(
        self,
        timestamp: datetime,
        stream_name: str,
        data: Dict[str, Any],
        session_id: Optional[UUID] = None,
        stream_type: Optional[str] = None,
    ):
        """Add a stream sample to the buffer."""
        sample = {
            "timestamp": timestamp,
            "session_id": session_id,
            "stream_name": stream_name,
            "stream_type": stream_type,
            "data": data,
        }
        self.stream_buffer.append(sample)

        if len(self.stream_buffer) >= self.batch_size:
            await self.flush_stream_samples()

    async def flush_predictions(self):
        """Flush prediction buffer to database."""
        if not self.prediction_buffer:
            return

        records = list(self.prediction_buffer)
        self.prediction_buffer.clear()

        try:
            async with self.db.session() as session:
                session.add_all([Prediction(**record) for record in records])
            print(f"Flushed {len(records)} predictions to database")
        except Exception as e:
            print(f"Error flushing predictions: {e}")
            # Re-add to buffer for retry
            self.prediction_buffer.extend(records)

    async def flush_features(self):
        """Flush feature buffer to database."""
        if not self.feature_buffer:
            return

        records = list(self.feature_buffer)
        self.feature_buffer.clear()

        try:
            async with self.db.session() as session:
                session.add_all([FeatureVector(**record) for record in records])
            print(f"Flushed {len(records)} feature vectors to database")
        except Exception as e:
            print(f"Error flushing features: {e}")
            self.feature_buffer.extend(records)

    async def flush_stream_samples(self):
        """Flush stream sample buffer to database."""
        if not self.stream_buffer:
            return

        records = list(self.stream_buffer)
        self.stream_buffer.clear()

        try:
            async with self.db.session() as session:
                session.add_all([StreamSample(**record) for record in records])
            print(f"Flushed {len(records)} stream samples to database")
        except Exception as e:
            print(f"Error flushing stream samples: {e}")
            self.stream_buffer.extend(records)

    async def flush_all(self):
        """Flush all buffers to database."""
        await asyncio.gather(
            self.flush_predictions(),
            self.flush_features(),
            self.flush_stream_samples(),
            return_exceptions=True,
        )

    # Direct write methods (not buffered, for important data)

    async def create_session(
        self,
        user_id: str,
        device_info: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> Session:
        """Create a new session (writes immediately)."""
        session_record = Session(
            user_id=user_id,
            device_info=device_info,
            notes=notes,
        )

        async with self.db.session() as session:
            session.add(session_record)
            await session.flush()
            await session.refresh(session_record)

        return session_record

    async def end_session(self, session_id: UUID, total_samples: int):
        """End a session (writes immediately)."""
        async with self.db.session() as session:
            result = await session.execute(
                select(Session).where(Session.session_id == session_id)
            )
            session_record = result.scalar_one_or_none()

            if session_record:
                session_record.end_time = datetime.utcnow()
                session_record.total_samples = total_samples

    async def add_event(
        self,
        session_id: UUID,
        timestamp: datetime,
        label: str,
        notes: Optional[str] = None,
        event_metadata: Optional[Dict[str, Any]] = None,
    ) -> Event:
        """Add an event annotation (writes immediately)."""
        event = Event(
            session_id=session_id,
            timestamp=timestamp,
            label=label,
            notes=notes,
            event_metadata=event_metadata,
        )

        async with self.db.session() as session:
            session.add(event)
            await session.flush()
            await session.refresh(event)

        return event
