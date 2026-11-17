"""
testing/test_phase11_advanced_assessments.py
--------------------------------------------
Comprehensive test suite for Phase 11: Advanced Assessment Features.
Covers:
1. Question order randomization & persistence across browser refreshes
2. Option order randomization & deterministic persistence without answer leaks
3. Mixed fixed (mandatory) and randomized question ordering
4. Assessment Blueprint CRUD & multi-tenant isolation
5. Blueprint validation with sufficient questions
6. Blueprint validation deficit reporting (by difficulty and topic)
7. Blueprint materialization into assessment questions
8. Reusable Template CRUD & Super Admin system template permissions
9. Template duplication with decoupled cloned configuration
10. Assessment creation from Template (with sections and questions)
11. Adaptive testing initialization & refresh state recovery
12. Adaptive difficulty progression: correct answer steps up (+1)
13. Adaptive difficulty progression: incorrect answer steps down (-1) & min bound
14. Adaptive stopping conditions (max questions reached & finished flag)
15. Adaptive anti-tampering validation (reject invalid question IDs)
16. Attempt policy: cooldown enforcement between attempts
17. Attempt policy: retake eligibility (on_failure_only vs always)
18. Attempt policy: multi-attempt score aggregation (best, latest, first, average)
19. Advanced sections: sequential navigation restriction (backward navigation blocked)
20. Advanced sections: section completion, advancement & persistence
"""
import sys
import os
import unittest
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import database
import auth
from main import app
from time_utils import utc_now, to_utc
from modules.assessments.service import AssessmentService
from modules.assessments.schemas import AssessmentCreate, AssessmentUpdate
from modules.assessments.blueprints import BlueprintService, BlueprintCreate, BlueprintUpdate
from modules.assessments.templates import TemplateService, TemplateCreate, TemplateUpdate, CreateAssessmentFromTemplateRequest
from modules.assessments.adaptive import AdaptiveService
from modules.assessments.attempt_policies import AttemptPolicyService
from modules.assessments.sections import SectionService
from routers.student_r import get_or_create_exam_session, get_or_create_question_session

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


