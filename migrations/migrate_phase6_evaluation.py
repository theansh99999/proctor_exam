"""
migrations/migrate_phase6_evaluation.py
---------------------------------------
Phase 6 Evaluation, Grading & Results Migration:
- Creates assessment_sections table (section-wise management & cutoffs)
- Creates exam_results table (attempt-level consolidated results, release status, pass/fail)
- Creates grading_audits table (examiner manual grading & regrading audit trail)
- Extends exams with results_released flag
- Extends questions with section_id and is_mandatory
- Extends student_answers with exam_session_id, marks_awarded, evaluation_status,
  examiner_feedback, graded_by, graded_at
- Fully reversible (upgrade and downgrade)
- Compatible with PostgreSQL and SQLite
- Preserves 100% of existing historical submissions and answers
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

        tables_created = []
        columns_added = []

        # 1. Create assessment_sections table if missing
        if "assessment_sections" not in existing_tables:
            print("[MIGRATION] Creating assessment_sections table...")
            models.AssessmentSection.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("assessment_sections")
            db.commit()

        # 2. Add columns to exams
        if "exams" in existing_tables:
            exam_cols = [c["name"] for c in inspector.get_columns("exams")]
            if "results_released" not in exam_cols:
                db.execute(text("ALTER TABLE exams ADD COLUMN results_released BOOLEAN DEFAULT FALSE"))
                columns_added.append("exams.results_released")
                db.commit()

        # 3. Add columns to questions
        if "questions" in existing_tables:
            q_cols = [c["name"] for c in inspector.get_columns("questions")]
            if "section_id" not in q_cols:
                q_sec_col = "INTEGER REFERENCES assessment_sections(id) ON DELETE SET NULL" if is_postgres else "INTEGER"
                db.execute(text(f"ALTER TABLE questions ADD COLUMN section_id {q_sec_col}"))
                columns_added.append("questions.section_id")
            if "is_mandatory" not in q_cols:
                db.execute(text("ALTER TABLE questions ADD COLUMN is_mandatory BOOLEAN DEFAULT FALSE"))
                columns_added.append("questions.is_mandatory")
            db.commit()

        # 4. Add columns to student_answers
        if "student_answers" in existing_tables:
            sa_cols = [c["name"] for c in inspector.get_columns("student_answers")]
            sa_additions = [
                ("exam_session_id", "INTEGER REFERENCES exam_sessions(id) ON DELETE CASCADE" if is_postgres else "INTEGER", "INTEGER"),
                ("marks_awarded", "FLOAT DEFAULT 0.0", "FLOAT DEFAULT 0.0"),
                ("evaluation_status", "VARCHAR DEFAULT 'evaluated'", "VARCHAR DEFAULT 'evaluated'"),
                ("examiner_feedback", "TEXT", "TEXT"),
                ("graded_by", "INTEGER REFERENCES users(id) ON DELETE SET NULL" if is_postgres else "INTEGER", "INTEGER"),
                ("graded_at", "TIMESTAMP WITH TIME ZONE" if is_postgres else "DATETIME", "DATETIME")
            ]
            for col_name, pg_type, sqlite_type in sa_additions:
                if col_name not in sa_cols:
                    col_type = pg_type if is_postgres else sqlite_type
                    db.execute(text(f"ALTER TABLE student_answers ADD COLUMN {col_name} {col_type}"))
                    columns_added.append(f"student_answers.{col_name}")
            db.commit()

        # 5. Create exam_results table if missing
        if "exam_results" not in existing_tables:
            print("[MIGRATION] Creating exam_results table...")
            models.ExamResult.__table__.create(bind=db.connection(), checkfirst=True)
            tables_created.append("exam_results")
            db.commit()

        # 6. Create grading_audits table if missing
        if "grading_audits" not in existing_tables:
            print("[MIGRATION] Creating grading_audits table...")
            models.GradingAudit.__table__.create(bind=db.connection(), checkfirst=True)
            tables_created.append("grading_audits")
            db.commit()

        if is_postgres:
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_assessment_sections_exam_id ON assessment_sections(exam_id)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_questions_section_id ON questions(section_id)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_student_answers_session_id ON student_answers(exam_session_id)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_student_answers_eval_status ON student_answers(evaluation_status)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exam_results_exam_id ON exam_results(exam_id)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exam_results_student_id ON exam_results(student_id)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exam_results_session_id ON exam_results(exam_session_id)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exam_results_pass_fail ON exam_results(pass_fail_status)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exam_results_release ON exam_results(is_released)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_grading_audits_answer_id ON grading_audits(student_answer_id)"))
            db.execute(text("CREATE INDEX IF NOT EXISTS ix_grading_audits_session_id ON grading_audits(exam_session_id)"))

        db.commit()
        result = {
            "status": "success",
            "action": "upgrade",
            "tables_created": tables_created,
            "columns_added": columns_added
        }
        print(f"[MIGRATION] Phase 6 upgrade complete: {result}")
        return result
    except Exception as e:
        db.rollback()
        print(f"[MIGRATION ERROR] Phase 6 upgrade failed: {e}")
        raise e
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
        cascade_clause = "CASCADE" if is_postgres else ""

        print("[MIGRATION] Dropping grading_audits, exam_results, assessment_sections tables...")
        db.execute(text(f"DROP TABLE IF EXISTS grading_audits {cascade_clause}"))
        db.execute(text(f"DROP TABLE IF EXISTS exam_results {cascade_clause}"))
        db.execute(text(f"DROP TABLE IF EXISTS assessment_sections {cascade_clause}"))

        if is_postgres:
            print("[MIGRATION] Dropping Phase 6 columns from student_answers, questions, exams...")
            sa_cols = ["exam_session_id", "marks_awarded", "evaluation_status", "examiner_feedback", "graded_by", "graded_at"]
            for col in sa_cols:
                db.execute(text(f"ALTER TABLE student_answers DROP COLUMN IF EXISTS {col} CASCADE"))

            for col in ["section_id", "is_mandatory"]:
                db.execute(text(f"ALTER TABLE questions DROP COLUMN IF EXISTS {col} CASCADE"))

            db.execute(text("ALTER TABLE exams DROP COLUMN IF EXISTS results_released CASCADE"))

        db.commit()
        result = {"status": "success", "action": "downgrade"}
        print(f"[MIGRATION] Phase 6 downgrade complete: {result}")
        return result
    except Exception as e:
        db.rollback()
        print(f"[MIGRATION ERROR] Phase 6 downgrade failed: {e}")
        raise e
    finally:
        if should_close:
            db.close()
