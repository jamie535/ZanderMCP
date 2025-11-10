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

import yaml
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

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


# Global context (set during lifespan)
app_context: Optional[AppContext] = None


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with all services."""
    global app_context

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

    # Create and set global context
    app_context = AppContext(
        buffer_manager=buffer_manager,
        websocket_server=websocket_server,
        db_manager=db_manager,
        persistence_manager=persistence_manager,
        realtime_tools=realtime_tools,
        history_tools=history_tools,
        session_tools=session_tools,
    )

    try:
        yield app_context
    finally:
        # Shutdown
        logger.info("Stopping ZanderMCP server...")

        await websocket_server.stop()
        await persistence_manager.stop()
        await db_manager.close()

        logger.info("ZanderMCP server stopped")


# Initialize FastMCP with lifespan
mcp = FastMCP("ZanderMCP", lifespan=app_lifespan)


@mcp.tool()
async def get_current_cognitive_load(user_id: Optional[str] = None) -> dict:
    """Get the latest cognitive load prediction.

    Returns the most recent workload measurement with confidence and trend.

    Args:
        user_id: Optional user identifier (uses latest if not specified)

    Returns:
        Dictionary with workload, confidence, timestamp, and trend
    """
    return await app_context.realtime_tools.get_current_cognitive_load(user_id)


@mcp.tool()
async def get_cognitive_state(user_id: Optional[str] = None) -> dict:
    """Get interpreted cognitive state with recommendations.

    Provides human-readable state ("focused", "moderate", "high_load", "overloaded")
    with actionable recommendations based on current workload.

    Args:
        user_id: Optional user identifier

    Returns:
        Dictionary with state, intensity, recommendations, and workload
    """
    return await app_context.realtime_tools.get_cognitive_state(user_id)


@mcp.tool()
async def get_workload_trend(minutes: int = 5, user_id: Optional[str] = None) -> dict:
    """Get workload trend over recent time period.

    Args:
        minutes: Number of minutes to look back (default: 5)
        user_id: Optional user identifier

    Returns:
        Dictionary with trend data, statistics, and sample values
    """
    return await app_context.realtime_tools.get_workload_trend(minutes, user_id)


@mcp.tool()
async def query_workload_history(
    minutes: int = 10,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> dict:
    """Query historical workload predictions from database.

    Args:
        minutes: Number of minutes to look back (default: 10)
        user_id: Optional filter by user
        session_id: Optional filter by session

    Returns:
        Dictionary with historical samples and statistics
    """
    return await app_context.history_tools.query_workload_history(minutes, user_id, session_id)


@mcp.tool()
async def get_session_summary(session_id: str) -> dict:
    """Get summary statistics for a recording session.

    Args:
        session_id: Session UUID

    Returns:
        Dictionary with session info and statistics
    """
    return await app_context.history_tools.get_session_summary(session_id)


@mcp.tool()
async def analyze_cognitive_patterns(
    start: str,
    end: str,
    user_id: Optional[str] = None
) -> dict:
    """Analyze cognitive patterns over a time range.

    Args:
        start: Start time in ISO format (e.g., "2025-01-10T10:00:00")
        end: End time in ISO format
        user_id: Optional filter by user

    Returns:
        Dictionary with pattern analysis (trends, high/low load periods)
    """
    return await app_context.history_tools.analyze_cognitive_patterns(start, end, user_id)


@mcp.tool()
async def get_recent_events(
    limit: int = 10,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> dict:
    """Get recent annotated events.

    Args:
        limit: Maximum number of events to return (default: 10)
        user_id: Optional filter by user
        session_id: Optional filter by session

    Returns:
        Dictionary with events list
    """
    return await app_context.history_tools.get_recent_events(limit, user_id, session_id)


@mcp.tool()
async def annotate_event(
    label: str,
    notes: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> dict:
    """Annotate an event in the current session.

    Useful for marking significant moments during data collection
    (e.g., "task_start", "break", "difficult_problem").

    Args:
        label: Event label/type
        notes: Optional description
        session_id: Session UUID (uses most recent if not specified)
        user_id: User identifier (for finding session if session_id not provided)

    Returns:
        Dictionary with event info
    """
    return await app_context.session_tools.annotate_event(label, notes, session_id, user_id)


@mcp.tool()
async def get_active_sessions(user_id: Optional[str] = None) -> dict:
    """Get list of currently active recording sessions.

    Args:
        user_id: Optional filter by user

    Returns:
        Dictionary with active sessions list
    """
    return await app_context.session_tools.get_active_sessions(user_id)


@mcp.tool()
async def end_session(session_id: str, notes: Optional[str] = None) -> dict:
    """End a recording session.

    Args:
        session_id: Session UUID to end
        notes: Optional closing notes

    Returns:
        Dictionary with session info
    """
    return await app_context.session_tools.end_session(session_id, notes)


@mcp.tool()
async def get_buffer_status() -> dict:
    """Get current buffer status and statistics.

    Returns statistics for all active session buffers including
    sample counts, timestamps, and buffer usage.

    Returns:
        Dictionary with buffer statistics
    """
    return await app_context.realtime_tools.get_buffer_status()


@mcp.tool()
async def list_classifiers() -> dict:
    """List available classification models.

    Returns:
        Dictionary with available classifiers and their metadata
    """
    classifiers_info = []

    for name, classifier in app_context.websocket_server.classifiers.items():
        info = classifier.get_metadata()
        classifiers_info.append({
            "name": name,
            "type": info.get("type"),
            "version": info.get("version"),
            "description": info.get("description"),
        })

    return {
        "classifiers": classifiers_info,
        "count": len(classifiers_info),
        "default": config["classifiers"]["default"],
    }


@mcp.tool()
async def get_server_stats() -> dict:
    """Get ZanderMCP server statistics.

    Returns connection info, buffer stats, and system status.

    Returns:
        Dictionary with server statistics
    """
    ws_stats = await app_context.websocket_server.get_stats()
    buffer_stats = await app_context.realtime_tools.get_buffer_status()

    return {
        "websocket": ws_stats,
        "buffers": buffer_stats,
        "classifiers_loaded": len(app_context.websocket_server.classifiers),
        "config": {
            "max_connections": config["websocket"]["max_connections"],
            "buffer_size": 1000,  # TODO: make configurable
            "database_connected": app_context.db_manager is not None,
        },
    }


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("ZanderMCP - Brain-Computer Interface MCP Server")
    logger.info("=" * 60)

    try:
        # Run FastMCP server
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
