"""

migrations/migrate_phase4_candidate_engine.py

---------------------------------------------

Phase 4 Candidate Assessment Flow & Exam Engine Migration:

- Adds score, submitted_at, submission_type, question_order to exam_sessions

- Adds answer_text, is_bookmarked to question_sessions

- Adds answer_text to student_answers

- Fully reversible (upgrade and downgrade)

- Compatible with PostgreSQL and SQLite

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

        is_postgres = (bind.dialect.name == "postgresql")

        existing_tables = inspector.get_table_names()



        added_cols = []



        # 1. Columns for exam_sessions

        if "exam_sessions" in existing_tables:

            es_cols = [c["name"] for c in inspector.get_columns("exam_sessions")]

            es_additions = [

                ("score", "FLOAT", "FLOAT"),

                ("submitted_at", "TIMESTAMP WITH TIME ZONE" if is_postgres else "DATETIME", "DATETIME"),

                ("submission_type", "VARCHAR DEFAULT 'manual'", "VARCHAR DEFAULT 'manual'"),

                ("question_order", "TEXT", "TEXT")

            ]

            for col_name, pg_type, sqlite_type in es_additions:

                if col_name not in es_cols:

                    col_type = pg_type if is_postgres else sqlite_type

                    db.execute(text(f"ALTER TABLE exam_sessions ADD COLUMN {col_name} {col_type}"))

                    added_cols.append(f"exam_sessions.{col_name}")



        # 2. Columns for question_sessions

        if "question_sessions" in existing_tables:

            qs_cols = [c["name"] for c in inspector.get_columns("question_sessions")]

            qs_additions = [

                ("answer_text", "TEXT", "TEXT"),

                ("is_bookmarked", "BOOLEAN DEFAULT FALSE", "BOOLEAN DEFAULT 0")

            ]

            for col_name, pg_type, sqlite_type in qs_additions:

                if col_name not in qs_cols:

                    col_type = pg_type if is_postgres else sqlite_type

                    db.execute(text(f"ALTER TABLE question_sessions ADD COLUMN {col_name} {col_type}"))

                    added_cols.append(f"question_sessions.{col_name}")



        # 3. Columns for student_answers

        if "student_answers" in existing_tables:

            sa_cols = [c["name"] for c in inspector.get_columns("student_answers")]

            if "answer_text" not in sa_cols:

                db.execute(text("ALTER TABLE student_answers ADD COLUMN answer_text TEXT"))

                added_cols.append("student_answers.answer_text")



        # 4. Columns for questions

        if "questions" in existing_tables:

            q_cols = [c["name"] for c in inspector.get_columns("questions")]

            if "type_config" not in q_cols:

                db.execute(text("ALTER TABLE questions ADD COLUMN type_config TEXT"))

                added_cols.append("questions.type_config")



        db.commit()

        result = {

            "status": "success",

            "action": "upgrade",

            "columns_added": added_cols

        }

        print(f"[MIGRATION] Phase 4 upgrade complete: {result}")

        return result

    except Exception as e:

        db.rollback()

        print(f"[MIGRATION] Phase 4 upgrade failed: {e}")

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

        is_postgres = (bind.dialect.name == "postgresql")



        if is_postgres:

            print("[MIGRATION] Dropping Phase 4 columns...")

            db.execute(text("""

                ALTER TABLE exam_sessions

                DROP COLUMN IF EXISTS score,

                DROP COLUMN IF EXISTS submitted_at,

                DROP COLUMN IF EXISTS submission_type,

                DROP COLUMN IF EXISTS question_order;

            """))

            db.execute(text("""

                ALTER TABLE question_sessions

                DROP COLUMN IF EXISTS answer_text,

                DROP COLUMN IF EXISTS is_bookmarked;

            """))

            db.execute(text("""

                ALTER TABLE student_answers

                DROP COLUMN IF EXISTS answer_text;

            """))

            db.execute(text("""

                ALTER TABLE questions

                DROP COLUMN IF EXISTS type_config;

            """))

            db.commit()



        result = {

            "status": "success",

            "action": "downgrade"

        }

        print(f"[MIGRATION] Phase 4 downgrade complete: {result}")

        return result

    except Exception as e:

        db.rollback()

        print(f"[MIGRATION] Phase 4 downgrade failed: {e}")

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
