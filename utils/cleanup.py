import os
import time
import shutil
import asyncio
import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, delete
from db.session import async_session
from db_models import RunSession, Video, AnalysisMeta

logger = logging.getLogger("cleanup")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_SESSION_DIR = os.path.join(BASE_DIR, "data", "run_sessions")

async def cleanup_database_and_files(max_age_seconds: float = 7 * 24 * 3600):
    """
    Query database for expired pending RunSessions (status='pending' and created_at < cutoff)
    and delete their corresponding physical directories and all related DB records (RunSession, Video, AnalysisMeta).
    
    This ensures that abandoned incomplete uploads do not clutter the "Unfinished Uploads" list
    in the UI as ghost items, while preserving all failed/done sessions completely intact.
    """
    logger.info("Starting expired pending sessions cleanup task...")
    try:
        async with async_session() as session:
            cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)
            
            # Select expired pending sessions only
            stmt = select(RunSession).where(
                (RunSession.status == "pending") & 
                (RunSession.created_at < cutoff)
            )
            result = await session.execute(stmt)
            expired_sessions = result.scalars().all()
            
            if not expired_sessions:
                logger.info("No expired pending sessions found.")
                return

            for run_sess in expired_sessions:
                run_session_id = str(run_sess.id)
                runner_id = str(run_sess.runner_id)
                
                # 1. Delete physical folder in run_sessions
                run_session_dir = os.path.join(RUN_SESSION_DIR, runner_id, run_session_id)
                if os.path.exists(run_session_dir):
                    logger.info(f"Deleting expired pending session folder: {run_session_dir}")
                    try:
                        shutil.rmtree(run_session_dir)
                    except Exception as e:
                        logger.error(f"Failed to delete directory {run_session_dir}: {e}")
                
                # 2. Delete all DB records for this pending session
                try:
                    # Delete corresponding Video records
                    await session.execute(delete(Video).where(Video.run_session_id == run_sess.id))
                    # Delete corresponding AnalysisMeta records
                    await session.execute(delete(AnalysisMeta).where(AnalysisMeta.run_session_id == run_sess.id))
                    # Delete the RunSession itself
                    await session.delete(run_sess)
                    logger.info(f"Deleted expired pending RunSession & Videos from database: {run_session_id}")
                except Exception as e:
                    logger.error(f"Failed to delete database records for session {run_session_id}: {e}")
            
            await session.commit()
    except Exception as e:
        logger.error(f"Error during pending session database cleanup: {e}")

async def cleanup_temp_dir_loop(temp_dir: str):
    """
    Periodically clean up files in temp_dir that are older than 24 hours (1 day).
    Also removes expired pending sessions (older than 7 days) entirely.
    Runs every 12 hours.
    """
    # 1 day (24 hours) buffer for temporary files in uploads_temp
    temp_max_age_seconds = 24 * 3600
    # 7 days buffer for incomplete pending sessions
    session_max_age_seconds = 7 * 24 * 3600

    logger.info(f"Starting temp dir cleanup loop for: {temp_dir}")
    while True:
        # 1. Clean up temp files (abandoned uploads before session creation)
        try:
            if os.path.exists(temp_dir):
                now = time.time()
                for filename in os.listdir(temp_dir):
                    file_path = os.path.join(temp_dir, filename)
                    if os.path.isfile(file_path):
                        mtime = os.path.getmtime(file_path)
                        age = now - mtime
                        if age > temp_max_age_seconds:
                            logger.info(f"Deleting expired temp file: {filename} (age: {age/3600:.1f} hours)")
                            try:
                                os.remove(file_path)
                            except Exception as e:
                                logger.error(f"Failed to delete {filename}: {e}")
        except Exception as e:
            logger.error(f"Error in temp files cleanup: {e}")
        
        # 2. Clean up database records and folders of expired pending sessions
        await cleanup_database_and_files(session_max_age_seconds)
        
        # Sleep for 12 hours
        await asyncio.sleep(12 * 3600)
