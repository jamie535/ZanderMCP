"""ZanderMCP main server - FastMCP server with WebSocket ingestion.

This is the main entry point that ties together:
- WebSocket server for edge relay connections
- Stream buffer for real-time data
- Database persistence
- Classification pipeline
- MCP tools for AI assistants
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Any, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

import yaml
from dotenv import load_dotenv
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from ingestion.stream_buffer import init_buffer_manager, SessionBufferManager
from ingestion.websocket_server import WebSocketServer
from database.connection import DatabaseManager
from database.persistence import PersistenceManager
from classifiers.signal_processing import SignalProcessingClassifier
from tools.realtime import RealtimeTools
from tools.history import HistoryTools
from tools.session import SessionTools

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)


@dataclass
class AppContext:
    """Application context with all initialized services."""
    buffer_manager: SessionBufferManager
    websocket_server: WebSocketServer
    db_manager: DatabaseManager
    persistence_manager: PersistenceManager
    realtime_tools: RealtimeTools
    history_tools: HistoryTools
    session_tools: SessionTools


# Global context for internal use (middleware sets this in Context state)
_app_context: Optional[AppContext] = None


def _get_app_context(ctx: Optional[Context] = None) -> AppContext:
    """Get application context from Context state or global fallback.

    Args:
        ctx: Optional Context object from FastMCP

    Returns:
        AppContext with all services

    Raises:
        ToolError: If server is not initialized
    """
    # Try to get from Context state first (preferred)
    if ctx is not None:
        app_ctx = ctx.get_state("app_context")
        if app_ctx is not None:
            return app_ctx

    # Fallback to global (for backwards compatibility during transition)
    if _app_context is not None:
        return _app_context

    raise ToolError(
        "Server not fully initialized. Please wait a moment and try again."
    )


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Manage application lifecycle with all services.

    Services are accessible via Context state in tools.
    """
    global _app_context

    logger.info("Starting ZanderMCP server...")

    # Initialize buffer manager
    logger.info("Initializing stream buffer...")
    buffer_manager = init_buffer_manager(default_buffer_size=1000)

    # Initialize database
    logger.info("Initializing database connection...")
    db_manager = DatabaseManager(
        pool_size=config["database"]["pool_size"],
        max_overflow=config["database"]["max_overflow"],
    )

    # Initialize database schema if needed
    try:
        await db_manager.initialize()
        logger.info("Database schema initialized")
    except Exception as e:
        logger.warning(f"Database initialization skipped (may already exist): {e}")

    # Initialize persistence manager
    logger.info("Initializing persistence manager...")
    persistence_manager = PersistenceManager(
        db_manager=db_manager,
        batch_size=config["database"]["batch_size"],
        flush_interval=config["database"]["flush_interval"],
    )
    await persistence_manager.start()

    # Load classifiers
    logger.info("Loading classifiers...")
    classifiers = {
        "signal_processing": SignalProcessingClassifier(
            sfreq=config["signal_processing"]["sampling_rate"],
        )
    }

    # Initialize tools
    logger.info("Initializing MCP tools...")
    realtime_tools = RealtimeTools(buffer_manager)
    history_tools = HistoryTools(db_manager)
    session_tools = SessionTools(db_manager, persistence_manager)

    # Initialize WebSocket server
    logger.info("Initializing WebSocket server...")
    websocket_server = WebSocketServer(
        host=config["websocket"]["host"],
        port=config["websocket"]["port"],
        api_key=os.getenv("EDGE_RELAY_API_KEY"),
        buffer_manager=buffer_manager,
        db_manager=db_manager,
        persistence_manager=persistence_manager,
        classifiers=classifiers,
        max_connections=config["websocket"]["max_connections"],
        heartbeat_interval=config["websocket"]["heartbeat_interval"],
    )

    # Start WebSocket server
    await websocket_server.start()

    logger.info("ZanderMCP server started successfully!")
    logger.info(f"WebSocket server listening on ws://{config['websocket']['host']}:{config['websocket']['port']}")

    # Create context
    _app_context = AppContext(
        buffer_manager=buffer_manager,
        websocket_server=websocket_server,
        db_manager=db_manager,
        persistence_manager=persistence_manager,
        realtime_tools=realtime_tools,
        history_tools=history_tools,
        session_tools=session_tools,
    )

    try:
        yield
    finally:
        # Shutdown
        logger.info("Stopping ZanderMCP server...")

        await websocket_server.stop()
        await persistence_manager.stop()
        await db_manager.close()

        logger.info("ZanderMCP server stopped")


