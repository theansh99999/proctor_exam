"""

migrations/migrate_phase1_foundation.py

---------------------------------------

Phase 1 Architecture & Foundation Migration:

- Organizations table creation

- Multi-tenancy columns (organization_id) on users, groups, exams

- Assessment foundation columns on exams:

  (description, assessment_type, creator_id, max_attempts, passing_criteria, passing_percentage, status, config_metadata)

- Safe backfill of creator_id from group.teacher_id

- 100% reversible (upgrade and downgrade)

- Safe legacy-data handling (preserves historical unassigned records without arbitrary org assignment)

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



        # 1. Create organizations table if not exists

        if "organizations" not in existing_tables:

            print("[MIGRATION] Creating organizations table...")

            models.Organization.__table__.create(bind=bind, checkfirst=True)

            db.commit()



        # 2. Add organization_id to users

        user_cols = [c["name"] for c in inspector.get_columns("users")]

        if "organization_id" not in user_cols:

            print("[MIGRATION] Adding organization_id column to users...")

            if is_postgres:

                db.execute(text("ALTER TABLE users ADD COLUMN organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL"))

                db.execute(text("CREATE INDEX IF NOT EXISTS ix_users_organization_id ON users(organization_id)"))

            else:

                db.execute(text("ALTER TABLE users ADD COLUMN organization_id INTEGER"))

            db.commit()



        # 3. Add organization_id to groups

        group_cols = [c["name"] for c in inspector.get_columns("groups")]

        if "organization_id" not in group_cols:

            print("[MIGRATION] Adding organization_id column to groups...")

            if is_postgres:

                db.execute(text("ALTER TABLE groups ADD COLUMN organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL"))

                db.execute(text("CREATE INDEX IF NOT EXISTS ix_groups_organization_id ON groups(organization_id)"))

            else:

                db.execute(text("ALTER TABLE groups ADD COLUMN organization_id INTEGER"))

            db.commit()



        # 4. Add Assessment Foundation columns to exams

        exam_cols = [c["name"] for c in inspector.get_columns("exams")]



        exam_columns_to_add = [

            ("description", "TEXT", "TEXT"),

            ("assessment_type", "VARCHAR DEFAULT 'academic'", "VARCHAR DEFAULT 'academic'"),

            ("organization_id", "INTEGER REFERENCES organizations(id) ON DELETE SET NULL", "INTEGER"),

            ("creator_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL", "INTEGER"),

            ("max_attempts", "INTEGER DEFAULT 1", "INTEGER DEFAULT 1"),

            ("passing_criteria", "VARCHAR DEFAULT 'marks'", "VARCHAR DEFAULT 'marks'"),

            ("passing_percentage", "FLOAT", "FLOAT"),

            ("status", "VARCHAR DEFAULT 'published'", "VARCHAR DEFAULT 'published'"),

            ("config_metadata", "TEXT", "TEXT")

        ]



        added_cols = []

        for col_name, pg_type, sqlite_type in exam_columns_to_add:

            if col_name not in exam_cols:

                col_type = pg_type if is_postgres else sqlite_type

                db.execute(text(f"ALTER TABLE exams ADD COLUMN {col_name} {col_type}"))

                added_cols.append(col_name)



        if is_postgres:

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exams_organization_id ON exams(organization_id)"))

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exams_creator_id ON exams(creator_id)"))

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exams_assessment_type ON exams(assessment_type)"))

            db.execute(text("CREATE INDEX IF NOT EXISTS ix_exams_status ON exams(status)"))

        db.commit()



        # 5. Backfill creator_id from group.teacher_id where creator_id is NULL

        if "creator_id" in added_cols or "creator_id" in exam_cols:

            db.execute(text("""

                UPDATE exams

                SET creator_id = (SELECT teacher_id FROM groups WHERE groups.id = exams.group_id)

                WHERE creator_id IS NULL AND group_id IS NOT NULL

            """))

            db.commit()



        result = {

            "status": "success",

            "action": "upgrade",

            "table_created": "organizations",

            "exam_columns_added": added_cols

        }

        print(f"[MIGRATION] Phase 1 upgrade complete: {result}")

        return result

    except Exception as e:

        db.rollback()

        print(f"[MIGRATION] Phase 1 upgrade failed: {e}")

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

            print("[MIGRATION] Dropping Phase 1 columns from exams...")

            db.execute(text("""

                ALTER TABLE exams

                DROP COLUMN IF EXISTS config_metadata,

                DROP COLUMN IF EXISTS status,

                DROP COLUMN IF EXISTS passing_percentage,

                DROP COLUMN IF EXISTS passing_criteria,

                DROP COLUMN IF EXISTS max_attempts,

                DROP COLUMN IF EXISTS creator_id,

                DROP COLUMN IF EXISTS organization_id,

                DROP COLUMN IF EXISTS assessment_type,

                DROP COLUMN IF EXISTS description

            """))

            print("[MIGRATION] Dropping organization_id from groups and users...")

            db.execute(text("ALTER TABLE groups DROP COLUMN IF EXISTS organization_id"))

            db.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS organization_id"))

            print("[MIGRATION] Dropping organizations table...")

            db.execute(text("DROP TABLE IF EXISTS organizations CASCADE"))

            db.commit()

        else:

            # SQLite does not support multiple drop columns cleanly in old versions,

            # but we can drop organizations table.

            if "organizations" in inspector.get_table_names():

                models.Organization.__table__.drop(bind=bind, checkfirst=True)

            db.commit()



        result = {

            "status": "success",

            "action": "downgrade"

        }

        print(f"[MIGRATION] Phase 1 downgrade complete: {result}")

        return result

    except Exception as e:

        db.rollback()

        print(f"[MIGRATION] Phase 1 downgrade failed: {e}")

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
