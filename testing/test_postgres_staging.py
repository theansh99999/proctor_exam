"""

testing/test_postgres_staging.py

--------------------------------

Comprehensive Pre-Architecture Verification on PostgreSQL Staging Database:

Database URL: postgresql://postgres:postgres@localhost:5432/exam_proctor_staging

(Production database 'exam_proctor' is 100% untouched)



Covers:

1. Migration 1 (group_members) Upgrade & Downgrade on PostgreSQL

2. Migration 2 (exam_sessions) Upgrade & Downgrade on PostgreSQL

3. Historical data preservation verification

4. Multiple concurrent answer requests on PostgreSQL (Row locking & Concurrency)

5. Background auto-finalization on PostgreSQL (Browser closed scenario)

6. Overall and per-question timer workflows on PostgreSQL

"""



import os

os.environ["TESTING"] = "1"



import unittest

import json

from datetime import datetime, timezone, timedelta

from concurrent.futures import ThreadPoolExecutor, as_completed



from sqlalchemy import create_engine, text, inspect

from sqlalchemy.orm import sessionmaker, joinedload

from fastapi.testclient import TestClient



import models

from main import app

from database import get_db

import auth

from time_utils import utc_now, to_utc, to_utc_iso

from migrations import (

    migrate_group_members,

    migrate_exam_sessions,

    migrate_phase1_foundation,

    migrate_phase2_assignments,

    migrate_phase3_question_bank,

    migrate_phase4_candidate_engine,

    migrate_phase5_proctoring,

    migrate_phase6_evaluation,

    migrate_phase8_integrations,

    migrate_phase11_advanced_assessments

)



# PostgreSQL Staging Connection

_base_db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/exam_proctor")

STAGING_DB_URL = os.getenv("STAGING_DATABASE_URL", _base_db_url.rsplit("/", 1)[0] + "/exam_proctor_staging")

staging_engine = create_engine(STAGING_DB_URL, pool_pre_ping=True)

StagingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=staging_engine)



def get_staging_db():

    db = StagingSessionLocal()

    try:

        yield db

    finally:

        db.close()



