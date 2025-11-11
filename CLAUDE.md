# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ZanderMCP is a cloud-based MCP (Model Context Protocol) server for real-time BCI (Brain-Computer Interface) classification and cognitive state monitoring. It enables AI assistants to access real-time brain data for adaptive behavior.

**Architecture:** Hybrid edge-cloud system with three main components:

1. **Edge Relay** (local): Reads LSL streams from EEG devices, forwards to cloud via WebSocket
2. **ZanderMCP Server** (cloud): FastMCP server with classification, persistence, and MCP tools
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
# Start database (Docker)
docker-compose up -d

# Stop database
docker-compose down

# Initialize database (run migrations)
uv run alembic upgrade head

# Create a new migration
uv run alembic revision --autogenerate -m "description"

# Rollback migration
uv run alembic downgrade -1
```

### Running Components

```bash
# Run edge relay (local machine with EEG device)
cd edge_relay
python relay.py edge_relay_config.yaml

# Run ZanderMCP server
uv run python server.py

# Run in MCP dev mode (with inspector):
uv run mcp dev server.py
# Then open http://localhost:6274 in your browser
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

### ✅ Phase 2 Complete

- **server.py**: Main FastMCP server with lifespan management (950+ lines)
  - ✅ FastMCP best practices implemented (Context API, error handling, security)
  - ✅ All 14 tools with comprehensive error handling and validation
  - ✅ Example return values in all tool docstrings
  - ✅ Security: `mask_error_details=True` for production
- **ingestion/websocket_server.py**: WebSocket server for edge relay connections (450 lines)
- **ingestion/stream_buffer.py**: In-memory buffer for real-time queries (340 lines)
- **tools/realtime.py**: Real-time cognitive state monitoring (450+ lines)
- **tools/history.py**: Historical database queries (400+ lines)
- **tools/session.py**: Session management and event annotation (270+ lines)
- **fastmcp.json**: Declarative configuration for deployment
- **Docker**: docker-compose.yml for TimescaleDB development database
- **Database**: Alembic migrations initialized and applied

### 📋 Phase 3+ Planned

- **classifiers/ml_client.py**: ML classifier client for Azure-hosted models
- Advanced analytics and pattern detection
- Multi-modal sensor fusion
- Mobile edge relay app
- Model training pipeline for new Azure models
- Production deployment (Kubernetes/Cloud Run)
- Data export tools (CSV/JSON/Parquet)

## MCP Tools (Implemented)

The server exposes 14 MCP tools for AI assistants:

**Real-time Monitoring:**

- `get_current_cognitive_load(user_id?)` → Latest workload with confidence and trend
- `get_cognitive_state(user_id?)` → Interpreted state (focused/moderate/high_load/overloaded) with recommendations
- `get_workload_trend(minutes=5, user_id?)` → Trend analysis over time period
- `get_buffer_status()` → In-memory buffer statistics

**Historical Queries:**

- `query_workload_history(minutes=10, user_id?, session_id?)` → Historical predictions from database
- `get_session_summary(session_id)` → Session statistics and info
- `analyze_cognitive_patterns(start, end, user_id?)` → Pattern analysis with trend detection
- `get_recent_events(limit=10, user_id?, session_id?)` → Recent annotated events

**Session Management:**

- `annotate_event(label, notes?, session_id?, user_id?)` → Mark significant moments
- `get_active_sessions(user_id?)` → List active recording sessions
- `end_session(session_id, notes?)` → Close a session

**Server Info:**

- `list_classifiers()` → Available classification models
- `get_server_stats()` → Connection info, buffer stats, system status

## FastMCP Best Practices (Implemented)

### ✅ Server Architecture

1. **Lifespan Management** (server.py:97-189)
   - Use `@asynccontextmanager` for startup/shutdown logic
   - Initialize long-running services (WebSocket, DB, persistence) in lifespan
   - Yield `None` (not service objects) - services accessed via Context or global
   - Proper cleanup in `finally` block to ensure graceful shutdown
   - **Critical**: Lifespan runs once per server instance, not per client session

2. **Context API Usage** (server.py:200-932)
   - All MCP tools accept `ctx: Context = None` parameter
   - Use `ctx.info()`, `ctx.error()` for logging (visible in MCP inspector)
   - Use `ctx.get_state()` / `ctx.set_state()` for request-scoped data
   - Never access services via global variables directly in tools
   - Use helper function `_get_app_context(ctx)` for safe service retrieval

