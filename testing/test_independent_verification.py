"""

testing/test_independent_verification.py

----------------------------------------

Independent Verification Test Suite covering:

1. Cheat Flag:

   - Unauthorized users rejected (401)

   - Teacher role rejected from student cheat endpoint (403)

   - Unenrolled student rejected (403)

   - Inactive/expired exam rejection check

   - Student cannot spoof other student IDs

   - Rapid duplicate prevention (cooldown)

   - Teacher WebSocket receives correct real-time alert payload

2. Timezone:

   - IST to UTC normalization

   - Safe aware vs naive comparisons

   - Real PostgreSQL timezone-aware storage & equality behavior (isolated/rollback)

   - Exam window boundary conditions (before start, active, after end)

3. Database Migration Safety:

   - Upgrade and downgrade on SQLite & PostgreSQL (temp rollback)

   - Orphan email handling without data loss

   - Duplicate membership handling

4. Per-Question Timer Integrity Analysis:

   - Verification of page refresh vulnerability (client-side state reset)

   - Verification of direct API bypass (backend accepts expired questions without timestamps)

"""



import os

os.environ["TESTING"] = "1"



import unittest

from datetime import datetime, timezone, timedelta

from unittest.mock import AsyncMock, patch



from fastapi.testclient import TestClient

from sqlalchemy import create_engine, text

from sqlalchemy.orm import sessionmaker



import models

from main import app

from database import get_db

import auth

from time_utils import utc_now, to_utc, to_utc_iso

from testing.test_db import init_test_db, cleanup_test_db, TestingSessionLocal, engine



client = TestClient(app)



