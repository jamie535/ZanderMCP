# ZanderMCP Deployment Guide

This guide covers deploying ZanderMCP server to production environments.

## Prerequisites

- PostgreSQL database (with TimescaleDB extension)
- Python 3.9+
- Environment variables configured
- Edge relay setup (optional, for EEG data ingestion)

## Environment Variables

Create a `.env` file or set these in your deployment platform:

```bash
# Required
POSTGRES_URL=postgresql+asyncpg://user:password@host:5432/zandermcp

# Optional
LOG_LEVEL=INFO
WEBSOCKET_HOST=0.0.0.0
WEBSOCKET_PORT=8765
EDGE_RELAY_API_KEY=your-secure-api-key-here

# Optional: For ML classifiers
AZURE_ML_ENDPOINT=https://your-endpoint.azureml.net/score
AZURE_ML_API_KEY=your-azure-key
```

## Deployment Options

### Option 1: Using fastmcp.json (Recommended)

The `fastmcp.json` file provides declarative configuration:

```json
{
  "name": "ZanderMCP",
  "version": "1.0.0",
  "deployment": {
    "transport": "stdio",
    "env": {
      "LOG_LEVEL": "INFO",
      "POSTGRES_URL": "${POSTGRES_URL}",
      "EDGE_RELAY_API_KEY": "${EDGE_RELAY_API_KEY}"
    }
  }
}
```

Run with:
```bash
fastmcp run
```

### Option 2: Direct Python Execution

```bash
python server.py
```

## Platform-Specific Guides

### Local Development

1. **Start database:**
   ```bash
   docker-compose up -d
   ```

2. **Run migrations:**
   ```bash
   alembic upgrade head
   ```

3. **Start server:**
   ```bash
   # With MCP Inspector
   mcp dev server.py

   # Or directly
   python server.py
   ```

### Claude Desktop Integration