# Initialize FastMCP with lifespan and security settings
mcp = FastMCP(
    name="ZanderMCP",
    lifespan=app_lifespan,
    mask_error_details=True,  # Security: mask internal error details in production
)


# =============================================================================
# MCP TOOLS (with tags for categorization)
# =============================================================================

@mcp.tool(tags={"realtime", "monitoring", "production"})
async def get_current_cognitive_load(
    user_id: Optional[str] = None,
    ctx: Context = None
) -> dict:
    """Get the latest cognitive load prediction.

    Returns the most recent workload measurement with confidence and trend.

    Args:
        user_id: Optional user identifier (uses latest if not specified)

    Returns:
        Dictionary with:
        - workload: float (0.0 to 1.0, normalized cognitive load)
        - confidence: float (0.0 to 1.0, prediction confidence)
        - timestamp: ISO 8601 timestamp
        - trend: str ("increasing", "stable", "decreasing")

    Example:
        {
            "workload": 0.65,
            "confidence": 0.89,
            "timestamp": "2025-01-10T14:23:15.123Z",
            "trend": "increasing"
        }
    """
    try:
        app_ctx = _get_app_context(ctx)
        result = await app_ctx.realtime_tools.get_current_cognitive_load(user_id)

        if ctx:
            await ctx.info(f"Retrieved cognitive load: {result.get('workload', 'N/A')}")

        return result
    except ToolError:
        raise
    except ValueError as e:
        raise ToolError(f"Invalid user_id: {e}")
    except Exception as e:
        if ctx:
            await ctx.error(f"Cognitive load query failed: {e}")
        raise ToolError("Failed to retrieve cognitive load. Please try again later.")


@mcp.tool(tags={"realtime", "monitoring", "production"})
async def get_cognitive_state(
    user_id: Optional[str] = None,
    ctx: Context = None
) -> dict:
    """Get interpreted cognitive state with recommendations.

    Provides human-readable state with actionable recommendations.

    Args:
        user_id: Optional user identifier

    Returns:
        Dictionary with:
        - state: str ("focused", "moderate", "high_load", "overloaded")
        - intensity: float (0.0 to 1.0)
        - recommendations: list of str (actionable advice)
        - workload: float (raw workload value)

    Example:
        {
            "state": "high_load",
            "intensity": 0.78,
            "recommendations": [
                "Consider taking a short break",
                "Reduce task complexity if possible"
            ],
            "workload": 0.78
        }
    """
    try:
        app_ctx = _get_app_context(ctx)
        result = await app_ctx.realtime_tools.get_cognitive_state(user_id)

        if ctx:
            await ctx.info(f"Cognitive state: {result.get('state', 'unknown')}")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Cognitive state query failed: {e}")
        raise ToolError("Failed to retrieve cognitive state. Please try again later.")


@mcp.tool(tags={"realtime", "analysis", "production"})
async def get_workload_trend(
    minutes: int = 5,
    user_id: Optional[str] = None,
    ctx: Context = None
) -> dict:
    """Get workload trend over recent time period.

    Args:
        minutes: Number of minutes to look back (default: 5, max: 60)
        user_id: Optional user identifier

    Returns:
        Dictionary with:
        - trend: str ("increasing", "stable", "decreasing")
        - mean: float (average workload)
        - std: float (standard deviation)
        - min: float (minimum workload)
        - max: float (maximum workload)
        - samples: list of {timestamp: str, workload: float}

    Example:
        {
            "trend": "increasing",
            "mean": 0.62,
            "std": 0.12,
            "min": 0.45,
            "max": 0.81,
            "samples": [
                {"timestamp": "2025-01-10T14:20:00Z", "workload": 0.45},
                {"timestamp": "2025-01-10T14:22:00Z", "workload": 0.81}
            ]
        }
    """
    try:
        if minutes <= 0 or minutes > 60:
            raise ToolError("minutes must be between 1 and 60")

        app_ctx = _get_app_context(ctx)
        result = await app_ctx.realtime_tools.get_workload_trend(minutes, user_id)

        if ctx:
            await ctx.info(f"Analyzed {len(result.get('samples', []))} samples over {minutes} minutes")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Workload trend query failed: {e}")
        raise ToolError("Failed to retrieve workload trend. Please try again later.")


