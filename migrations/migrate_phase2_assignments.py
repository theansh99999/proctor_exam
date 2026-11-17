"""

migrations/migrate_phase2_assignments.py

----------------------------------------

Phase 2 Assessment Management Migration:

- Creates assessment_assignments table for individual candidates and group assignments

- Adds instructions, randomize_questions, enable_negative_marking, visibility to exams table

- Safe and reversible (upgrade and downgrade)

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



        # 1. Add new columns to exams

        exam_cols = [c["name"] for c in inspector.get_columns("exams")]

        columns_to_add = [

            ("instructions", "TEXT", "TEXT"),

            ("randomize_questions", "BOOLEAN DEFAULT FALSE", "BOOLEAN DEFAULT 0"),

            ("enable_negative_marking", "BOOLEAN DEFAULT FALSE", "BOOLEAN DEFAULT 0"),

            ("visibility", "VARCHAR DEFAULT 'group_only'", "VARCHAR DEFAULT 'group_only'")

        ]



        added_cols = []

        for col_name, pg_type, sqlite_type in columns_to_add:

            if col_name not in exam_cols:

                col_type = pg_type if is_postgres else sqlite_type

                db.execute(text(f"ALTER TABLE exams ADD COLUMN {col_name} {col_type}"))

                added_cols.append(col_name)



        if is_postgres:

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exams_visibility ON exams(visibility)"))

        db.commit()



        # 2. Create assessment_assignments table if not exists

        if "assessment_assignments" not in existing_tables:

            print("[MIGRATION] Creating assessment_assignments table...")

            models.AssessmentAssignment.__table__.create(bind=bind, checkfirst=True)

            db.commit()



        result = {

            "status": "success",

            "action": "upgrade",

            "table_created": "assessment_assignments",

            "columns_added_to_exams": added_cols

        }

        print(f"[MIGRATION] Phase 2 upgrade complete: {result}")

        return result

    except Exception as e:

        db.rollback()

        print(f"[MIGRATION] Phase 2 upgrade failed: {e}")

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

        inspector = inspect(bind)



        print("[MIGRATION] Dropping assessment_assignments table...")

        if is_postgres:

            db.execute(text("DROP TABLE IF EXISTS assessment_assignments CASCADE"))

            print("[MIGRATION] Dropping Phase 2 columns from exams...")

            db.execute(text("""

                ALTER TABLE exams

                DROP COLUMN IF EXISTS visibility,

                DROP COLUMN IF EXISTS enable_negative_marking,

                DROP COLUMN IF EXISTS randomize_questions,

                DROP COLUMN IF EXISTS instructions

            """))

            db.commit()

        else:

            if "assessment_assignments" in inspector.get_table_names():

                models.AssessmentAssignment.__table__.drop(bind=bind, checkfirst=True)

            db.commit()



        result = {

            "status": "success",

            "action": "downgrade"

        }

        print(f"[MIGRATION] Phase 2 downgrade complete: {result}")

        return result

    except Exception as e:

        db.rollback()

        print(f"[MIGRATION] Phase 2 downgrade failed: {e}")

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
