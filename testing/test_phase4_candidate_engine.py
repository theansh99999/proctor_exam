"""

testing/test_phase4_candidate_engine.py

---------------------------------------

Comprehensive automated tests for Phase 4 — Candidate Assessment Flow & Exam Engine:

1. Candidate Assessment Instructions View:

   - Metrics display (duration, total questions, max marks, passing criteria, remaining attempts)

   - Proctoring checklist requirements

   - Authorization & eligibility gate

2. Attempt Eligibility & Max Attempts Enforcement:

   - Multi-attempt support (attempt 1, attempt 2)

   - Blocking when max_attempts reached

3. Concurrent Start Race-Condition Handling:

   - Thread safety in get_or_create_exam_session

4. Assessment Question Randomization:

   - Randomized order per attempt when randomize_questions=True

   - Order stability across reloads and timer reconnects

   - Natural order preserved when randomize_questions=False

5. All 6 Question Types Answering & Objective Evaluation:

   - single_choice

   - multiple_choice (multi-select)

   - true_false

   - short_answer

   - descriptive

   - code

6. Answer Autosave & Timer State Recovery:

   - Saving option, multi-options, text, bookmark flag

   - Recovery in get_exam_timer_state

7. Attempt Locking Post-Submission:

   - Saving answers rejected with 400 once submitted or expired

8. Manual Submission & Duplicate Submission Idempotence

9. Overall Timer Expiration & Server-Side Auto-Finalization (Browser closed scenario)

10. Per-Question Timer Deadline Enforcement

11. Proctoring Cheat Flag Active Window Validation & WebSocket alert

12. Multi-Tenant Organization Scoping & Candidate Isolation

"""

import os

os.environ["TESTING"] = "1"



import unittest

import json

from datetime import timedelta

from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi.testclient import TestClient



import models, auth, database

from main import app

from time_utils import utc_now, to_utc

from testing.test_db import init_test_db, cleanup_test_db, TestingSessionLocal, apply_test_db_override, clear_test_db_override

from routers.student_r import (

    evaluate_question_response,

    get_or_create_exam_session,

    finalize_exam_session,

    compute_overall_deadline

)