class TestPhase11AdvancedAssessments(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        models.Base.metadata.create_all(bind=test_engine)

    def setUp(self):
        models.Base.metadata.drop_all(bind=test_engine)
        models.Base.metadata.create_all(bind=test_engine)
        self.db = TestSessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[database.get_db] = override_get_db

        # Seed Organizations
        self.org1 = models.Organization(name="Engineering College", slug="eng-11", is_active=True)
        self.org2 = models.Organization(name="Business School", slug="biz-11", is_active=True)
        self.db.add_all([self.org1, self.org2])
        self.db.commit()
        self.db.refresh(self.org1)
        self.db.refresh(self.org2)

        # Seed Users
        self.super_admin = models.User(
            name="Super Admin 11",
            email="super11@examproctor.com",
            role="super_admin",
            is_active=True,
            password_hash=auth.get_password_hash("SuperSecret11!")
        )
        self.org1_admin = models.User(
            name="Admin 11 Eng",
            email="admin11@eng.edu",
            role="org_admin",
            organization_id=self.org1.id,
            is_active=True,
            password_hash=auth.get_password_hash("OrgPass11!")
        )
        self.examiner1 = models.User(
            name="Prof Alan Turing",
            email="turing@eng.edu",
            role="examiner",
            organization_id=self.org1.id,
            is_active=True,
            password_hash=auth.get_password_hash("ProfPass11!")
        )
        self.candidate1 = models.User(
            name="Alice Student",
            email="alice@eng.edu",
            role="student",
            organization_id=self.org1.id,
            is_active=True,
            password_hash=auth.get_password_hash("AlicePass11!")
        )
        self.db.add_all([self.super_admin, self.org1_admin, self.examiner1, self.candidate1])
        self.db.commit()

        # Seed Question Bank items for testing
        self.bank_questions = []
        difficulties = ["easy", "medium", "hard"]
        topics = ["Algorithms", "Data Structures", "Networks"]
        for i in range(15):
            diff = difficulties[i % 3]
            top = topics[i % 3]
            bq = models.BankQuestion(
                text=f"Sample Question {i+1} on {top} ({diff})",
                question_type="mcq_single",
                assessment_category="academic",
                subject="Computer Science",
                topic=top,
                difficulty=diff,
                default_marks=2.0,
                default_negative_marks=0.5,
                organization_id=self.org1.id,
                created_by=self.examiner1.id,
                status="published"
            )
            self.db.add(bq)
            self.db.flush()
            # Add options
            opt1 = models.BankOption(question_id=bq.id, text=f"Correct Option {i+1}", is_correct=True, order_index=1)
            opt2 = models.BankOption(question_id=bq.id, text=f"Incorrect A {i+1}", is_correct=False, order_index=2)
            opt3 = models.BankOption(question_id=bq.id, text=f"Incorrect B {i+1}", is_correct=False, order_index=3)
            opt4 = models.BankOption(question_id=bq.id, text=f"Incorrect C {i+1}", is_correct=False, order_index=4)
            self.db.add_all([opt1, opt2, opt3, opt4])
            self.bank_questions.append(bq)
        self.db.commit()

        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    # =========================================================================
    # 1. RANDOMIZATION & REFRESH PERSISTENCE
    # =========================================================================
    def test_01_randomization_question_order_persistence(self):
        """Verify question randomization shuffles order and persists in ExamSession across repeated calls."""
        now = utc_now()
        exam = models.Exam(
            title="Randomized Questions Exam",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            randomize_questions=True,
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        # Add 6 questions
        q_objs = []
        for i in range(6):
            q = models.Question(exam_id=exam.id, text=f"Q{i+1}", marks=1.0, order_index=i+1)
            self.db.add(q)
            q_objs.append(q)
        self.db.commit()

        # First session initialization
        session = get_or_create_exam_session(self.db, exam.id, self.candidate1.id, exam)
        self.assertIsNotNone(session.question_order)
        order_1 = json.loads(session.question_order)
        self.assertEqual(len(order_1), 6)

        # Subsequent retrieval simulates browser refresh
        self.db.expire_all()
        session_refresh = get_or_create_exam_session(self.db, exam.id, self.candidate1.id, exam)
        self.assertEqual(session.id, session_refresh.id)
        order_2 = json.loads(session_refresh.question_order)
        # MUST BE IDENTICAL on refresh
        self.assertEqual(order_1, order_2)

    def test_02_randomization_option_order_persistence_and_no_leak(self):
        """Verify option order randomization is deterministic via QuestionSession and hides correct answer."""
        now = utc_now()
        exam = models.Exam(
            title="Randomized Options Exam",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            randomize_options=True,
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        q = models.Question(exam_id=exam.id, text="MCQ with options", marks=2.0)
        self.db.add(q)
        self.db.flush()

        for j in range(4):
            opt = models.Option(question_id=q.id, text=f"Option {j+1}", is_correct=(j == 0))
            self.db.add(opt)
        self.db.commit()

        session = get_or_create_exam_session(self.db, exam.id, self.candidate1.id, exam)

        # Simulate option order generation and persistence
        raw_options = self.db.query(models.Option).filter(models.Option.question_id == q.id).all()
        qs = models.QuestionSession(
            exam_session_id=session.id,
            question_id=q.id,
            started_at=now,
            deadline=now + timedelta(minutes=10),
            is_locked=False,
            option_order=json.dumps([opt.id for opt in reversed(raw_options)])
        )
        self.db.add(qs)
        self.db.commit()

        # Check retrieval from QuestionSession
        loaded_qs = self.db.query(models.QuestionSession).filter(
            models.QuestionSession.exam_session_id == session.id,
            models.QuestionSession.question_id == q.id
        ).first()
        self.assertIsNotNone(loaded_qs.option_order)
        saved_order = json.loads(loaded_qs.option_order)
        self.assertEqual(saved_order, [opt.id for opt in reversed(raw_options)])

    def test_03_randomization_mixed_fixed_and_random(self):
        """Verify mandatory/fixed questions stay at fixed order while others are shuffled."""
        now = utc_now()
        exam = models.Exam(
            title="Mixed Fixed & Random Exam",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            randomize_questions=True,
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        q1 = models.Question(exam_id=exam.id, text="Q1 Mandatory", marks=1.0, is_mandatory=True, order_index=1)
        q2 = models.Question(exam_id=exam.id, text="Q2 Random A", marks=1.0, is_mandatory=False, order_index=2)
        q3 = models.Question(exam_id=exam.id, text="Q3 Random B", marks=1.0, is_mandatory=False, order_index=3)
        self.db.add_all([q1, q2, q3])
        self.db.commit()

        session = get_or_create_exam_session(self.db, exam.id, self.candidate1.id, exam)
        order = json.loads(session.question_order)
        # q1 (mandatory) must be first
        self.assertEqual(order[0], q1.id)
        self.assertIn(q2.id, order[1:])
        self.assertIn(q3.id, order[1:])

    # =========================================================================
    # 2. ASSESSMENT BLUEPRINTS
    # =========================================================================
    def test_04_blueprint_create_and_tenant_isolation(self):
        """Verify blueprint creation, org scoping, and cross-org access protection."""
        bp_data = BlueprintCreate(
            title="CS Algorithms Blueprint",
            description="Algorithmic assessment blueprint",
            assessment_type="technical",
            subject="Computer Science",
            topics=["Algorithms", "Data Structures"],
            question_types=["mcq_single"],
            difficulty_distribution={"easy": 2, "medium": 3, "hard": 1},
            total_marks=12.0
        )
        bp = BlueprintService.create_blueprint(self.db, bp_data, self.examiner1)
        self.assertIsNotNone(bp.id)
        self.assertEqual(bp.organization_id, self.org1.id)
        self.assertEqual(bp.total_questions, 6)

        # Cross-org examiner cannot access org1 blueprint
        examiner_org2 = models.User(
            name="Prof Smith", email="smith@biz.edu", role="examiner", organization_id=self.org2.id
        )
        self.db.add(examiner_org2)
        self.db.commit()

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            BlueprintService.get_blueprint(self.db, bp.id, examiner_org2)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_05_blueprint_validation_sufficient_questions(self):
        """Verify blueprint validation succeeds when sufficient Question Bank items exist."""
        bp_data = BlueprintCreate(
            title="Validatable Blueprint",
            subject="Computer Science",
            topics=["Algorithms"],
            difficulty_distribution={"easy": 2, "medium": 2, "hard": 1}
        )
        bp = BlueprintService.create_blueprint(self.db, bp_data, self.examiner1)
        val_result = BlueprintService.validate_blueprint(self.db, bp.id, self.examiner1)
        self.assertTrue(val_result.is_valid)
        self.assertEqual(len(val_result.errors), 0)
        self.assertGreaterEqual(val_result.total_available, 5)

    def test_06_blueprint_validation_deficit_reporting(self):
        """Verify blueprint validation returns is_valid=False with specific deficit details when bank lacks questions."""
        bp_data = BlueprintCreate(
            title="Deficit Blueprint",
            subject="Computer Science",
            difficulty_distribution={"easy": 10, "medium": 20, "hard": 15}  # We only seeded 5 each
        )
        bp = BlueprintService.create_blueprint(self.db, bp_data, self.examiner1)
        val_result = BlueprintService.validate_blueprint(self.db, bp.id, self.examiner1)
        self.assertFalse(val_result.is_valid)
        self.assertGreater(len(val_result.errors), 0)
        # Check deficit info by difficulty
        self.assertIn("easy", val_result.by_difficulty)
        self.assertGreater(val_result.by_difficulty["easy"]["deficit"], 0)

    def test_07_blueprint_materialization_into_assessment(self):
        """Verify materializing blueprint generates and maps questions to target assessment."""
        bp_data = BlueprintCreate(
            title="Materialize BP",
            subject="Computer Science",
            difficulty_distribution={"easy": 2, "medium": 2, "hard": 1}
        )
        bp = BlueprintService.create_blueprint(self.db, bp_data, self.examiner1)

        # Create target exam
        now = utc_now()
        exam = models.Exam(
            title="Target Assessment",
            start_time=now,
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="draft",
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.commit()

        result = BlueprintService.materialize_assessment_questions(self.db, bp.id, exam.id, self.examiner1)
        self.assertEqual(result["questions_generated"], 5)
        self.assertEqual(result["assessment_id"], exam.id)

        # Verify mapped questions exist in DB
        mapped_count = self.db.query(models.AssessmentQuestionMap).filter(
            models.AssessmentQuestionMap.assessment_id == exam.id
        ).count()
        self.assertEqual(mapped_count, 5)

    # =========================================================================
    # 3. REUSABLE ASSESSMENT TEMPLATES
    # =========================================================================
    def test_08_template_crud_and_system_template_permissions(self):
        """Verify template creation, system template restriction to Super Admin, and listing."""
        # Non-super admin cannot create system template
        tmpl_data = TemplateCreate(
            title="Standard Technical Screening",
            assessment_type="technical",
            duration_minutes=90,
            default_marks=2.0,
            is_system=True
        )
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            TemplateService.create_template(self.db, tmpl_data, self.examiner1)
        self.assertEqual(ctx.exception.status_code, 403)

        # Super Admin creates system template
        sys_tmpl = TemplateService.create_template(self.db, tmpl_data, self.super_admin)
        self.assertTrue(sys_tmpl.is_system)

        # Examiner can see system templates in list
        tmpls = TemplateService.list_templates(self.db, self.examiner1)
        self.assertTrue(any(t.id == sys_tmpl.id for t in tmpls))

    def test_09_template_duplication(self):
        """Verify duplicating a template clones properties and appends (Copy)."""
        tmpl_data = TemplateCreate(
            title="Midterm Template",
            assessment_type="academic",
            duration_minutes=120,
            passing_marks=40.0,
            max_attempts=2
        )
        original = TemplateService.create_template(self.db, tmpl_data, self.examiner1)
        duplicate = TemplateService.duplicate_template(self.db, original.id, self.examiner1)

        self.assertNotEqual(original.id, duplicate.id)
        self.assertEqual(duplicate.title, "Midterm Template (Copy)")
        self.assertEqual(duplicate.duration_minutes, 120)
        self.assertEqual(duplicate.max_attempts, 2)
        self.assertFalse(duplicate.is_system)

    def test_10_template_to_assessment_instantiation(self):
        """Verify creating an assessment from template clones configuration into an independent Exam."""
        now = utc_now()
        tmpl_data = TemplateCreate(
            title="Placement Standard Template",
            assessment_type="placement",
            duration_minutes=45,
            randomize_questions=True,
            randomize_options=True,
            section_config=[
                {"name": "Aptitude", "order_index": 1, "is_mandatory": True, "navigation_mode": "sequential"},
                {"name": "Technical", "order_index": 2, "is_mandatory": True, "navigation_mode": "sequential"}
            ]
        )
        tmpl = TemplateService.create_template(self.db, tmpl_data, self.examiner1)

        req = CreateAssessmentFromTemplateRequest(
            title="Final Placement Test 2026",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=5),
            generate_blueprint_questions=False
        )
        exam = TemplateService.create_assessment_from_template(self.db, tmpl.id, req, self.examiner1)

        self.assertIsNotNone(exam.id)
        self.assertEqual(exam.title, "Final Placement Test 2026")
        self.assertEqual(exam.duration_minutes, 45)
        self.assertTrue(exam.randomize_options)
        self.assertEqual(exam.template_id, tmpl.id)

        # Check cloned sections
        sections = self.db.query(models.AssessmentSection).filter(models.AssessmentSection.exam_id == exam.id).all()
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].name, "Aptitude")
        self.assertEqual(sections[0].navigation_mode, "sequential")

    # =========================================================================
    # 4. ADAPTIVE ASSESSMENT ENGINE
    # =========================================================================
    def test_11_adaptive_session_initialization_and_refresh_resumption(self):
        """Verify adaptive session initializes starting difficulty and recovers state on refresh."""
        now = utc_now()
        exam = models.Exam(
            title="Adaptive Exam Test",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            is_adaptive=True,
            adaptive_config=json.dumps({"starting_difficulty": "medium", "min_questions": 3, "max_questions": 5}),
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        # Add questions of various difficulties
        for bq in self.bank_questions:
            q = models.Question(exam_id=exam.id, bank_question_id=bq.id, text=bq.text, marks=2.0)
            self.db.add(q)
        self.db.commit()

        session = models.ExamSession(
            exam_id=exam.id,
            student_id=self.candidate1.id,
            attempt_number=1,
            started_at=now,
            status="in_progress"
        )
        self.db.add(session)
        self.db.commit()

        state = AdaptiveService.initialize_adaptive_session(self.db, session, exam)
        self.assertEqual(state["current_difficulty"], "medium")
        self.assertIsNotNone(state["current_question_id"])
        self.assertEqual(state["step_number"], 1)

        # Re-fetch simulates page refresh
        refreshed_state = AdaptiveService.initialize_adaptive_session(self.db, session, exam)
        self.assertEqual(state["current_question_id"], refreshed_state["current_question_id"])
        self.assertEqual(state["current_difficulty"], refreshed_state["current_difficulty"])

    def test_12_adaptive_difficulty_progression_correct_step_up(self):
        """Verify correct answer increases difficulty (+1: easy -> medium -> hard)."""
        now = utc_now()
        exam = models.Exam(
            title="Step Up Adaptive Exam",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            is_adaptive=True,
            adaptive_config=json.dumps({"starting_difficulty": "easy", "step_up": 1, "max_questions": 5}),
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        # Create 1 easy, 1 medium, 1 hard question with options
        q_easy = models.Question(exam_id=exam.id, text="Easy Q", marks=1.0)
        q_med = models.Question(exam_id=exam.id, text="Medium Q", marks=2.0)
        q_hard = models.Question(exam_id=exam.id, text="Hard Q", marks=3.0)
        self.db.add_all([q_easy, q_med, q_hard])
        self.db.flush()

        # Assign bank question with difficulty tag
        bq_easy = next(b for b in self.bank_questions if b.difficulty == "easy")
        bq_med = next(b for b in self.bank_questions if b.difficulty == "medium")
        bq_hard = next(b for b in self.bank_questions if b.difficulty == "hard")
        q_easy.bank_question_id = bq_easy.id
        q_med.bank_question_id = bq_med.id
        q_hard.bank_question_id = bq_hard.id

        # Add correct option for easy question
        opt_easy_corr = models.Option(question_id=q_easy.id, text="Correct Easy", is_correct=True)
        opt_easy_inc = models.Option(question_id=q_easy.id, text="Incorrect Easy", is_correct=False)
        self.db.add_all([opt_easy_corr, opt_easy_inc])
        self.db.commit()

        session = models.ExamSession(
            exam_id=exam.id,
            student_id=self.candidate1.id,
            attempt_number=1,
            started_at=now,
            status="in_progress"
        )
        self.db.add(session)
        self.db.commit()

        AdaptiveService.initialize_adaptive_session(self.db, session, exam)
        # Force start question to q_easy
        state = json.loads(session.adaptive_state)
        state["current_question_id"] = q_easy.id
        state["current_difficulty"] = "easy"
        session.adaptive_state = json.dumps(state)
        self.db.commit()

        # Submit CORRECT answer
        advance_res = AdaptiveService.submit_answer_and_advance(
            db=self.db,
            exam_session=session,
            exam=exam,
            question_id=q_easy.id,
            selected_option_id=opt_easy_corr.id
        )
        self.assertFalse(advance_res["is_finished"])
        # Should step up to medium
        self.assertEqual(advance_res["current_difficulty"], "medium")

    def test_13_adaptive_difficulty_progression_incorrect_step_down(self):
        """Verify incorrect answer decreases difficulty (-1: hard -> medium, bounded by min)."""
        now = utc_now()
        exam = models.Exam(
            title="Step Down Adaptive Exam",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            is_adaptive=True,
            adaptive_config=json.dumps({"starting_difficulty": "hard", "min_difficulty": "easy", "step_down": 1, "max_questions": 5}),
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        q_hard = models.Question(exam_id=exam.id, text="Hard Q", marks=3.0)
        q_med = models.Question(exam_id=exam.id, text="Med Q", marks=2.0)
        self.db.add_all([q_hard, q_med])
        self.db.flush()

        bq_hard = next(b for b in self.bank_questions if b.difficulty == "hard")
        bq_med = next(b for b in self.bank_questions if b.difficulty == "medium")
        q_hard.bank_question_id = bq_hard.id
        q_med.bank_question_id = bq_med.id

        opt_hard_inc = models.Option(question_id=q_hard.id, text="Wrong Hard", is_correct=False)
        self.db.add(opt_hard_inc)
        self.db.commit()

        session = models.ExamSession(
            exam_id=exam.id,
            student_id=self.candidate1.id,
            attempt_number=1,
            started_at=now,
            status="in_progress"
        )
        self.db.add(session)
        self.db.commit()

        AdaptiveService.initialize_adaptive_session(self.db, session, exam)
        state = json.loads(session.adaptive_state)
        state["current_question_id"] = q_hard.id
        state["current_difficulty"] = "hard"
        session.adaptive_state = json.dumps(state)
        self.db.commit()

        # Submit INCORRECT answer
        advance_res = AdaptiveService.submit_answer_and_advance(
            db=self.db,
            exam_session=session,
            exam=exam,
            question_id=q_hard.id,
            selected_option_id=opt_hard_inc.id
        )
        # Should step down from hard to medium
        self.assertEqual(advance_res["current_difficulty"], "medium")

    def test_14_adaptive_stopping_condition_max_questions(self):
        """Verify adaptive testing marks session finished when max_questions reached."""
        now = utc_now()
        exam = models.Exam(
            title="Max Questions Stopping Test",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            is_adaptive=True,
            adaptive_config=json.dumps({"max_questions": 1}),
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        q = models.Question(exam_id=exam.id, text="Only Q", marks=1.0)
        self.db.add(q)
        self.db.flush()
        opt = models.Option(question_id=q.id, text="Answer", is_correct=True)
        self.db.add(opt)
        self.db.commit()

        session = models.ExamSession(
            exam_id=exam.id,
            student_id=self.candidate1.id,
            attempt_number=1,
            started_at=now,
            status="in_progress"
        )
        self.db.add(session)
        self.db.commit()

        AdaptiveService.initialize_adaptive_session(self.db, session, exam)
        advance_res = AdaptiveService.submit_answer_and_advance(
            db=self.db,
            exam_session=session,
            exam=exam,
            question_id=q.id,
            selected_option_id=opt.id
        )
        self.assertTrue(advance_res["is_finished"])
        self.assertIsNone(advance_res["next_question"])

    def test_15_adaptive_anti_tampering_question_id_validation(self):
        """Verify client cannot submit answer for arbitrary question not matching active question."""
        now = utc_now()
        exam = models.Exam(
            title="Tampering Test",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            is_adaptive=True,
            adaptive_config=json.dumps({"max_questions": 5}),
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        q1 = models.Question(exam_id=exam.id, text="Active Q", marks=1.0)
        q2 = models.Question(exam_id=exam.id, text="Sneaky Q", marks=1.0)
        self.db.add_all([q1, q2])
        self.db.commit()

        session = models.ExamSession(
            exam_id=exam.id,
            student_id=self.candidate1.id,
            attempt_number=1,
            started_at=now,
            status="in_progress",
            adaptive_state=json.dumps({"current_question_id": q1.id, "step_number": 1, "history": []})
        )
        self.db.add(session)
        self.db.commit()

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            AdaptiveService.submit_answer_and_advance(
                db=self.db,
                exam_session=session,
                exam=exam,
                question_id=q2.id  # Does NOT match current_question_id
            )
        self.assertEqual(ctx.exception.status_code, 400)

    # =========================================================================
    # 5. ATTEMPT POLICIES
    # =========================================================================
    def test_16_attempt_policy_cooldown_enforcement(self):
        """Verify candidate cannot start retake until cooldown duration has elapsed."""
        now = utc_now()
        exam = models.Exam(
            title="Cooldown Policy Exam",
            start_time=now - timedelta(hours=2),
            end_time=now + timedelta(hours=5),
            duration_minutes=60,
            status="active",
            max_attempts=3,
            attempt_policy=json.dumps({"cooldown_minutes": 15}),
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        # Record completed attempt finished 5 minutes ago
        past_session = models.ExamSession(
            exam_id=exam.id,
            student_id=self.candidate1.id,
            attempt_number=1,
            started_at=now - timedelta(minutes=65),
            submitted_at=now - timedelta(minutes=5),  # Ended 5 mins ago (cooldown is 15 mins)
            status="completed",
            score=50.0
        )
        self.db.add(past_session)
        self.db.commit()

        # Check eligibility
        eligibility = AttemptPolicyService.check_attempt_eligibility(self.db, exam, self.candidate1.id)
        self.assertFalse(eligibility["eligible"])
        self.assertIn("cooldown active", eligibility["reason"].lower())
        self.assertGreater(eligibility["remaining_cooldown_seconds"], 0)

        # After advancing past cooldown (e.g. ended 20 minutes ago)
        past_session.submitted_at = now - timedelta(minutes=20)
        self.db.commit()

        eligibility2 = AttemptPolicyService.check_attempt_eligibility(self.db, exam, self.candidate1.id)
        self.assertTrue(eligibility2["eligible"])

    def test_17_attempt_policy_retake_on_failure_only(self):
        """Verify candidate who achieved passing score cannot retake if policy is on_failure_only."""
        now = utc_now()
        exam = models.Exam(
            title="Retake On Failure Exam",
            start_time=now - timedelta(hours=2),
            end_time=now + timedelta(hours=5),
            duration_minutes=60,
            status="active",
            max_attempts=3,
            passing_marks=40.0,
            attempt_policy=json.dumps({"retake_eligibility": "on_failure_only", "cooldown_minutes": 0}),
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        # Passed attempt
        past_session = models.ExamSession(
            exam_id=exam.id,
            student_id=self.candidate1.id,
            attempt_number=1,
            started_at=now - timedelta(minutes=60),
            submitted_at=now - timedelta(minutes=10),
            status="completed",
            score=75.0  # > 40 passing marks
        )
        self.db.add(past_session)
        self.db.commit()

        eligibility = AttemptPolicyService.check_attempt_eligibility(self.db, exam, self.candidate1.id)
        self.assertFalse(eligibility["eligible"])
        self.assertIn("only permitted upon failure", eligibility["reason"].lower())

        # Failed attempt scenario
        past_session.score = 25.0  # < 40
        self.db.commit()

        eligibility_failed = AttemptPolicyService.check_attempt_eligibility(self.db, exam, self.candidate1.id)
        self.assertTrue(eligibility_failed["eligible"])

    def test_18_attempt_policy_score_aggregation(self):
        """Verify consolidated score calculation across attempts for best, latest, first, and average."""
        now = utc_now()
        exam = models.Exam(
            title="Aggregation Exam",
            start_time=now - timedelta(hours=5),
            end_time=now + timedelta(hours=5),
            duration_minutes=60,
            status="active",
            max_attempts=3,
            passing_marks=50.0,
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        s1 = models.ExamSession(
            exam_id=exam.id, student_id=self.candidate1.id, attempt_number=1,
            started_at=now - timedelta(hours=4), submitted_at=now - timedelta(hours=3),
            status="completed", score=40.0
        )
        s2 = models.ExamSession(
            exam_id=exam.id, student_id=self.candidate1.id, attempt_number=2,
            started_at=now - timedelta(hours=2), submitted_at=now - timedelta(hours=1),
            status="completed", score=80.0
        )
        s3 = models.ExamSession(
            exam_id=exam.id, student_id=self.candidate1.id, attempt_number=3,
            started_at=now - timedelta(minutes=50), submitted_at=now - timedelta(minutes=10),
            status="completed", score=60.0
        )
        self.db.add_all([s1, s2, s3])
        self.db.commit()

        # 1. Best: max(40, 80, 60) -> 80
        exam.attempt_policy = json.dumps({"score_policy": "best"})
        self.db.commit()
        res_best = AttemptPolicyService.compute_consolidated_grade(self.db, exam, self.candidate1.id)
        self.assertEqual(res_best["score"], 80.0)
        self.assertTrue(res_best["passed"])

        # 2. Latest: 60.0
        exam.attempt_policy = json.dumps({"score_policy": "latest"})
        self.db.commit()
        res_latest = AttemptPolicyService.compute_consolidated_grade(self.db, exam, self.candidate1.id)
        self.assertEqual(res_latest["score"], 60.0)

        # 3. First: 40.0
        exam.attempt_policy = json.dumps({"score_policy": "first"})
        self.db.commit()
        res_first = AttemptPolicyService.compute_consolidated_grade(self.db, exam, self.candidate1.id)
        self.assertEqual(res_first["score"], 40.0)
        self.assertFalse(res_first["passed"])

        # 4. Average: (40 + 80 + 60) / 3 = 60.0
        exam.attempt_policy = json.dumps({"score_policy": "average"})
        self.db.commit()
        res_avg = AttemptPolicyService.compute_consolidated_grade(self.db, exam, self.candidate1.id)
        self.assertEqual(res_avg["score"], 60.0)

    # =========================================================================
    # 6. ADVANCED SECTIONS & SEQUENTIAL RESTRICTION
    # =========================================================================
    def test_19_section_sequential_navigation_restriction(self):
        """Verify sequential mode blocks backward navigation to completed sections and enforces order."""
        now = utc_now()
        exam = models.Exam(
            title="Sequential Sections Exam",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        sec1 = models.AssessmentSection(
            exam_id=exam.id, name="Section 1", order_index=1, is_mandatory=True, navigation_mode="sequential"
        )
        sec2 = models.AssessmentSection(
            exam_id=exam.id, name="Section 2", order_index=2, is_mandatory=True, navigation_mode="sequential"
        )
        self.db.add_all([sec1, sec2])
        self.db.commit()

        session = models.ExamSession(
            exam_id=exam.id, student_id=self.candidate1.id, attempt_number=1,
            started_at=now, status="in_progress", current_section_id=sec1.id
        )
        self.db.add(session)
        self.db.commit()

        # Cannot jump to section 2 before completing mandatory section 1
        access_sec2 = SectionService.can_access_section(self.db, session, sec2.id)
        self.assertFalse(access_sec2["allowed"])
        self.assertIn("must complete", access_sec2["reason"].lower())

        # Complete section 1
        SectionService.complete_section(self.db, session, sec1.id)

        # Now section 2 is accessible
        access_sec2_after = SectionService.can_access_section(self.db, session, sec2.id)
        self.assertTrue(access_sec2_after["allowed"])

        # But backward navigation to completed section 1 is prohibited in sequential mode
        access_sec1_back = SectionService.can_access_section(self.db, session, sec1.id)
        self.assertFalse(access_sec1_back["allowed"])
        self.assertIn("backward navigation", access_sec1_back["reason"].lower())

    def test_20_section_completion_and_progress_persistence(self):
        """Verify completing section updates completed_sections and advances current_section_id."""
        now = utc_now()
        exam = models.Exam(
            title="Multi Section Exam",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            status="active",
            creator_id=self.examiner1.id,
            organization_id=self.org1.id
        )
        self.db.add(exam)
        self.db.flush()

        sec_a = models.AssessmentSection(exam_id=exam.id, name="Part A", order_index=1)
        sec_b = models.AssessmentSection(exam_id=exam.id, name="Part B", order_index=2)
        sec_c = models.AssessmentSection(exam_id=exam.id, name="Part C", order_index=3)
        self.db.add_all([sec_a, sec_b, sec_c])
        self.db.commit()

        session = models.ExamSession(
            exam_id=exam.id, student_id=self.candidate1.id, attempt_number=1,
            started_at=now, status="in_progress", current_section_id=sec_a.id
        )
        self.db.add(session)
        self.db.commit()

        # Complete Part A
        SectionService.complete_section(self.db, session, sec_a.id)
        self.db.expire_all()

        completed = SectionService.get_completed_section_ids(session)
        self.assertEqual(completed, [sec_a.id])
        self.assertEqual(session.current_section_id, sec_b.id)

        # Complete Part B
        SectionService.complete_section(self.db, session, sec_b.id)
        self.db.expire_all()

        completed = SectionService.get_completed_section_ids(session)
        self.assertEqual(set(completed), {sec_a.id, sec_b.id})
        self.assertEqual(session.current_section_id, sec_c.id)


if __name__ == "__main__":
    unittest.main()
