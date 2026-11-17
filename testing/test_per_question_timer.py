"""

testing/test_per_question_timer.py

----------------------------------

Automated test suite verifying:

1. Server-side per-question timer tracking & state sync.

2. Page refresh does NOT reset timer.

3. Direct API submission for expired questions is strictly rejected.

4. Direct form submit bypass is discarded (0 marks for expired questions).

5. Question navigation locking (cannot modify previous locked question).

6. Multi-attempt support in ExamSession (attempt_number increments).

7. Effective question deadline capped by overall exam deadline.

8. Server-side exam completion on last question expiry (browser close simulation).

9. Cheat flag active-window boundary validations (future/past exam rejected).

10. Overall timer backwards compatibility and non-regression.

"""



import os

os.environ["TESTING"] = "1"



import unittest

from datetime import datetime, timezone, timedelta

from unittest.mock import AsyncMock, patch



from fastapi.testclient import TestClient



import models

from main import app

from database import get_db

import auth

from time_utils import utc_now, to_utc, to_utc_iso

from testing.test_db import init_test_db, cleanup_test_db, TestingSessionLocal, engine



client = TestClient(app)



class TestServerSidePerQuestionTimer(unittest.TestCase):



    def setUp(self):

        init_test_db()

        self.db = TestingSessionLocal()



        # Teacher

        self.teacher = models.User(

            email="prof_timer@test.com",

            name="Professor Timer",

            password_hash=auth.get_password_hash("Password123"),

            role="teacher"

        )

        self.db.add(self.teacher)



        # Student

        self.student = models.User(

            email="alice_timer@test.com",

            name="Alice Timer",

            password_hash=auth.get_password_hash("Password123"),

            role="student"

        )

        self.db.add(self.student)

        self.db.commit()



        # Group

        self.group = models.Group(name="Physics Cohort", teacher_id=self.teacher.id)

        self.db.add(self.group)

        self.db.commit()



        # Enroll student

        self.db.add(models.GroupMember(

            group_id=self.group.id,

            student_id=self.student.id,

            student_email=self.student.email

        ))

        self.db.commit()



        # Active Per-Question Exam

        now = utc_now()

        self.pq_exam = models.Exam(

            title="Quantum Mechanics Quiz",

            group_id=self.group.id,

            start_time=now - timedelta(minutes=5),

            end_time=now + timedelta(minutes=55),

            duration_minutes=60,

            timer_type="per_question",

            default_marks=2.0,

            default_negative_marks=0.0,

            passing_marks=2.0

        )

        self.db.add(self.pq_exam)

        self.db.commit()



        # Question 1 (30s limit)

        self.q1 = models.Question(exam_id=self.pq_exam.id, text="Q1 Planck constant?", marks=2.0, time_limit_seconds=30)

        # Question 2 (30s limit)

        self.q2 = models.Question(exam_id=self.pq_exam.id, text="Q2 Wave particle duality?", marks=2.0, time_limit_seconds=30)

        self.db.add_all([self.q1, self.q2])

        self.db.commit()



        self.q1_opt1 = models.Option(question_id=self.q1.id, text="h = 6.626e-34", is_correct=True)

        self.q1_opt2 = models.Option(question_id=self.q1.id, text="h = 3.0e8", is_correct=False)

        self.q2_opt1 = models.Option(question_id=self.q2.id, text="De Broglie", is_correct=True)

        self.q2_opt2 = models.Option(question_id=self.q2.id, text="Newton", is_correct=False)

        self.db.add_all([self.q1_opt1, self.q1_opt2, self.q2_opt1, self.q2_opt2])

        self.db.commit()



        # Tokens

        self.student_token = auth.create_access_token({"sub": self.student.email, "role": "student"})

        self.teacher_token = auth.create_access_token({"sub": self.teacher.email, "role": "teacher"})



    def tearDown(self):

        self.db.close()

        cleanup_test_db()



    # =========================================================================

    # 1. CHEAT FLAG ACTIVE WINDOW BOUNDARY TESTS

    # =========================================================================

    def test_cheat_flag_future_exam_rejected(self):

        """Violations for exams that haven't started yet are rejected with HTTP 400."""

        now = utc_now()

        future_exam = models.Exam(

            title="Future Exam",

            group_id=self.group.id,

            start_time=now + timedelta(hours=1),

            end_time=now + timedelta(hours=2),

            duration_minutes=60,

            passing_marks=1.0

        )

        self.db.add(future_exam)

        self.db.commit()



        res = client.post(

            "/student/api/cheat_flag",

            json={"exam_id": future_exam.id, "description": "Violation"},

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res.status_code, 400)

        self.assertIn("has not started yet", res.json()["detail"])



    def test_cheat_flag_expired_exam_rejected(self):

        """Violations for exams that already ended are rejected with HTTP 400."""

        now = utc_now()

        past_exam = models.Exam(

            title="Past Exam",

            group_id=self.group.id,

            start_time=now - timedelta(hours=3),

            end_time=now - timedelta(hours=1),

            duration_minutes=60,

            passing_marks=1.0

        )

        self.db.add(past_exam)

        self.db.commit()



        res = client.post(

            "/student/api/cheat_flag",

            json={"exam_id": past_exam.id, "description": "Violation"},

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res.status_code, 400)

        self.assertIn("has already ended", res.json()["detail"])



    # =========================================================================

    # 2. SERVER-SIDE PER-QUESTION TIMER & REFRESH RESILIENCE

    # =========================================================================

    def test_timer_state_initialization(self):

        """Calling timer_state initializes ExamSession and QuestionSession for Q1."""

        res = client.get(

            f"/student/api/exam/{self.pq_exam.id}/timer_state",

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res.status_code, 200)

        data = res.json()

        self.assertEqual(data["status"], "active")

        self.assertEqual(data["timer_type"], "per_question")

        self.assertEqual(data["current_question_id"], self.q1.id)

        self.assertEqual(data["current_question_index"], 1)

        self.assertGreaterEqual(data["remaining_seconds"], 28)

        self.assertLessEqual(data["remaining_seconds"], 30)



    def test_page_refresh_does_not_reset_timer(self):

        """

        Simulating page refresh: After starting Q1 and advancing time,

        subsequent timer_state returns the decreased remaining seconds, NOT resetting to 30.

        """

        # Step 1: Initialize session

        client.get(f"/student/api/exam/{self.pq_exam.id}/timer_state", headers={"Authorization": f"Bearer {self.student_token}"})



        # Step 2: Simulate 12 seconds elapsed by advancing started_at in DB

        qs = self.db.query(models.QuestionSession).join(models.ExamSession).filter(

            models.ExamSession.exam_id == self.pq_exam.id,

            models.QuestionSession.question_id == self.q1.id

        ).first()

        self.assertIsNotNone(qs)



        # Shift deadline 12 seconds closer

        qs.deadline = qs.deadline - timedelta(seconds=12)

        self.db.commit()



        # Step 3: Student refreshes page (calls timer_state)

        res_refresh = client.get(

            f"/student/api/exam/{self.pq_exam.id}/timer_state",

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        data = res_refresh.json()

        # Remaining time should be ~18s (30 - 12), NOT reset to 30s!

        self.assertLessEqual(data["remaining_seconds"], 19)

        self.assertGreaterEqual(data["remaining_seconds"], 16)



    # =========================================================================

    # 3. DIRECT API & EXPIRED QUESTION REJECTION

    # =========================================================================

    def test_answer_submission_within_deadline_succeeds(self):

        """Submitting answer within deadline succeeds and records submitted_at."""

        # Initialize

        client.get(f"/student/api/exam/{self.pq_exam.id}/timer_state", headers={"Authorization": f"Bearer {self.student_token}"})



        payload = {"question_id": self.q1.id, "selected_option_id": self.q1_opt1.id}

        res = client.post(

            f"/student/api/exam/{self.pq_exam.id}/save_question_answer",

            json=payload,

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res.status_code, 200)

        self.assertEqual(res.json()["status"], "saved")



        # Verify DB

        qs = self.db.query(models.QuestionSession).filter_by(question_id=self.q1.id).first()

        self.assertEqual(qs.selected_option_id, self.q1_opt1.id)

        self.assertIsNotNone(qs.submitted_at)



    def test_direct_api_expired_answer_rejected(self):

        """Submitting answer to save_question_answer after deadline + grace is rejected with HTTP 400."""

        # Initialize

        client.get(f"/student/api/exam/{self.pq_exam.id}/timer_state", headers={"Authorization": f"Bearer {self.student_token}"})



        # Artificially expire Q1 deadline in DB (passed 10 seconds ago)

        qs = self.db.query(models.QuestionSession).filter_by(question_id=self.q1.id).first()

        qs.deadline = utc_now() - timedelta(seconds=10)

        self.db.commit()



        # Attempt to submit answer via API

        payload = {"question_id": self.q1.id, "selected_option_id": self.q1_opt1.id}

        res = client.post(

            f"/student/api/exam/{self.pq_exam.id}/save_question_answer",

            json=payload,

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res.status_code, 400)

        self.assertIn("Question deadline has expired", res.json()["detail"])



    def test_direct_form_submit_discards_expired_answers(self):

        """

        Submitting form data directly to /submit_exam/{id} with answers for expired questions

        must DISCARD the expired answers and NOT award points.

        """

        # Initialize session

        client.get(f"/student/api/exam/{self.pq_exam.id}/timer_state", headers={"Authorization": f"Bearer {self.student_token}"})



        # Answer Q1 lawfully within deadline

        client.post(

            f"/student/api/exam/{self.pq_exam.id}/save_question_answer",

            json={"question_id": self.q1.id, "selected_option_id": self.q1_opt1.id}, # Correct (+2.0)

            headers={"Authorization": f"Bearer {self.student_token}"}

        )



        # Move to Q2 and expire Q2 without answering it in session

        client.post(

            f"/student/api/exam/{self.pq_exam.id}/next_question",

            json={"current_question_id": self.q1.id},

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        q2_s = self.db.query(models.QuestionSession).filter_by(question_id=self.q2.id).first()

        q2_s.deadline = utc_now() - timedelta(seconds=10) # Expired!

        q2_s.is_locked = True

        self.db.commit()



        # Attacker tries to bypass timer by sending form POST with correct answers for BOTH Q1 and Q2

        bypass_form = {

            f"question_{self.q1.id}": str(self.q1_opt1.id),

            f"question_{self.q2.id}": str(self.q2_opt1.id)  # Correct answer for Q2, but Q2 expired!

        }

        res = client.post(

            f"/student/submit_exam/{self.pq_exam.id}",

            data=bypass_form,

            headers={"Authorization": f"Bearer {self.student_token}"},

            follow_redirects=False

        )

        self.assertEqual(res.status_code, 302)



        # Verify score in DB: only Q1 (2.0) should be awarded! Q2 must be 0!

        sub = self.db.query(models.Submission).filter_by(exam_id=self.pq_exam.id, student_id=self.student.id).first()

        self.assertEqual(sub.score, 2.0)



    # =========================================================================

    # 4. QUESTION NAVIGATION LOCKING & AUTO-ADVANCE

    # =========================================================================

    def test_question_navigation_locks_previous_question(self):

        """Moving to next question permanently locks the previous question."""

        # Initialize

        client.get(f"/student/api/exam/{self.pq_exam.id}/timer_state", headers={"Authorization": f"Bearer {self.student_token}"})



        # Advance to Q2

        res_next = client.post(

            f"/student/api/exam/{self.pq_exam.id}/next_question",

            json={"current_question_id": self.q1.id},

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res_next.status_code, 200)

        self.assertEqual(res_next.json()["question_id"], self.q2.id)



        # Attempt to change Q1 answer now

        res_back = client.post(

            f"/student/api/exam/{self.pq_exam.id}/save_question_answer",

            json={"question_id": self.q1.id, "selected_option_id": self.q1_opt2.id},

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        self.assertEqual(res_back.status_code, 400)

        self.assertIn("Question deadline has expired", res_back.json()["detail"])



    # =========================================================================

    # 5. MULTI-ATTEMPT SUPPORT IN EXAM_SESSION

    # =========================================================================

    def test_multi_attempt_support(self):

        """ExamSession records separate attempts with incremented attempt_number."""

        from routers.student_r import get_or_create_exam_session

        self.pq_exam.max_attempts = 2

        self.db.commit()



        # Attempt 1

        s1 = get_or_create_exam_session(self.db, self.pq_exam.id, self.student.id, self.pq_exam)

        self.assertEqual(s1.attempt_number, 1)



        # Complete attempt 1

        s1.status = "completed"

        self.db.commit()



        # Attempt 2

        s2 = get_or_create_exam_session(self.db, self.pq_exam.id, self.student.id, self.pq_exam)

        self.assertEqual(s2.attempt_number, 2)

        self.assertNotEqual(s1.id, s2.id)



    # =========================================================================

    # 6. QUESTION DEADLINE CAPPED BY OVERALL EXAM DEADLINE

    # =========================================================================

    def test_question_deadline_capped_by_overall_exam_deadline(self):

        """

        When overall exam has only 15 seconds remaining, a 60-second question's deadline

        must be capped at the overall exam deadline (15 seconds), NOT 60 seconds.

        """

        now = utc_now()

        # Exam with only 15 seconds left

        tight_exam = models.Exam(

            title="Tight Exam",

            group_id=self.group.id,

            start_time=now - timedelta(minutes=59),

            end_time=now + timedelta(seconds=15),

            duration_minutes=60,

            timer_type="per_question",

            passing_marks=1.0

        )

        self.db.add(tight_exam)

        self.db.commit()



        q = models.Question(exam_id=tight_exam.id, text="Long limit Q", time_limit_seconds=120)

        self.db.add(q)

        self.db.commit()



        from routers.student_r import get_or_create_exam_session, get_or_create_question_session

        es = get_or_create_exam_session(self.db, tight_exam.id, self.student.id, tight_exam)

        qs = get_or_create_question_session(self.db, es, q, tight_exam)



        # Question deadline must not exceed overall exam deadline

        self.assertLessEqual(to_utc(qs.deadline), to_utc(es.overall_deadline))

        seconds_allowed = (to_utc(qs.deadline) - now).total_seconds()

        self.assertLessEqual(seconds_allowed, 16) # ~15 seconds, NOT 120 seconds!



    # =========================================================================

    # 7. SERVER-SIDE AUTO-COMPLETION ON LAST QUESTION EXPIRY

    # =========================================================================

    def test_server_side_completion_on_all_questions_expired(self):

        """When all questions are expired, timer_state auto-finalizes the session and creates a Submission."""

        # Initialize session (Q1 active)

        client.get(f"/student/api/exam/{self.pq_exam.id}/timer_state", headers={"Authorization": f"Bearer {self.student_token}"})



        # Answer Q1

        client.post(

            f"/student/api/exam/{self.pq_exam.id}/save_question_answer",

            json={"question_id": self.q1.id, "selected_option_id": self.q1_opt1.id},

            headers={"Authorization": f"Bearer {self.student_token}"}

        )



        # Advance to Q2 (Q2 active)

        client.post(

            f"/student/api/exam/{self.pq_exam.id}/next_question",

            json={"current_question_id": self.q1.id},

            headers={"Authorization": f"Bearer {self.student_token}"}

        )



        # Expire all questions

        for qs in self.db.query(models.QuestionSession).all():

            qs.deadline = utc_now() - timedelta(seconds=10)

            qs.is_locked = True

        self.db.commit()



        # Client queries timer_state (or background poll)

        res = client.get(

            f"/student/api/exam/{self.pq_exam.id}/timer_state",

            headers={"Authorization": f"Bearer {self.student_token}"}

        )

        data = res.json()

        self.assertEqual(data["status"], "completed")

        self.assertTrue(data["is_expired"])



        # Submission was created on the server!

        sub = self.db.query(models.Submission).filter_by(exam_id=self.pq_exam.id, student_id=self.student.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 2.0)



    # =========================================================================

    # 8. OVERALL TIMER BACKWARDS COMPATIBILITY

    # =========================================================================

    def test_overall_timer_exam_workflow_preserved(self):

        """Standard overall-timer exams function normally with multi-question form submission."""

        now = utc_now()

        overall_exam = models.Exam(

            title="Overall Timer Exam",

            group_id=self.group.id,

            start_time=now - timedelta(minutes=10),

            end_time=now + timedelta(minutes=50),

            duration_minutes=60,

            timer_type="overall",

            default_marks=5.0,

            passing_marks=5.0

        )

        self.db.add(overall_exam)

        self.db.commit()



        oq1 = models.Question(exam_id=overall_exam.id, text="Overall Q1", marks=5.0)

        self.db.add(oq1)

        self.db.commit()

        opt = models.Option(question_id=oq1.id, text="Correct", is_correct=True)

        self.db.add(opt)

        self.db.commit()



        # Submit form

        res = client.post(

            f"/student/submit_exam/{overall_exam.id}",

            data={f"question_{oq1.id}": str(opt.id)},

            headers={"Authorization": f"Bearer {self.student_token}"},

            follow_redirects=False

        )

        self.assertEqual(res.status_code, 302)



        sub = self.db.query(models.Submission).filter_by(exam_id=overall_exam.id, student_id=self.student.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 5.0)





if __name__ == "__main__":

    unittest.main()