Add to your Claude Desktop MCP configuration file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "zandermcp": {
      "command": "python",
      "args": ["/absolute/path/to/ZanderMCP/server.py"],
      "env": {
        "POSTGRES_URL": "postgresql+asyncpg://localhost/zandermcp",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Or with `uv` (recommended):

```json
{
  "mcpServers": {
    "zandermcp": {
      "command": "uv",
      "args": ["run", "python", "/absolute/path/to/ZanderMCP/server.py"],
      "env": {
        "POSTGRES_URL": "postgresql+asyncpg://localhost/zandermcp"
      }
    }
  }
}
```

### Docker Deployment

#### Development (Local Database)

Use the provided `docker-compose.yml`:

```bash
docker-compose up -d
```

This starts:
- PostgreSQL + TimescaleDB
- Exposed on port 5432

#### Production (Full Stack - TODO)

Create `docker-compose.prod.yml`:

```yaml
version: '3.8'

services:
  zandermcp:
    build: .
    ports:
      - "8765:8765"  # WebSocket
    environment:
      - POSTGRES_URL=postgresql+asyncpg://postgres:password@db:5432/zandermcp
      - LOG_LEVEL=INFO
      - WEBSOCKET_HOST=0.0.0.0
      - WEBSOCKET_PORT=8765
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: timescale/timescaledb:latest-pg16
    environment:
      - POSTGRES_DB=zandermcp
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=secure-password-here
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
```

Run:
```bash
docker-compose -f docker-compose.prod.yml up -d
```

### Cloud Platforms

#### Fly.io

1. **Create `Dockerfile`** (TODO - needs to be created):
   ```dockerfile
   FROM python:3.12-slim

   WORKDIR /app

   COPY pyproject.toml ./
   RUN pip install -e .

   COPY . .

   CMD ["python", "server.py"]
   ```

2. **Initialize Fly app:**
   ```bash
   fly launch
   ```

3. **Set secrets:**
   ```bash
   fly secrets set POSTGRES_URL=your-connection-string
   fly secrets set EDGE_RELAY_API_KEY=your-api-key
   ```

4. **Deploy:**
   ```bash
   fly deploy
   ```

#### Railway

1. **Connect GitHub repository**
2. **Add PostgreSQL service** (Railway provides TimescaleDB)
3. **Set environment variables:**
   - `POSTGRES_URL`: Provided by Railway
   - `EDGE_RELAY_API_KEY`: Your secure key
   - `LOG_LEVEL`: INFO
4. **Deploy:** Auto-deploys on git push

#### AWS ECS (TODO)

1. **Build and push Docker image to ECR**
2. **Create ECS Task Definition**
3. **Configure RDS PostgreSQL + TimescaleDB**
4. **Set up load balancer for WebSocket**
5. **Deploy ECS Service**

#### Google Cloud Run (TODO)

```bash
# Build container
gcloud builds submit --tag gcr.io/PROJECT_ID/zandermcp

# Deploy
gcloud run deploy zandermcp \
  --image gcr.io/PROJECT_ID/zandermcp \
  --platform managed \
  --set-env-vars POSTGRES_URL=your-connection-string
```

## Database Setup

### TimescaleDB Extension

Ensure TimescaleDB is enabled on your PostgreSQL database:

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
```

### Running Migrations

```bash
# Apply all migrations
alembic upgrade head

# Check current version
alembic current

# Rollback one migration
alembic downgrade -1
```

### Database Connection Pooling

The server uses SQLAlchemy async with connection pooling (configured in `config.yaml`):

```yaml
database:
  pool_size: 10          # Max connections
  max_overflow: 20       # Additional connections when needed
  batch_size: 50         # Batch write size
  flush_interval: 5.0    # Seconds before flush
```

## Edge Relay Setup

The edge relay runs on the local machine with the EEG device.

### Configuration

Edit `edge_relay/edge_relay_config.yaml`:

```yaml
lsl:
  stream_name: "YourEEGDevice"  # LSL stream name

cloud:
  endpoint: "ws://your-server.com:8765"  # ZanderMCP server URL
  api_key: "your-edge-relay-api-key"
  user_id: "user_001"

preprocessing:
  enabled: false  # Set true to reduce bandwidth

compression:
  enabled: true
  format: "msgpack"  # or "json"
```

### Running Edge Relay

```bash
cd edge_relay
python relay.py edge_relay_config.yaml
```

The relay will:
- Auto-reconnect on disconnection
- Buffer data during outages
- Compress data for bandwidth efficiency

## Monitoring & Logging

### Log Levels

Set via `LOG_LEVEL` environment variable:
- `DEBUG`: Verbose output (development)
- `INFO`: Standard output (production)
- `WARNING`: Warnings only
- `ERROR`: Errors only

### MCP Inspector (Development)

Run server with MCP Inspector for debugging:

```bash
mcp dev server.py
```

Open http://localhost:6274 to:
- See all available tools
- Test tool calls
- View logs in real-time
- Inspect request/response data

### Health Checks

Use the `get_server_stats()` MCP tool to check server health:

```python
# Returns:
{
  "websocket": {
    "active_connections": 2,
    "host": "0.0.0.0",
    "port": 8765,
    "uptime_seconds": 3600
  },
  "buffers": {
    "total_sessions": 1,
    "total_samples": 850
  },
  "classifiers_loaded": 1,
  "config": {
    "database_connected": true
  }
}
```

## Security Best Practices

### ✅ Implemented

1. **Error Masking**: `mask_error_details=True` prevents internal error leakage
2. **Input Validation**: All tools validate parameters
3. **Database Credentials**: Never hardcoded, always via environment variables
4. **API Keys**: Required for edge relay authentication

### TODO: Additional Security

1. **HTTPS/WSS**: Use TLS for WebSocket connections
2. **Rate Limiting**: Limit requests per client
3. **Authentication**: Add user authentication for MCP tools
4. **Encryption**: Encrypt sensitive data at rest

## Performance Optimization

### Database

1. **Connection Pooling**: Configured in `config.yaml`
2. **Batched Writes**: 50 samples or 5 seconds (configurable)
3. **Indexes**: Optimized for time-range queries
4. **TimescaleDB**: Automatic time-based partitioning

### WebSocket Server

1. **Max Connections**: Set in `config.yaml` (default: 10)
2. **Heartbeat**: Keep-alive every 30 seconds
3. **Compression**: msgpack for reduced bandwidth

### Buffer Management

1. **In-Memory Buffer**: Bounded deque (1000 samples default)
2. **Automatic Cleanup**: Old data purged after persistence
3. **Per-Session Isolation**: Separate buffers per user session

## Troubleshooting

### Server Won't Start

**Issue:** Database connection failed
```bash
# Check POSTGRES_URL format
echo $POSTGRES_URL
# Should be: postgresql+asyncpg://user:password@host:port/database

# Test connection
psql $POSTGRES_URL
```

**Issue:** Port already in use
```bash
# Change WebSocket port in config.yaml or .env
WEBSOCKET_PORT=8766
```

### Edge Relay Issues

**Issue:** Can't find LSL stream
```python
# List available streams
import pylsl
streams = pylsl.resolve_streams()
print([s.name() for s in streams])
```

**Issue:** WebSocket connection refused
```bash
# Check server is running
curl http://your-server:8765

# Check firewall rules
# Ensure port 8765 is open
```

### Performance Issues

**Issue:** High latency
```yaml
# Reduce batch size in config.yaml
database:
  batch_size: 25
  flush_interval: 2.0
```

**Issue:** Database slowness
```sql
-- Check database indexes
SELECT * FROM pg_indexes WHERE tablename = 'predictions';

-- Analyze query performance
EXPLAIN ANALYZE SELECT * FROM predictions
WHERE timestamp > NOW() - INTERVAL '5 minutes';
```

## Backup & Recovery

### Database Backups

```bash
# Backup
pg_dump -Fc $POSTGRES_URL > zandermcp_backup.dump

# Restore
pg_restore -d $POSTGRES_URL zandermcp_backup.dump
```

### Configuration Backups

Always version control:
- `config.yaml`
- `edge_relay/edge_relay_config.yaml`
- `fastmcp.json`
- `.env.example` (template, not actual `.env`)

## Scaling Considerations

### Horizontal Scaling (TODO)

- **Load Balancer**: Distribute WebSocket connections
- **Database Read Replicas**: For historical queries
- **Redis Cache**: For frequently accessed data
- **Message Queue**: For asynchronous processing

### Vertical Scaling

- Increase `pool_size` in `config.yaml`
- Increase `max_connections` for WebSocket
- Add more database resources (CPU, RAM)

## Support & Documentation

- **Development Guide**: See `CLAUDE.md`
- **API Reference**: Use MCP Inspector or call `list_classifiers()`
- **Configuration**: See `config.yaml` and `fastmcp.json`
- **Issues**: Report at GitHub repository

## Next Steps

After deployment:

1. **Test edge relay connection** from local machine
2. **Verify database persistence** by checking `predictions` table
3. **Test MCP tools** via Claude Desktop or MCP Inspector
4. **Set up monitoring** and health checks
5. **Configure backups** for production data
