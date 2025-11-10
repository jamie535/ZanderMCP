"""Session management MCP tools.

These tools provide session control and event annotation capabilities.
"""

from datetime import datetime
from typing import Dict, Any, Optional
from uuid import UUID
import logging

from sqlalchemy import select

from database.connection import DatabaseManager
from database.persistence import PersistenceManager
from database.models import Session, Event

logger = logging.getLogger(__name__)


class SessionTools:
    """MCP tools for session management and annotation."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        persistence_manager: PersistenceManager,
    ):
        """Initialize session tools.

        Args:
            db_manager: Database manager
            persistence_manager: Persistence manager
        """
        self.db = db_manager
        self.persistence = persistence_manager

    async def annotate_event(
        self,
        label: str,
        notes: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Annotate an event in the current session.

        This is useful for marking significant moments during data collection
        (e.g., "task_start", "break", "difficult_problem", etc.)

        Args:
            label: Event label/type
            notes: Optional description
            session_id: Session UUID (uses most recent if not specified)
            user_id: User identifier (for finding session)
            metadata: Optional additional metadata

        Returns:
            Dictionary with event info
        """
        try:
            # Get session ID if not provided
            if not session_id:
                if not user_id:
                    return {
                        "error": "Must provide either session_id or user_id",
                        "event_id": None,
                    }

                # Find most recent active session for user
                async with self.db.session() as db_session:
                    query = select(Session).where(
                        Session.user_id == user_id,
                        Session.end_time.is_(None)
                    ).order_by(Session.start_time.desc()).limit(1)

                    result = await db_session.execute(query)
                    session_record = result.scalar_one_or_none()

                    if not session_record:
                        return {
                            "error": f"No active session found for user {user_id}",
                            "event_id": None,
                        }

                    session_id = str(session_record.session_id)

            # Create event
            event = await self.persistence.add_event(
                session_id=UUID(session_id),
                timestamp=datetime.utcnow(),
                label=label,
                notes=notes,
                event_metadata=metadata,
            )

            logger.info(f"Event annotated: {label} in session {session_id}")

            return {
                "event_id": str(event.event_id),
                "session_id": str(event.session_id),
                "timestamp": event.timestamp.isoformat(),
                "label": event.label,
                "notes": event.notes,
            }

        except Exception as e:
            logger.error(f"Error annotating event: {e}", exc_info=True)
            return {
                "error": str(e),
                "event_id": None,
            }

    async def end_session(
        self,
        session_id: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """End a recording session.

        Args:
            session_id: Session UUID to end
            notes: Optional closing notes

        Returns:
            Dictionary with session info
        """
        try:
            session_uuid = UUID(session_id)

            async with self.db.session() as db_session:
                # Get session
                query = select(Session).where(Session.session_id == session_uuid)
                result = await db_session.execute(query)
                session_record = result.scalar_one_or_none()

                if not session_record:
                    return {
                        "error": f"Session {session_id} not found",
                        "session_id": None,
                    }

                if session_record.end_time:
                    return {
                        "error": f"Session {session_id} already ended",
                        "session_id": str(session_record.session_id),
                        "end_time": session_record.end_time.isoformat(),
                    }

                # End session
                session_record.end_time = datetime.utcnow()

                if notes:
                    if session_record.notes:
                        session_record.notes += f"\n\nClosing notes: {notes}"
                    else:
                        session_record.notes = notes

                # Calculate total samples (from predictions count)
                # This would ideally come from tracking during the session
                # For now, we'll leave it as is

                await db_session.commit()

            logger.info(f"Session ended: {session_id}")

            return {
                "session_id": str(session_record.session_id),
                "user_id": session_record.user_id,
                "start_time": session_record.start_time.isoformat(),
                "end_time": session_record.end_time.isoformat(),
                "duration_seconds": (
                    session_record.end_time - session_record.start_time
                ).total_seconds(),
                "notes": session_record.notes,
            }

        except Exception as e:
            logger.error(f"Error ending session: {e}", exc_info=True)
            return {
                "error": str(e),
                "session_id": None,
            }

    async def get_active_sessions(
        self,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get list of currently active sessions.

        Args:
            user_id: Optional filter by user

        Returns:
            Dictionary with active sessions list
        """
        try:
            async with self.db.session() as session:
                query = select(Session).where(Session.end_time.is_(None))

                if user_id:
                    query = query.where(Session.user_id == user_id)

                query = query.order_by(Session.start_time.desc())

                result = await session.execute(query)
                sessions = result.scalars().all()

                sessions_list = []
                for sess in sessions:
                    duration = (datetime.utcnow() - sess.start_time).total_seconds()

                    sessions_list.append({
                        "session_id": str(sess.session_id),
                        "user_id": sess.user_id,
                        "start_time": sess.start_time.isoformat(),
                        "duration_seconds": duration,
                        "total_samples": sess.total_samples,
                        "notes": sess.notes,
                    })

                return {
                    "sessions": sessions_list,
                    "count": len(sessions_list),
                }

        except Exception as e:
            logger.error(f"Error getting active sessions: {e}", exc_info=True)
            return {
                "error": str(e),
                "sessions": [],
                "count": 0,
            }

    async def create_session(
        self,
        user_id: str,
        notes: Optional[str] = None,
        device_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new recording session.

        Args:
            user_id: User identifier
            notes: Optional session notes
            device_info: Optional device information

        Returns:
            Dictionary with new session info
        """
        try:
            session = await self.persistence.create_session(
                user_id=user_id,
                device_info=device_info,
                notes=notes,
            )

            logger.info(f"Session created: {session.session_id} for user {user_id}")

            return {
                "session_id": str(session.session_id),
                "user_id": session.user_id,
                "start_time": session.start_time.isoformat(),
                "notes": session.notes,
                "device_info": session.device_info,
            }

        except Exception as e:
            logger.error(f"Error creating session: {e}", exc_info=True)
            return {
                "error": str(e),
                "session_id": None,
            }

    async def update_session_notes(
        self,
        session_id: str,
        notes: str,
        append: bool = True,
    ) -> Dict[str, Any]:
        """Update session notes.

        Args:
            session_id: Session UUID
            notes: Notes to add/set
            append: If True, append to existing notes; if False, replace

        Returns:
            Dictionary with updated session info
        """
        try:
            session_uuid = UUID(session_id)

            async with self.db.session() as db_session:
                query = select(Session).where(Session.session_id == session_uuid)
                result = await db_session.execute(query)
                session_record = result.scalar_one_or_none()

                if not session_record:
                    return {
                        "error": f"Session {session_id} not found",
                        "session_id": None,
                    }

                if append and session_record.notes:
                    session_record.notes += f"\n{notes}"
                else:
                    session_record.notes = notes

                await db_session.commit()

            logger.info(f"Session notes updated: {session_id}")

            return {
                "session_id": str(session_record.session_id),
                "notes": session_record.notes,
            }

        except Exception as e:
            logger.error(f"Error updating session notes: {e}", exc_info=True)
            return {
                "error": str(e),
                "session_id": None,
            }

    async def export_session_data(
        self,
        session_id: str,
        format: str = "json",
        include_features: bool = False,
    ) -> Dict[str, Any]:
        """Export session data for offline analysis.

        Args:
            session_id: Session UUID to export
            format: Export format ("json" | "csv")
            include_features: Include raw feature vectors

        Returns:
            Dictionary with export info or error
        """
        try:
            # This is a placeholder for future implementation
            # Full implementation would:
            # 1. Query all predictions for session
            # 2. Optionally query feature vectors
            # 3. Format as JSON or CSV
            # 4. Return download URL or data

            return {
                "error": "Export functionality not yet implemented",
                "session_id": session_id,
                "format": format,
                "note": "Will be implemented in Phase 3",
            }

        except Exception as e:
            logger.error(f"Error exporting session: {e}", exc_info=True)
            return {
                "error": str(e),
                "session_id": None,
            }