3. **Error Handling Pattern**
   ```python
   @mcp.tool()
   async def my_tool(param: str, ctx: Context = None) -> dict:
       try:
           app_ctx = _get_app_context(ctx)
           # ... tool logic
           if ctx:
               await ctx.info("Operation successful")
           return result
       except ToolError:
           raise  # Re-raise ToolError as-is
       except ValueError as e:
           raise ToolError(f"Invalid input: {e}")  # Convert to ToolError
       except Exception as e:
           if ctx:
               await ctx.error(f"Internal error: {e}")
           raise ToolError("Operation failed. Please try again.")
   ```

4. **Security Configuration**
   ```python
   mcp = FastMCP(
       name="ZanderMCP",
       lifespan=app_lifespan,
       mask_error_details=True,  # Masks internal errors from clients
   )
   ```

5. **Input Validation**
   - Always validate parameters at tool entry (ranges, required fields, formats)
   - Raise `ToolError` with clear messages for validation failures
   - Example: `if minutes <= 0 or minutes > 60: raise ToolError("minutes must be between 1 and 60")`

6. **Documentation Standards**
   - All tools must have comprehensive docstrings with:
     - Description of functionality
     - `Args:` section with parameter descriptions
     - `Returns:` section with detailed structure
     - `Example:` section with actual JSON return value
   - Example return values help LLMs understand tool output structure

7. **Configuration Management**
   - Use `fastmcp.json` for declarative server configuration
   - Specify dependencies, Python version, transport settings
   - Use environment variable placeholders: `${VARIABLE_NAME}`

## Important Implementation Notes

1. **Always use async/await**: All I/O operations (database, WebSocket, HTTP) must be async to prevent blocking
2. **Channel mapping**: EEG channels must match the names in config.yaml (F3, F4, C3, Cz, C4, P3, P4)
3. **Numpy array shape**: EEG data is always (n_channels, n_samples), not (n_samples, n_channels)
4. **Timestamps**: Use timezone-aware datetime (PostgreSQL TIMESTAMPTZ), always UTC
5. **Error handling**: WebSocket disconnections are expected; use auto-reconnect with exponential backoff
6. **Memory management**: Stream buffers should be bounded (use collections.deque with maxlen)
7. **Tool errors**: Always use `ToolError` from `fastmcp.exceptions`, never generic exceptions
8. **Context logging**: Use `ctx.info()` / `ctx.error()` for debugging, not print() or logger directly

## Key Files Reference

### Core Server
- `server.py`: Main FastMCP server with lifespan, tools, error handling (950+ lines)
- `fastmcp.json`: Declarative server configuration (dependencies, transport, env vars)
- `config.yaml`: Application configuration (WebSocket, DB, signal processing)

### Database Layer
- `database/models.py`: SQLAlchemy ORM models (Session, Prediction, Event, etc.)
- `database/connection.py`: Async database connection and initialization
- `database/persistence.py`: Batched write manager
- `alembic/`: Database migration scripts

### Signal Processing
- `signal_processing/preprocessing.py`: Filtering and PSD computation
- `signal_processing/features.py`: Band power extraction and workload calculation

### Classification
- `classifiers/base.py`: Abstract classifier interface
- `classifiers/signal_processing.py`: Deterministic classifier (no ML)

### MCP Tools
- `tools/realtime.py`: Real-time cognitive state monitoring
- `tools/history.py`: Historical database queries
- `tools/session.py`: Session management and event annotation

### Data Ingestion
- `ingestion/websocket_server.py`: WebSocket server for edge relays
- `ingestion/stream_buffer.py`: In-memory buffer for real-time queries
- `edge_relay/relay.py`: LSL to WebSocket relay application
- `edge_relay/edge_relay_config.yaml`: Edge relay configuration

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

- MCP Specification: <https://modelcontextprotocol.io>
- FastMCP Documentation: <https://github.com/jlowin/fastmcp>
- Lab Streaming Layer: <https://labstreaminglayer.org>
- TimescaleDB Docs: <https://docs.timescale.com>
- Original signal processing: bci-direct project
