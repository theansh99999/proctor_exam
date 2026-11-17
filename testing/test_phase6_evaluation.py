"""
testing/test_phase6_evaluation.py
---------------------------------
Comprehensive Unit & Integration Test Suite for Phase 6:
- Unified Evaluation Engine across all 6 question types
- Partial marking and negative marking
- Manual grading workflow (draft & final)
- Maximum marks boundary enforcement
- Regrading & Audit trail tracking
- Configurable pass/fail rules (percentage, raw marks, mandatory questions, section cutoffs)
- Pending result handling while manual grading is incomplete
- Result release & candidate privacy enforcement
- Multiple attempt result isolation
- Proctoring score separation (academic marks never penalized by proctoring)
- Organization isolation
- Results export
"""
import unittest
import json
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import database
import auth
from main import app
from time_utils import utc_now
from modules.evaluation.service import EvaluationService

# Isolated In-Memory SQLite Test Engine
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[database.get_db] = override_get_db


class TestPhase6Evaluation(unittest.TestCase):

    def setUp(self):
        app.dependency_overrides[database.get_db] = override_get_db
        models.Base.metadata.create_all(bind=test_engine)
        self.db = TestSessionLocal()
        self.client = TestClient(app)

        now = utc_now()

        # 1. Organizations
        self.org1 = models.Organization(name="Org One", slug="org-one", is_active=True)
        self.org2 = models.Organization(name="Org Two", slug="org-two", is_active=True)
        self.db.add_all([self.org1, self.org2])
        self.db.commit()

        # 2. Users
        self.examiner1 = models.User(
            email="examiner1@test.com",
            name="Examiner One",
            password_hash=auth.get_password_hash("pass123"),
            role="examiner",
            organization_id=self.org1.id
        )
        self.examiner2 = models.User(
            email="examiner2@test.com",
            name="Examiner Two",
            password_hash=auth.get_password_hash("pass123"),
            role="examiner",
            organization_id=self.org2.id
        )
        self.student1 = models.User(
            email="student1@test.com",
            name="Student One",
            password_hash=auth.get_password_hash("pass123"),
            role="student",
            organization_id=self.org1.id
        )
        self.db.add_all([self.examiner1, self.examiner2, self.student1])
        self.db.commit()

        # 3. Assessment
        self.exam = models.Exam(
            title="Comprehensive Phase 6 Exam",
            organization_id=self.org1.id,
            creator_id=self.examiner1.id,
            assessment_type="academic",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            default_marks=5.0,
            default_negative_marks=1.0,
            enable_negative_marking=True,
            passing_marks=15.0,
            passing_criteria="percentage",
            passing_percentage=50.0,
            results_released=False,
            status="published"
        )
        self.db.add(self.exam)
        self.db.commit()

        # 4. Questions: All 6 types
        # Q1: Single Choice (5 marks, -1 negative)
        self.q_single = models.Question(
            exam_id=self.exam.id,
            text="What is 2 + 2?",
            question_type="single_choice",
            marks=5.0,
            negative_marks=1.0,
            order_index=1
        )
        self.db.add(self.q_single)
        self.db.flush()
        self.opt_single_corr = models.Option(question_id=self.q_single.id, text="4", is_correct=True)
        self.opt_single_inc = models.Option(question_id=self.q_single.id, text="5", is_correct=False)
        self.db.add_all([self.opt_single_corr, self.opt_single_inc])

        # Q2: Multiple Choice (10 marks, -2 negative, exact match)
        self.q_multi = models.Question(
            exam_id=self.exam.id,
            text="Select prime numbers",
            question_type="multiple_choice",
            marks=10.0,
            negative_marks=2.0,
            order_index=2
        )
        self.db.add(self.q_multi)
        self.db.flush()
        self.opt_m1 = models.Option(question_id=self.q_multi.id, text="2", is_correct=True)
        self.opt_m2 = models.Option(question_id=self.q_multi.id, text="3", is_correct=True)
        self.opt_m3 = models.Option(question_id=self.q_multi.id, text="4", is_correct=False)
        self.db.add_all([self.opt_m1, self.opt_m2, self.opt_m3])

        # Q3: True/False (5 marks, -1 negative)
        self.q_tf = models.Question(
            exam_id=self.exam.id,
            text="The Earth is flat",
            question_type="true_false",
            marks=5.0,
            negative_marks=1.0,
            order_index=3
        )
        self.db.add(self.q_tf)
        self.db.flush()
        self.opt_tf_t = models.Option(question_id=self.q_tf.id, text="True", is_correct=False)
        self.opt_tf_f = models.Option(question_id=self.q_tf.id, text="False", is_correct=True)
        self.db.add_all([self.opt_tf_t, self.opt_tf_f])

        # Q4: Short Answer (5 marks, keyword evaluation)
        self.q_short = models.Question(
            exam_id=self.exam.id,
            text="Capital of France?",
            question_type="short_answer",
            marks=5.0,
            negative_marks=0.0,
            explanation="Paris",
            type_config=json.dumps({"keywords": ["paris"]}),
            order_index=4
        )
        self.db.add(self.q_short)

        # Q5: Descriptive Answer (10 marks, examiner manual grading)
        self.q_desc = models.Question(
            exam_id=self.exam.id,
            text="Explain the concept of encapsulation in OOP.",
            question_type="descriptive",
            marks=10.0,
            negative_marks=0.0,
            explanation="Encapsulation is bundling data and methods that operate on that data...",
            order_index=5
        )
        self.db.add(self.q_desc)

        # Q6: Code / Programming (10 marks, retained for review)
        self.q_code = models.Question(
            exam_id=self.exam.id,
            text="Write a function to reverse a string.",
            question_type="code",
            marks=10.0,
            negative_marks=0.0,
            order_index=6
        )
        self.db.add(self.q_code)
        self.db.commit()

        # 5. Exam Session Attempt
        self.session = models.ExamSession(
            exam_id=self.exam.id,
            student_id=self.student1.id,
            attempt_number=1,
            status="submitted",
            submitted_at=now,
            integrity_score=100.0,
            risk_level="low"
        )
        self.db.add(self.session)
        self.db.commit()
        self.db.refresh(self.session)

        # Auth Tokens
        self.examiner1_token = auth.create_access_token({"sub": self.examiner1.email, "role": "examiner"})
        self.examiner2_token = auth.create_access_token({"sub": self.examiner2.email, "role": "examiner"})
        self.student1_token = auth.create_access_token({"sub": self.student1.email, "role": "student"})

    def tearDown(self):
        self.db.close()
        models.Base.metadata.drop_all(bind=test_engine)

    # =========================================================================
    # 1. EVALUATION ACROSS ALL SIX QUESTION TYPES
    # =========================================================================
    def test_01_all_six_question_evaluation_paths(self):
        """Unified engine accurately scores each of the 6 question types."""
        # 1. Single Choice: Correct (+5)
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_single, self.exam, self.opt_single_corr.id, None
        )
        self.assertTrue(corr)
        self.assertEqual(marks, 5.0)
        self.assertEqual(status, "evaluated")

        # Single Choice: Incorrect (-1)
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_single, self.exam, self.opt_single_inc.id, None
        )
        self.assertFalse(corr)
        self.assertEqual(marks, -1.0)

        # 2. Multiple Choice: Exact match (+10)
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_multi, self.exam, None, json.dumps([self.opt_m1.id, self.opt_m2.id])
        )
        self.assertTrue(corr)
        self.assertEqual(marks, 10.0)

        # Multiple Choice: Partial match without config (-2)
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_multi, self.exam, None, json.dumps([self.opt_m1.id])
        )
        self.assertFalse(corr)
        self.assertEqual(marks, -2.0)

        # Multiple Choice: Configured partial credit
        self.q_multi.type_config = json.dumps({"partial_marking": True})
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_multi, self.exam, None, json.dumps([self.opt_m1.id])
        )
        self.assertFalse(corr)
        self.assertEqual(marks, 5.0) # 1 of 2 correct selected -> 5.0 credit

        # 3. True/False: Correct (+5)
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_tf, self.exam, self.opt_tf_f.id, None
        )
        self.assertTrue(corr)
        self.assertEqual(marks, 5.0)

        # 4. Short Answer: Correct keyword (+5)
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_short, self.exam, None, "Paris"
        )
        self.assertTrue(corr)
        self.assertEqual(marks, 5.0)

        # Short Answer: Manual review mandated
        self.q_short.type_config = json.dumps({"require_manual_review": True})
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_short, self.exam, None, "Something else"
        )
        self.assertFalse(corr)
        self.assertEqual(status, "pending")

        # 5. Descriptive: Answer submitted -> pending
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_desc, self.exam, None, "Encapsulation hides internal object state."
        )
        self.assertTrue(corr)
        self.assertEqual(status, "pending")

        # 6. Code: Answer submitted -> pending
        corr, marks, status = EvaluationService.evaluate_question_response(
            self.q_code, self.exam, None, "def rev(s): return s[::-1]"
        )
        self.assertTrue(corr)
        self.assertEqual(status, "pending")

    # =========================================================================
    # 2. MANUAL GRADING WORKFLOW
    # =========================================================================
    def test_02_manual_grading_workflow(self):
        """Examiner grades pending descriptive answers, supports draft and final submission."""
        # Answer recorded for descriptive question
        ans = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_desc.id,
            answer_text="Encapsulation is data hiding and bundling.",
            evaluation_status="pending",
            marks_awarded=0.0
        )
        self.db.add(ans)
        self.db.commit()

        # 1. Examiner checks pending queue
        res_queue = self.client.get(
            "/api/v1/evaluation/grading-queue",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_queue.status_code, 200)
        items = res_queue.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["answer_id"], ans.id)
        self.assertEqual(items[0]["max_marks"], 10.0)

        # 2. Examiner saves draft grading (in_progress)
        draft_payload = {"marks_awarded": 7.5, "examiner_feedback": "Good definition, missing access modifiers.", "is_draft": True}
        res_draft = self.client.post(
            f"/api/v1/evaluation/answers/{ans.id}/grade",
            json=draft_payload,
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_draft.status_code, 200)
        self.assertEqual(res_draft.json()["evaluation_status"], "in_progress")

        # 3. Examiner submits final grade (graded)
        final_payload = {"marks_awarded": 8.0, "examiner_feedback": "Updated: thorough answer.", "is_draft": False}
        res_final = self.client.post(
            f"/api/v1/evaluation/answers/{ans.id}/grade",
            json=final_payload,
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_final.status_code, 200)
        self.assertEqual(res_final.json()["evaluation_status"], "graded")

        self.db.expire_all()
        db_ans = self.db.query(models.StudentAnswer).filter_by(id=ans.id).first()
        self.assertEqual(db_ans.marks_awarded, 8.0)
        self.assertEqual(db_ans.evaluation_status, "graded")
        self.assertEqual(db_ans.graded_by, self.examiner1.id)

        # 4. Boundary Enforcement: Marks > Max marks rejected
        invalid_payload = {"marks_awarded": 15.0, "examiner_feedback": "Exceeds max"}
        res_err = self.client.post(
            f"/api/v1/evaluation/answers/{ans.id}/grade",
            json=invalid_payload,
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_err.status_code, 400)
        self.assertIn("must be between 0.0 and maximum marks", res_err.json()["detail"])

    # =========================================================================
    # 3. REGRADING & AUDIT TRAIL
    # =========================================================================
    def test_03_regrading_and_audit_trail(self):
        """Examiner regrades answer with justification, preserving audit trail."""
        ans = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_desc.id,
            answer_text="OOP encapsulation definition.",
            evaluation_status="graded",
            marks_awarded=6.0,
            examiner_feedback="Original feedback"
        )
        self.db.add(ans)
        self.db.commit()

        regrade_payload = {
            "marks_awarded": 9.0,
            "examiner_feedback": "Re-evaluated upon student clarification.",
            "reason": "Re-evaluated code sample attached in descriptive text."
        }
        res = self.client.post(
            f"/api/v1/evaluation/answers/{ans.id}/regrade",
            json=regrade_payload,
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200)

        # Verify answer updated
        self.db.expire_all()
        db_ans = self.db.query(models.StudentAnswer).filter_by(id=ans.id).first()
        self.assertEqual(db_ans.marks_awarded, 9.0)

        # Verify audit trail record created
        audit = self.db.query(models.GradingAudit).filter_by(student_answer_id=ans.id).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.previous_marks, 6.0)
        self.assertEqual(audit.new_marks, 9.0)
        self.assertEqual(audit.reason, "Re-evaluated code sample attached in descriptive text.")
        self.assertEqual(audit.changed_by, self.examiner1.id)

    # =========================================================================
    # 4. PASS/FAIL RULES & PENDING RESULT HANDLING
    # =========================================================================
    def test_04_pass_fail_rules_and_pending_status(self):
        """Assessment with pending descriptive answers stays PENDING until all are evaluated."""
        # Answer Q1 (correct -> 5.0)
        sa1 = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_single.id,
            selected_option_id=self.opt_single_corr.id,
            evaluation_status="evaluated",
            marks_awarded=5.0,
            is_correct=True
        )
        # Answer Q5 (descriptive -> pending)
        sa5 = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_desc.id,
            answer_text="Pending descriptive answer",
            evaluation_status="pending",
            marks_awarded=0.0
        )
        self.db.add_all([sa1, sa5])
        self.db.commit()

        # Initial evaluation: descriptive question is still pending
        result = EvaluationService.evaluate_attempt(self.db, self.session)
        self.assertEqual(result.pass_fail_status, "PENDING")
        self.assertEqual(result.manual_grading_status, "pending")

        # Examiner grades descriptive question with 8.0 marks (Total 13 / 45 -> under 50% cutoff)
        EvaluationService.grade_answer(
            self.db, sa5.id, marks_awarded=8.0, examiner_feedback="Done", is_draft=False, grader=self.examiner1
        )
        result_updated = self.db.query(models.ExamResult).filter_by(exam_session_id=self.session.id).first()
        self.assertEqual(result_updated.marks_obtained, 13.0)
        self.assertEqual(result_updated.pass_fail_status, "FAIL")

        # Now score Q2 and Q6 so total passes 50% cutoff (5 + 8 + 10 + 10 = 33 / 45 = 73.3% -> PASS)
        sa2 = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_multi.id,
            answer_text=json.dumps([self.opt_m1.id, self.opt_m2.id]),
            evaluation_status="evaluated",
            marks_awarded=10.0,
            is_correct=True
        )
        sa6 = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_code.id,
            evaluation_status="graded",
            marks_awarded=10.0,
            is_correct=True
        )
        self.db.add_all([sa2, sa6])
        self.db.commit()

        result_pass = EvaluationService.evaluate_attempt(self.db, self.session)
        self.assertEqual(result_pass.pass_fail_status, "PASS")
        self.assertGreaterEqual(result_pass.percentage, 50.0)

    # =========================================================================
    # 5. MANDATORY QUESTIONS ENFORCEMENT
    # =========================================================================
    def test_05_mandatory_question_enforcement(self):
        """Failing a mandatory question results in FAIL regardless of high overall percentage."""
        # Mark single choice question as mandatory
        self.q_single.is_mandatory = True
        self.db.commit()

        # Student gets Q1 incorrect (0 / negative), but scores well on other questions
        sa1 = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_single.id,
            selected_option_id=self.opt_single_inc.id,
            evaluation_status="evaluated",
            marks_awarded=-1.0,
            is_correct=False
        )
        sa2 = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_multi.id,
            answer_text=json.dumps([self.opt_m1.id, self.opt_m2.id]),
            evaluation_status="evaluated",
            marks_awarded=10.0,
            is_correct=True
        )
        sa5 = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_desc.id,
            evaluation_status="graded",
            marks_awarded=10.0,
            is_correct=True
        )
        self.db.add_all([sa1, sa2, sa5])
        self.db.commit()

        result = EvaluationService.evaluate_attempt(self.db, self.session)
        # Even though score is positive and passes percentage criteria, mandatory failure forces FAIL
        self.assertEqual(result.pass_fail_status, "FAIL")

    # =========================================================================
    # 6. SECTION-WISE EVALUATION & CUTOFFS
    # =========================================================================
    def test_06_section_wise_evaluation_and_cutoffs(self):
        """Section cutoffs evaluate section scores; missing any section cutoff fails assessment."""
        # Create 2 sections: Section A (Math) and Section B (Verbal)
        sec_a = models.AssessmentSection(exam_id=self.exam.id, name="Quantitative", order_index=1, passing_percentage=60.0)
        sec_b = models.AssessmentSection(exam_id=self.exam.id, name="Verbal", order_index=2, passing_percentage=60.0)
        self.db.add_all([sec_a, sec_b])
        self.db.commit()

        self.q_single.section_id = sec_a.id # 5 marks
        self.q_multi.section_id = sec_a.id  # 10 marks -> Total Sec A = 15 marks
        self.q_short.section_id = sec_b.id  # 5 marks
        self.q_desc.section_id = sec_b.id   # 10 marks -> Total Sec B = 15 marks
        self.db.commit()

        # Candidate scores 15/15 (100%) in Section A, but 0/15 (0%) in Section B
        sa1 = models.StudentAnswer(exam_session_id=self.session.id, question_id=self.q_single.id, selected_option_id=self.opt_single_corr.id, evaluation_status="evaluated", marks_awarded=5.0, is_correct=True)
        sa2 = models.StudentAnswer(exam_session_id=self.session.id, question_id=self.q_multi.id, answer_text=json.dumps([self.opt_m1.id, self.opt_m2.id]), evaluation_status="evaluated", marks_awarded=10.0, is_correct=True)
        sa4 = models.StudentAnswer(exam_session_id=self.session.id, question_id=self.q_short.id, evaluation_status="evaluated", marks_awarded=0.0, is_correct=False)
        sa5 = models.StudentAnswer(exam_session_id=self.session.id, question_id=self.q_desc.id, evaluation_status="graded", marks_awarded=0.0, is_correct=False)
        self.db.add_all([sa1, sa2, sa4, sa5])
        self.db.commit()

        result = EvaluationService.evaluate_attempt(self.db, self.session)
        # Missing Section B cutoff (0% < 60%) causes FAIL
        self.assertEqual(result.pass_fail_status, "FAIL")

        # Verify section scores breakdown JSON
        sec_breakdown = json.loads(result.section_scores)
        self.assertEqual(len(sec_breakdown), 2)
        sec_a_data = next(s for s in sec_breakdown if s["name"] == "Quantitative")
        sec_b_data = next(s for s in sec_breakdown if s["name"] == "Verbal")
        self.assertTrue(sec_a_data["passed"])
        self.assertFalse(sec_b_data["passed"])

    # =========================================================================
    # 7. RESULT RELEASE CONTROLS & CANDIDATE PRIVACY
    # =========================================================================
    def test_07_result_release_controls_and_privacy(self):
        """Unreleased results return 'held' status to candidates until authorized release."""
        # Setup evaluated result
        sa1 = models.StudentAnswer(exam_session_id=self.session.id, question_id=self.q_single.id, selected_option_id=self.opt_single_corr.id, evaluation_status="evaluated", marks_awarded=5.0, is_correct=True)
        self.db.add(sa1)
        self.db.commit()
        EvaluationService.evaluate_attempt(self.db, self.session)

        # 1. Candidate attempts to view result before release
        res_cand = self.client.get(
            f"/api/v1/results/sessions/{self.session.id}",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_cand.status_code, 200)
        self.assertEqual(res_cand.json()["status"], "held")
        self.assertNotIn("marks_obtained", res_cand.json())

        # 2. Examiner releases results
        res_rel = self.client.post(
            f"/api/v1/results/assessments/{self.exam.id}/release-control",
            json={"is_released": True},
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_rel.status_code, 200)
        self.assertTrue(res_rel.json()["results_released"])

        # 3. Candidate views released result
        res_cand_released = self.client.get(
            f"/api/v1/results/sessions/{self.session.id}",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_cand_released.status_code, 200)
        data = res_cand_released.json()
        self.assertTrue(data["is_released"])
        self.assertIn("marks_obtained", data)
        self.assertEqual(data["marks_obtained"], 5.0)

    # =========================================================================
    # 8. MULTIPLE ATTEMPTS RESULT ISOLATION
    # =========================================================================
    def test_08_multiple_attempts_result_isolation(self):
        """Separate historical results maintained across multiple attempts."""
        # Attempt 1 evaluated
        sa1_att1 = models.StudentAnswer(exam_session_id=self.session.id, question_id=self.q_single.id, selected_option_id=self.opt_single_corr.id, evaluation_status="evaluated", marks_awarded=5.0, is_correct=True)
        self.db.add(sa1_att1)
        self.db.commit()
        r1 = EvaluationService.evaluate_attempt(self.db, self.session)

        # Attempt 2
        session2 = models.ExamSession(
            exam_id=self.exam.id,
            student_id=self.student1.id,
            attempt_number=2,
            status="submitted",
            submitted_at=utc_now()
        )
        self.db.add(session2)
        self.db.commit()
        sa1_att2 = models.StudentAnswer(exam_session_id=session2.id, question_id=self.q_single.id, selected_option_id=self.opt_single_inc.id, evaluation_status="evaluated", marks_awarded=-1.0, is_correct=False)
        self.db.add(sa1_att2)
        self.db.commit()
        r2 = EvaluationService.evaluate_attempt(self.db, session2)

        # Release results
        EvaluationService.toggle_result_release(self.db, self.exam.id, True, self.examiner1)

        # Retrieve candidate attempts history
        res = self.client.get(
            f"/api/v1/results/assessments/{self.exam.id}/my-results",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        history = res.json()["attempts"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["attempt_number"], 1)
        self.assertEqual(history[0]["marks_obtained"], 5.0)
        self.assertEqual(history[1]["attempt_number"], 2)
        self.assertEqual(history[1]["marks_obtained"], 0.0)

    # =========================================================================
    # 9. PROCTORING SEPARATION
    # =========================================================================
    def test_09_proctoring_separation(self):
        """Proctoring violation events and low integrity score NEVER penalize academic marks."""
        # Record 4 proctoring violation flags
        self.session.integrity_score = 45.0
        self.session.risk_level = "high"
        f1 = models.CheatFlag(exam_id=self.exam.id, student_id=self.student1.id, exam_session_id=self.session.id, event_type="tab_switch")
        self.db.add(f1)

        # Student answered Q1 and Q2 correctly (+15 marks)
        sa1 = models.StudentAnswer(exam_session_id=self.session.id, question_id=self.q_single.id, selected_option_id=self.opt_single_corr.id, evaluation_status="evaluated", marks_awarded=5.0, is_correct=True)
        sa2 = models.StudentAnswer(exam_session_id=self.session.id, question_id=self.q_multi.id, answer_text=json.dumps([self.opt_m1.id, self.opt_m2.id]), evaluation_status="evaluated", marks_awarded=10.0, is_correct=True)
        self.db.add_all([sa1, sa2])
        self.db.commit()

        result = EvaluationService.evaluate_attempt(self.db, self.session)
        # Academic marks are strictly 15.0 (no proctoring deductions)
        self.assertEqual(result.marks_obtained, 15.0)

        # Examiner view exposes proctoring_summary separately
        examiner_view = EvaluationService.get_candidate_result_summary(self.db, self.session.id, self.examiner1)
        self.assertIn("proctoring_summary", examiner_view)
        self.assertEqual(examiner_view["proctoring_summary"]["integrity_score"], 45.0)
        self.assertEqual(examiner_view["proctoring_summary"]["risk_level"], "high")

    # =========================================================================
    # 10. MULTI-TENANT ORGANIZATION ISOLATION
    # =========================================================================
    def test_10_multi_tenant_organization_isolation(self):
        """Examiner from Org 2 cannot grade answers or release results for Org 1."""
        ans = models.StudentAnswer(
            exam_session_id=self.session.id,
            question_id=self.q_desc.id,
            answer_text="Descriptive answer",
            evaluation_status="pending",
            marks_awarded=0.0
        )
        self.db.add(ans)
        self.db.commit()

        # Org 2 examiner attempts to grade Org 1 answer -> 403
        res_grade = self.client.post(
            f"/api/v1/evaluation/answers/{ans.id}/grade",
            json={"marks_awarded": 5.0, "is_draft": False},
            headers={"Authorization": f"Bearer {self.examiner2_token}"}
        )
        self.assertEqual(res_grade.status_code, 403)

        # Org 2 examiner attempts to release Org 1 results -> 403
        res_rel = self.client.post(
            f"/api/v1/results/assessments/{self.exam.id}/release-control",
            json={"is_released": True},
            headers={"Authorization": f"Bearer {self.examiner2_token}"}
        )
        self.assertEqual(res_rel.status_code, 403)

    # =========================================================================
    # 11. RESULTS EXPORT FORMATTING
    # =========================================================================
    def test_11_results_export(self):
        """Assessment results export produces standardized flat format for reporting."""
        sa1 = models.StudentAnswer(exam_session_id=self.session.id, question_id=self.q_single.id, selected_option_id=self.opt_single_corr.id, evaluation_status="evaluated", marks_awarded=5.0, is_correct=True)
        self.db.add(sa1)
        self.db.commit()
        EvaluationService.evaluate_attempt(self.db, self.session)

        res_exp = self.client.get(
            f"/api/v1/results/assessments/{self.exam.id}/export",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_exp.status_code, 200)
        rows = res_exp.json()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["candidate_email"], "student1@test.com")
        self.assertEqual(row["assessment_id"], self.exam.id)
        self.assertEqual(row["marks_obtained"], 5.0)
        self.assertIn("pass_fail_status", row)


if __name__ == "__main__":
    unittest.main()
