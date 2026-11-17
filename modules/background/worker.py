"""
modules/background/worker.py
----------------------------
Background worker and scheduler for asynchronous and scheduled tasks:
- Scheduled assessment reminders (24h and 1h ahead) with idempotency
- External integration sync retry processing (with retry limits)
- Expired exam session auto-finalization
- Graceful shutdown handling (SIGTERM, SIGINT)
- Idempotent and fail-safe execution
"""
import time
import signal
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import models
from database import SessionLocal
from time_utils import utc_now, to_utc
from modules.notifications.service import NotificationService
from modules.integrations.service import IntegrationService
from routers.student_r import finalize_exam_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("examproctor.worker")

RUNNING = True


def signal_handler(signum, frame):
    global RUNNING
    logger.info("[WORKER] Received shutdown signal (%s). Finishing current jobs...", signum)
    RUNNING = False


class BackgroundWorker:
    def __init__(self, check_interval_seconds: int = 60):
        self.interval = check_interval_seconds
        self.last_reminders_run: Optional[datetime] = None
        self.last_sync_retry_run: Optional[datetime] = None
        self.last_finalization_run: Optional[datetime] = None

    def process_reminders(self, db) -> Dict[str, int]:
        try:
            res = NotificationService.process_scheduled_reminders(db)
            if res.get("reminders_24h", 0) > 0 or res.get("reminders_1h", 0) > 0:
                logger.info("[WORKER] Assessment reminders dispatched: %s", res)
            return res
        except Exception as e:
            logger.error("[WORKER] Error processing assessment reminders: %s", e)
            return {"error": 1}

    def process_failed_sync_retries(self, db) -> int:
        """Retry transient failed external integration syncs up to max retries."""
        retried_count = 0
        try:
            # Query failed sync records that haven't exceeded 3 retries
            failed_syncs = db.query(models.SyncRecord).filter(
                models.SyncRecord.status == "failed",
                models.SyncRecord.retry_count < 3
            ).limit(10).all()

            for sync in failed_syncs:
                sync_id = sync.id
                super_admin = db.query(models.User).filter_by(role="super_admin").first()
                if super_admin:
                    try:
                        IntegrationService.retry_failed_sync(db, sync_id, super_admin)
                        retried_count += 1
                        logger.info("[WORKER] Retried sync record ID %s", sync_id)
                    except Exception as re_err:
                        logger.warning("[WORKER] Retry failed for sync record %s: %s", sync_id, re_err)
        except Exception as e:
            logger.error("[WORKER] Error in sync retry loop: %s", e)
        return retried_count

    def process_expired_session_finalization(self, db) -> int:
        """Find active sessions that exceeded overall deadline and finalize them."""
        finalized_count = 0
        now = utc_now()
        try:
            expired_sessions = db.query(models.ExamSession).filter(
                models.ExamSession.status == "in_progress",
                models.ExamSession.overall_deadline.isnot(None),
                models.ExamSession.overall_deadline < now
            ).limit(20).all()

            for sess in expired_sessions:
                exam = db.query(models.Exam).filter_by(id=sess.exam_id).first()
                student = db.query(models.User).filter_by(id=sess.student_id).first()
                if exam and student:
                    try:
                        finalize_exam_session(db, sess, exam, student, submission_type="auto_submitted")
                        finalized_count += 1
                        logger.info("[WORKER] Auto-finalized expired exam session ID %s", sess.id)
                    except Exception as fin_err:
                        logger.warning("[WORKER] Could not auto-finalize session %s: %s", sess.id, fin_err)
        except Exception as e:
            logger.error("[WORKER] Error in expired session finalization: %s", e)
        return finalized_count

    def run_cycle(self) -> Dict[str, Any]:
        """Execute one complete cycle of background jobs with isolated DB session."""
        db = SessionLocal()
        stats = {}
        try:
            stats["reminders"] = self.process_reminders(db)
            stats["sync_retries"] = self.process_failed_sync_retries(db)
            stats["expired_finalizations"] = self.process_expired_session_finalization(db)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("[WORKER] Cycle error: %s", e)
        finally:
            db.close()
        return stats

    def start(self):
        logger.info("[WORKER] ExamProctor Background Worker started (poll interval: %ds).", self.interval)
        while RUNNING:
            self.run_cycle()
            # Sleep in small increments to respond quickly to SIGINT/SIGTERM
            for _ in range(self.interval):
                if not RUNNING:
                    break
                time.sleep(1)
        logger.info("[WORKER] Worker shutdown gracefully.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    worker = BackgroundWorker(check_interval_seconds=int(sys.argv[1]) if len(sys.argv) > 1 else 30)
    worker.start()
