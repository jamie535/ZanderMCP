# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ZanderMCP is a cloud-based MCP (Model Context Protocol) server for real-time BCI (Brain-Computer Interface) classification and cognitive state monitoring. It enables AI assistants to access real-time brain data for adaptive behavior.

**Architecture:** Hybrid edge-cloud system with three main components:
1. **Edge Relay** (local): Reads LSL streams from EEG devices, forwards to cloud via WebSocket
2. **ZanderMCP Server** (cloud): FastMCP server with classification, persistence, and MCP tools (TODO)
3. **Database**: PostgreSQL + TimescaleDB for time-series data storage

## Development Commands

### Installation
```bash
# Install dependencies
pip install -e .
# or with uv (preferred):
uv pip install -e .
```

### Database
```bash
# Initialize database (run migrations)
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"

# Rollback migration
alembic downgrade -1
```

### Running Components
```bash
# Run edge relay (local machine with EEG device)
cd edge_relay
python relay.py edge_relay_config.yaml

# Run ZanderMCP server (TODO - not implemented yet)
python server.py
# or in MCP dev mode:
mcp dev server.py
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_signal_processing.py
```

### Code Quality
```bash
# Format code
black .

# Lint code
ruff check --fix .
```

## Architecture

### Data Flow: EEG Device → AI Assistant

```
EEG Device → LSL Stream → Edge Relay → WebSocket (compressed)
  → ZanderMCP Server → Classifier → Database
  → MCP Tools → AI Assistant
```

**Latency budget:** Target <200ms end-to-end (currently achieved)

### Key Design Patterns

1. **Hybrid Edge-Cloud Processing**
   - Edge relay does optional preprocessing to reduce bandwidth (8KB/s → 1-2KB/s)
   - Cloud handles classification and persistence
   - In-memory buffer in cloud for low-latency real-time queries

2. **Classifier Plugin System**
   - All classifiers inherit from `BaseClassifier` (classifiers/base.py)
   - Must implement `predict()` and `get_metadata()`
   - Currently implemented: `SignalProcessingClassifier` (deterministic, no ML)
   - ML classifiers: Call Azure-hosted models via HTTP REST API (classifiers/ml_client.py - TODO)

3. **Batched Database Writes**
   - Uses `PersistenceManager` (database/persistence.py) to batch writes
   - Default: 50 samples or 5 seconds, whichever comes first
   - Prevents blocking classification pipeline
   - Trade-off: Up to 5s of data could be lost on crash

4. **TimescaleDB Hypertables**
   - `predictions` and `stream_samples` tables use automatic time-based partitioning
   - Enables efficient time-range queries
   - Supports data retention policies and compression

### Signal Processing Pipeline

Located in `signal_processing/` (ported from bci-direct project):

1. **Bandpass filter** (1-40 Hz, 4th order Butterworth) - `preprocessing.py:filter_eeg_data()`
2. **Power Spectral Density** (4s window, 2s overlap, Hanning) - `preprocessing.py:compute_psd()`
3. **Band power extraction** (delta, theta, alpha, beta, gamma) - `features.py:extract_band_powers()`
4. **Workload calculation** (weighted combination) - `features.py:calculate_workload()`

Weights for workload (from config.yaml):
- Frontal theta: 0.10
- Theta/beta ratio: 0.45
- Parietal alpha: 0.45
- Theta/alpha ratio: 2.0

### Database Schema

**Core Tables:**
- `sessions`: BCI recording sessions (user_id, start_time, device_info)
- `predictions`: Classification predictions (hypertable, indexed by timestamp + session_id + user_id)
- `events`: User-annotated research events
- `feature_vectors`: Extracted EEG features (optional, for ML training)
- `stream_samples`: Raw LSL stream data (optional, high volume)
- `model_predictions`: Model performance tracking

**Important indexes:**
- `idx_predictions_session_time`: (session_id, timestamp DESC) - for session queries
- `idx_predictions_user_time`: (user_id, timestamp DESC) - for user history
- `idx_predictions_classifier`: (classifier_name, timestamp DESC) - for classifier comparison

## Configuration

### Main Server Config (config.yaml)
- WebSocket server settings (host, port, max_connections)
- Signal processing parameters (chunk_length, sampling_rate, filter cutoffs)
- Required EEG channels (frontal: F3/F4, central: C3/Cz/C4, parietal: P3/P4)
- Classifier selection and weights
- Database persistence options (batch_size, flush_interval)
- Session management (timeout, auto_start)

### Edge Relay Config (edge_relay/edge_relay_config.yaml)
- LSL stream name (must match EEG device)
- Cloud endpoint (WebSocket URL)
- API key and user_id for authentication
- Preprocessing options (enable/disable feature extraction)
- Buffer size and compression settings

### Environment Variables (.env)
- `POSTGRES_URL`: Database connection string (required)
- `WEBSOCKET_HOST` and `WEBSOCKET_PORT`: WebSocket server config
- `AZURE_ML_ENDPOINT`: Azure-hosted model REST API endpoint (optional)
- `AZURE_ML_API_KEY`: Azure ML authentication key (optional)
- `REDIS_URL`: Session caching (optional)
- `EDGE_RELAY_API_KEY`: Authentication for edge relays