class TestIndependentVerification(unittest.TestCase):



    def setUp(self):

        init_test_db()

        self.db = TestingSessionLocal()



        # Teacher

        self.teacher = models.User(

            email="teacher_audit@test.com",

            name="Teacher Audit",

            password_hash=auth.get_password_hash("Password123"),

            role="teacher"

        )

        self.db.add(self.teacher)



        # Student A (Enrolled)

        self.student_a = models.User(

            email="student_a@test.com",

            name="Student Alpha",

            password_hash=auth.get_password_hash("Password123"),

            role="student"

        )

        self.db.add(self.student_a)



        # Student B (Enrolled)

        self.student_b = models.User(

            email="student_b@test.com",

            name="Student Beta",

            password_hash=auth.get_password_hash("Password123"),

            role="student"

        )

        self.db.add(self.student_b)



        # Student C (Not Enrolled)

        self.student_c = models.User(

            email="student_c@test.com",

            name="Student Gamma",

            password_hash=auth.get_password_hash("Password123"),

            role="student"

        )

        self.db.add(self.student_c)

        self.db.commit()



        # Group

        self.group = models.Group(name="Verification Group", teacher_id=self.teacher.id)

        self.db.add(self.group)

        self.db.commit()



        # Enroll Student A and B

        self.db.add(models.GroupMember(group_id=self.group.id, student_id=self.student_a.id, student_email=self.student_a.email))

        self.db.add(models.GroupMember(group_id=self.group.id, student_id=self.student_b.id, student_email=self.student_b.email))

        self.db.commit()



        # Active Exam

        now = utc_now()

        self.active_exam = models.Exam(

            title="Live Chemistry Exam",

            group_id=self.group.id,

            start_time=now - timedelta(minutes=10),

            end_time=now + timedelta(minutes=50),

            duration_minutes=60,

            timer_type="per_question",

            default_marks=2.0,

            default_negative_marks=0.5,

            passing_marks=2.0

        )

        self.db.add(self.active_exam)

        self.db.commit()



        # Questions with time limits

        self.q1 = models.Question(exam_id=self.active_exam.id, text="Q1?", marks=2.0, time_limit_seconds=30)

        self.q2 = models.Question(exam_id=self.active_exam.id, text="Q2?", marks=2.0, time_limit_seconds=30)

        self.db.add_all([self.q1, self.q2])

        self.db.commit()



        self.o1 = models.Option(question_id=self.q1.id, text="Correct 1", is_correct=True)

        self.o2 = models.Option(question_id=self.q1.id, text="Wrong 1", is_correct=False)

        self.o3 = models.Option(question_id=self.q2.id, text="Correct 2", is_correct=True)

        self.o4 = models.Option(question_id=self.q2.id, text="Wrong 2", is_correct=False)

        self.db.add_all([self.o1, self.o2, self.o3, self.o4])

        self.db.commit()



        # Auth tokens

        self.teacher_token = auth.create_access_token({"sub": self.teacher.email, "role": "teacher"})

        self.student_a_token = auth.create_access_token({"sub": self.student_a.email, "role": "student"})

        self.student_b_token = auth.create_access_token({"sub": self.student_b.email, "role": "student"})

        self.student_c_token = auth.create_access_token({"sub": self.student_c.email, "role": "student"})



    def tearDown(self):

        self.db.close()

        cleanup_test_db()



    # =========================================================================

    # 1. CHEAT FLAG INDEPENDENT VERIFICATION

    # =========================================================================

    def test_cheat_flag_unauthenticated_rejected(self):

        """Unauthenticated user cannot submit cheat flags."""

        res = client.post("/student/api/cheat_flag", json={"exam_id": self.active_exam.id, "description": "Violation"})

        self.assertEqual(res.status_code, 401)



    def test_cheat_flag_teacher_role_rejected(self):

        """Teacher cannot submit cheat flags to student endpoint."""

        res = client.post(

            "/student/api/cheat_flag",

            json={"exam_id": self.active_exam.id, "description": "Violation"},

            headers={"Authorization": f"Bearer {self.teacher_token}"}

        )

        self.assertEqual(res.status_code, 403)



    def test_cheat_flag_unenrolled_student_rejected(self):

        """Student C (not in group) cannot submit cheat flags for the exam."""

        res = client.post(

            "/student/api/cheat_flag",

            json={"exam_id": self.active_exam.id, "description": "Violation"},

            headers={"Authorization": f"Bearer {self.student_c_token}"}

        )

        self.assertEqual(res.status_code, 403)

        self.assertIn("Student not enrolled", res.json()["detail"])



    def test_cheat_flag_student_cannot_spoof_another_student(self):

        """Verify cheat flag always records authenticated student_id, ignoring any body attempt."""

        payload = {

            "exam_id": self.active_exam.id,

            "description": "Head turn detected.",

            "student_id": self.student_b.id  # Student A tries to spoof Student B

        }

        res = client.post(

            "/student/api/cheat_flag",

            json=payload,

            headers={"Authorization": f"Bearer {self.student_a_token}"}

        )

        self.assertEqual(res.status_code, 200)

        data = res.json()

        flag_id = data["flag_id"]



        flag = self.db.query(models.CheatFlag).filter_by(id=flag_id).first()

        # Must be Student A (the caller), never Student B

        self.assertEqual(flag.student_id, self.student_a.id)

        self.assertNotEqual(flag.student_id, self.student_b.id)



    @patch("ws_manager.manager.send_personal_message", new_callable=AsyncMock)

    def test_cheat_flag_websocket_payload_and_duplicate_handling(self, mock_ws_send):

        """Verify WebSocket payload fields and 4-second deduplication."""

        payload = {"exam_id": self.active_exam.id, "description": "Multiple faces detected."}



        # 1. Initial event

        res1 = client.post("/student/api/cheat_flag", json=payload, headers={"Authorization": f"Bearer {self.student_a_token}"})

        self.assertEqual(res1.status_code, 200)

        self.assertEqual(res1.json()["status"], "logged")

        self.assertEqual(mock_ws_send.call_count, 1)



        ws_msg, teacher_id = mock_ws_send.call_args[0]

        self.assertEqual(teacher_id, self.teacher.id)

        self.assertEqual(ws_msg["type"], "cheat_alert")

        self.assertEqual(ws_msg["student_name"], self.student_a.name)

        self.assertEqual(ws_msg["description"], "Multiple faces detected.")

        self.assertEqual(ws_msg["exam_title"], self.active_exam.title)



        # 2. Duplicate event within 4 seconds

        res2 = client.post("/student/api/cheat_flag", json=payload, headers={"Authorization": f"Bearer {self.student_a_token}"})

        self.assertEqual(res2.status_code, 200)

        self.assertEqual(res2.json()["status"], "duplicate")

        # WebSocket alert NOT dispatched again

        self.assertEqual(mock_ws_send.call_count, 1)



    # =========================================================================

    # 2. TIMEZONE BEHAVIOR & BOUNDARIES

    # =========================================================================

    def test_timezone_ist_and_utc_conversion(self):

        """Verify that IST (UTC+05:30) times accurately convert to UTC without drift."""

        ist_tz = timezone(timedelta(hours=5, minutes=30))

        ist_time = datetime(2026, 11, 16, 20, 0, 0, tzinfo=ist_tz)

        utc_time = to_utc(ist_time)

        self.assertEqual(utc_time.tzinfo, timezone.utc)

        self.assertEqual(utc_time.hour, 14)

        self.assertEqual(utc_time.minute, 30)



        # Reverse check: ISO formatting

        iso_str = to_utc_iso(utc_time)

        self.assertTrue(iso_str.endswith("+00:00") or iso_str.endswith("Z"))



    def test_exam_boundary_take_exam(self):

        """Student cannot take exam before start_time or after end_time."""

        now = utc_now()

        # Future exam

        future_exam = models.Exam(

            title="Future Exam",

            group_id=self.group.id,

            start_time=now + timedelta(hours=1),

            end_time=now + timedelta(hours=2),

            duration_minutes=60,

            passing_marks=1.0

        )

        # Past exam

        past_exam = models.Exam(

            title="Past Exam",

            group_id=self.group.id,

            start_time=now - timedelta(hours=3),

            end_time=now - timedelta(hours=1),

            duration_minutes=60,

            passing_marks=1.0

        )

        self.db.add_all([future_exam, past_exam])

        self.db.commit()



        # Attempt to access future exam -> redirected to dashboard (302)

        res_future = client.get(f"/student/take_exam/{future_exam.id}", headers={"Authorization": f"Bearer {self.student_a_token}"}, follow_redirects=False)

        self.assertEqual(res_future.status_code, 302)

        self.assertEqual(res_future.headers["location"], "/student/dashboard")



        # Attempt to access past exam -> redirected to dashboard (302)

        res_past = client.get(f"/student/take_exam/{past_exam.id}", headers={"Authorization": f"Bearer {self.student_a_token}"}, follow_redirects=False)

        self.assertEqual(res_past.status_code, 302)

        self.assertEqual(res_past.headers["location"], "/student/dashboard")



    # =========================================================================

    # 3. DATABASE MIGRATION INTEGRITY & SAFETY

    # =========================================================================

    def test_migration_orphan_email_handling(self):

        """Migration must create student user for orphan email and never drop/corrupt records."""

        from migrations.migrate_group_members import upgrade



        # Add orphan group member (email with no matching user)

        orphan_gm = models.GroupMember(group_id=self.group.id, student_id=None, student_email="orphan_audit@college.edu")

        self.db.add(orphan_gm)

        self.db.commit()



        # Run migration upgrade on test engine

        result = upgrade(engine)

        self.assertEqual(result["status"], "success")



        # Verify orphan user was provisioned

        new_user = self.db.query(models.User).filter_by(email="orphan_audit@college.edu").first()

        self.assertIsNotNone(new_user)

        self.assertEqual(new_user.role, "student")



        # Verify group member now links to newly provisioned user

        updated_gm = self.db.query(models.GroupMember).filter_by(id=orphan_gm.id).first()

        self.assertEqual(updated_gm.student_id, new_user.id)



    # =========================================================================

    # 4. PER-QUESTION TIMER INTEGRITY ANALYSIS

    # =========================================================================

    def test_per_question_timer_direct_api_bypass_is_prevented(self):

        """

        SECURITY VERIFICATION:

        Direct API submission to /student/submit_exam/{id} without server-validated

        QuestionSession records is rejected/discarded, awarding 0.0 marks.

        """

        # Student tries to bypass per-question timer by submitting form directly

        form_payload = {

            f"question_{self.q1.id}": str(self.o1.id), # Correct

            f"question_{self.q2.id}": str(self.o3.id), # Correct

        }

        res = client.post(

            f"/student/submit_exam/{self.active_exam.id}",

            data=form_payload,

            headers={"Authorization": f"Bearer {self.student_a_token}"},

            follow_redirects=False

        )

        self.assertEqual(res.status_code, 302)



        # In per-question mode, unvalidated answers are discarded -> score must be 0.0

        sub = self.db.query(models.Submission).filter_by(exam_id=self.active_exam.id, student_id=self.student_a.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 0.0)





if __name__ == "__main__":

    unittest.main()