@mcp.tool(tags={"historical", "database", "production"})
async def query_workload_history(
    minutes: int = 10,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None
) -> dict:
    """Query historical workload predictions from database.

    Args:
        minutes: Number of minutes to look back (default: 10, max: 1440)
        user_id: Optional filter by user
        session_id: Optional filter by session

    Returns:
        Dictionary with:
        - samples: list of predictions with timestamps and metadata
        - count: int (number of samples)
        - mean: float (average workload)
        - std: float (standard deviation)

    Example:
        {
            "samples": [
                {
                    "timestamp": "2025-01-10T14:20:00Z",
                    "workload": 0.65,
                    "classifier": "signal_processing",
                    "session_id": "abc-123"
                }
            ],
            "count": 150,
            "mean": 0.58,
            "std": 0.15
        }
    """
    try:
        if minutes <= 0 or minutes > 1440:
            raise ToolError("minutes must be between 1 and 1440 (24 hours)")

        app_ctx = _get_app_context(ctx)

        if ctx:
            await ctx.info(f"Querying {minutes} minutes of historical data...")

        result = await app_ctx.history_tools.query_workload_history(
            minutes, user_id, session_id
        )

        if ctx:
            await ctx.info(f"Retrieved {result.get('count', 0)} historical samples")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"History query failed: {e}")
        raise ToolError("Failed to query workload history. Please try again later.")


@mcp.tool(tags={"historical", "session", "production"})
async def get_session_summary(
    session_id: str,
    ctx: Context = None
) -> dict:
    """Get summary statistics for a recording session.

    Args:
        session_id: Session UUID

    Returns:
        Dictionary with:
        - session_id: str
        - user_id: str
        - start_time: ISO 8601 timestamp
        - end_time: ISO 8601 timestamp or null
        - duration_seconds: float
        - sample_count: int
        - mean_workload: float
        - max_workload: float
        - min_workload: float

    Example:
        {
            "session_id": "abc-123",
            "user_id": "user_1",
            "start_time": "2025-01-10T14:00:00Z",
            "end_time": "2025-01-10T15:30:00Z",
            "duration_seconds": 5400,
            "sample_count": 2700,
            "mean_workload": 0.58,
            "max_workload": 0.92,
            "min_workload": 0.23
        }
    """
    try:
        if not session_id or not session_id.strip():
            raise ToolError("session_id is required")

        app_ctx = _get_app_context(ctx)
        result = await app_ctx.history_tools.get_session_summary(session_id)

        if ctx:
            duration = result.get("duration_seconds", 0)
            await ctx.info(f"Session duration: {duration/60:.1f} minutes")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Session summary query failed: {e}")
        raise ToolError(f"Failed to retrieve session summary. Please check the session_id.")


