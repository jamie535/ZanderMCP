# ZanderMCP

Cloud-based MCP (Model Context Protocol) server for real-time BCI classification and cognitive state monitoring.

## Overview

ZanderMCP enables AI assistants (Claude, Continue, etc.) to access real-time brain-computer interface (BCI) data for adaptive behavior and research applications. The system consists of:

- **Edge Relay**: Lightweight local service that forwards LSL streams to the cloud
- **ZanderMCP Server**: Cloud-hosted FastMCP server with classification and persistence
- **Model Service**: Separate service for hosting ML classifiers (optional)
- **Database**: PostgreSQL + TimescaleDB for time-series data storage

## Architecture

```
┌─────────────────────────────┐
│ Local (with EEG device)      │
│  EEG Device → LSL Stream    │
│        ↓                     │
│  Edge Relay (relay.py)      │
│   - Reads LSL               │
│   - Preprocesses (optional) │
│   - Sends to cloud          │
└─────────────────────────────┘
          ↓ WebSocket
┌─────────────────────────────┐
│ Cloud Deployment             │
│  ZanderMCP Server           │
│   - WebSocket ingestion     │
│   - Classification          │
│   - MCP tools for AI        │
│   - Database persistence    │
└─────────────────────────────┘
          ↑ MCP Protocol
┌─────────────────────────────┐
│ AI Clients                   │
│  Claude Code, Claude Desktop│
│  Continue, Custom MCP apps  │
└─────────────────────────────┘
```

## Features

### ✅ Implemented (Phase 1)

- **Database Layer**
  - PostgreSQL with TimescaleDB for time-series optimization
  - SQLAlchemy async ORM with connection pooling
  - Batched writes for performance
  - Alembic migrations for schema management

- **Signal Processing**
  - Ported from bci-direct project
  - Bandpass filtering (1-40 Hz, 4th order Butterworth)
  - Power spectral density computation
  - Band power extraction (delta, theta, alpha, beta, gamma)
  - Deterministic workload calculation

- **Classifiers**
  - Base classifier interface
  - Signal processing classifier (deterministic, no ML required)
  - ML classifier client for Azure-hosted models (planned)

- **Edge Relay**
  - LSL stream reading
  - WebSocket connection to cloud
  - Auto-reconnection with buffering
  - Optional local preprocessing
  - Compression support (msgpack/json)

### 🚧 In Progress (Phase 2)

- **ZanderMCP Server** (server.py)
  - FastMCP implementation
  - WebSocket server for edge relay
  - MCP tools for cognitive load queries
  - Session management
  - Real-time classification pipeline

- **ML Classifier Integration**
  - HTTP client for Azure-hosted models
  - Feature extraction and preprocessing
  - Fallback to signal processing classifier

- **Deployment**
  - Docker containers
  - docker-compose for local dev
  - Cloud deployment configs

## Project Structure

```
ZanderMCP/
├── server.py                      # Main FastMCP server (TODO)
├── edge_relay/
│   ├── relay.py                   # Edge relay application ✓
│   └── edge_relay_config.yaml     # Edge relay config ✓
├── ingestion/
│   ├── websocket_server.py        # WebSocket ingestion (TODO)
│   └── stream_buffer.py           # Real-time buffer (TODO)
├── classifiers/
│   ├── base.py                    # Base classifier ✓
│   ├── signal_processing.py       # Signal processing classifier ✓
│   └── azure_ml.py                # Azure ML classifier client (TODO)
├── signal_processing/
│   ├── preprocessing.py           # Filtering, PSD ✓
│   └── features.py                # Feature extraction ✓
├── database/
│   ├── models.py                  # SQLAlchemy models ✓
│   ├── connection.py              # DB connection ✓
│   └── persistence.py             # Batched writes ✓
├── tools/
│   ├── realtime.py                # Real-time MCP tools (TODO)
│   ├── history.py                 # Historical query tools (TODO)
│   └── session.py                 # Session management (TODO)
├── alembic/                        # Database migrations ✓
├── pyproject.toml                  # Dependencies ✓
├── config.yaml                     # Server configuration ✓
├── .env.example                    # Environment variables template ✓
└── README.md                       # This file ✓
```

## Installation

### Prerequisites

- Python 3.12+
- PostgreSQL with TimescaleDB extension
- For edge relay: LSL-compatible EEG device

### Setup

1. **Clone and install dependencies:**

```bash
cd ZanderMCP
pip install -e .
# or with uv:
uv pip install -e .
```

2. **Configure environment:**

```bash
cp .env.example .env
# Edit .env with your database URL and API keys
```

3. **Initialize database:**

```bash
# Create database schema and TimescaleDB hypertables
alembic upgrade head
# or run initialization script:
python -c "import asyncio; from database.connection import init_database; asyncio.run(init_database())"
```

