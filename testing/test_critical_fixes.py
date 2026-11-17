"""

testing/test_critical_fixes.py

------------------------------

Comprehensive automated tests verifying the critical bug fixes:

1. Cheat flag pipeline:

   - Backend API connection (/student/api/cheat_flag)

   - Database persistence

   - WebSocket alert dispatch to teacher

   - Duplicate event prevention (cooldown)

2. Datetime timezone consistency:

   - UTC consistency across models and utility functions

   - Naive vs aware comparison safety

   - Start time before end time validation

3. Database relationships and migration:

   - GroupMember.student_id FK and relationship

   - GroupMember.email fallback property

   - Migration script upgrade and downgrade execution

4. Per-question timer:

   - timer_type validation ("overall" vs "per_question")

   - Mandatory positive time_limit_seconds per question on create & edit

"""



import os

os.environ["TESTING"] = "1"



import unittest

from datetime import datetime, timezone, timedelta

from unittest.mock import AsyncMock, patch



from fastapi.testclient import TestClient

from sqlalchemy import create_engine

from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool



import models

from main import app

from database import get_db

import auth

from time_utils import utc_now, to_utc, to_utc_iso

from testing.test_db import init_test_db, cleanup_test_db, TestingSessionLocal, engine



client = TestClient(app)