@mcp.tool(tags={"historical", "analysis", "research"})
async def analyze_cognitive_patterns(
    start: str,
    end: str,
    user_id: Optional[str] = None,
    ctx: Context = None
) -> dict:
    """Analyze cognitive patterns over a time range.

    Args:
        start: Start time in ISO 8601 format (e.g., "2025-01-10T10:00:00Z")
        end: End time in ISO 8601 format
        user_id: Optional filter by user

    Returns:
        Dictionary with:
        - trend: str ("increasing", "stable", "decreasing")
        - high_load_periods: list of {start: str, end: str, duration_seconds: float}
        - low_load_periods: list of {start: str, end: str, duration_seconds: float}
        - mean_workload: float
        - peak_workload: float
        - recovery_periods: int (count of recovery periods)

    Example:
        {
            "trend": "stable",
            "high_load_periods": [
                {
                    "start": "2025-01-10T11:30:00Z",
                    "end": "2025-01-10T11:45:00Z",
                    "duration_seconds": 900
                }
            ],
            "low_load_periods": [...],
            "mean_workload": 0.52,
            "peak_workload": 0.89,
            "recovery_periods": 3
        }
    """
    try:
        # Validate ISO 8601 timestamps
        try:
            datetime.fromisoformat(start.replace('Z', '+00:00'))
            datetime.fromisoformat(end.replace('Z', '+00:00'))
        except ValueError:
            raise ToolError(
                "Invalid timestamp format. Use ISO 8601 format (e.g., '2025-01-10T10:00:00Z')"
            )

        app_ctx = _get_app_context(ctx)

        if ctx:
            await ctx.info(f"Analyzing patterns from {start} to {end}...")

        result = await app_ctx.history_tools.analyze_cognitive_patterns(
            start, end, user_id
        )

        if ctx:
            high_load_count = len(result.get("high_load_periods", []))
            await ctx.info(f"Found {high_load_count} high load periods")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Pattern analysis failed: {e}")
        raise ToolError("Failed to analyze cognitive patterns. Please try again later.")


@mcp.tool(tags={"historical", "research", "annotation"})
async def get_recent_events(
    limit: int = 10,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    ctx: Context = None
) -> dict:
    """Get recent annotated events.

    Args:
        limit: Maximum number of events to return (default: 10, max: 100)
        user_id: Optional filter by user
        session_id: Optional filter by session

    Returns:
        Dictionary with:
        - events: list of {
            event_id: str,
            label: str,
            notes: str,
            timestamp: str,
            session_id: str,
            user_id: str
          }
        - count: int

    Example:
        {
            "events": [
                {
                    "event_id": "evt-123",
                    "label": "task_start",
                    "notes": "Beginning math problems",
                    "timestamp": "2025-01-10T14:30:00Z",
                    "session_id": "abc-123",
                    "user_id": "user_1"
                }
            ],
            "count": 1
        }
    """
    try:
        if limit <= 0 or limit > 100:
            raise ToolError("limit must be between 1 and 100")

        app_ctx = _get_app_context(ctx)
        result = await app_ctx.history_tools.get_recent_events(
            limit, user_id, session_id
        )

        if ctx:
            await ctx.info(f"Retrieved {result.get('count', 0)} events")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Events query failed: {e}")
        raise ToolError("Failed to retrieve events. Please try again later.")


@mcp.tool(tags={"research", "annotation", "production"})
async def annotate_event(
    label: str,
    notes: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    ctx: Context = None
) -> dict:
    """Annotate an event in the current session.

    Useful for marking significant moments during data collection.

    Args:
        label: Event label/type (e.g., "task_start", "break", "difficult_problem")
        notes: Optional description
        session_id: Session UUID (uses most recent if not specified)
        user_id: User identifier (for finding session if session_id not provided)

    Returns:
        Dictionary with:
        - event_id: str
        - label: str
        - notes: str
        - timestamp: str
        - session_id: str

    Example:
        {
            "event_id": "evt-456",
            "label": "task_complete",
            "notes": "Finished all exercises",
            "timestamp": "2025-01-10T15:00:00Z",
            "session_id": "abc-123"
        }
    """
    try:
        if not label or not label.strip():
            raise ToolError("label is required")

        app_ctx = _get_app_context(ctx)

        if ctx:
            await ctx.info(f"Annotating event: {label}")

        result = await app_ctx.session_tools.annotate_event(
            label, notes, session_id, user_id
        )

        if ctx:
            await ctx.info(f"Event annotated successfully: {result.get('event_id')}")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Event annotation failed: {e}")
        raise ToolError("Failed to annotate event. Please check the session_id.")