4. **Configure edge relay:**

Edit `edge_relay/edge_relay_config.yaml`:
- Set `lsl.stream_name` to your EEG device's LSL stream name
- Set `cloud.endpoint` to your ZanderMCP server URL
- Set `cloud.api_key` and `cloud.user_id`

## Usage

### Running Edge Relay (Local Machine)

```bash
cd edge_relay
python relay.py edge_relay_config.yaml
```

The edge relay will:
1. Connect to your local LSL stream
2. Connect to the cloud ZanderMCP server
3. Forward EEG data continuously
4. Auto-reconnect if connection is lost
5. Buffer data during disconnections

### Running ZanderMCP Server (Cloud)

```bash
# TODO: Once server.py is implemented
python server.py
# or with MCP dev mode:
mcp dev server.py
```

### Using with AI Clients

**Claude Code / Claude Desktop:**

Add to your MCP configuration:

```json
{
  "mcpServers": {
    "zandermcp": {
      "command": "python",
      "args": ["/path/to/ZanderMCP/server.py"]
    }
  }
}
```

**Example AI Assistant Usage:**

```
User: "How is my cognitive load right now?"

AI calls: get_current_cognitive_load()
Response: { workload: 0.73, confidence: 1.0, trend: "increasing" }

AI: "Your cognitive load is moderately high (0.73) and increasing.
     You might want to take a break soon."
```

## MCP Tools (Planned)

### Real-time Tools
- `get_current_cognitive_load()` - Latest workload prediction
- `get_cognitive_state()` - Current state with context
- `check_attention_level()` - Attention score

### Classifier Tools
- `list_classifiers()` - Available classifiers
- `switch_classifier(name)` - Change active classifier
- `get_classifier_info()` - Current classifier metadata

### Historical Tools
- `query_workload_history(minutes)` - Recent trends
- `get_session_summary()` - Session statistics
- `analyze_cognitive_patterns(start, end)` - Pattern analysis

### Research Tools
- `export_session_data(format)` - Download data
- `get_raw_features(timestamp)` - Raw features for debugging
- `annotate_event(timestamp, label, notes)` - Mark events

## Database Schema

### Tables

- **sessions**: BCI recording sessions
- **predictions**: Classification predictions (hypertable)
- **events**: User-annotated events
- **feature_vectors**: Extracted EEG features (optional)
- **stream_samples**: Raw stream data (optional, high volume)
- **model_predictions**: Model performance tracking

### Time-Series Optimization

Tables `predictions` and `stream_samples` use TimescaleDB hypertables for:
- Automatic partitioning by time
- Efficient time-range queries
- Data retention policies
- Continuous aggregates

## Configuration

### server.py Configuration (config.yaml)

See `config.yaml` for full configuration options:
- WebSocket server settings
- Signal processing parameters
- Classifier configuration
- Database persistence options
- Session management

### Edge Relay Configuration

See `edge_relay/edge_relay_config.yaml`:
- LSL stream name
- Cloud endpoint and auth
- Preprocessing options
- Buffer and compression settings

## Development

### Running Tests

```bash
pytest tests/
```

### Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Code Formatting

```bash
black .
ruff check --fix .
```

## Deployment

### Docker Deployment (TODO)

```bash
# Build and run with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f zandermcp
```

### Cloud Platforms

- **Fly.io**: `fly launch` and `fly deploy`
- **Railway**: Connect GitHub repo, auto-deploy
- **AWS ECS**: Use provided Dockerfile
- **GCP Cloud Run**: `gcloud run deploy`

## Use Cases

### 1. Adaptive AI Assistants
AI assistants detect high cognitive load and:
- Simplify explanations
- Suggest breaks
- Adjust interaction complexity
- Provide encouragement

### 2. Research & Data Collection
- Continuous data logging
- Event annotation
- Session management
- Export for offline analysis

### 3. Neurofeedback Applications
- Real-time workload monitoring
- Training applications
- Performance optimization
- Attention training

### 4. BCI Control Systems
- Intent detection
- Command classification
- Adaptive interfaces
- Accessibility applications

## Roadmap

- [x] Phase 1: Database, signal processing, edge relay
- [ ] Phase 2: ZanderMCP server, MCP tools
- [ ] Phase 3: Model service, ML classifier support
- [ ] Phase 4: Docker deployment, CI/CD
- [ ] Phase 5: Advanced analytics, multi-user support
- [ ] Phase 6: Mobile edge relay app

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Submit a pull request

## License

[To be determined]

## Acknowledgments

- Signal processing code ported from [bci-direct](https://github.com/yourusername/bci-direct)
- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Uses [Lab Streaming Layer](https://labstreaminglayer.org/)

## Support

For issues, questions, or contributions:
- GitHub Issues: [repository URL]
- Documentation: [docs URL]
- Email: [contact email]
