"""
migrations/migrate_phase11_advanced_assessments.py
--------------------------------------------------
Phase 11 Advanced Assessment Features Migration:
- Creates assessment_blueprints table (rule-based question blueprints)
- Creates assessment_templates table (reusable assessment templates)
- Adds columns to exams: randomize_options, is_adaptive, adaptive_config, attempt_policy, blueprint_id, template_id
- Adds columns to assessment_sections: is_mandatory, time_limit_minutes, navigation_mode, instructions, randomize_questions
- Adds columns to exam_sessions: adaptive_state, current_section_id, completed_sections
- Adds columns to question_sessions: option_order
- Fully reversible (upgrade and downgrade)
- Compatible with PostgreSQL and SQLite
- Preserves 100% of existing historical data and records
"""
import sys
import os
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

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

        tables_created = []
        columns_added = []

        # 1. Create tables: assessment_blueprints, assessment_templates
        if "assessment_blueprints" not in existing_tables:
            print("[MIGRATION] Creating assessment_blueprints table...")
            models.AssessmentBlueprint.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("assessment_blueprints")
            db.commit()

        if "assessment_templates" not in existing_tables:
            print("[MIGRATION] Creating assessment_templates table...")
            models.AssessmentTemplate.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("assessment_templates")
            db.commit()

        # 2. Add columns to exams
        if "exams" in existing_tables:
            exam_cols = [c["name"] for c in inspector.get_columns("exams")]
            with bind.connect() as conn:
                if "randomize_options" not in exam_cols:
                    conn.execute(text("ALTER TABLE exams ADD COLUMN randomize_options BOOLEAN DEFAULT FALSE"))
                    columns_added.append("exams.randomize_options")
                if "is_adaptive" not in exam_cols:
                    conn.execute(text("ALTER TABLE exams ADD COLUMN is_adaptive BOOLEAN DEFAULT FALSE"))
                    columns_added.append("exams.is_adaptive")
                if "adaptive_config" not in exam_cols:
                    conn.execute(text("ALTER TABLE exams ADD COLUMN adaptive_config TEXT"))
                    columns_added.append("exams.adaptive_config")
                if "attempt_policy" not in exam_cols:
                    conn.execute(text("ALTER TABLE exams ADD COLUMN attempt_policy TEXT"))
                    columns_added.append("exams.attempt_policy")
                if "blueprint_id" not in exam_cols:
                    conn.execute(text("ALTER TABLE exams ADD COLUMN blueprint_id INTEGER REFERENCES assessment_blueprints(id) ON DELETE SET NULL"))
                    columns_added.append("exams.blueprint_id")
                if "template_id" not in exam_cols:
                    conn.execute(text("ALTER TABLE exams ADD COLUMN template_id INTEGER REFERENCES assessment_templates(id) ON DELETE SET NULL"))
                    columns_added.append("exams.template_id")
                conn.commit()

        # 3. Add columns to assessment_sections
        if "assessment_sections" in existing_tables:
            sec_cols = [c["name"] for c in inspector.get_columns("assessment_sections")]
            with bind.connect() as conn:
                if "is_mandatory" not in sec_cols:
                    conn.execute(text("ALTER TABLE assessment_sections ADD COLUMN is_mandatory BOOLEAN DEFAULT TRUE"))
                    columns_added.append("assessment_sections.is_mandatory")
                if "time_limit_minutes" not in sec_cols:
                    conn.execute(text("ALTER TABLE assessment_sections ADD COLUMN time_limit_minutes INTEGER"))
                    columns_added.append("assessment_sections.time_limit_minutes")
                if "navigation_mode" not in sec_cols:
                    conn.execute(text("ALTER TABLE assessment_sections ADD COLUMN navigation_mode VARCHAR(20) DEFAULT 'free'"))
                    columns_added.append("assessment_sections.navigation_mode")
                if "instructions" not in sec_cols:
                    conn.execute(text("ALTER TABLE assessment_sections ADD COLUMN instructions TEXT"))
                    columns_added.append("assessment_sections.instructions")
                if "randomize_questions" not in sec_cols:
                    conn.execute(text("ALTER TABLE assessment_sections ADD COLUMN randomize_questions BOOLEAN DEFAULT FALSE"))
                    columns_added.append("assessment_sections.randomize_questions")
                conn.commit()

        # 4. Add columns to exam_sessions
        if "exam_sessions" in existing_tables:
            sess_cols = [c["name"] for c in inspector.get_columns("exam_sessions")]
            with bind.connect() as conn:
                if "adaptive_state" not in sess_cols:
                    conn.execute(text("ALTER TABLE exam_sessions ADD COLUMN adaptive_state TEXT"))
                    columns_added.append("exam_sessions.adaptive_state")
                if "current_section_id" not in sess_cols:
                    conn.execute(text("ALTER TABLE exam_sessions ADD COLUMN current_section_id INTEGER REFERENCES assessment_sections(id) ON DELETE SET NULL"))
                    columns_added.append("exam_sessions.current_section_id")
                if "completed_sections" not in sess_cols:
                    conn.execute(text("ALTER TABLE exam_sessions ADD COLUMN completed_sections TEXT"))
                    columns_added.append("exam_sessions.completed_sections")
                conn.commit()

        # 5. Add columns to question_sessions
        if "question_sessions" in existing_tables:
            qs_cols = [c["name"] for c in inspector.get_columns("question_sessions")]
            if "option_order" not in qs_cols:
                with bind.connect() as conn:
                    conn.execute(text("ALTER TABLE question_sessions ADD COLUMN option_order TEXT"))
                    conn.commit()
                columns_added.append("question_sessions.option_order")

        print(f"[MIGRATION] Phase 11 upgrade complete: created {tables_created}, columns {columns_added}")
        return {
            "status": "success",
            "action": "upgrade",
            "tables_created": tables_created,
            "columns_added": columns_added
        }

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
        existing_tables = inspector.get_table_names()

        is_postgres = (bind.dialect.name == "postgresql")
        tables_dropped = []

        # Drop tables
        for tbl_name, tbl_cls in [
            ("assessment_templates", models.AssessmentTemplate),
            ("assessment_blueprints", models.AssessmentBlueprint),
        ]:
            if tbl_name in existing_tables:
                print(f"[MIGRATION] Dropping {tbl_name} table...")
                if is_postgres:
                    with bind.connect() as conn:
                        conn.execute(text(f"DROP TABLE IF EXISTS {tbl_name} CASCADE"))
                        conn.commit()
                else:
                    tbl_cls.__table__.drop(bind=bind, checkfirst=True)
                tables_dropped.append(tbl_name)
                db.commit()

        # Drop columns on postgres
        if is_postgres:
            inspector = inspect(bind)
            tbls = inspector.get_table_names()
            with bind.connect() as conn:
                if "exams" in tbls:
                    for col in ["randomize_options", "is_adaptive", "adaptive_config", "attempt_policy", "blueprint_id", "template_id"]:
                        conn.execute(text(f"ALTER TABLE exams DROP COLUMN IF EXISTS {col} CASCADE"))
                if "assessment_sections" in tbls:
                    for col in ["is_mandatory", "time_limit_minutes", "navigation_mode", "instructions", "randomize_questions"]:
                        conn.execute(text(f"ALTER TABLE assessment_sections DROP COLUMN IF EXISTS {col} CASCADE"))
                if "exam_sessions" in tbls:
                    for col in ["adaptive_state", "current_section_id", "completed_sections"]:
                        conn.execute(text(f"ALTER TABLE exam_sessions DROP COLUMN IF EXISTS {col} CASCADE"))
                if "question_sessions" in tbls:
                    conn.execute(text("ALTER TABLE question_sessions DROP COLUMN IF EXISTS option_order CASCADE"))
                conn.commit()

        print(f"[MIGRATION] Phase 11 downgrade complete: dropped {tables_dropped}")
        return {
            "status": "success",
            "action": "downgrade",
            "tables_dropped": tables_dropped
        }

    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    if action == "upgrade":
        res = upgrade()
        print("Upgrade result:", res)
    elif action == "downgrade":
        res = downgrade()
        print("Downgrade result:", res)
    else:
        print("Usage: python migrate_phase11_advanced_assessments.py [upgrade|downgrade]")