@mcp.tool(tags={"session", "monitoring", "production"})
async def get_active_sessions(
    user_id: Optional[str] = None,
    ctx: Context = None
) -> dict:
    """Get list of currently active recording sessions.

    Args:
        user_id: Optional filter by user

    Returns:
        Dictionary with:
        - sessions: list of {
            session_id: str,
            user_id: str,
            start_time: str,
            device_info: dict,
            sample_count: int
          }
        - count: int

    Example:
        {
            "sessions": [
                {
                    "session_id": "abc-123",
                    "user_id": "user_1",
                    "start_time": "2025-01-10T14:00:00Z",
                    "device_info": {"type": "Emotiv EPOC", "channels": 14},
                    "sample_count": 1200
                }
            ],
            "count": 1
        }
    """
    try:
        app_ctx = _get_app_context(ctx)
        result = await app_ctx.session_tools.get_active_sessions(user_id)

        if ctx:
            await ctx.info(f"Found {result.get('count', 0)} active sessions")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Active sessions query failed: {e}")
        raise ToolError("Failed to retrieve active sessions. Please try again later.")


@mcp.tool(tags={"session", "management", "production"})
async def end_session(
    session_id: str,
    notes: Optional[str] = None,
    ctx: Context = None
) -> dict:
    """End a recording session.

    Args:
        session_id: Session UUID to end
        notes: Optional closing notes

    Returns:
        Dictionary with:
        - session_id: str
        - end_time: str
        - duration_seconds: float
        - status: str ("ended")

    Example:
        {
            "session_id": "abc-123",
            "end_time": "2025-01-10T15:30:00Z",
            "duration_seconds": 5400,
            "status": "ended"
        }
    """
    try:
        if not session_id or not session_id.strip():
            raise ToolError("session_id is required")

        app_ctx = _get_app_context(ctx)

        if ctx:
            await ctx.info(f"Ending session: {session_id}")

        result = await app_ctx.session_tools.end_session(session_id, notes)

        if ctx:
            duration = result.get("duration_seconds", 0)
            await ctx.info(f"Session ended. Duration: {duration/60:.1f} minutes")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"End session failed: {e}")
        raise ToolError("Failed to end session. Please check the session_id.")


@mcp.tool(tags={"admin", "monitoring", "debug"})
async def get_buffer_status(ctx: Context = None) -> dict:
    """Get current buffer status and statistics.

    Returns statistics for all active session buffers.

    Returns:
        Dictionary with:
        - buffers: dict of session_id -> {
            size: int,
            capacity: int,
            oldest_timestamp: str,
            newest_timestamp: str,
            utilization: float (0.0 to 1.0)
          }
        - total_sessions: int
        - total_samples: int

    Example:
        {
            "buffers": {
                "abc-123": {
                    "size": 850,
                    "capacity": 1000,
                    "oldest_timestamp": "2025-01-10T14:50:00Z",
                    "newest_timestamp": "2025-01-10T15:00:00Z",
                    "utilization": 0.85
                }
            },
            "total_sessions": 1,
            "total_samples": 850
        }
    """
    try:
        app_ctx = _get_app_context(ctx)
        result = await app_ctx.realtime_tools.get_buffer_status()

        if ctx:
            total = result.get("total_samples", 0)
            sessions = result.get("total_sessions", 0)
            await ctx.info(f"Buffer status: {sessions} sessions, {total} samples")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Buffer status query failed: {e}")
        raise ToolError("Failed to retrieve buffer status. Please try again later.")


@mcp.tool(tags={"admin", "classifier", "production"})
async def list_classifiers(ctx: Context = None) -> dict:
    """List available classification models.

    Returns:
        Dictionary with:
        - classifiers: list of {
            name: str,
            type: str,
            version: str,
            description: str
          }
        - count: int
        - default: str (default classifier name)

    Example:
        {
            "classifiers": [
                {
                    "name": "signal_processing",
                    "type": "deterministic",
                    "version": "1.0.0",
                    "description": "Signal processing based workload classifier"
                }
            ],
            "count": 1,
            "default": "signal_processing"
        }
    """
    try:
        app_ctx = _get_app_context(ctx)
        classifiers_info = []

        for name, classifier in app_ctx.websocket_server.classifiers.items():
            info = classifier.get_metadata()
            classifiers_info.append({
                "name": name,
                "type": info.get("type"),
                "version": info.get("version"),
                "description": info.get("description"),
            })

        result = {
            "classifiers": classifiers_info,
            "count": len(classifiers_info),
            "default": config["classifiers"]["default"],
        }

        if ctx:
            await ctx.info(f"Available classifiers: {len(classifiers_info)}")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"List classifiers failed: {e}")
        raise ToolError("Failed to list classifiers. Please try again later.")


