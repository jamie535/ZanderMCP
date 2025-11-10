"""WebSocket server for receiving EEG data from edge relays.

This module handles incoming WebSocket connections from edge relays,
authenticates them, and routes data to the appropriate classifiers and buffers.
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, Optional, Set, Any
from uuid import UUID, uuid4
import logging

try:
    import msgpack
    MSGPACK_AVAILABLE = True
except ImportError:
    MSGPACK_AVAILABLE = False

import websockets
from websockets.server import WebSocketServerProtocol
import numpy as np

from ingestion.stream_buffer import SessionBufferManager
from database.connection import DatabaseManager
from database.persistence import PersistenceManager
from classifiers.base import BaseClassifier

logger = logging.getLogger(__name__)


class WebSocketServer:
    """WebSocket server for edge relay connections."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        api_key: str = None,
        buffer_manager: SessionBufferManager = None,
        db_manager: DatabaseManager = None,
        persistence_manager: PersistenceManager = None,
        classifiers: Dict[str, BaseClassifier] = None,
        max_connections: int = 100,
        heartbeat_interval: float = 30.0,
    ):
        """Initialize WebSocket server.

        Args:
            host: Host to bind to
            port: Port to listen on
            api_key: Required API key for authentication
            buffer_manager: Stream buffer manager
            db_manager: Database manager
            persistence_manager: Persistence manager
            classifiers: Dictionary of available classifiers
            max_connections: Maximum concurrent connections
            heartbeat_interval: Ping interval in seconds
        """
        self.host = host
        self.port = port
        self.api_key = api_key
        self.buffer_manager = buffer_manager
        self.db_manager = db_manager
        self.persistence_manager = persistence_manager
        self.classifiers = classifiers or {}
        self.max_connections = max_connections
        self.heartbeat_interval = heartbeat_interval

        # Active connections
        self.connections: Set[WebSocketServerProtocol] = set()
        self.connection_info: Dict[WebSocketServerProtocol, Dict[str, Any]] = {}

        # Session tracking
        self.active_sessions: Dict[str, UUID] = {}  # user_id -> session_id

        # Server instance
        self.server = None
        self.running = False

    async def start(self):
        """Start the WebSocket server."""
        logger.info(f"Starting WebSocket server on {self.host}:{self.port}")

        self.server = await websockets.serve(
            self.handle_connection,
            self.host,
            self.port,
            ping_interval=self.heartbeat_interval,
            ping_timeout=self.heartbeat_interval * 2,
        )

        self.running = True
        logger.info(f"WebSocket server listening on ws://{self.host}:{self.port}")

    async def stop(self):
        """Stop the WebSocket server and close all connections."""
        logger.info("Stopping WebSocket server")
        self.running = False

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # Close all active connections
        for ws in list(self.connections):
            await ws.close()

        logger.info("WebSocket server stopped")

    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """Handle a new WebSocket connection.

        Args:
            websocket: WebSocket connection
            path: Request path
        """
        remote_addr = websocket.remote_address
        logger.info(f"New connection from {remote_addr}")

        # Check connection limit
        if len(self.connections) >= self.max_connections:
            logger.warning(f"Connection limit reached, rejecting {remote_addr}")
            await websocket.close(1008, "Server at capacity")
            return

        # Authenticate
        try:
            user_id = await self._authenticate(websocket)
            if not user_id:
                logger.warning(f"Authentication failed for {remote_addr}")
                await websocket.close(1008, "Authentication failed")
                return
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            await websocket.close(1011, "Authentication error")
            return

        # Register connection
        self.connections.add(websocket)
        self.connection_info[websocket] = {
            "user_id": user_id,
            "connected_at": datetime.utcnow(),
            "messages_received": 0,
        }

        # Get or create session
        session_id = await self._get_or_create_session(user_id)
        self.connection_info[websocket]["session_id"] = session_id

        logger.info(f"Client authenticated: user={user_id}, session={session_id}")

        try:
            # Handle messages
            async for message in websocket:
                await self._handle_message(websocket, message, user_id, session_id)
                self.connection_info[websocket]["messages_received"] += 1

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection closed: {user_id}")
        except Exception as e:
            logger.error(f"Error handling connection: {e}", exc_info=True)
        finally:
            # Clean up
            self.connections.remove(websocket)
            del self.connection_info[websocket]
            logger.info(f"Client disconnected: {user_id}")

    async def _authenticate(self, websocket: WebSocketServerProtocol) -> Optional[str]:
        """Authenticate a WebSocket connection.

        Expects first message to be JSON with api_key and user_id.

        Args:
            websocket: WebSocket connection

        Returns:
            user_id if authenticated, None otherwise
        """
        try:
            # Wait for auth message with timeout
            auth_message = await asyncio.wait_for(
                websocket.recv(),
                timeout=10.0
            )

            # Parse auth message
            if isinstance(auth_message, bytes):
                auth_data = json.loads(auth_message.decode('utf-8'))
            else:
                auth_data = json.loads(auth_message)

            # Check API key
            if self.api_key and auth_data.get("api_key") != self.api_key:
                logger.warning(f"Invalid API key from {websocket.remote_address}")
                return None

            # Get user_id
            user_id = auth_data.get("user_id")
            if not user_id:
                logger.warning("No user_id provided in auth message")
                return None

            # Send auth success
            await websocket.send(json.dumps({"status": "authenticated", "user_id": user_id}))

            return user_id

        except asyncio.TimeoutError:
            logger.warning("Authentication timeout")
            return None
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return None

    async def _get_or_create_session(self, user_id: str) -> UUID:
        """Get existing session or create a new one for user.

        Args:
            user_id: User identifier

        Returns:
            Session UUID
        """
        # Check if user has active session
        if user_id in self.active_sessions:
            return self.active_sessions[user_id]

        # Create new session
        if self.persistence_manager:
            session = await self.persistence_manager.create_session(
                user_id=user_id,
                notes="Created by WebSocket server"
            )
            session_id = session.session_id
        else:
            session_id = uuid4()

        self.active_sessions[user_id] = session_id
        logger.info(f"Created new session {session_id} for user {user_id}")

        return session_id

    async def _handle_message(
        self,
        websocket: WebSocketServerProtocol,
        message: bytes | str,
        user_id: str,
        session_id: UUID,
    ):
        """Handle an incoming message from edge relay.

        Args:
            websocket: WebSocket connection
            message: Received message
            user_id: User identifier
            session_id: Session UUID
        """
        try:
            # Parse message
            data = await self._parse_message(message)

            # Extract message type
            msg_type = data.get("type", "raw_sample")
            timestamp_str = data.get("timestamp")
            payload = data.get("data")

            # Parse timestamp
            if timestamp_str:
                if isinstance(timestamp_str, str):
                    timestamp = datetime.fromisoformat(timestamp_str)
                elif isinstance(timestamp_str, (int, float)):
                    timestamp = datetime.fromtimestamp(timestamp_str)
                else:
                    timestamp = datetime.utcnow()
            else:
                timestamp = datetime.utcnow()

            # Handle different message types
            if msg_type == "raw_sample":
                await self._handle_raw_sample(payload, timestamp, user_id, session_id)
            elif msg_type == "features":
                await self._handle_features(payload, timestamp, user_id, session_id)
            elif msg_type == "heartbeat":
                await websocket.send(json.dumps({"type": "heartbeat_ack"}))
            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            # Send error back to client
            try:
                await websocket.send(json.dumps({"error": str(e)}))
            except:
                pass

    async def _parse_message(self, message: bytes | str) -> Dict[str, Any]:
        """Parse incoming message (msgpack or JSON).

        Args:
            message: Raw message

        Returns:
            Parsed message dictionary
        """
        if isinstance(message, bytes):
            # Try msgpack first
            if MSGPACK_AVAILABLE:
                try:
                    return msgpack.unpackb(message, raw=False)
                except:
                    pass

            # Fall back to JSON
            try:
                return json.loads(message.decode('utf-8'))
            except:
                raise ValueError("Unable to parse message as msgpack or JSON")
        else:
            # String message, parse as JSON
            return json.loads(message)

    async def _handle_raw_sample(
        self,
        data: Dict[str, Any],
        timestamp: datetime,
        user_id: str,
        session_id: UUID,
    ):
        """Handle raw EEG sample.

        Args:
            data: Sample data (should contain EEG array)
            timestamp: Sample timestamp
            user_id: User identifier
            session_id: Session UUID
        """
        # Convert data to numpy array if needed
        if "channels" in data:
            eeg_data = np.array(data["channels"])
        elif "eeg" in data:
            eeg_data = np.array(data["eeg"])
        else:
            logger.warning("No EEG data in raw_sample")
            return

        # Add to buffer
        if self.buffer_manager:
            await self.buffer_manager.add_sample(
                session_id=session_id,
                timestamp=timestamp,
                data=eeg_data,
                user_id=user_id,
                sample_type="raw",
                metadata={"source": "edge_relay"}
            )

        # TODO: Classify if we have enough data (implement batching logic)
        # For now, we'll classify every sample (not optimal for production)
        if self.classifiers:
            await self._classify_and_store(eeg_data, timestamp, user_id, session_id)

    async def _handle_features(
        self,
        data: Dict[str, Any],
        timestamp: datetime,
        user_id: str,
        session_id: UUID,
    ):
        """Handle preprocessed features from edge relay.

        Args:
            data: Feature dictionary
            timestamp: Sample timestamp
            user_id: User identifier
            session_id: Session UUID
        """
        # Add to buffer
        if self.buffer_manager:
            await self.buffer_manager.add_sample(
                session_id=session_id,
                timestamp=timestamp,
                data=data,
                user_id=user_id,
                sample_type="features",
                metadata={"source": "edge_relay"}
            )

        # TODO: If we have ML classifier that takes features, classify here

    async def _classify_and_store(
        self,
        eeg_data: np.ndarray,
        timestamp: datetime,
        user_id: str,
        session_id: UUID,
    ):
        """Classify EEG data and store prediction.

        Args:
            eeg_data: EEG data array
            timestamp: Sample timestamp
            user_id: User identifier
            session_id: Session UUID
        """
        try:
            # Get default classifier (signal_processing)
            classifier = self.classifiers.get("signal_processing")
            if not classifier:
                logger.warning("No classifier available")
                return

            # Classify
            result = await classifier.predict(eeg_data)

            # Add prediction to buffer
            if self.buffer_manager:
                await self.buffer_manager.add_sample(
                    session_id=session_id,
                    timestamp=timestamp,
                    data=result,
                    user_id=user_id,
                    sample_type="prediction",
                    metadata={
                        "classifier": classifier.name,
                        "version": classifier.version,
                    }
                )

            # Store in database
            if self.persistence_manager:
                await self.persistence_manager.add_prediction(
                    timestamp=timestamp,
                    session_id=session_id,
                    user_id=user_id,
                    classifier_name=classifier.name,
                    workload=result.get("workload"),
                    attention=result.get("attention"),
                    confidence=result.get("confidence"),
                    features=result.get("features"),
                    processing_time_ms=result.get("metadata", {}).get("processing_time_ms"),
                    classifier_version=classifier.version,
                )

        except Exception as e:
            logger.error(f"Classification error: {e}", exc_info=True)

    async def get_stats(self) -> Dict[str, Any]:
        """Get server statistics.

        Returns:
            Dictionary with server stats
        """
        total_messages = sum(
            info["messages_received"] for info in self.connection_info.values()
        )

        return {
            "active_connections": len(self.connections),
            "max_connections": self.max_connections,
            "active_sessions": len(self.active_sessions),
            "total_messages_received": total_messages,
            "uptime": (datetime.utcnow() - min(
                (info["connected_at"] for info in self.connection_info.values()),
                default=datetime.utcnow()
            )).total_seconds() if self.connection_info else 0,
        }
