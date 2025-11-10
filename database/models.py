"""SQLAlchemy models for ZanderMCP database schema."""

from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    ARRAY,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Session(Base):
    """Represents a BCI recording session."""

    __tablename__ = "sessions"

    session_id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(String(100), nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    device_info = Column(JSONB, nullable=True)
    total_samples = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
    active_classifiers = Column(ARRAY(String), nullable=True)
    active_streams = Column(ARRAY(String), nullable=True)

    def __repr__(self):
        return f"<Session {self.session_id} user={self.user_id}>"


class Prediction(Base):
    """Stores real-time classification predictions.

    This is a TimescaleDB hypertable for time-series optimization.
    """

    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    session_id = Column(
        PGUUID(as_uuid=True), ForeignKey("sessions.session_id"), nullable=False, index=True
    )
    user_id = Column(String(100), nullable=False, index=True)
    classifier_name = Column(String(100), nullable=False)

    # Prediction outputs
    workload = Column(Float, nullable=True)
    attention = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)

    # Metadata
    features = Column(JSONB, nullable=True)
    processing_time_ms = Column(Float, nullable=True)
    classifier_version = Column(String(50), nullable=True)

    def __repr__(self):
        return f"<Prediction {self.timestamp} workload={self.workload}>"


class Event(Base):
    """User-annotated events during a session (for research)."""

    __tablename__ = "events"

    event_id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(
        PGUUID(as_uuid=True), ForeignKey("sessions.session_id"), nullable=False
    )
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    label = Column(String(100), nullable=False)
    notes = Column(Text, nullable=True)
    event_metadata = Column(JSONB, nullable=True)

    def __repr__(self):
        return f"<Event {self.label} at {self.timestamp}>"


class FeatureVector(Base):
    """Stores extracted features for ML training or debugging.

    Optional - only populated if config.database.persist.features is true.
    """

    __tablename__ = "feature_vectors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    session_id = Column(
        PGUUID(as_uuid=True), ForeignKey("sessions.session_id"), nullable=False
    )

    # Individual features (for easy querying)
    frontal_theta = Column(Float, nullable=True)
    frontal_beta = Column(Float, nullable=True)
    parietal_alpha = Column(Float, nullable=True)
    theta_beta_ratio = Column(Float, nullable=True)
    theta_alpha_ratio = Column(Float, nullable=True)

    # All features as JSON (flexible)
    all_features = Column(JSONB, nullable=True)

    def __repr__(self):
        return f"<FeatureVector {self.timestamp}>"


class ModelPrediction(Base):
    """Tracks model performance and predictions for monitoring."""

    __tablename__ = "model_predictions"

    prediction_id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=func.now(), index=True)
    model_name = Column(String(100), nullable=False, index=True)
    model_version = Column(String(50), nullable=True)

    input_features = Column(JSONB, nullable=False)
    output = Column(JSONB, nullable=False)
    latency_ms = Column(Float, nullable=True)

    # For A/B testing or validation
    ground_truth = Column(Float, nullable=True)
    error = Column(Float, nullable=True)

    def __repr__(self):
        return f"<ModelPrediction {self.model_name} at {self.timestamp}>"


class StreamSample(Base):
    """Stores raw samples from any LSL stream (optional, high volume).

    This is a TimescaleDB hypertable for time-series optimization.
    Only used if config.database.persist.raw_samples is true.
    """

    __tablename__ = "stream_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    session_id = Column(
        PGUUID(as_uuid=True), ForeignKey("sessions.session_id"), nullable=True
    )
    stream_name = Column(String(100), nullable=False, index=True)
    stream_type = Column(String(50), nullable=True)

    # Raw data stored as JSON for flexibility
    data = Column(JSONB, nullable=False)

    def __repr__(self):
        return f"<StreamSample {self.stream_name} at {self.timestamp}>"