@mcp.tool(tags={"admin", "monitoring", "debug"})
async def get_server_stats(ctx: Context = None) -> dict:
    """Get ZanderMCP server statistics.

    Returns connection info, buffer stats, and system status.

    Returns:
        Dictionary with:
        - websocket: {
            active_connections: int,
            host: str,
            port: int,
            uptime_seconds: float
          }
        - buffers: buffer status dictionary
        - classifiers_loaded: int
        - config: {
            max_connections: int,
            buffer_size: int,
            database_connected: bool
          }

    Example:
        {
            "websocket": {
                "active_connections": 2,
                "host": "0.0.0.0",
                "port": 8765,
                "uptime_seconds": 3600
            },
            "buffers": {...},
            "classifiers_loaded": 1,
            "config": {
                "max_connections": 10,
                "buffer_size": 1000,
                "database_connected": true
            }
        }
    """
    try:
        app_ctx = _get_app_context(ctx)

        ws_stats = await app_ctx.websocket_server.get_stats()
        buffer_stats = await app_ctx.realtime_tools.get_buffer_status()

        result = {
            "websocket": ws_stats,
            "buffers": buffer_stats,
            "classifiers_loaded": len(app_ctx.websocket_server.classifiers),
            "config": {
                "max_connections": config["websocket"]["max_connections"],
                "buffer_size": 1000,  # TODO: make configurable
                "database_connected": app_ctx.db_manager is not None,
            },
        }

        if ctx:
            connections = ws_stats.get("active_connections", 0)
            await ctx.info(f"Server stats: {connections} active connections")

        return result
    except ToolError:
        raise
    except Exception as e:
        if ctx:
            await ctx.error(f"Server stats query failed: {e}")
        raise ToolError("Failed to retrieve server statistics. Please try again later.")


# =============================================================================
# MCP RESOURCES (read-only data sources)
# =============================================================================

@mcp.resource("config://server", tags={"config", "admin"})
async def server_configuration(ctx: Context = None) -> dict:
    """Server configuration as a readable resource.

    Provides server configuration, classifier info, and deployment settings.
    """
    try:
        app_ctx = _get_app_context(ctx)

        return {
            "server": {
                "name": "ZanderMCP",
                "version": "1.0.0",
                "environment": os.getenv("ENVIRONMENT", "development"),
            },
            "websocket": {
                "host": config["websocket"]["host"],
                "port": config["websocket"]["port"],
                "max_connections": config["websocket"]["max_connections"],
            },
            "database": {
                "connected": app_ctx.db_manager is not None,
                "batch_size": config["database"]["batch_size"],
                "flush_interval": config["database"]["flush_interval"],
            },
            "classifiers": {
                "default": config["classifiers"]["default"],
                "available": list(app_ctx.websocket_server.classifiers.keys()),
            },
            "signal_processing": {
                "sampling_rate": config["signal_processing"]["sampling_rate"],
                "chunk_length": config["signal_processing"]["chunk_length"],
            },
        }
    except Exception as e:
        if ctx:
            await ctx.error(f"Failed to read server configuration: {e}")
        raise ToolError("Failed to read server configuration.")


@mcp.resource("config://classifiers", tags={"config", "classifier"})
async def classifiers_config(ctx: Context = None) -> dict:
    """Available classifiers and their metadata.

    Provides detailed information about each classifier including
    type, version, and configuration parameters.
    """
    try:
        app_ctx = _get_app_context(ctx)

        classifiers_info = {}
        for name, classifier in app_ctx.websocket_server.classifiers.items():
            metadata = classifier.get_metadata()
            classifiers_info[name] = {
                "type": metadata.get("type"),
                "version": metadata.get("version"),
                "description": metadata.get("description"),
                "parameters": metadata.get("parameters", {}),
            }

        return {
            "classifiers": classifiers_info,
            "default": config["classifiers"]["default"],
            "count": len(classifiers_info),
        }
    except Exception as e:
        if ctx:
            await ctx.error(f"Failed to read classifiers config: {e}")
        raise ToolError("Failed to read classifiers configuration.")