class TestPostgreSQLStaging(unittest.TestCase):



    @classmethod

    def setUpClass(cls):

        os.environ["MOCK_EMAIL"] = "true"

        # Override FastAPI get_db dependency with staging DB

        app.dependency_overrides[get_db] = get_staging_db

        cls.client = TestClient(app)



    @classmethod

    def tearDownClass(cls):

        app.dependency_overrides.clear()

        staging_engine.dispose()



    def setUp(self):

        # Recreate clean staging schema before tests

        models.Base.metadata.drop_all(bind=staging_engine)

        models.Base.metadata.create_all(bind=staging_engine)

        self.db = StagingSessionLocal()

        self._seed_historical_data()



    def tearDown(self):

        self.db.close()



    def _seed_historical_data(self):

        """Seed realistic historical data to verify preservation across migrations."""

        self.teacher = models.User(

            email="prof_staging@univ.edu",

            name="Prof Staging",

            password_hash=auth.get_password_hash("SecretPass123!"),

            role="teacher"

        )

        self.student1 = models.User(

            email="student1_staging@univ.edu",

            name="Student One",

            password_hash=auth.get_password_hash("SecretPass123!"),

            role="student"

        )

        self.student2 = models.User(

            email="student2_staging@univ.edu",

            name="Student Two",

            password_hash=auth.get_password_hash("SecretPass123!"),

            role="student"

        )

        self.db.add_all([self.teacher, self.student1, self.student2])

        self.db.commit()



        self.group = models.Group(name="Staging Chemistry Group", teacher_id=self.teacher.id)

        self.db.add(self.group)

        self.db.commit()



        # Enrolled member with student_id

        self.db.add(models.GroupMember(

            group_id=self.group.id,

            student_id=self.student1.id,

            student_email=self.student1.email

        ))

        # Enrolled member without student_id (legacy email format)

        self.db.add(models.GroupMember(

            group_id=self.group.id,

            student_id=None,

            student_email=self.student2.email

        ))

        # Orphan member (email with no matching User record)

        self.db.add(models.GroupMember(

            group_id=self.group.id,

            student_id=None,

            student_email="orphan_applicant@univ.edu"

        ))

        self.db.commit()



        # Historical completed exam

        now = utc_now()

        self.past_exam = models.Exam(

            title="Historical Midterm Exam",

            group_id=self.group.id,

            start_time=now - timedelta(days=7),

            end_time=now - timedelta(days=7, hours=-2),

            duration_minutes=120,

            timer_type="overall",

            default_marks=5.0,

            passing_marks=5.0

        )

        self.db.add(self.past_exam)

        self.db.commit()



        self.past_q = models.Question(exam_id=self.past_exam.id, text="Historical Q?", marks=5.0)

        self.db.add(self.past_q)

        self.db.commit()



        self.past_opt1 = models.Option(question_id=self.past_q.id, text="Correct", is_correct=True)

        self.past_opt2 = models.Option(question_id=self.past_q.id, text="Incorrect", is_correct=False)

        self.db.add_all([self.past_opt1, self.past_opt2])

        self.db.commit()



        # Historical submission

        self.past_sub = models.Submission(

            exam_id=self.past_exam.id,

            student_id=self.student1.id,

            score=5.0,

            submitted_at=now - timedelta(days=7, hours=-1)

        )

        self.db.add(self.past_sub)

        self.db.commit()



        self.past_ans = models.StudentAnswer(

            submission_id=self.past_sub.id,

            question_id=self.past_q.id,

            selected_option_id=self.past_opt1.id,

            is_correct=True

        )

        self.db.add(self.past_ans)

        self.db.commit()



        # Generate tokens

        self.student1_token = auth.create_access_token({"sub": self.student1.email, "role": "student"})

        self.student2_token = auth.create_access_token({"sub": self.student2.email, "role": "student"})

        self.teacher_token = auth.create_access_token({"sub": self.teacher.email, "role": "teacher"})



    # =========================================================================

    # 1. POSTGRESQL MIGRATION 1: GROUP MEMBERS UPGRADE & DOWNGRADE

    # =========================================================================

    def test_01_postgres_migrate_group_members_lifecycle(self):

        """Test Migration 1 upgrade and downgrade on PostgreSQL staging."""

        # 1. Run upgrade

        res_up = migrate_group_members.upgrade(staging_engine)

        self.assertEqual(res_up["status"], "success")



        inspector = inspect(staging_engine)

        cols = [c["name"] for c in inspector.get_columns("group_members")]

        self.assertIn("student_id", cols)



        # Verify orphan email handling: a student user was created for 'orphan_applicant@univ.edu'

        orphan_user = self.db.query(models.User).filter_by(email="orphan_applicant@univ.edu").first()

        self.assertIsNotNone(orphan_user)

        self.assertEqual(orphan_user.role, "student")



        # Verify group member now has student_id set

        orphan_gm = self.db.query(models.GroupMember).filter_by(student_email="orphan_applicant@univ.edu").first()

        self.assertEqual(orphan_gm.student_id, orphan_user.id)

        self.db.commit() # Commit transaction so table lock is released before DDL!



        # 2. Run downgrade

        res_down = migrate_group_members.downgrade(staging_engine)

        self.assertEqual(res_down["status"], "success")



        inspector = inspect(staging_engine)

        cols_after = [c["name"] for c in inspector.get_columns("group_members")]

        self.assertNotIn("student_id", cols_after)



        # Re-apply upgrade for subsequent tests

        migrate_group_members.upgrade(staging_engine)

        self.db.commit()



    # =========================================================================

    # 2. POSTGRESQL MIGRATION 2: EXAM SESSIONS UPGRADE & DOWNGRADE

    # =========================================================================

    def test_02_postgres_migrate_exam_sessions_lifecycle(self):

        """Test Migration 2 upgrade and downgrade on PostgreSQL staging."""

        self.db.commit()

        # 1. Run downgrade first (in case tables exist from Base.metadata.create_all)

        res_down = migrate_exam_sessions.downgrade(staging_engine)

        self.assertEqual(res_down["status"], "success")



        inspector = inspect(staging_engine)

        tables = inspector.get_table_names()

        self.assertNotIn("exam_sessions", tables)

        self.assertNotIn("question_sessions", tables)



        # 2. Run upgrade

        res_up = migrate_exam_sessions.upgrade(staging_engine)

        self.assertEqual(res_up["status"], "success")



        inspector = inspect(staging_engine)

        tables_after = inspector.get_table_names()

        self.assertIn("exam_sessions", tables_after)

        self.assertIn("question_sessions", tables_after)

        self.db.commit()



    # =========================================================================

    # 3. HISTORICAL DATA PRESERVATION VERIFICATION

    # =========================================================================

    def test_03_historical_submissions_preserved(self):

        """Verify that historical completed exams, submissions, scores, and answers remain intact."""

        sub = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 5.0)

        self.assertEqual(sub.student.email, self.student1.email)

        self.assertEqual(len(sub.answers), 1)

        self.assertTrue(sub.answers[0].is_correct)

        self.assertEqual(sub.exam.title, "Historical Midterm Exam")



    # =========================================================================

    # 4. OVERALL TIMER WORKFLOW ON POSTGRESQL

    # =========================================================================

    def test_04_postgres_overall_timer_workflow(self):

        """Test active overall timer exam creation, answering, and submission on PostgreSQL."""

        now = utc_now()

        exam = models.Exam(

            title="Live Overall Chemistry Exam",

            group_id=self.group.id,

            start_time=now - timedelta(minutes=5),

            end_time=now + timedelta(minutes=55),

            duration_minutes=60,

            timer_type="overall",

            default_marks=4.0,

            passing_marks=4.0

        )

        self.db.add(exam)

        self.db.commit()



        q = models.Question(exam_id=exam.id, text="Avogadro constant?", marks=4.0)

        self.db.add(q)

        self.db.commit()

        opt_correct = models.Option(question_id=q.id, text="6.022e23", is_correct=True)

        opt_wrong = models.Option(question_id=q.id, text="3.1415", is_correct=False)

        self.db.add_all([opt_correct, opt_wrong])

        self.db.commit()



        # Submit answer via form submission

        res = self.client.post(

            f"/student/submit_exam/{exam.id}",

            data={f"question_{q.id}": str(opt_correct.id)},

            headers={"Authorization": f"Bearer {self.student1_token}"},

            follow_redirects=False

        )

        self.assertEqual(res.status_code, 302)



        # Check PostgreSQL submission record

        sub = self.db.query(models.Submission).filter_by(exam_id=exam.id, student_id=self.student1.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 4.0)



    # =========================================================================

    # 5. PER-QUESTION TIMER WORKFLOW ON POSTGRESQL

    # =========================================================================

    def test_05_postgres_per_question_timer_workflow(self):

        """Test per-question timer: state sync, answer submission, locking, and direct API protection on PostgreSQL."""

        now = utc_now()

        pq_exam = models.Exam(

            title="Postgres Per Question Exam",

            group_id=self.group.id,

            start_time=now - timedelta(minutes=2),

            end_time=now + timedelta(minutes=58),

            duration_minutes=60,

            timer_type="per_question",

            default_marks=3.0,

            passing_marks=3.0

        )

        self.db.add(pq_exam)

        self.db.commit()



        q1 = models.Question(exam_id=pq_exam.id, text="Postgres Q1?", marks=3.0, time_limit_seconds=45)

        q2 = models.Question(exam_id=pq_exam.id, text="Postgres Q2?", marks=3.0, time_limit_seconds=45)

        self.db.add_all([q1, q2])

        self.db.commit()



        q1_opt = models.Option(question_id=q1.id, text="Correct 1", is_correct=True)

        q2_opt = models.Option(question_id=q2.id, text="Correct 2", is_correct=True)

        self.db.add_all([q1_opt, q2_opt])

        self.db.commit()



        # 1. State sync

        res_sync = self.client.get(

            f"/student/api/exam/{pq_exam.id}/timer_state",

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res_sync.status_code, 200)

        sync_data = res_sync.json()

        self.assertEqual(sync_data["current_question_id"], q1.id)

        self.assertGreater(sync_data["remaining_seconds"], 40)



        # 2. Save answer to Q1 within deadline

        res_save = self.client.post(

            f"/student/api/exam/{pq_exam.id}/save_question_answer",

            json={"question_id": q1.id, "selected_option_id": q1_opt.id},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res_save.status_code, 200)

        self.assertEqual(res_save.json()["status"], "saved")



        # 3. Advance to Q2

        res_next = self.client.post(

            f"/student/api/exam/{pq_exam.id}/next_question",

            json={"current_question_id": q1.id},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res_next.status_code, 200)

        self.assertEqual(res_next.json()["question_id"], q2.id)



        # 4. Attempt to modify Q1 after moving to Q2 -> must return HTTP 400

        res_modify_locked = self.client.post(

            f"/student/api/exam/{pq_exam.id}/save_question_answer",

            json={"question_id": q1.id, "selected_option_id": None},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res_modify_locked.status_code, 400)



        # 5. Expire Q2 artificially in PostgreSQL DB

        q2_s = self.db.query(models.QuestionSession).filter_by(question_id=q2.id).first()

        q2_s.deadline = utc_now() - timedelta(seconds=15)

        q2_s.is_locked = True

        self.db.commit()



        # 6. Attempt direct API submission of expired Q2 via form POST -> must be discarded!

        res_sub = self.client.post(

            f"/student/submit_exam/{pq_exam.id}",

            data={f"question_{q1.id}": str(q1_opt.id), f"question_{q2.id}": str(q2_opt.id)},

            headers={"Authorization": f"Bearer {self.student1_token}"},

            follow_redirects=False

        )

        self.assertEqual(res_sub.status_code, 302)



        # Check final score: Only Q1 (3.0) awarded, Q2 (expired) = 0

        final_sub = self.db.query(models.Submission).filter_by(exam_id=pq_exam.id, student_id=self.student1.id).first()

        self.assertEqual(final_sub.score, 3.0)



    # =========================================================================

    # 6. MULTIPLE CONCURRENT ANSWER REQUESTS (ROW LOCKING & INTEGRITY)

    # =========================================================================

    def test_06_postgres_concurrent_answer_requests(self):

        """Test multiple concurrent answer requests against PostgreSQL under thread pool load."""

        now = utc_now()

        conc_exam = models.Exam(

            title="Concurrent Test Exam",

            group_id=self.group.id,

            start_time=now - timedelta(minutes=1),

            end_time=now + timedelta(minutes=59),

            duration_minutes=60,

            timer_type="per_question",

            default_marks=2.0,

            passing_marks=2.0

        )

        self.db.add(conc_exam)

        self.db.commit()



        q = models.Question(exam_id=conc_exam.id, text="Concurrent Q?", marks=2.0, time_limit_seconds=60)

        self.db.add(q)

        self.db.commit()



        opt1 = models.Option(question_id=q.id, text="Opt 1", is_correct=True)

        opt2 = models.Option(question_id=q.id, text="Opt 2", is_correct=False)

        self.db.add_all([opt1, opt2])

        self.db.commit()



        # Initialize session

        self.client.get(f"/student/api/exam/{conc_exam.id}/timer_state", headers={"Authorization": f"Bearer {self.student1_token}"})



        # Fire 8 concurrent requests with alternating options across separate DB sessions/threads

        results = []

        from routers.student_r import save_question_answer, QuestionAnswerRequest



        def post_answer(opt_id):

            db_thread = StagingSessionLocal()

            try:

                req = QuestionAnswerRequest(question_id=q.id, selected_option_id=opt_id)

                res = save_question_answer(

                    exam_id=conc_exam.id,

                    req=req,

                    db=db_thread,

                    current_user=self.student1

                )

                return res

            finally:

                db_thread.close()



        with ThreadPoolExecutor(max_workers=8) as executor:

            futures = [executor.submit(post_answer, opt1.id if i % 2 == 0 else opt2.id) for i in range(8)]

            for f in as_completed(futures):

                results.append(f.result())



        # Verify all concurrent requests succeeded with 'status': 'saved' without database deadlock

        for r in results:

            self.assertEqual(r["status"], "saved")



        # Exactly 1 QuestionSession row exists in PostgreSQL

        q_count = self.db.query(models.QuestionSession).filter_by(question_id=q.id).count()

        self.assertEqual(q_count, 1)



    # =========================================================================

    # 7. BACKGROUND AUTO-FINALIZATION (BROWSER CLOSED SCENARIO) ON POSTGRESQL

    # =========================================================================

    def test_07_postgres_background_auto_finalization_browser_closed(self):

        """

        Simulate browser closed scenario:

        Student starts exam, answers Q1, then closes the browser (no further requests).

        After all question deadlines have passed, server background finalization

        must create the Submission record with correct score on PostgreSQL.

        """

        now = utc_now()

        auto_exam = models.Exam(

            title="Auto Finalize Exam",

            group_id=self.group.id,

            start_time=now - timedelta(minutes=5),

            end_time=now + timedelta(minutes=55),

            duration_minutes=60,

            timer_type="per_question",

            default_marks=5.0,

            passing_marks=5.0

        )

        self.db.add(auto_exam)

        self.db.commit()



        q1 = models.Question(exam_id=auto_exam.id, text="Auto Q1?", marks=5.0, time_limit_seconds=30)

        self.db.add(q1)

        self.db.commit()

        opt1 = models.Option(question_id=q1.id, text="Correct", is_correct=True)

        self.db.add(opt1)

        self.db.commit()



        # 1. Student opens exam and answers Q1

        self.client.get(f"/student/api/exam/{auto_exam.id}/timer_state", headers={"Authorization": f"Bearer {self.student1_token}"})

        self.client.post(

            f"/student/api/exam/{auto_exam.id}/save_question_answer",

            json={"question_id": q1.id, "selected_option_id": opt1.id},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )



        # 2. Student CLOSES BROWSER (disconnects).

        # Time passes beyond question deadline

        qs = self.db.query(models.QuestionSession).filter_by(question_id=q1.id).first()

        qs.deadline = utc_now() - timedelta(seconds=20)

        qs.is_locked = True

        self.db.commit()



        # 3. Server-side check executes (e.g. background job or student reopening dashboard)

        # Verify Submission does NOT exist yet

        sub_before = self.db.query(models.Submission).filter_by(exam_id=auto_exam.id, student_id=self.student1.id).first()

        self.assertIsNone(sub_before)



        # Trigger timer_state probe or finalize_session endpoint

        res = self.client.get(

            f"/student/api/exam/{auto_exam.id}/timer_state",

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        data = res.json()

        self.assertEqual(data["status"], "completed")

        self.assertTrue(data["is_expired"])



        # Submission is now persisted in PostgreSQL!

        sub_after = self.db.query(models.Submission).filter_by(exam_id=auto_exam.id, student_id=self.student1.id).first()

        self.assertIsNotNone(sub_after)

        self.assertEqual(sub_after.score, 5.0)



        # ExamSession is marked auto_submitted or completed

        session = self.db.query(models.ExamSession).filter_by(exam_id=auto_exam.id, student_id=self.student1.id).first()

        self.assertIn(session.status, ["completed", "auto_submitted"])



    # =========================================================================

    # 8. POSTGRESQL MIGRATION 3: PHASE 1 FOUNDATION (UPGRADE & DOWNGRADE)

    # =========================================================================

    def test_08_postgres_migrate_phase1_foundation_lifecycle(self):

        """Test Phase 1 Migration upgrade and downgrade on PostgreSQL staging."""

        self.db.commit()



        # 1. Downgrade first to test clean slate

        res_down = migrate_phase1_foundation.downgrade(staging_engine)

        self.assertEqual(res_down["status"], "success")



        inspector = inspect(staging_engine)

        self.assertNotIn("organizations", inspector.get_table_names())

        exam_cols = [c["name"] for c in inspector.get_columns("exams")]

        self.assertNotIn("assessment_type", exam_cols)

        self.assertNotIn("creator_id", exam_cols)



        # 2. Run Upgrade

        res_up = migrate_phase1_foundation.upgrade(staging_engine)

        self.assertEqual(res_up["status"], "success")



        inspector_after = inspect(staging_engine)

        self.assertIn("organizations", inspector_after.get_table_names())



        user_cols = [c["name"] for c in inspector_after.get_columns("users")]

        self.assertIn("organization_id", user_cols)



        group_cols = [c["name"] for c in inspector_after.get_columns("groups")]

        self.assertIn("organization_id", group_cols)



        exam_cols_after = [c["name"] for c in inspector_after.get_columns("exams")]

        self.assertIn("organization_id", exam_cols_after)

        self.assertIn("creator_id", exam_cols_after)

        self.assertIn("assessment_type", exam_cols_after)

        self.assertIn("description", exam_cols_after)

        self.assertIn("max_attempts", exam_cols_after)

        self.assertIn("passing_criteria", exam_cols_after)

        self.assertIn("status", exam_cols_after)

        self.assertIn("config_metadata", exam_cols_after)



        # 3. Verify creator_id backfill on existing past_exam from group.teacher_id

        past_e = self.db.query(models.Exam).filter_by(id=self.past_exam.id).first()

        self.assertEqual(past_e.creator_id, self.teacher.id)



        # 4. Verify historical submissions and scores are 100% intact

        sub = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 5.0)



    # =========================================================================

    # 9. POSTGRESQL MIGRATION 4: PHASE 2 ASSIGNMENTS (UPGRADE & DOWNGRADE)

    # =========================================================================

    def test_09_postgres_migrate_phase2_assignments_lifecycle(self):

        """Test Phase 2 Migration upgrade and downgrade on PostgreSQL staging."""

        self.db.commit()



        # 1. Downgrade first to test clean slate

        res_down = migrate_phase2_assignments.downgrade(staging_engine)

        self.assertEqual(res_down["status"], "success")



        inspector = inspect(staging_engine)

        self.assertNotIn("assessment_assignments", inspector.get_table_names())

        exam_cols = [c["name"] for c in inspector.get_columns("exams")]

        self.assertNotIn("instructions", exam_cols)

        self.assertNotIn("randomize_questions", exam_cols)

        self.assertNotIn("visibility", exam_cols)



        # 2. Run Upgrade

        res_up = migrate_phase2_assignments.upgrade(staging_engine)

        self.assertEqual(res_up["status"], "success")



        inspector_after = inspect(staging_engine)

        self.assertIn("assessment_assignments", inspector_after.get_table_names())



        exam_cols_after = [c["name"] for c in inspector_after.get_columns("exams")]

        self.assertIn("instructions", exam_cols_after)

        self.assertIn("randomize_questions", exam_cols_after)

        self.assertIn("enable_negative_marking", exam_cols_after)

        self.assertIn("visibility", exam_cols_after)



        # 3. Create assignment on PostgreSQL staging

        assignment = models.AssessmentAssignment(

            assessment_id=self.past_exam.id,

            candidate_id=self.student1.id,

            assigned_by=self.teacher.id

        )

        self.db.add(assignment)

        self.db.commit()



        # Query assignment from PostgreSQL

        found_asgn = self.db.query(models.AssessmentAssignment).filter_by(

            assessment_id=self.past_exam.id,

            candidate_id=self.student1.id

        ).first()

        self.assertIsNotNone(found_asgn)

        self.assertEqual(found_asgn.candidate_id, self.student1.id)



        # 4. Verify historical completed exams and submissions are 100% intact

        sub = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 5.0)



    # =========================================================================

    # 10. POSTGRESQL MIGRATION 5: PHASE 3 QUESTION BANK (UPGRADE & DOWNGRADE)

    # =========================================================================

    def test_10_postgres_migrate_phase3_question_bank_lifecycle(self):

        """Test Phase 3 Question Bank migration upgrade and downgrade on PostgreSQL staging."""

        self.db.commit()



        # 1. Downgrade first to test clean slate

        res_down = migrate_phase3_question_bank.downgrade(staging_engine)

        self.assertEqual(res_down["status"], "success")



        inspector = inspect(staging_engine)

        staging_tables = inspector.get_table_names()

        self.assertNotIn("bank_questions", staging_tables)

        self.assertNotIn("bank_options", staging_tables)

        self.assertNotIn("assessment_questions", staging_tables)



        q_cols = [c["name"] for c in inspector.get_columns("questions")]

        self.assertNotIn("bank_question_id", q_cols)

        self.assertNotIn("question_type", q_cols)

        self.assertNotIn("explanation", q_cols)



        # 2. Run Upgrade

        res_up = migrate_phase3_question_bank.upgrade(staging_engine)

        self.assertEqual(res_up["status"], "success")



        inspector_after = inspect(staging_engine)

        staging_tables_after = inspector_after.get_table_names()

        self.assertIn("bank_questions", staging_tables_after)

        self.assertIn("bank_options", staging_tables_after)

        self.assertIn("assessment_questions", staging_tables_after)



        q_cols_after = [c["name"] for c in inspector_after.get_columns("questions")]

        self.assertIn("bank_question_id", q_cols_after)

        self.assertIn("order_index", q_cols_after)

        self.assertIn("question_type", q_cols_after)

        self.assertIn("explanation", q_cols_after)



        # 3. Create Bank Question & Options on PostgreSQL Staging

        bq = models.BankQuestion(

            text="Postgres Staging Test Question: What is normalization?",

            question_type="single_choice",

            assessment_category="technical",

            subject="Databases",

            topic="Normalization",

            difficulty="medium",

            default_marks=3.0,

            default_negative_marks=0.5,

            explanation="Normalization minimizes data redundancy and improves integrity.",

            created_by=self.teacher.id,

            status="published"

        )

        self.db.add(bq)

        self.db.flush()



        opt1 = models.BankOption(question_id=bq.id, text="Minimizes redundancy", is_correct=True, order_index=0)

        opt2 = models.BankOption(question_id=bq.id, text="Increases storage use", is_correct=False, order_index=1)

        self.db.add_all([opt1, opt2])



        # Map to exam

        map_entry = models.AssessmentQuestionMap(

            assessment_id=self.past_exam.id,

            bank_question_id=bq.id,

            order_index=1,

            marks=3.0,

            negative_marks=0.5

        )

        self.db.add(map_entry)

        self.db.commit()



        # Query back from PostgreSQL

        found_bq = self.db.query(models.BankQuestion).filter_by(id=bq.id).first()

        self.assertIsNotNone(found_bq)

        self.assertEqual(len(found_bq.options), 2)

        self.assertEqual(found_bq.subject, "Databases")



        # 4. Verify historical submissions and scores remain 100% intact

        sub = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 5.0)



    # =========================================================================

    # 11. POSTGRESQL MIGRATION 6: PHASE 4 CANDIDATE ENGINE (UPGRADE & DOWNGRADE)

    # =========================================================================

    def test_11_postgres_migrate_phase4_candidate_engine_lifecycle(self):

        """Test Phase 4 Candidate Engine migration upgrade and downgrade on PostgreSQL staging."""

        self.db.commit()



        # 1. Downgrade first to test clean slate

        res_down = migrate_phase4_candidate_engine.downgrade(staging_engine)

        self.assertEqual(res_down["status"], "success")



        inspector = inspect(staging_engine)

        es_cols = [c["name"] for c in inspector.get_columns("exam_sessions")]

        self.assertNotIn("question_order", es_cols)

        self.assertNotIn("submission_type", es_cols)



        qs_cols = [c["name"] for c in inspector.get_columns("question_sessions")]

        self.assertNotIn("answer_text", qs_cols)

        self.assertNotIn("is_bookmarked", qs_cols)



        sa_cols = [c["name"] for c in inspector.get_columns("student_answers")]

        self.assertNotIn("answer_text", sa_cols)



        q_cols = [c["name"] for c in inspector.get_columns("questions")]

        self.assertNotIn("type_config", q_cols)



        # 2. Run Upgrade

        res_up = migrate_phase4_candidate_engine.upgrade(staging_engine)

        self.assertEqual(res_up["status"], "success")



        inspector_after = inspect(staging_engine)

        es_cols_after = [c["name"] for c in inspector_after.get_columns("exam_sessions")]

        self.assertIn("score", es_cols_after)

        self.assertIn("submitted_at", es_cols_after)

        self.assertIn("submission_type", es_cols_after)

        self.assertIn("question_order", es_cols_after)



        qs_cols_after = [c["name"] for c in inspector_after.get_columns("question_sessions")]

        self.assertIn("answer_text", qs_cols_after)

        self.assertIn("is_bookmarked", qs_cols_after)



        sa_cols_after = [c["name"] for c in inspector_after.get_columns("student_answers")]

        self.assertIn("answer_text", sa_cols_after)



        q_cols_after = [c["name"] for c in inspector_after.get_columns("questions")]

        self.assertIn("type_config", q_cols_after)



        # 3. Create Multi-Attempt ExamSession on PostgreSQL Staging

        now = utc_now()

        sess = models.ExamSession(

            exam_id=self.past_exam.id,

            student_id=self.student1.id,

            attempt_number=2,

            started_at=now - timedelta(minutes=20),

            overall_deadline=now + timedelta(minutes=40),

            status="submitted",

            score=9.5,

            submitted_at=now,

            submission_type="manual",

            question_order=json.dumps([1, 2, 3])

        )

        self.db.add(sess)

        self.db.flush()



        # Add QuestionSession with answer_text and is_bookmarked

        q_sess = models.QuestionSession(

            exam_session_id=sess.id,

            question_id=self.past_q.id,

            started_at=now - timedelta(minutes=15),

            deadline=now + timedelta(minutes=15),

            answer_text="PostgreSQL staging answer text",

            is_bookmarked=True

        )

        self.db.add(q_sess)

        self.db.commit()



        # Query back from PostgreSQL

        found_sess = self.db.query(models.ExamSession).filter_by(id=sess.id).first()

        self.assertIsNotNone(found_sess)

        self.assertEqual(found_sess.score, 9.5)

        self.assertEqual(found_sess.submission_type, "manual")

        self.assertEqual(json.loads(found_sess.question_order), [1, 2, 3])



        found_qs = self.db.query(models.QuestionSession).filter_by(id=q_sess.id).first()

        self.assertIsNotNone(found_qs)

        self.assertEqual(found_qs.answer_text, "PostgreSQL staging answer text")

        self.assertTrue(found_qs.is_bookmarked)



        # 4. Verify historical submissions and scores remain 100% intact

        sub = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 5.0)



    # =========================================================================

    # 12. POSTGRESQL MIGRATION 7: PHASE 5 PROCTORING (UPGRADE & DOWNGRADE)

    # =========================================================================

    def test_12_postgres_migrate_phase5_proctoring_lifecycle(self):

        """Test Phase 5 Proctoring migration upgrade, downgrade, scoring and review on PostgreSQL staging."""

        self.db.commit()



        # 1. Downgrade first to test clean slate

        res_down = migrate_phase5_proctoring.downgrade(staging_engine)

        self.assertEqual(res_down["status"], "success")



        inspector = inspect(staging_engine)

        self.assertNotIn("proctoring_policies", inspector.get_table_names())



        cf_cols = [c["name"] for c in inspector.get_columns("cheat_flags")]

        self.assertNotIn("event_type", cf_cols)

        self.assertNotIn("severity", cf_cols)

        self.assertNotIn("review_decision", cf_cols)



        es_cols = [c["name"] for c in inspector.get_columns("exam_sessions")]

        self.assertNotIn("integrity_score", es_cols)

        self.assertNotIn("risk_level", es_cols)



        # 2. Run Upgrade

        res_up = migrate_phase5_proctoring.upgrade(staging_engine)

        self.assertEqual(res_up["status"], "success")



        inspector_after = inspect(staging_engine)

        self.assertIn("proctoring_policies", inspector_after.get_table_names())



        cf_cols_after = [c["name"] for c in inspector_after.get_columns("cheat_flags")]

        self.assertIn("exam_session_id", cf_cols_after)

        self.assertIn("event_type", cf_cols_after)

        self.assertIn("severity", cf_cols_after)

        self.assertIn("validation_status", cf_cols_after)

        self.assertIn("review_decision", cf_cols_after)



        es_cols_after = [c["name"] for c in inspector_after.get_columns("exam_sessions")]

        self.assertIn("integrity_score", es_cols_after)

        self.assertIn("risk_level", es_cols_after)

        self.assertIn("proctoring_status", es_cols_after)



        # 3. Create Proctoring Policy on PostgreSQL Staging

        from modules.proctoring.service import ProctoringService

        policy = ProctoringService.get_or_create_policy(self.db, self.past_exam)

        self.assertIsNotNone(policy)

        self.assertEqual(policy.exam_id, self.past_exam.id)



        # 4. Ingest Event on PostgreSQL Staging

        now = utc_now()

        flag = models.CheatFlag(

            exam_id=self.past_exam.id,

            student_id=self.student1.id,

            event_type="camera_disconnected",

            severity="high",

            description="Camera disconnected on staging",

            validation_status="valid",

            timestamp=now

        )

        self.db.add(flag)

        self.db.commit()



        found_flag = self.db.query(models.CheatFlag).filter_by(id=flag.id).first()

        self.assertIsNotNone(found_flag)

        self.assertEqual(found_flag.severity, "high")

        self.assertEqual(found_flag.event_type, "camera_disconnected")



        # 5. Examiner Review Workflow on PostgreSQL Staging

        from modules.proctoring.schemas import ProctoringEventReview

        review_data = ProctoringEventReview(

            review_decision="legitimate",

            reviewer_notes="Camera unplugged by mistake, resumed immediately."

        )

        reviewed = ProctoringService.review_event(self.db, flag.id, review_data, self.teacher)

        self.assertEqual(reviewed.review_decision, "legitimate")

        self.assertEqual(reviewed.reviewed_by, self.teacher.id)



        # 6. Verify historical submissions and scores remain 100% intact

        sub = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 5.0)



    # =========================================================================

    # 13. POSTGRESQL MIGRATION 8: PHASE 6 EVALUATION (UPGRADE & DOWNGRADE)

    # =========================================================================

    def test_13_postgres_migrate_phase6_evaluation_lifecycle(self):

        """Test Phase 6 Evaluation migration upgrade, downgrade and workflows on PostgreSQL staging."""

        self.db.commit()



        # 1. Downgrade Phase 6

        res_down = migrate_phase6_evaluation.downgrade(staging_engine)

        self.assertEqual(res_down["status"], "success")



        inspector = inspect(staging_engine)

        tables = inspector.get_table_names()

        self.assertNotIn("assessment_sections", tables)

        self.assertNotIn("exam_results", tables)

        self.assertNotIn("grading_audits", tables)



        exam_cols = [c["name"] for c in inspector.get_columns("exams")]

        self.assertNotIn("results_released", exam_cols)



        # 2. Upgrade Phase 6

        res_up = migrate_phase6_evaluation.upgrade(staging_engine)

        self.assertEqual(res_up["status"], "success")



        inspector_after = inspect(staging_engine)

        tables_after = inspector_after.get_table_names()

        self.assertIn("assessment_sections", tables_after)

        self.assertIn("exam_results", tables_after)

        self.assertIn("grading_audits", tables_after)



        exam_cols_after = [c["name"] for c in inspector_after.get_columns("exams")]

        self.assertIn("results_released", exam_cols_after)



        q_cols_after = [c["name"] for c in inspector_after.get_columns("questions")]

        self.assertIn("section_id", q_cols_after)

        self.assertIn("is_mandatory", q_cols_after)



        sa_cols_after = [c["name"] for c in inspector_after.get_columns("student_answers")]

        self.assertIn("exam_session_id", sa_cols_after)

        self.assertIn("marks_awarded", sa_cols_after)

        self.assertIn("evaluation_status", sa_cols_after)



        # 3. Create Assessment and Section on PostgreSQL staging

        now = utc_now()

        p6_exam = models.Exam(

            title="Postgres Phase 6 Exam",

            group_id=self.group.id,

            creator_id=self.teacher.id,

            start_time=now - timedelta(hours=1),

            end_time=now + timedelta(hours=1),

            duration_minutes=30,

            default_marks=10.0,

            passing_marks=5.0

        )

        self.db.add(p6_exam)

        self.db.commit()



        sec = models.AssessmentSection(

            exam_id=p6_exam.id,

            name="Staging Section A",

            order_index=1,

            max_marks=10.0,

            passing_percentage=50.0

        )

        self.db.add(sec)

        self.db.commit()

        self.assertIsNotNone(sec.id)



        # 4. Create and Evaluate ExamSession attempt on PostgreSQL staging

        sess = models.ExamSession(

            exam_id=p6_exam.id,

            student_id=self.student1.id,

            attempt_number=1,

            status="submitted",

            submitted_at=now,

            integrity_score=100.0,

            risk_level="low"

        )

        self.db.add(sess)

        self.db.commit()



        # Add question and answer

        q_desc = models.Question(

            exam_id=p6_exam.id,

            section_id=sec.id,

            text="Explain staging evaluation.",

            question_type="descriptive",

            marks=10.0

        )

        self.db.add(q_desc)

        self.db.commit()



        sa = models.StudentAnswer(

            exam_session_id=sess.id,

            question_id=q_desc.id,

            answer_text="Staging evaluation answer text.",

            evaluation_status="pending",

            marks_awarded=0.0

        )

        self.db.add(sa)

        self.db.commit()



        from modules.evaluation.service import EvaluationService



        # Initial evaluation -> PENDING

        res = EvaluationService.evaluate_attempt(self.db, sess)

        self.assertEqual(res.pass_fail_status, "PENDING")

        self.assertEqual(res.manual_grading_status, "pending")



        # 5. Examiner grades answer on PostgreSQL staging

        graded_sa = EvaluationService.grade_answer(

            self.db, sa.id, marks_awarded=8.0, examiner_feedback="Great staging test.", is_draft=False, grader=self.teacher

        )

        self.assertEqual(graded_sa.marks_awarded, 8.0)

        self.assertEqual(graded_sa.evaluation_status, "graded")



        # Result recalculates to PASS on PostgreSQL staging

        res_after_grade = self.db.query(models.ExamResult).filter_by(exam_session_id=sess.id).first()

        self.assertGreaterEqual(res_after_grade.marks_obtained, 8.0)

        self.assertEqual(res_after_grade.pass_fail_status, "PASS")



        # 6. Regrade with audit trail on PostgreSQL staging

        regraded_sa = EvaluationService.regrade_answer(

            self.db, sa.id, marks_awarded=9.5, examiner_feedback="Updated marks.", reason="PostgreSQL staging regrade audit test.", grader=self.teacher

        )

        self.assertEqual(regraded_sa.marks_awarded, 9.5)

        audit = self.db.query(models.GradingAudit).filter_by(student_answer_id=sa.id).first()

        self.assertIsNotNone(audit)

        self.assertEqual(audit.previous_marks, 8.0)

        self.assertEqual(audit.new_marks, 9.5)



        # 7. Release results toggle on PostgreSQL staging

        rel_info = EvaluationService.toggle_result_release(self.db, p6_exam.id, True, self.teacher)

        self.assertTrue(rel_info["results_released"])



        # 8. Historical submissions preserved

        past_sub_check = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(past_sub_check)

        self.assertEqual(past_sub_check.score, 5.0)



    # =========================================================================

    # 14. POSTGRESQL ANALYTICS, DASHBOARDS & REPORTING INTEGRATION (PHASE 7)

    # =========================================================================

    def test_14_postgres_analytics_integration(self):

        """Test Phase 7 Analytics, Dashboards and Reporting on live PostgreSQL staging."""

        self.db.commit()

        from modules.analytics.service import AnalyticsService



        # Ensure session and result record exists for student1 on past_exam

        now = utc_now()

        sess14 = self.db.query(models.ExamSession).filter_by(

            exam_id=self.past_exam.id,

            student_id=self.student1.id

        ).first()

        if not sess14:

            sess14 = models.ExamSession(

                exam_id=self.past_exam.id,

                student_id=self.student1.id,

                attempt_number=1,

                status="submitted",

                submitted_at=now,

                integrity_score=95.0,

                risk_level="low"

            )

            self.db.add(sess14)

            self.db.commit()



        res14 = self.db.query(models.ExamResult).filter_by(

            exam_id=self.past_exam.id,

            student_id=self.student1.id

        ).first()

        if not res14:

            res14 = models.ExamResult(

                exam_id=self.past_exam.id,

                student_id=self.student1.id,

                exam_session_id=sess14.id,

                attempt_number=1,

                total_marks=5.0,

                marks_obtained=5.0,

                percentage=100.0,

                pass_fail_status="PASS",

                correct_count=1,

                incorrect_count=0,

                unanswered_count=0,

                is_released=True,

                submission_timestamp=now

            )

            self.db.add(res14)

            self.db.commit()



        # 1. Examiner dashboard metrics on PostgreSQL

        examiner_metrics = AnalyticsService.get_examiner_dashboard_metrics(self.db, self.teacher)

        self.assertIsNotNone(examiner_metrics)

        self.assertGreater(examiner_metrics["total_assessments"], 0)

        self.assertIn("status_counts", examiner_metrics)

        self.assertIn("pass_rate", examiner_metrics)

        self.assertIn("fail_rate", examiner_metrics)

        self.assertIn("awaiting_release_count", examiner_metrics)



        # 2. Examiner filters by assessment_type and status on PostgreSQL

        filtered_metrics = AnalyticsService.get_examiner_dashboard_metrics(

            self.db, self.teacher, assessment_type="academic"

        )

        self.assertIsNotNone(filtered_metrics)

        self.assertGreaterEqual(filtered_metrics["total_assessments"], 1)



        # 3. Candidate performance analytics on PostgreSQL

        cand_perf = AnalyticsService.get_candidate_performance_analytics(

            self.db, self.student1.id, self.teacher

        )

        self.assertEqual(cand_perf["candidate_id"], self.student1.id)

        self.assertGreaterEqual(cand_perf["total_assessments_attempted"], 1)

        self.assertIn("improvement_trend", cand_perf)

        self.assertIn("attempts_history", cand_perf)

        self.assertIn("topic_performance", cand_perf)



        # 4. Assessment deep-dive analytics on PostgreSQL

        assessment_perf = AnalyticsService.get_assessment_analytics(

            self.db, self.past_exam.id, self.teacher

        )

        self.assertEqual(assessment_perf["assessment_id"], self.past_exam.id)

        self.assertIn("total_assigned", assessment_perf)

        self.assertIn("average_score", assessment_perf)

        self.assertIn("pass_percentage", assessment_perf)

        self.assertIn("question_analytics", assessment_perf)

        self.assertIn("proctoring_summary", assessment_perf)



        # 5. Question bank analytics with zero-division safety on PostgreSQL

        q_bank_analytics = AnalyticsService.get_question_bank_analytics(

            self.db, self.past_exam.id, self.teacher

        )

        self.assertIsInstance(q_bank_analytics, list)

        for q_item in q_bank_analytics:

            self.assertIn("correct_percentage", q_item)

            self.assertIn("frequently_incorrect", q_item)

            self.assertGreaterEqual(q_item["correct_percentage"], 0.0)



        # 6. Organization dashboard metrics on PostgreSQL

        org_metrics = AnalyticsService.get_organization_dashboard_metrics(

            self.db, self.teacher

        )

        self.assertIsNotNone(org_metrics)

        self.assertIn("total_assessments", org_metrics)

        self.assertIn("activity_trend", org_metrics)

        self.assertEqual(len(org_metrics["activity_trend"]), 7)



        # 7. CSV report generation on PostgreSQL

        csv_results = AnalyticsService.generate_assessment_results_csv(

            self.db, self.past_exam.id, self.teacher

        )

        self.assertIn("Candidate ID", csv_results)

        self.assertIn("Marks Obtained", csv_results)



        csv_cand = AnalyticsService.generate_candidate_performance_csv(

            self.db, self.student1.id, self.teacher

        )

        self.assertIn("Assessment ID", csv_cand)

        self.assertIn("Attempt Number", csv_cand)



        csv_questions = AnalyticsService.generate_question_analytics_csv(

            self.db, self.past_exam.id, self.teacher

        )

        self.assertIn("Question ID", csv_questions)

        self.assertIn("Frequently Incorrect", csv_questions)



        # 8. Historical submissions preserved on PostgreSQL

        past_sub_check = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(past_sub_check)

        self.assertEqual(past_sub_check.score, 5.0)



    # =========================================================================

    # 15. POSTGRESQL MIGRATION 8: PHASE 8 INTEGRATIONS (UPGRADE & DOWNGRADE)

    # =========================================================================

    def test_15_postgres_integrations_lifecycle(self):

        """Test Phase 8 Integration migration lifecycle and services on live PostgreSQL staging."""

        self.db.commit()



        # 1. Downgrade first to test clean slate

        res_down = migrate_phase8_integrations.downgrade(staging_engine)

        self.assertEqual(res_down["status"], "success")



        inspector = inspect(staging_engine)

        self.assertNotIn("integration_configs", inspector.get_table_names())

        self.assertNotIn("integration_logs", inspector.get_table_names())

        self.assertNotIn("sync_records", inspector.get_table_names())



        # 2. Run Upgrade

        res_up = migrate_phase8_integrations.upgrade(staging_engine)

        self.assertEqual(res_up["status"], "success")



        inspector_after = inspect(staging_engine)

        self.assertIn("integration_configs", inspector_after.get_table_names())

        self.assertIn("integration_logs", inspector_after.get_table_names())

        self.assertIn("sync_records", inspector_after.get_table_names())



        from modules.integrations.service import IntegrationService

        from modules.integrations.schemas import (

            QuestionGenerationRequest,

            QuestionApprovalSubmitRequest,

            ServiceNowSyncRequest,

            IntegrationConfigUpdate

        )



        staging_admin = self.db.query(models.User).filter_by(role="org_admin").first()

        if not staging_admin:

            staging_admin = models.User(

                email="org_admin_staging@univ.edu",

                name="Staging Org Admin",

                password_hash=auth.get_password_hash("SecretPass123!"),

                role="org_admin"

            )

            self.db.add(staging_admin)

            self.db.commit()



        # 3. Configure integration on PostgreSQL staging

        cfg_out = IntegrationService.update_config(

            self.db, "servicenow",

            IntegrationConfigUpdate(

                base_url="https://staging-mock.service-now.com",

                auth_type="basic",

                credentials={"username": "staging_admin", "password": "StagingPassword123!"},

                config_metadata={"assessment_table": "u_staging_exam", "mock_mode": True}

            ),

            staging_admin

        )

        self.assertEqual(cfg_out.base_url, "https://staging-mock.service-now.com")

        self.assertNotIn("StagingPassword123!", str(cfg_out.masked_credentials))



        # 4. Test connection on PostgreSQL staging

        conn_res = IntegrationService.test_connection(self.db, "servicenow", self.teacher)

        self.assertEqual(conn_res.status, "connected")



        # 5. Question Generator request and approval on PostgreSQL staging

        req_q = QuestionGenerationRequest(

            assessment_id=self.past_exam.id,

            subject="Chemistry",

            topic="Thermodynamics",

            question_type="single_choice",

            quantity=2

        )

        preview = IntegrationService.request_generated_questions(self.db, req_q, self.teacher)

        self.assertEqual(len(preview.questions), 2)



        approval_res = IntegrationService.approve_and_import_questions(

            self.db,

            QuestionApprovalSubmitRequest(

                batch_id=preview.batch_id,

                questions=preview.questions,

                approved_indices=[0, 1],

                target_assessment_id=self.past_exam.id

            ),

            self.teacher

        )

        self.assertEqual(approval_res.approved_count, 2)

        self.assertEqual(len(approval_res.imported_bank_question_ids), 2)



        # 6. ServiceNow Outbound Sync on PostgreSQL staging (Idempotent)

        sync_res = IntegrationService.sync_to_servicenow(

            self.db,

            ServiceNowSyncRequest(exam_id=self.past_exam.id, sync_type="all"),

            self.teacher

        )

        self.assertEqual(sync_res.status, "success")

        self.assertGreaterEqual(sync_res.records_synced, 1)



        # Re-sync without force: should be idempotent (0 newly synced)

        sync_res_idemp = IntegrationService.sync_to_servicenow(

            self.db,

            ServiceNowSyncRequest(exam_id=self.past_exam.id, sync_type="all", force_resync=False),

            self.teacher

        )

        self.assertEqual(sync_res_idemp.records_synced, 0)



        # 7. Integration audit logs on PostgreSQL staging

        logs_resp = IntegrationService.get_logs(self.db, None, 10, 0, self.teacher)

        self.assertGreater(logs_resp.total, 0)

        for log_item in logs_resp.logs:

            self.assertNotIn("StagingPassword123!", str(log_item.error_details or ""))

            self.assertNotIn("StagingPassword123!", str(log_item.request_summary or ""))



        # 8. Historical submissions preserved on PostgreSQL

        past_sub_check = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(past_sub_check)

        self.assertEqual(past_sub_check.score, 5.0)



    def test_16_postgres_notifications_lifecycle(self):

        """Test Phase 9 Notification migration lifecycle, preferences, announcements, and reminders on live PostgreSQL staging."""

        from migrations import migrate_phase9_notifications

        from modules.notifications.service import NotificationService

        from modules.notifications.schemas import (

            NotificationPreferenceUpdate,

            AnnouncementCreateRequest

        )



        self.db.commit()



        # 1. Downgrade Phase 9

        down_res = migrate_phase9_notifications.downgrade(staging_engine)

        self.assertEqual(down_res["status"], "success")



        inspector = inspect(staging_engine)

        tables_after_down = inspector.get_table_names()

        for tbl in ["notification_delivery_logs", "announcements", "notifications", "notification_preferences"]:

            self.assertNotIn(tbl, tables_after_down)



        # 2. Upgrade Phase 9

        up_res = migrate_phase9_notifications.upgrade(staging_engine)

        self.assertEqual(up_res["status"], "success")



        inspector = inspect(staging_engine)

        tables_after_up = inspector.get_table_names()

        for tbl in ["notification_delivery_logs", "announcements", "notifications", "notification_preferences"]:

            self.assertIn(tbl, tables_after_up)



        # 3. In-App Notification creation & querying on PostgreSQL

        notif_res = NotificationService.send_notification(

            db=self.db,

            recipient_id=self.student1.id,

            category="lifecycle",

            event_type="assessment_published",

            title="Staging Assessment Live",

            message="Your staging exam is now live.",

            channels=["in_app"]

        )

        self.assertEqual(notif_res["status"], "delivered")

        notif_id = notif_res["notification_id"]



        unread_count = NotificationService.get_unread_count(self.db, self.student1)

        self.assertGreaterEqual(unread_count, 1)



        # 4. Mark as read on PostgreSQL

        read_notif = NotificationService.mark_as_read(self.db, notif_id, self.student1)

        self.assertTrue(read_notif.is_read)

        self.assertIsNotNone(read_notif.read_at)



        # 5. User Notification Preferences on PostgreSQL staging

        pref = NotificationService.update_preferences(

            db=self.db,

            user_id=self.student1.id,

            data=NotificationPreferenceUpdate(reminders_enabled=True, email_enabled=False),

            current_user=self.student1

        )

        self.assertFalse(pref.email_enabled)

        self.assertTrue(pref.reminders_enabled)



        # 6. Examiner Announcement on PostgreSQL staging

        ann_res = NotificationService.send_announcement(

            db=self.db,

            req=AnnouncementCreateRequest(

                title="Staging Broadcast",

                content="Exam starts at scheduled time.",

                target_type="group",

                target_id=self.group.id,

                channel="in_app"

            ),

            current_user=self.teacher

        )

        self.assertEqual(ann_res.status, "sent")

        self.assertGreaterEqual(ann_res.recipient_count, 1)



        # Verify delivery breakdown

        delivery_stats = NotificationService.get_announcement_delivery_status(self.db, ann_res.id, self.teacher)

        self.assertGreaterEqual(delivery_stats.in_app_delivered, 1)



        # 7. Scheduled Reminders Scan on PostgreSQL staging

        reminder_stats = NotificationService.process_scheduled_reminders(self.db)

        self.assertIn("total_sent", reminder_stats)



        # 8. Historical submissions preserved on PostgreSQL

        past_sub_check = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(past_sub_check)

        self.assertEqual(past_sub_check.score, 5.0)



    def test_17_postgres_admin_lifecycle(self):

        """Test Phase 10 Platform Administration migration lifecycle, audit logging, configs, and user governance on live PostgreSQL staging."""

        from migrations import migrate_phase10_admin

        from modules.admin.service import AdminService

        from modules.admin.schemas import OrganizationCreateAdmin, UserCreateAdmin



        self.db.commit()



        # 1. Downgrade Phase 10 on live PostgreSQL

        down_res = migrate_phase10_admin.downgrade(staging_engine)

        self.assertEqual(down_res["status"], "success")



        inspector = inspect(staging_engine)

        tables_after_down = inspector.get_table_names()

        for tbl in ["organization_configs", "platform_configs", "audit_logs"]:

            self.assertNotIn(tbl, tables_after_down)



        # 2. Upgrade Phase 10 on live PostgreSQL

        up_res = migrate_phase10_admin.upgrade(staging_engine)

        self.assertEqual(up_res["status"], "success")



        inspector = inspect(staging_engine)

        tables_after_up = inspector.get_table_names()

        for tbl in ["organization_configs", "platform_configs", "audit_logs"]:

            self.assertIn(tbl, tables_after_up)



        # Verify added columns exist

        user_cols = [c["name"] for c in inspector.get_columns("users")]

        self.assertIn("is_active", user_cols)

        self.assertIn("is_suspended", user_cols)

        org_cols = [c["name"] for c in inspector.get_columns("organizations")]

        self.assertIn("is_suspended", org_cols)



        # 3. Create Super Admin User on PostgreSQL

        super_admin = models.User(

            email="super_staging@platform.com",

            name="Super Admin Staging",

            password_hash=auth.get_password_hash("SuperStaging123!"),

            role="super_admin",

            is_active=True,

            is_suspended=False

        )

        self.db.add(super_admin)

        self.db.commit()

        self.db.refresh(super_admin)



        # 4. Create Organization via AdminService on PostgreSQL

        org = AdminService.create_organization(

            db=self.db,

            data=OrganizationCreateAdmin(

                name="PostgreSQL Staging Academy",

                slug="pg-staging-acad",

                description="Live staging database test organization",

                is_active=True,

                is_suspended=False

            ),

            current_user=super_admin

        )

        self.assertIsNotNone(org.id)



        # 5. Set Organization and Platform Configurations on PostgreSQL

        AdminService.set_org_config(

            db=self.db,

            org_id=org.id,

            key="branding_name",

            value="Postgres Academy Portal",

            value_type="string",

            current_user=super_admin

        )

        org_configs = AdminService.get_org_configs(self.db, org.id, super_admin)

        self.assertEqual(org_configs["branding_name"]["value"], "Postgres Academy Portal")



        AdminService.set_platform_config(

            db=self.db,

            key="platform_name",

            value="ExamProctor Staging Enterprise",

            value_type="string",

            current_user=super_admin

        )

        plat_configs = AdminService.get_platform_configs(self.db, super_admin)

        self.assertEqual(plat_configs["platform_name"]["value"], "ExamProctor Staging Enterprise")



        # 6. User Lifecycle on PostgreSQL staging

        user = AdminService.create_user(

            db=self.db,

            data=UserCreateAdmin(

                name="Candidate PG",

                email="candidate_pg@staging.edu",

                password="StagingPassword123!",

                role="candidate",

                organization_id=org.id,

                is_active=True,

                is_suspended=False

            ),

            current_user=super_admin

        )

        self.assertIsNotNone(user.id)



        # Suspend user

        suspended_u = AdminService.update_user_status(

            db=self.db,

            user_id=user.id,

            is_suspended=True,

            reason="Staging test suspension",

            current_user=super_admin

        )

        self.assertTrue(suspended_u.is_suspended)



        # Password reset

        reset_res = AdminService.reset_user_password(

            db=self.db,

            user_id=user.id,

            current_user=super_admin

        )

        self.assertIn("temporary_password", reset_res)



        # 7. Audit log verification on PostgreSQL staging

        audit_logs = AdminService.get_audit_logs(

            db=self.db,

            current_user=super_admin,

            org_id=org.id

        )

        self.assertGreaterEqual(len(audit_logs), 2)

        logged_actions = [a["action"] for a in audit_logs]

        self.assertIn("org.create", logged_actions)

        self.assertIn("user.create", logged_actions)



        # 8. Historical data preserved on PostgreSQL

        past_sub_check2 = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(past_sub_check2)

        self.assertEqual(past_sub_check2.score, 5.0)



    # =========================================================================

    # 18. POSTGRESQL MIGRATION 11: PHASE 11 ADVANCED ASSESSMENTS (LIFECYCLE)

    # =========================================================================

    def test_18_postgres_advanced_assessments(self):

        """Test Phase 11 Advanced Assessment Features migration lifecycle, blueprints, templates, adaptive engine, attempt policies and sections on live PostgreSQL staging."""

        from modules.assessments.blueprints import BlueprintService, BlueprintCreate

        from modules.assessments.templates import TemplateService, TemplateCreate, CreateAssessmentFromTemplateRequest

        from modules.assessments.adaptive import AdaptiveService

        from modules.assessments.attempt_policies import AttemptPolicyService

        from modules.assessments.sections import SectionService

        from routers.student_r import get_or_create_exam_session



        self.db.commit()



        # 1. Downgrade Phase 11 on live PostgreSQL

        down_res = migrate_phase11_advanced_assessments.downgrade(staging_engine)

        self.assertEqual(down_res["status"], "success")



        inspector = inspect(staging_engine)

        tables_after_down = inspector.get_table_names()

        for tbl in ["assessment_blueprints", "assessment_templates"]:

            self.assertNotIn(tbl, tables_after_down)



        # 2. Upgrade Phase 11 on live PostgreSQL

        up_res = migrate_phase11_advanced_assessments.upgrade(staging_engine)

        self.assertEqual(up_res["status"], "success")



        inspector = inspect(staging_engine)

        tables_after_up = inspector.get_table_names()

        for tbl in ["assessment_blueprints", "assessment_templates"]:

            self.assertIn(tbl, tables_after_up)



        # Verify added columns on live PostgreSQL

        exam_cols = [c["name"] for c in inspector.get_columns("exams")]

        for col in ["randomize_options", "is_adaptive", "adaptive_config", "attempt_policy", "blueprint_id", "template_id"]:

            self.assertIn(col, exam_cols)



        sec_cols = [c["name"] for c in inspector.get_columns("assessment_sections")]

        for col in ["is_mandatory", "time_limit_minutes", "navigation_mode", "instructions", "randomize_questions"]:

            self.assertIn(col, sec_cols)



        sess_cols = [c["name"] for c in inspector.get_columns("exam_sessions")]

        for col in ["adaptive_state", "current_section_id", "completed_sections"]:

            self.assertIn(col, sess_cols)



        qs_cols = [c["name"] for c in inspector.get_columns("question_sessions")]

        self.assertIn("option_order", qs_cols)



        # 3. Assessment Blueprint CRUD & Validation on PostgreSQL

        super_admin = self.db.query(models.User).filter_by(role="super_admin").first()

        if not super_admin:

            super_admin = models.User(

                email="super11_pg@platform.com",

                name="Super Admin PG",

                password_hash=auth.get_password_hash("SuperPass123!"),

                role="super_admin",

                is_active=True

            )

            self.db.add(super_admin)

            self.db.commit()

            self.db.refresh(super_admin)



        org = self.db.query(models.Organization).first()

        if not org:

            org = models.Organization(name="Staging University PG", slug="staging-univ-pg", is_active=True)

            self.db.add(org)

            self.db.commit()

            self.db.refresh(org)



        bp_data = BlueprintCreate(

            title="PostgreSQL Staging Blueprint",

            subject="Computer Science",

            difficulty_distribution={"easy": 2, "medium": 3, "hard": 1},

            organization_id=org.id if org else None

        )

        bp = BlueprintService.create_blueprint(self.db, bp_data, super_admin)

        self.assertIsNotNone(bp.id)

        self.assertEqual(bp.title, "PostgreSQL Staging Blueprint")



        val = BlueprintService.validate_blueprint(self.db, bp.id, super_admin)

        self.assertIsNotNone(val)

        self.assertIn("easy", val.by_difficulty)



        # 4. Assessment Template CRUD & Assessment Instantiation on PostgreSQL

        tmpl_data = TemplateCreate(

            title="PostgreSQL Staging Template",

            assessment_type="technical",

            duration_minutes=75,

            randomize_options=True,

            is_adaptive=True,

            section_config=[

                {"name": "Coding Part 1", "order_index": 1, "is_mandatory": True, "navigation_mode": "sequential"},

                {"name": "Coding Part 2", "order_index": 2, "is_mandatory": True, "navigation_mode": "sequential"}

            ],

            is_system=True

        )

        tmpl = TemplateService.create_template(self.db, tmpl_data, super_admin)

        self.assertIsNotNone(tmpl.id)

        self.assertTrue(tmpl.is_system)



        # Duplicate template

        dupl = TemplateService.duplicate_template(self.db, tmpl.id, super_admin)

        self.assertEqual(dupl.title, "PostgreSQL Staging Template (Copy)")



        # Create assessment from template

        now = utc_now()

        req = CreateAssessmentFromTemplateRequest(

            title="PostgreSQL Exam from Template",

            start_time=now + timedelta(hours=1),

            end_time=now + timedelta(hours=4),

            generate_blueprint_questions=False

        )

        created_exam = TemplateService.create_assessment_from_template(self.db, tmpl.id, req, super_admin)

        self.assertIsNotNone(created_exam.id)

        self.assertEqual(created_exam.duration_minutes, 75)

        self.assertTrue(created_exam.randomize_options)



        # 5. Adaptive Session & State Persistence on PostgreSQL

        student = self.db.query(models.User).filter_by(role="student").first()

        if not student:

            student = self.db.query(models.User).filter_by(role="candidate").first()



        # Create active exam for adaptive session testing

        adaptive_exam = models.Exam(

            title="PostgreSQL Adaptive Exam",

            start_time=now - timedelta(hours=1),

            end_time=now + timedelta(hours=2),

            duration_minutes=60,

            status="active",

            is_adaptive=True,

            adaptive_config=json.dumps({"starting_difficulty": "medium", "max_questions": 5}),

            creator_id=super_admin.id

        )

        self.db.add(adaptive_exam)

        self.db.flush()



        # Add a question

        pg_q = models.Question(exam_id=adaptive_exam.id, text="PostgreSQL Q", marks=2.0)

        self.db.add(pg_q)

        self.db.flush()

        pg_opt = models.Option(question_id=pg_q.id, text="Option PG", is_correct=True)

        self.db.add(pg_opt)

        self.db.commit()



        session = get_or_create_exam_session(self.db, adaptive_exam.id, student.id, adaptive_exam)

        self.assertIsNotNone(session.id)

        self.assertIsNotNone(session.adaptive_state)

        parsed_state = json.loads(session.adaptive_state)

        self.assertEqual(parsed_state["current_difficulty"], "medium")



        # 6. Attempt Policy & Cooldown on PostgreSQL

        eligibility = AttemptPolicyService.check_attempt_eligibility(self.db, adaptive_exam, student.id)

        self.assertTrue(eligibility["eligible"])



        # 7. Section Progression on PostgreSQL

        sec1 = models.AssessmentSection(

            exam_id=adaptive_exam.id, name="PG Sec 1", order_index=1, is_mandatory=True, navigation_mode="sequential"

        )

        sec2 = models.AssessmentSection(

            exam_id=adaptive_exam.id, name="PG Sec 2", order_index=2, is_mandatory=True, navigation_mode="sequential"

        )

        self.db.add_all([sec1, sec2])

        self.db.commit()



        # Sequential access check

        can_sec2 = SectionService.can_access_section(self.db, session, sec2.id)

        self.assertFalse(can_sec2["allowed"])



        # Complete section 1

        SectionService.complete_section(self.db, session, sec1.id)

        can_sec2_after = SectionService.can_access_section(self.db, session, sec2.id)

        self.assertTrue(can_sec2_after["allowed"])



        # 8. Historical data intact on PostgreSQL staging

        past_sub_check = self.db.query(models.Submission).filter_by(id=self.past_sub.id).first()

        self.assertIsNotNone(past_sub_check)

        self.assertEqual(past_sub_check.score, 5.0)





if __name__ == "__main__":

    unittest.main()