class TestCriticalFixes(unittest.TestCase):



    def setUp(self):

        init_test_db()

        self.db = TestingSessionLocal()



        # Create Teacher

        self.teacher = models.User(

            email="teacher_fix@test.com",

            name="Teacher Fix",

            password_hash=auth.get_password_hash("Password123"),

            role="teacher"

        )

        self.db.add(self.teacher)

        self.db.commit()

        self.db.refresh(self.teacher)



        # Create Student 1

        self.student = models.User(

            email="student_fix@test.com",

            name="Student Fix",

            password_hash=auth.get_password_hash("Password123"),

            role="student"

        )

        self.db.add(self.student)

        self.db.commit()

        self.db.refresh(self.student)



        # Create Student 2 (Unenrolled)

        self.student2 = models.User(

            email="student_unassigned@test.com",

            name="Student Unassigned",

            password_hash=auth.get_password_hash("Password123"),

            role="student"

        )

        self.db.add(self.student2)

        self.db.commit()

        self.db.refresh(self.student2)



        # Create Group

        self.group = models.Group(

            name="Computer Science 101",

            teacher_id=self.teacher.id

        )

        self.db.add(self.group)

        self.db.commit()

        self.db.refresh(self.group)



        # Enroll Student 1 in Group using new student_id

        self.member = models.GroupMember(

            group_id=self.group.id,

            student_id=self.student.id,

            student_email=self.student.email

        )

        self.db.add(self.member)

        self.db.commit()



        # Create Exam

        now = utc_now()

        self.exam = models.Exam(

            title="Python Midterm",

            group_id=self.group.id,

            start_time=now - timedelta(hours=1),

            end_time=now + timedelta(hours=2),

            duration_minutes=60,

            timer_type="overall",

            default_marks=1.0,

            default_negative_marks=0.0,

            passing_marks=1.0

        )

        self.db.add(self.exam)

        self.db.commit()

        self.db.refresh(self.exam)



        # Add Question

        self.q1 = models.Question(

            exam_id=self.exam.id,

            text="What is Python?",

            marks=1.0,

            negative_marks=0.0,

            time_limit_seconds=45

        )

        self.db.add(self.q1)

        self.db.commit()

        self.db.refresh(self.q1)



        self.opt1 = models.Option(question_id=self.q1.id, text="Programming Language", is_correct=True)

        self.opt2 = models.Option(question_id=self.q1.id, text="Snake", is_correct=False)

        self.db.add_all([self.opt1, self.opt2])

        self.db.commit()



        # Generate tokens

        self.teacher_token = auth.create_access_token({"sub": self.teacher.email, "role": "teacher"})

        self.student_token = auth.create_access_token({"sub": self.student.email, "role": "student"})

        self.student2_token = auth.create_access_token({"sub": self.student2.email, "role": "student"})



    def tearDown(self):

        self.db.close()

        cleanup_test_db()



    # =========================================================================

    # 1. TIMEZONE & DATETIME CONSISTENCY TESTS

    # =========================================================================

    def test_utc_now_is_timezone_aware(self):

        now = utc_now()

        self.assertIsNotNone(now.tzinfo)

        self.assertEqual(now.tzinfo, timezone.utc)



    def test_to_utc_handles_naive_aware_and_strings(self):

        # Naive datetime

        naive = datetime(2026, 4, 18, 12, 0, 0)

        aware = to_utc(naive)

        self.assertEqual(aware.tzinfo, timezone.utc)

        self.assertEqual(aware.hour, 12)



        # Aware datetime (non-UTC offset)

        offset_tz = timezone(timedelta(hours=5, minutes=30))

        ist_dt = datetime(2026, 4, 18, 17, 30, 0, tzinfo=offset_tz)

        converted = to_utc(ist_dt)

        self.assertEqual(converted.tzinfo, timezone.utc)

        self.assertEqual(converted.hour, 12)



        # String with 'Z'

        z_str = "2026-04-18T12:00:00Z"

        from_z = to_utc(z_str)

        self.assertEqual(from_z.tzinfo, timezone.utc)

        self.assertEqual(from_z.hour, 12)



        # String with offset

        offset_str = "2026-04-18T17:30:00+05:30"

        from_offset = to_utc(offset_str)

        self.assertEqual(from_offset.tzinfo, timezone.utc)

        self.assertEqual(from_offset.hour, 12)



        # HTML5 datetime-local string (no timezone info)

        local_str = "2026-04-18T12:00"

        from_local = to_utc(local_str)

        self.assertEqual(from_local.tzinfo, timezone.utc)

        self.assertEqual(from_local.hour, 12)



    def test_safe_datetime_comparisons_no_crash(self):

        """Ensure naive vs aware comparison doesn't raise TypeError when passed through to_utc."""

        naive_dt = datetime(2026, 1, 1, 0, 0, 0)

        aware_now = utc_now()

        # Direct comparison would fail: naive_dt < aware_now -> TypeError

        # Safe comparison using to_utc:

        self.assertTrue(to_utc(naive_dt) < aware_now)



    def test_exam_start_time_must_be_before_end_time(self):

        """API must reject exam where start_time >= end_time."""

        invalid_payload = {

            "title": "Invalid Datetime Exam",

            "group_id": self.group.id,

            "start_time": "2026-05-01T15:00:00Z",

            "end_time": "2026-05-01T14:00:00Z",  # end before start

            "duration_minutes": 60,

            "timer_type": "overall",

            "default_marks": 1.0,

            "default_negative_marks": 0.0,

            "passing_marks": 0.5,

            "questions": [

                {

                    "text": "Valid Q",

                    "options": [

                        {"text": "A", "is_correct": True},

                        {"text": "B", "is_correct": False}

                    ]

                }

            ]

        }

        res = client.post(

            "/teacher/api/create_exam",

            json=invalid_payload,

            headers={"Authorization": f"Bearer {self.teacher_token}"}

        )

        self.assertEqual(res.status_code, 400)

        self.assertIn("start_time must be strictly before end_time", res.json()["detail"])



    # =========================================================================

    # 2. DATABASE RELATIONSHIP & MIGRATION TESTS

    # =========================================================================

    def test_group_member_student_id_fk_and_relationship(self):

        """Verify GroupMember.student relationship and student_id foreign key."""

        gm = self.db.query(models.GroupMember).filter_by(group_id=self.group.id, student_id=self.student.id).first()

        self.assertIsNotNone(gm)

        self.assertEqual(gm.student_id, self.student.id)

        self.assertEqual(gm.student.name, "Student Fix")

        self.assertEqual(gm.email, "student_fix@test.com")



    def test_group_member_email_fallback_property(self):

        """Legacy records without student_id fallback to student_email."""

        legacy_gm = models.GroupMember(

            group_id=self.group.id,

            student_id=None,

            student_email="legacy@test.com"

        )

        self.assertEqual(legacy_gm.email, "legacy@test.com")



    def test_migrate_group_members_upgrade_and_downgrade(self):

        """Run the migration script on isolated database to verify safety."""

        from migrations.migrate_group_members import upgrade, downgrade



        # Test upgrade

        upgrade(engine)



        # Verify student_id column exists

        from sqlalchemy import inspect

        inspector = inspect(engine)

        columns = [c["name"] for c in inspector.get_columns("group_members")]

        self.assertIn("student_id", columns)



        # Test downgrade

        downgrade(engine)

        # Downgrade preserves student_email and completes without raising errors



    # =========================================================================

    # 3. CHEAT FLAG PIPELINE & WEBSOCKET ALERTS

    # =========================================================================

    @patch("ws_manager.manager.send_personal_message", new_callable=AsyncMock)

    def test_cheat_flag_persistence_and_websocket_alert(self, mock_ws_send):

        """Student logging cheat flag persists violation in DB and sends WebSocket alert."""

        payload = {

            "exam_id": self.exam.id,

            "description": "Tab switched or window minimized."

        }

        res = client.post(

            "/student/api/cheat_flag",

            json=payload,

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res.status_code, 200)

        data = res.json()

        self.assertEqual(data["status"], "logged")

        self.assertIn("flag_id", data)



        # Verify DB persistence

        flag = self.db.query(models.CheatFlag).filter_by(id=data["flag_id"]).first()

        self.assertIsNotNone(flag)

        self.assertEqual(flag.student_id, self.student.id)

        self.assertEqual(flag.description, "Tab switched or window minimized.")

        self.assertFalse(flag.is_resolved)

        self.assertIsNotNone(flag.timestamp)



        # Verify WebSocket alert was sent to the exam's teacher

        mock_ws_send.assert_called_once()

        sent_payload, recipient_id = mock_ws_send.call_args[0]

        self.assertEqual(recipient_id, self.teacher.id)

        self.assertEqual(sent_payload["type"], "cheat_alert")

        self.assertEqual(sent_payload["student_name"], self.student.name)

        self.assertEqual(sent_payload["description"], "Tab switched or window minimized.")

        self.assertEqual(sent_payload["exam_title"], self.exam.title)



    @patch("ws_manager.manager.send_personal_message", new_callable=AsyncMock)

    def test_cheat_flag_duplicate_prevention(self, mock_ws_send):

        """Submitting identical violation within 4 seconds is deduplicated."""

        payload = {

            "exam_id": self.exam.id,

            "description": "No face detected in webcam."

        }

        # First call: logged

        res1 = client.post(

            "/student/api/cheat_flag",

            json=payload,

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res1.status_code, 200)

        self.assertEqual(res1.json()["status"], "logged")

        self.assertEqual(mock_ws_send.call_count, 1)



        # Second immediate call: duplicate

        res2 = client.post(

            "/student/api/cheat_flag",

            json=payload,

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res2.status_code, 200)

        self.assertEqual(res2.json()["status"], "duplicate")



        # WS alert was NOT resent for the duplicate call

        self.assertEqual(mock_ws_send.call_count, 1)



        # Exactly 1 row in DB for this violation

        flags = self.db.query(models.CheatFlag).filter_by(

            exam_id=self.exam.id,

            student_id=self.student.id,

            description="No face detected in webcam."

        ).all()

        self.assertEqual(len(flags), 1)



    def test_cheat_flag_unenrolled_student_rejected(self):

        """Student not enrolled in group cannot log cheat flags for the exam."""

        payload = {

            "exam_id": self.exam.id,

            "description": "Unauthorized attempt."

        }

        res = client.post(

            "/student/api/cheat_flag",

            json=payload,

            headers={"Authorization": f"Bearer {self.student2_token}"}

        )

        self.assertEqual(res.status_code, 403)

        self.assertIn("Student not enrolled in this exam", res.json()["detail"])



    # =========================================================================

    # 4. PER-QUESTION TIMER VALIDATION TESTS

    # =========================================================================

    def test_per_question_timer_requires_positive_time_limit(self):

        """When timer_type == 'per_question', questions missing time_limit_seconds must fail with HTTP 400."""

        invalid_exam = {

            "title": "Per Question Timed Exam",

            "group_id": self.group.id,

            "start_time": "2026-05-01T10:00:00Z",

            "end_time": "2026-05-01T12:00:00Z",

            "duration_minutes": 120,

            "timer_type": "per_question",

            "default_marks": 1.0,

            "default_negative_marks": 0.0,

            "passing_marks": 1.0,

            "questions": [

                {

                    "text": "Question without time limit",

                    "time_limit_seconds": None,  # Missing!

                    "options": [

                        {"text": "A", "is_correct": True},

                        {"text": "B", "is_correct": False}

                    ]

                }

            ]

        }

        res = client.post(

            "/teacher/api/create_exam",

            json=invalid_exam,

            headers={"Authorization": f"Bearer {self.teacher_token}"}

        )

        self.assertEqual(res.status_code, 400)

        self.assertIn("must have a positive time_limit_seconds", res.json()["detail"])



    def test_per_question_timer_valid_creation(self):

        """When timer_type == 'per_question' and all questions have valid limits, creation succeeds."""

        valid_exam = {

            "title": "Valid Per Question Exam",

            "group_id": self.group.id,

            "start_time": "2026-05-01T10:00:00Z",

            "end_time": "2026-05-01T12:00:00Z",

            "duration_minutes": 120,

            "timer_type": "per_question",

            "default_marks": 2.0,

            "default_negative_marks": 0.0,

            "passing_marks": 1.0,

            "questions": [

                {

                    "text": "Q1 with limit",

                    "time_limit_seconds": 60,

                    "marks": 2.0,

                    "options": [

                        {"text": "A", "is_correct": True},

                        {"text": "B", "is_correct": False}

                    ]

                },

                {

                    "text": "Q2 with limit",

                    "time_limit_seconds": 45,

                    "marks": 2.0,

                    "options": [

                        {"text": "C", "is_correct": True},

                        {"text": "D", "is_correct": False}

                    ]

                }

            ]

        }

        res = client.post(

            "/teacher/api/create_exam",

            json=valid_exam,

            headers={"Authorization": f"Bearer {self.teacher_token}"}

        )

        self.assertEqual(res.status_code, 200)

        self.assertEqual(res.json()["status"], "success")



        # Verify DB values

        created = self.db.query(models.Exam).filter_by(title="Valid Per Question Exam").first()

        self.assertIsNotNone(created)

        self.assertEqual(created.timer_type, "per_question")

        self.assertEqual(len(created.questions), 2)

        self.assertEqual(created.questions[0].time_limit_seconds, 60)

        self.assertEqual(created.questions[1].time_limit_seconds, 45)



    def test_invalid_timer_type_rejected(self):

        """Unknown timer_type is rejected with HTTP 400."""

        invalid_timer = {

            "title": "Invalid Timer Type Exam",

            "group_id": self.group.id,

            "start_time": "2026-05-01T10:00:00Z",

            "end_time": "2026-05-01T12:00:00Z",

            "duration_minutes": 120,

            "timer_type": "invalid_mode",

            "default_marks": 1.0,

            "default_negative_marks": 0.0,

            "passing_marks": 0.5,

            "questions": [

                {

                    "text": "Sample Q",

                    "options": [

                        {"text": "A", "is_correct": True},

                        {"text": "B", "is_correct": False}

                    ]

                }

            ]

        }

        res = client.post(

            "/teacher/api/create_exam",

            json=invalid_timer,

            headers={"Authorization": f"Bearer {self.teacher_token}"}

        )

        self.assertEqual(res.status_code, 400)

        self.assertIn("Invalid timer_type", res.json()["detail"])





if __name__ == "__main__":

    unittest.main()