@mcp.resource("data://session/{session_id}/export", tags={"data", "export", "research"})
async def export_session_data(session_id: str, ctx: Context = None) -> str:
    """Export session data as CSV format.

    Returns CSV data for a recording session including all predictions,
    events, and metadata.

    Args:
        session_id: Session UUID to export

    Returns:
        CSV formatted string
    """
    try:
        app_ctx = _get_app_context(ctx)

        if ctx:
            await ctx.info(f"Exporting session {session_id}...")

        # Get session summary
        summary = await app_ctx.history_tools.get_session_summary(session_id)

        # Get all predictions for this session
        # Using a large time window to get all data
        history = await app_ctx.history_tools.query_workload_history(
            minutes=10080,  # 1 week
            session_id=session_id
        )

        # Build CSV
        csv_lines = [
            "timestamp,workload,confidence,classifier,session_id,user_id"
        ]

        for sample in history.get("samples", []):
            csv_lines.append(
                f"{sample.get('timestamp')},"
                f"{sample.get('workload')},"
                f"{sample.get('confidence')},"
                f"{sample.get('classifier')},"
                f"{sample.get('session_id')},"
                f"{sample.get('user_id')}"
            )

        if ctx:
            await ctx.info(f"Exported {len(csv_lines)-1} rows")

        return "\n".join(csv_lines)

    except Exception as e:
        if ctx:
            await ctx.error(f"Session export failed: {e}")
        raise ToolError("Failed to export session data.")


@mcp.resource("docs://api-guide", tags={"docs", "help"})
def api_documentation() -> str:
    """ZanderMCP API documentation and usage guide.

    Provides comprehensive documentation for using the ZanderMCP server.
    """
    return """# ZanderMCP API Guide

## Overview
ZanderMCP provides real-time BCI data analysis through MCP tools.

## Tool Categories

### Real-time Monitoring (tags: realtime, monitoring)
- get_current_cognitive_load() - Latest workload prediction
- get_cognitive_state() - Interpreted cognitive state with recommendations
- get_workload_trend() - Trend analysis over time

### Historical Queries (tags: historical, database)
- query_workload_history() - Historical predictions from database
- get_session_summary() - Session statistics
- analyze_cognitive_patterns() - Pattern analysis with trends

### Session Management (tags: session, management)
- get_active_sessions() - List active sessions
- end_session() - Close a session
- annotate_event() - Mark significant moments

### Research Tools (tags: research, annotation)
- annotate_event() - Annotate events for research
- get_recent_events() - Recent annotated events

### Admin Tools (tags: admin, monitoring)
- get_server_stats() - Server statistics
- get_buffer_status() - Buffer status
- list_classifiers() - Available classifiers

## Resources

- config://server - Server configuration
- config://classifiers - Classifier metadata
- data://session/{id}/export - Export session as CSV
- docs://api-guide - This guide

## Example Workflow

1. Check cognitive load: get_current_cognitive_load()
2. Get recommendations: get_cognitive_state()
3. Annotate significant moments: annotate_event()
4. Analyze patterns: analyze_cognitive_patterns()
5. Export data: Read resource data://session/{id}/export
"""


# =============================================================================
# MCP PROMPTS (templates for AI workflows)
# =============================================================================

@mcp.prompt(tags={"analysis", "monitoring"})
def analyze_cognitive_load(user_id: Optional[str] = None) -> str:
    """Generate a prompt for comprehensive cognitive load analysis.

    Use this prompt template to guide AI assistants through a complete
    cognitive load analysis workflow.

    Args:
        user_id: Optional user identifier to analyze
    """
    user_filter = f" for user {user_id}" if user_id else ""

    return f"""Perform a comprehensive cognitive load analysis{user_filter}:

1. **Current State Assessment**
   - Call get_current_cognitive_load({f"user_id='{user_id}'" if user_id else ""})
   - Call get_cognitive_state({f"user_id='{user_id}'" if user_id else ""})
   - Interpret the current workload level and trend

2. **Trend Analysis**
   - Call get_workload_trend(minutes=30{f", user_id='{user_id}'" if user_id else ""})
   - Identify patterns in the last 30 minutes
   - Note any significant changes or anomalies

3. **Recommendations**
   - Based on current state and trends, provide:
     * Immediate actions (if workload is high)
     * Suggested break timing
     * Task complexity adjustments
     * Environmental modifications

4. **Summary**
   - Provide a concise summary of findings
   - Highlight any concerns or positive patterns
"""