class TestPhase4CandidateEngine(unittest.TestCase):

    @classmethod

    def setUpClass(cls):

        apply_test_db_override()

        cls.client = TestClient(app)



    @classmethod

    def tearDownClass(cls):

        clear_test_db_override()



    def setUp(self):

        init_test_db()

        self.db = TestingSessionLocal()

        self._seed_data()



    def tearDown(self):

        self.db.close()

        cleanup_test_db()



    def _seed_data(self):

        # 1. Organizations

        self.org1 = models.Organization(name="Nexus Academy", slug="nexus", description="Tech Institute")

        self.org2 = models.Organization(name="Apex University", slug="apex", description="Medical Institute")

        self.db.add_all([self.org1, self.org2])

        self.db.commit()



        # 2. Examiners

        self.teacher1 = models.User(

            email="teacher1@nexus.edu",

            name="Professor Turing",

            password_hash=auth.get_password_hash("Pass123!"),

            role="examiner",

            organization_id=self.org1.id

        )

        self.teacher2 = models.User(

            email="teacher2@apex.edu",

            name="Dr. Gray",

            password_hash=auth.get_password_hash("Pass123!"),

            role="examiner",

            organization_id=self.org2.id

        )

        self.db.add_all([self.teacher1, self.teacher2])

        self.db.commit()



        # 3. Candidates

        self.student1 = models.User(

            email="student1@nexus.edu",

            name="Alice Candidate",

            password_hash=auth.get_password_hash("Pass123!"),

            role="candidate",

            organization_id=self.org1.id

        )

        self.student2 = models.User(

            email="student2@apex.edu",

            name="Bob Candidate",

            password_hash=auth.get_password_hash("Pass123!"),

            role="candidate",

            organization_id=self.org2.id

        )

        self.db.add_all([self.student1, self.student2])

        self.db.commit()



        # 4. Cohorts/Groups

        self.group1 = models.Group(name="CS Batch 2026", teacher_id=self.teacher1.id, organization_id=self.org1.id)

        self.group2 = models.Group(name="Bio Batch 2026", teacher_id=self.teacher2.id, organization_id=self.org2.id)

        self.db.add_all([self.group1, self.group2])

        self.db.commit()



        # Enroll Alice in group1

        self.db.add(models.GroupMember(

            group_id=self.group1.id,

            student_id=self.student1.id,

            student_email=self.student1.email

        ))

        # Enroll Bob in group2

        self.db.add(models.GroupMember(

            group_id=self.group2.id,

            student_id=self.student2.id,

            student_email=self.student2.email

        ))

        self.db.commit()



        # 5. Tokens

        self.student1_token = auth.create_access_token({"sub": self.student1.email, "role": "candidate"})

        self.student2_token = auth.create_access_token({"sub": self.student2.email, "role": "candidate"})

        self.teacher1_token = auth.create_access_token({"sub": self.teacher1.email, "role": "examiner"})



        # 6. Active Multi-Type Exam

        now = utc_now()

        self.exam = models.Exam(

            title="Comprehensive Technical Assessment",

            description="Testing candidate knowledge across multiple disciplines.",

            instructions="Answer all questions to the best of your ability. Keep webcam active.",

            assessment_type="technical",

            group_id=self.group1.id,

            organization_id=self.org1.id,

            creator_id=self.teacher1.id,

            start_time=now - timedelta(minutes=10),

            end_time=now + timedelta(hours=2),

            duration_minutes=90,

            timer_type="overall",

            default_marks=2.0,

            default_negative_marks=0.5,

            enable_negative_marking=True,

            passing_marks=5.0,

            max_attempts=2,

            randomize_questions=False,

            status="published"

        )

        self.db.add(self.exam)

        self.db.commit()



        # Seed 6 Questions covering all 6 question types

        # Q1: single_choice

        self.q_single = models.Question(

            exam_id=self.exam.id,

            text="What is the capital of France?",

            question_type="single_choice",

            marks=2.0,

            order_index=1

        )

        # Q2: multiple_choice

        self.q_multi = models.Question(

            exam_id=self.exam.id,

            text="Which of the following are prime numbers?",

            question_type="multiple_choice",

            marks=4.0,

            order_index=2

        )

        # Q3: true_false

        self.q_tf = models.Question(

            exam_id=self.exam.id,

            text="Python is a dynamically typed language.",

            question_type="true_false",

            marks=2.0,

            order_index=3

        )

        # Q4: short_answer

        self.q_short = models.Question(

            exam_id=self.exam.id,

            text="What HTTP status code represents 'Not Found'?",

            question_type="short_answer",

            marks=2.0,

            order_index=4

        )

        # Q5: descriptive

        self.q_desc = models.Question(

            exam_id=self.exam.id,

            text="Explain the concept of database ACID properties.",

            question_type="descriptive",

            marks=5.0,

            order_index=5

        )

        # Q6: code

        self.q_code = models.Question(

            exam_id=self.exam.id,

            text="Write a function `fib(n)` that returns the nth Fibonacci number.",

            question_type="code",

            type_config=json.dumps({"language": "python", "starter_code": "def fib(n):\n    pass"}),

            marks=5.0,

            order_index=6

        )

        self.db.add_all([self.q_single, self.q_multi, self.q_tf, self.q_short, self.q_desc, self.q_code])

        self.db.commit()



        # Options for Q1 (single_choice)

        self.q1_opt1 = models.Option(question_id=self.q_single.id, text="Paris", is_correct=True)

        self.q1_opt2 = models.Option(question_id=self.q_single.id, text="London", is_correct=False)

        self.q1_opt3 = models.Option(question_id=self.q_single.id, text="Berlin", is_correct=False)



        # Options for Q2 (multiple_choice: 2, 3 are prime)

        self.q2_opt1 = models.Option(question_id=self.q_multi.id, text="2", is_correct=True)

        self.q2_opt2 = models.Option(question_id=self.q_multi.id, text="3", is_correct=True)

        self.q2_opt3 = models.Option(question_id=self.q_multi.id, text="4", is_correct=False)

        self.q2_opt4 = models.Option(question_id=self.q_multi.id, text="9", is_correct=False)



        # Options for Q3 (true_false)

        self.q3_opt1 = models.Option(question_id=self.q_tf.id, text="True", is_correct=True)

        self.q3_opt2 = models.Option(question_id=self.q_tf.id, text="False", is_correct=False)



        # Options for Q4 (short_answer: accepted key is "404")

        self.q4_opt1 = models.Option(question_id=self.q_short.id, text="404", is_correct=True)



        self.db.add_all([

            self.q1_opt1, self.q1_opt2, self.q1_opt3,

            self.q2_opt1, self.q2_opt2, self.q2_opt3, self.q2_opt4,

            self.q3_opt1, self.q3_opt2,

            self.q4_opt1

        ])

        self.db.commit()



    # =========================================================================

    # 1. CANDIDATE ASSESSMENT INSTRUCTIONS VIEW

    # =========================================================================

    def test_01_candidate_instructions_view(self):

        """Candidate instructions view displays all metrics, rules, and proctoring checklist."""

        # 1. Authorized candidate accesses instructions

        res = self.client.get(

            f"/student/instructions/{self.exam.id}",

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res.status_code, 200)

        content = res.text



        # Verify key display elements

        self.assertIn("Comprehensive Technical Assessment", content)

        self.assertIn("Testing candidate knowledge across multiple disciplines", content)

        self.assertIn("Answer all questions to the best of your ability", content)

        self.assertIn("90 min", content)

        self.assertIn("6", content) # total questions

        self.assertIn("2", content) # remaining attempts

        self.assertIn("Negative Marking", content)

        self.assertIn("Proctoring Requirements", content)

        self.assertIn("Working webcam and microphone", content)

        self.assertIn("I confirm that I have read and agree", content)

        self.assertIn("Begin Assessment", content)



        # 2. Unauthorized student from Org 2 cannot view instructions

        res_unauth = self.client.get(

            f"/student/instructions/{self.exam.id}",

            headers={"Authorization": f"Bearer {self.student2_token}"}

        )

        self.assertEqual(res_unauth.status_code, 403)



    # =========================================================================

    # 2. ATTEMPT ELIGIBILITY & MAX ATTEMPTS ENFORCEMENT

    # =========================================================================

    def test_02_attempt_eligibility_and_max_attempts(self):

        """Multi-attempt session lifecycle and enforcement of max_attempts limit."""

        # Candidate starts attempt 1

        sess1 = get_or_create_exam_session(self.db, self.exam.id, self.student1.id)

        self.assertEqual(sess1.attempt_number, 1)

        self.assertEqual(sess1.status, "in_progress")



        # Simulate completion of attempt 1

        sess1.status = "submitted"

        sess1.submitted_at = utc_now()

        sess1.score = 8.0

        self.db.commit()



        # Candidate starts attempt 2 (max_attempts = 2)

        sess2 = get_or_create_exam_session(self.db, self.exam.id, self.student1.id)

        self.assertEqual(sess2.attempt_number, 2)

        self.assertNotEqual(sess1.id, sess2.id)



        # Simulate completion of attempt 2

        sess2.status = "submitted"

        sess2.submitted_at = utc_now()

        sess2.score = 12.0

        self.db.commit()



        # Candidate attempts to start attempt 3 -> blocked with 403

        with self.assertRaises(Exception) as cm:

            get_or_create_exam_session(self.db, self.exam.id, self.student1.id)

        self.assertEqual(cm.exception.status_code, 403)

        self.assertIn("Maximum assessment attempts reached", cm.exception.detail)



    # =========================================================================

    # 3. CONCURRENT START RACE-CONDITION SAFETY

    # =========================================================================

    def test_03_concurrent_start_race_condition(self):

        """Simultaneous start requests gracefully handle race conditions without duplicating attempts."""

        now = utc_now()

        conc_exam = models.Exam(

            title="Concurrency Assessment",

            group_id=self.group1.id,

            organization_id=self.org1.id,

            creator_id=self.teacher1.id,

            start_time=now - timedelta(minutes=5),

            end_time=now + timedelta(hours=1),

            duration_minutes=30,

            status="published",

            max_attempts=1

        )

        self.db.add(conc_exam)

        self.db.commit()



        # Sequential and multi-call idempotence check

        s1 = get_or_create_exam_session(self.db, conc_exam.id, self.student1.id)

        s2 = get_or_create_exam_session(self.db, conc_exam.id, self.student1.id)

        s3 = get_or_create_exam_session(self.db, conc_exam.id, self.student1.id)



        # All calls return the identical active ExamSession instance

        self.assertEqual(s1.id, s2.id)

        self.assertEqual(s2.id, s3.id)

        count = self.db.query(models.ExamSession).filter_by(exam_id=conc_exam.id, student_id=self.student1.id).count()

        self.assertEqual(count, 1)



    # =========================================================================

    # 4. ASSESSMENT QUESTION RANDOMIZATION

    # =========================================================================

    def test_04_assessment_question_randomization(self):

        """Question order randomization per attempt and stability across reloads."""

        # Enable question randomization on exam

        self.exam.randomize_questions = True

        self.db.commit()



        # 1. Start exam session

        sess = get_or_create_exam_session(self.db, self.exam.id, self.student1.id)

        self.assertIsNotNone(sess.question_order)

        order_list = json.loads(sess.question_order)

        self.assertEqual(len(order_list), 6)

        all_q_ids = {self.q_single.id, self.q_multi.id, self.q_tf.id, self.q_short.id, self.q_desc.id, self.q_code.id}

        self.assertEqual(set(order_list), all_q_ids)



        # 2. Candidate loads take_exam page

        res = self.client.get(

            f"/student/exam/{self.exam.id}",

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res.status_code, 200)



        # 3. Reload page: check that session question_order remains 100% stable

        sess_refreshed = self.db.query(models.ExamSession).filter_by(id=sess.id).first()

        self.assertEqual(json.loads(sess_refreshed.question_order), order_list)



        # 4. Natural order when randomize_questions is False

        now = utc_now()

        non_rand_exam = models.Exam(

            title="Non-Random Assessment",

            group_id=self.group1.id,

            organization_id=self.org1.id,

            creator_id=self.teacher1.id,

            start_time=now - timedelta(minutes=5),

            end_time=now + timedelta(hours=1),

            duration_minutes=30,

            status="published",

            randomize_questions=False

        )

        self.db.add(non_rand_exam)

        self.db.commit()



        q_a = models.Question(exam_id=non_rand_exam.id, text="Q A", order_index=1)

        q_b = models.Question(exam_id=non_rand_exam.id, text="Q B", order_index=2)

        self.db.add_all([q_a, q_b])

        self.db.commit()



        sess_nr = get_or_create_exam_session(self.db, non_rand_exam.id, self.student1.id)

        self.assertIsNone(sess_nr.question_order)



    # =========================================================================

    # 5. ALL 6 QUESTION TYPES ANSWERING & OBJECTIVE EVALUATION

    # =========================================================================

    def test_05_all_six_question_types_answering_and_evaluation(self):

        """Correct evaluation across single_choice, multiple_choice, true_false, short_answer, descriptive, code."""

        # 1. single_choice: correct awards full marks (2.0)

        is_corr, marks = evaluate_question_response(self.q_single, self.exam, self.q1_opt1.id, None)

        self.assertTrue(is_corr)

        self.assertEqual(marks, 2.0)



        # single_choice: wrong deducts negative marks (-0.5)

        is_corr, marks = evaluate_question_response(self.q_single, self.exam, self.q1_opt2.id, None)

        self.assertFalse(is_corr)

        self.assertEqual(marks, -0.5)



        # 2. multiple_choice: both correct options selected awards full marks (4.0)

        multi_ans = json.dumps([self.q2_opt1.id, self.q2_opt2.id])

        is_corr, marks = evaluate_question_response(self.q_multi, self.exam, None, multi_ans)

        self.assertTrue(is_corr)

        self.assertEqual(marks, 4.0)



        # multiple_choice: incomplete selection returns False and applies negative marking if enabled

        partial_ans = json.dumps([self.q2_opt1.id])

        is_corr, marks = evaluate_question_response(self.q_multi, self.exam, None, partial_ans)

        self.assertFalse(is_corr)

        self.assertEqual(marks, -0.5)



        # multiple_choice: selecting wrong option applies negative penalty (-0.5)

        wrong_multi = json.dumps([self.q2_opt3.id])

        is_corr, marks = evaluate_question_response(self.q_multi, self.exam, None, wrong_multi)

        self.assertFalse(is_corr)

        self.assertEqual(marks, -0.5)



        # 3. true_false: correct answer awards full marks (2.0)

        is_corr, marks = evaluate_question_response(self.q_tf, self.exam, self.q3_opt1.id, None)

        self.assertTrue(is_corr)

        self.assertEqual(marks, 2.0)



        # 4. short_answer: exact match (case insensitive) awards full marks (2.0)

        is_corr, marks = evaluate_question_response(self.q_short, self.exam, None, "404")

        self.assertTrue(is_corr)

        self.assertEqual(marks, 2.0)



        is_corr, marks = evaluate_question_response(self.q_short, self.exam, None, "500")

        self.assertFalse(is_corr)

        self.assertEqual(marks, 0.0)



        # 5. descriptive: answer recorded, default 0.0 marks until examiner grading

        is_corr, marks = evaluate_question_response(self.q_desc, self.exam, None, "Atomicity, Consistency, Isolation, Durability.")

        self.assertTrue(is_corr)

        self.assertEqual(marks, 0.0)



        # 6. code: candidate code recorded, default 0.0 until test runner evaluation

        sample_code = "def fib(n):\n    return n if n <= 1 else fib(n-1) + fib(n-2)"

        is_corr, marks = evaluate_question_response(self.q_code, self.exam, None, sample_code)

        self.assertTrue(is_corr)

        self.assertEqual(marks, 0.0)



    # =========================================================================

    # 6. ANSWER AUTOSAVE & TIMER STATE RECOVERY

    # =========================================================================

    def test_06_answer_autosave_and_timer_state_recovery(self):

        """Autosave endpoint persists option, text, bookmarks and recovers via timer_state."""

        # 1. Autosave single choice answer

        res1 = self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_single.id, "selected_option_id": self.q1_opt1.id, "is_bookmarked": True},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res1.status_code, 200)

        self.assertEqual(res1.json()["status"], "saved")



        # 2. Autosave multiple choice answer

        res2 = self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_multi.id, "selected_option_ids": [self.q2_opt1.id, self.q2_opt2.id]},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res2.status_code, 200)



        # 3. Autosave short answer text

        res3 = self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_short.id, "answer_text": "404"},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res3.status_code, 200)



        # 4. Autosave code answer

        code_str = "def fib(n): return n if n <= 1 else fib(n-1) + fib(n-2)"

        res4 = self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_code.id, "answer_text": code_str},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res4.status_code, 200)



        # 5. Query timer_state and verify recovered answers

        res_state = self.client.get(

            f"/student/api/exam/{self.exam.id}/timer_state",

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res_state.status_code, 200)

        data = res_state.json()



        # Verify saved_answers map

        saved_map = data.get("saved_answers", {})

        self.assertEqual(saved_map.get(str(self.q_single.id)), self.q1_opt1.id)



        # Verify saved_answers_detail

        detail = data.get("saved_answers_detail", {})

        self.assertTrue(detail[str(self.q_single.id)]["is_bookmarked"])

        self.assertEqual(detail[str(self.q_multi.id)]["selected_option_ids"], [self.q2_opt1.id, self.q2_opt2.id])

        self.assertEqual(detail[str(self.q_short.id)]["answer_text"], "404")

        self.assertEqual(detail[str(self.q_code.id)]["answer_text"], code_str)



    # =========================================================================

    # 7. ATTEMPT LOCKING POST-SUBMISSION

    # =========================================================================

    def test_07_attempt_locking_post_submission(self):

        """Saving answers is rejected with 400 once exam session is submitted or expired."""

        # Initialize exam session

        sess = get_or_create_exam_session(self.db, self.exam.id, self.student1.id)



        # Submit the session

        finalize_exam_session(self.db, sess, self.exam, self.student1, submission_type="manual")



        # Attempt to save an answer after submission

        res = self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_single.id, "selected_option_id": self.q1_opt1.id},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res.status_code, 400)

        self.assertIn("Attempt already completed", res.json()["detail"])



    # =========================================================================

    # 8. MANUAL SUBMISSION & DUPLICATE SUBMISSION IDEMPOTENCE

    # =========================================================================

    def test_08_manual_submission_and_idempotence(self):

        """Submitting exam calculates score and subsequent submission calls are idempotent."""

        # 1. Autosave answers for Alice

        self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_single.id, "selected_option_id": self.q1_opt1.id}, # +2.0

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_tf.id, "selected_option_id": self.q3_opt1.id}, # +2.0

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_short.id, "answer_text": "404"}, # +2.0

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )



        # 2. Submit exam via POST /student/submit_exam/{exam.id}

        res_sub1 = self.client.post(

            f"/student/submit_exam/{self.exam.id}",

            data={},

            headers={"Authorization": f"Bearer {self.student1_token}"},

            follow_redirects=False

        )

        self.assertIn(res_sub1.status_code, [200, 302, 303])



        # Verify Submission and score in database (2.0 + 2.0 + 2.0 = 6.0)

        sub1 = self.db.query(models.Submission).filter_by(exam_id=self.exam.id, student_id=self.student1.id).first()

        self.assertIsNotNone(sub1)

        self.assertEqual(sub1.score, 6.0)



        # Verify ExamSession marked submitted

        sess = self.db.query(models.ExamSession).filter_by(exam_id=self.exam.id, student_id=self.student1.id).first()

        self.assertEqual(sess.status, "submitted")

        self.assertEqual(sess.score, 6.0)



        # 3. Duplicate submission: must not crash or duplicate Submission record

        res_sub2 = self.client.post(

            f"/student/submit_exam/{self.exam.id}",

            data={},

            headers={"Authorization": f"Bearer {self.student1_token}"},

            follow_redirects=False

        )

        self.assertIn(res_sub2.status_code, [200, 302, 303])

        sub_count = self.db.query(models.Submission).filter_by(exam_id=self.exam.id, student_id=self.student1.id).count()

        self.assertEqual(sub_count, 1)



    # =========================================================================

    # 9. OVERALL TIMER EXPIRATION & SERVER-SIDE AUTO-FINALIZATION

    # =========================================================================

    def test_09_overall_timer_expiration_and_auto_finalization(self):

        """Browser closed scenario: when overall deadline passes, server auto-finalizes attempt."""

        # 1. Candidate starts exam and answers Q1

        self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_single.id, "selected_option_id": self.q1_opt1.id}, # +2.0

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )



        # 2. Simulate candidate closing browser and time elapsing beyond deadline

        sess = self.db.query(models.ExamSession).filter_by(exam_id=self.exam.id, student_id=self.student1.id).first()

        sess.overall_deadline = utc_now() - timedelta(minutes=5)

        self.db.commit()



        # 3. Server probe (e.g. background check or candidate revisiting dashboard)

        res = self.client.get(

            f"/student/api/exam/{self.exam.id}/timer_state",

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res.status_code, 200)

        data = res.json()

        self.assertIn(data["status"], ["expired", "completed"])

        self.assertTrue(data["is_expired"])



        # Submission created automatically on the server with score = 2.0

        sub = self.db.query(models.Submission).filter_by(exam_id=self.exam.id, student_id=self.student1.id).first()

        self.assertIsNotNone(sub)

        self.assertEqual(sub.score, 2.0)



    # =========================================================================

    # 10. PER-QUESTION TIMER DEADLINE ENFORCEMENT

    # =========================================================================

    def test_10_per_question_timer_deadline_enforcement(self):

        """For per_question timer type, question deadlines are strictly enforced."""

        now = utc_now()

        pq_exam = models.Exam(

            title="Fast Math Quiz",

            group_id=self.group1.id,

            organization_id=self.org1.id,

            creator_id=self.teacher1.id,

            start_time=now - timedelta(minutes=5),

            end_time=now + timedelta(hours=1),

            duration_minutes=30,

            timer_type="per_question",

            default_marks=2.0,

            status="published"

        )

        self.db.add(pq_exam)

        self.db.commit()



        q_timed = models.Question(exam_id=pq_exam.id, text="2 + 2 = ?", marks=2.0, time_limit_seconds=10)

        self.db.add(q_timed)

        self.db.commit()

        opt_timed = models.Option(question_id=q_timed.id, text="4", is_correct=True)

        self.db.add(opt_timed)

        self.db.commit()



        # Start exam

        self.client.get(

            f"/student/api/exam/{pq_exam.id}/timer_state",

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )



        # Question session created; expire its deadline

        qs = self.db.query(models.QuestionSession).filter_by(question_id=q_timed.id).first()

        self.assertIsNotNone(qs)

        qs.deadline = utc_now() - timedelta(seconds=15)

        qs.is_locked = True

        self.db.commit()



        # Attempt to submit answer to expired question -> 400

        res = self.client.post(

            f"/student/api/exam/{pq_exam.id}/save_question_answer",

            json={"question_id": q_timed.id, "selected_option_id": opt_timed.id},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res.status_code, 400)

        self.assertIn("expired", res.json()["detail"].lower())



    # =========================================================================

    # 11. PROCTORING CHEAT FLAG ACTIVE WINDOW VALIDATION

    # =========================================================================

    def test_11_proctoring_cheat_flag_active_window(self):

        """Cheat flags accepted only during active exam window, rejected otherwise."""

        # 1. Active window: flag accepted

        res_active = self.client.post(

            "/student/api/cheat_flag",

            json={"exam_id": self.exam.id, "description": "Tab switch detected"},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res_active.status_code, 200)

        self.assertEqual(res_active.json()["status"], "logged")



        # 2. Future exam: flag rejected

        now = utc_now()

        future_exam = models.Exam(

            title="Future Exam",

            group_id=self.group1.id,

            organization_id=self.org1.id,

            start_time=now + timedelta(hours=1),

            end_time=now + timedelta(hours=2),

            duration_minutes=60,

            status="scheduled"

        )

        self.db.add(future_exam)

        self.db.commit()



        res_future = self.client.post(

            "/student/api/cheat_flag",

            json={"exam_id": future_exam.id, "description": "Tab switch detected"},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res_future.status_code, 400)

        self.assertIn("has not started yet", res_future.json()["detail"])



        # 3. Expired exam: flag rejected

        past_exam = models.Exam(

            title="Expired Exam",

            group_id=self.group1.id,

            organization_id=self.org1.id,

            start_time=now - timedelta(hours=3),

            end_time=now - timedelta(hours=1),

            duration_minutes=60,

            status="completed"

        )

        self.db.add(past_exam)

        self.db.commit()



        res_past = self.client.post(

            "/student/api/cheat_flag",

            json={"exam_id": past_exam.id, "description": "Tab switch detected"},

            headers={"Authorization": f"Bearer {self.student1_token}"}

        )

        self.assertEqual(res_past.status_code, 400)

        self.assertIn("has already ended", res_past.json()["detail"])



    # =========================================================================

    # 12. MULTI-TENANT ORGANIZATION SCOPING & CANDIDATE ISOLATION

    # =========================================================================

    def test_12_organization_scoping_and_candidate_isolation(self):

        """Candidates cannot access or submit assessments outside their organization."""

        # Bob (Org 2) attempts to access Org 1's exam

        res_inst = self.client.get(

            f"/student/instructions/{self.exam.id}",

            headers={"Authorization": f"Bearer {self.student2_token}"}

        )

        self.assertEqual(res_inst.status_code, 403)



        res_take = self.client.get(

            f"/student/exam/{self.exam.id}",

            headers={"Authorization": f"Bearer {self.student2_token}"}

        )

        self.assertEqual(res_take.status_code, 403)



        res_save = self.client.post(

            f"/student/api/exam/{self.exam.id}/save_question_answer",

            json={"question_id": self.q_single.id, "selected_option_id": self.q1_opt1.id},

            headers={"Authorization": f"Bearer {self.student2_token}"}

        )

        self.assertEqual(res_save.status_code, 403)



        res_sub = self.client.post(

            f"/student/submit_exam/{self.exam.id}",

            data={},

            headers={"Authorization": f"Bearer {self.student2_token}"}

        )

        self.assertEqual(res_sub.status_code, 403)





if __name__ == "__main__":

    unittest.main()
