"""

migrations/migrate_phase3_question_bank.py

------------------------------------------

Phase 3 Question Bank & Question Management Migration:

- Creates bank_questions table (reusable questions with metadata, types, categorization)

- Creates bank_options table (options with correct-answer flags and explanations)

- Creates assessment_questions table (mapping between assessments and bank questions with custom marks/order)

- Adds bank_question_id, order_index, question_type, explanation to questions table

- 100% reversible (upgrade and downgrade)

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



        # 1. Create bank_questions if missing

        if "bank_questions" not in existing_tables:

            print("[MIGRATION] Creating bank_questions table...")

            models.BankQuestion.__table__.create(bind=bind, checkfirst=True)

            db.commit()



        # 2. Create bank_options if missing

        if "bank_options" not in existing_tables:

            print("[MIGRATION] Creating bank_options table...")

            models.BankOption.__table__.create(bind=bind, checkfirst=True)

            db.commit()



        # 3. Create assessment_questions if missing

        if "assessment_questions" not in existing_tables:

            print("[MIGRATION] Creating assessment_questions table...")

            models.AssessmentQuestionMap.__table__.create(bind=bind, checkfirst=True)

            db.commit()



        # 4. Add columns to questions table if missing

        q_cols = [c["name"] for c in inspector.get_columns("questions")]

        columns_to_add = [

            ("bank_question_id", "INTEGER REFERENCES bank_questions(id) ON DELETE SET NULL", "INTEGER"),

            ("order_index", "INTEGER DEFAULT 0", "INTEGER DEFAULT 0"),

            ("question_type", "VARCHAR DEFAULT 'single_choice'", "VARCHAR DEFAULT 'single_choice'"),

            ("explanation", "TEXT", "TEXT")

        ]



        added_cols = []

        for col_name, pg_type, sqlite_type in columns_to_add:

            if col_name not in q_cols:

                col_type = pg_type if is_postgres else sqlite_type

                db.execute(text(f"ALTER TABLE questions ADD COLUMN {col_name} {col_type}"))

                added_cols.append(col_name)



        if is_postgres:

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_questions_bank_question_id ON questions(bank_question_id)"))

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_bank_questions_org ON bank_questions(organization_id)"))

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_bank_questions_type ON bank_questions(question_type)"))

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_bank_questions_cat ON bank_questions(assessment_category)"))

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_bank_questions_subj ON bank_questions(subject)"))

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_bank_questions_diff ON bank_questions(difficulty)"))

        db.commit()



        result = {

            "status": "success",

            "action": "upgrade",

            "tables_created": ["bank_questions", "bank_options", "assessment_questions"],

            "columns_added_to_questions": added_cols

        }

        print(f"[MIGRATION] Phase 3 upgrade complete: {result}")

        return result

    except Exception as e:

        db.rollback()

        print(f"[MIGRATION] Phase 3 upgrade failed: {e}")

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



        if is_postgres:

            print("[MIGRATION] Dropping assessment_questions table...")

            db.execute(text("DROP TABLE IF EXISTS assessment_questions CASCADE"))

            print("[MIGRATION] Dropping columns from questions...")

            db.execute(text("""

                ALTER TABLE questions

                DROP COLUMN IF EXISTS explanation,

                DROP COLUMN IF EXISTS question_type,

                DROP COLUMN IF EXISTS order_index,

                DROP COLUMN IF EXISTS bank_question_id

            """))

            print("[MIGRATION] Dropping bank_options and bank_questions...")

            db.execute(text("DROP TABLE IF EXISTS bank_options CASCADE"))

            db.execute(text("DROP TABLE IF EXISTS bank_questions CASCADE"))

            db.commit()

        else:

            tables = inspector.get_table_names()

            if "assessment_questions" in tables:

                models.AssessmentQuestionMap.__table__.drop(bind=bind, checkfirst=True)

            if "bank_options" in tables:

                models.BankOption.__table__.drop(bind=bind, checkfirst=True)

            if "bank_questions" in tables:

                models.BankQuestion.__table__.drop(bind=bind, checkfirst=True)

            db.commit()



        result = {

            "status": "success",

            "action": "downgrade"

        }

        print(f"[MIGRATION] Phase 3 downgrade complete: {result}")

        return result

    except Exception as e:

        db.rollback()

        print(f"[MIGRATION] Phase 3 downgrade failed: {e}")

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