@mcp.prompt(tags={"research", "analysis"})
def research_session_analysis(session_id: str) -> str:
    """Generate a prompt for detailed research session analysis.

    Use this to guide AI through analyzing a complete BCI research session.

    Args:
        session_id: Session UUID to analyze
    """
    return f"""Conduct a detailed research analysis of BCI session {session_id}:

1. **Session Overview**
   - Call get_session_summary(session_id="{session_id}")
   - Review duration, sample count, and basic statistics

2. **Pattern Analysis**
   - Call analyze_cognitive_patterns() with session start/end times
   - Identify high-load periods and recovery periods
   - Calculate mean workload and variability

3. **Event Correlation**
   - Call get_recent_events(session_id="{session_id}")
   - Correlate events with workload patterns
   - Identify cause-and-effect relationships

4. **Data Export**
   - Read resource data://session/{session_id}/export
   - Mention data is available for offline analysis

5. **Research Insights**
   - Summarize key findings
   - Suggest hypotheses for further investigation
   - Recommend follow-up experiments
"""


@mcp.prompt(tags={"monitoring", "production"})
def monitor_active_sessions() -> str:
    """Generate a prompt for monitoring all active BCI sessions.

    Use this for operational monitoring and system health checks.
    """
    return """Monitor all active BCI sessions and system health:

1. **Active Sessions**
   - Call get_active_sessions()
   - Review each session: duration, user, sample count
   - Identify any sessions running longer than expected

2. **System Health**
   - Call get_server_stats()
   - Check WebSocket connections
   - Review buffer utilization
   - Verify database connectivity

3. **Real-time Monitoring**
   - For each active session:
     * Call get_current_cognitive_load(user_id=...)
     * Check for concerning patterns (sustained high load)
     * Review recent trends

4. **Alerts and Actions**
   - Flag any sessions requiring attention
   - Recommend interventions for high cognitive load
   - Suggest session management actions if needed

5. **Summary Dashboard**
   - Total active sessions
   - System resource utilization
   - Average cognitive load across all users
   - Any alerts or concerns
"""


@mcp.prompt(tags={"onboarding", "help"})
def getting_started_guide() -> str:
    """Generate an onboarding prompt for new users.

    Helps AI assistants guide users through their first ZanderMCP session.
    """
    return """Welcome to ZanderMCP! Let me guide you through getting started:

1. **Initial Setup Check**
   - Read resource config://server
   - Verify edge relay is connected (check get_server_stats())
   - Confirm active session exists (get_active_sessions())

2. **First Cognitive Load Check**
   - Call get_current_cognitive_load()
   - Explain what the workload value means (0.0 = low, 1.0 = high)
   - Call get_cognitive_state() for human-readable interpretation

3. **Understanding Trends**
   - Call get_workload_trend(minutes=5)
   - Explain how trends work (increasing/stable/decreasing)
   - Demonstrate real-time responsiveness

4. **Annotation Demo**
   - Show how to mark significant moments:
     annotate_event(label="demo_start", notes="Starting ZanderMCP demo")
   - Explain use cases for research and tracking

5. **Available Capabilities**
   - Read resource docs://api-guide
   - Highlight key tools for their use case
   - Explain when to use each tool category

6. **Next Steps**
   - Suggest first real use case
   - Offer to set up monitoring or analysis
   - Provide tips for effective BCI data collection
"""


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("ZanderMCP - Brain-Computer Interface MCP Server")
    logger.info("=" * 60)

    try:
        # Run FastMCP server (stdio transport for Claude Desktop by default)
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