## Implementation Status

### ✅ Phase 1 Complete
- Database layer (SQLAlchemy async, connection pooling, batched writes)
- Signal processing (filtering, PSD, band powers, deterministic workload)
- Classifiers (base interface, signal processing classifier)
- Edge relay (LSL reading, WebSocket forwarding, auto-reconnect, buffering)
- Alembic migrations setup

### 🚧 Phase 2 In Progress (TODO)
- **server.py**: Main FastMCP server (not implemented)
- **ingestion/websocket_server.py**: WebSocket server for edge relay connections
- **ingestion/stream_buffer.py**: In-memory buffer for real-time queries
- **tools/**: MCP tools for AI assistants (realtime.py, history.py, session.py)
- **classifiers/ml_client.py**: ML classifier client for Azure-hosted models

### 📋 Phase 3+ Planned
- Docker deployment (Dockerfile, docker-compose.yml)
- Advanced analytics and pattern detection
- Multi-modal sensor fusion
- Mobile edge relay app
- Model training pipeline for new Azure models

## MCP Tools (Planned API)

When implementing tools/ directory, expose these MCP tools:

**Real-time:**
- `get_current_cognitive_load()` → {workload, confidence, timestamp, trend}
- `get_cognitive_state()` → {state, intensity, duration, recommendations}

**Classifiers:**
- `list_classifiers()` → list of available classifiers
- `switch_classifier(name)` → change active classifier
- `get_classifier_info()` → current classifier metadata

**Historical:**
- `query_workload_history(minutes)` → recent trends
- `get_session_summary()` → session statistics
- `analyze_cognitive_patterns(start, end)` → pattern analysis

**Research:**
- `annotate_event(timestamp, label, notes)` → mark events
- `export_session_data(session_id, format)` → CSV/JSON/Parquet export
- `get_raw_features(timestamp)` → raw feature vector

## Important Implementation Notes

1. **Always use async/await**: All I/O operations (database, WebSocket, HTTP) must be async to prevent blocking
2. **Channel mapping**: EEG channels must match the names in config.yaml (F3, F4, C3, Cz, C4, P3, P4)
3. **Numpy array shape**: EEG data is always (n_channels, n_samples), not (n_samples, n_channels)
4. **Timestamps**: Use timezone-aware datetime (PostgreSQL TIMESTAMPTZ), always UTC
5. **Error handling**: WebSocket disconnections are expected; use auto-reconnect with exponential backoff
6. **Memory management**: Stream buffers should be bounded (use collections.deque with maxlen)

## Key Files Reference

- `database/models.py`: SQLAlchemy ORM models (Session, Prediction, Event, etc.)
- `database/connection.py`: Async database connection and initialization
- `database/persistence.py`: Batched write manager
- `signal_processing/preprocessing.py`: Filtering and PSD computation
- `signal_processing/features.py`: Band power extraction and workload calculation
- `classifiers/base.py`: Abstract classifier interface
- `classifiers/signal_processing.py`: Deterministic classifier (no ML)
- `edge_relay/relay.py`: LSL to WebSocket relay application
- `config.yaml`: Main server configuration
- `alembic/`: Database migration scripts

## Adding a New Classifier

### Option 1: Azure-Hosted ML Model
1. Create new file in `classifiers/` (e.g., `azure_workload_classifier.py`)
2. Inherit from `BaseClassifier` (classifiers/base.py)
3. Implement `async def predict(eeg_data: np.ndarray, **kwargs)`:
   - Extract features using signal_processing functions
   - Call Azure ML endpoint via HTTP (aiohttp)
   - Return prediction with confidence
4. Implement `def get_metadata()` with Azure model info
5. Add Azure endpoint URL to `config.yaml` under `classifiers.azure_models`
6. Add classifier name to `config.yaml` under `classifiers.available`
7. Register in classifier manager (server.py, when implemented)

### Option 2: Local Classifier
1. Create new file in `classifiers/` (e.g., `my_classifier.py`)
2. Inherit from `BaseClassifier` (classifiers/base.py)
3. Implement `async def predict(eeg_data: np.ndarray, **kwargs) -> Dict[str, Any]`
4. Implement `def get_metadata() -> Dict[str, Any]`
5. Add to `config.yaml` under `classifiers.available`
6. Register in classifier manager (server.py, when implemented)

## Debugging Tips

- **LSL connection issues**: Use `pylsl.resolve_streams()` to list available streams
- **Database connection**: Check `POSTGRES_URL` format and TimescaleDB extension is enabled
- **WebSocket issues**: Test with `websocat` or `wscat` tools before using edge relay
- **Signal processing**: Visualize PSD output to verify filtering is working
- **Performance**: Check database batch_size and flush_interval in config.yaml

## References

- MCP Specification: https://modelcontextprotocol.io
- FastMCP Documentation: https://github.com/jlowin/fastmcp
- Lab Streaming Layer: https://labstreaminglayer.org
- TimescaleDB Docs: https://docs.timescale.com
- Original signal processing: bci-direct project
