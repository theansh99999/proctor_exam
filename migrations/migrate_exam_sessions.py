"""
migrations/migrate_exam_sessions.py
-----------------------------------
Safe, reversible migration to create:
- exam_sessions (multi-attempt tracking, overall_deadline, status)
- question_sessions (question-level deadlines, row locking, answer persistence)

Compatible with both PostgreSQL and SQLite.
DO NOT RUN ON PRODUCTION WITHOUT EXPLICIT APPROVAL.
"""

import sys
import os
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import models
from database import SessionLocal

def upgrade(db=None) -> dict:
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    elif hasattr(db, "connect") and not hasattr(db, "get_bind"):
        SessionMaker = sessionmaker(bind=db)
        db = SessionMaker()
        should_close = True

    try:
        bind = db.get_bind()
        inspector = inspect(bind)
        existing_tables = inspector.get_table_names()

        # Create exam_sessions if missing
        if "exam_sessions" not in existing_tables:
            print("[MIGRATION] Creating exam_sessions table...")
            models.ExamSession.__table__.create(bind=bind, checkfirst=True)

        # Create question_sessions if missing
        if "question_sessions" not in existing_tables:
            print("[MIGRATION] Creating question_sessions table...")
            models.QuestionSession.__table__.create(bind=bind, checkfirst=True)

        db.commit()
        result = {
            "status": "success",
            "action": "upgrade",
            "tables_created": ["exam_sessions", "question_sessions"]
        }
        print(f"[MIGRATION] Upgrade complete: {result}")
        return result
    except Exception as e:
        db.rollback()
        print(f"[MIGRATION] Upgrade failed: {e}")
        raise
    finally:
        if should_close:
            db.close()

def downgrade(db=None) -> dict:
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    elif hasattr(db, "connect") and not hasattr(db, "get_bind"):
        SessionMaker = sessionmaker(bind=db)
        db = SessionMaker()
        should_close = True

    try:
        bind = db.get_bind()
        inspector = inspect(bind)
        is_postgres = (bind.dialect.name == "postgresql")
        existing_tables = inspector.get_table_names()

        if is_postgres:
            print("[MIGRATION] Dropping question_sessions and exam_sessions tables with CASCADE...")
            db.execute(text("DROP TABLE IF EXISTS question_sessions CASCADE;"))
            db.execute(text("DROP TABLE IF EXISTS exam_sessions CASCADE;"))
        else:
            if "question_sessions" in existing_tables:
                print("[MIGRATION] Dropping question_sessions table...")
                models.QuestionSession.__table__.drop(bind=bind, checkfirst=True)

            if "exam_sessions" in existing_tables:
                print("[MIGRATION] Dropping exam_sessions table...")
                models.ExamSession.__table__.drop(bind=bind, checkfirst=True)

        db.commit()
        result = {
            "status": "success",
            "action": "downgrade",
            "tables_dropped": ["question_sessions", "exam_sessions"]
        }
        print(f"[MIGRATION] Downgrade complete: {result}")
        return result
    except Exception as e:
        db.rollback()
        print(f"[MIGRATION] Downgrade failed: {e}")
        raise
    finally:
        if should_close:
            db.close()

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    if action == "downgrade":
        downgrade()
    else:
        upgrade()
