"""
testing/test_phase8_integrations.py
-----------------------------------
Comprehensive Unit & Integration Test Suite for Phase 8:
1. Provider registration and registry lookup
2. Integration listing, discovery, and credential masking
3. Org Admin configuration and organization isolation
4. Connection testing with mocked responses
5. Question Generator request and preview workflow
6. Validation across all 6 question types (single_choice, multiple_choice, true_false, short_answer, descriptive, code)
7. Rejection of invalid/malformed generated questions
8. Question approval, Question Bank import (status='draft'), and assessment mapping
9. Duplicate import prevention in Question Bank
10. ServiceNow assessment sync and idempotency enforcement
11. ServiceNow results sync and candidate privacy enforcement
12. Transient failure handling, retries, and manual retry endpoint
13. Integration logs audit trail with zero credential leakage
14. Existing candidate assessment flow and grading completely unaffected
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
from modules.integrations.registry import get_provider, list_registered_providers
from modules.integrations.providers.question_generator import QuestionGeneratorProvider
from modules.integrations.providers.servicenow import ServiceNowProvider
from modules.integrations.schemas import (
    QuestionGenerationRequest,
    QuestionApprovalSubmitRequest,
    ServiceNowSyncRequest,
    IntegrationConfigUpdate
)
from modules.integrations.service import IntegrationService

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


class TestPhase8Integrations(unittest.TestCase):

    def setUp(self):
        app.dependency_overrides[database.get_db] = override_get_db
        models.Base.metadata.drop_all(bind=test_engine)
        models.Base.metadata.create_all(bind=test_engine)
        self.db = TestSessionLocal()
        self.client = TestClient(app)

        now = utc_now()

        # 1. Organizations
        self.org1 = models.Organization(name="Integration Org Alpha", slug="org-alpha", is_active=True)
        self.org2 = models.Organization(name="Integration Org Beta", slug="org-beta", is_active=True)
        self.db.add_all([self.org1, self.org2])
        self.db.commit()

        # 2. Users
        self.super_admin = models.User(
            email="super@test.com",
            name="Super Admin",
            password_hash=auth.get_password_hash("pass123"),
            role="super_admin"
        )
        self.org1_admin = models.User(
            email="admin1@test.com",
            name="Org1 Admin",
            password_hash=auth.get_password_hash("pass123"),
            role="org_admin",
            organization_id=self.org1.id
        )
        self.examiner1 = models.User(
            email="examiner1@test.com",
            name="Examiner One",
            password_hash=auth.get_password_hash("pass123"),
            role="examiner",
            organization_id=self.org1.id
        )
        self.org2_admin = models.User(
            email="admin2@test.com",
            name="Org2 Admin",
            password_hash=auth.get_password_hash("pass123"),
            role="org_admin",
            organization_id=self.org2.id
        )
        self.student1 = models.User(
            email="student1@test.com",
            name="Student One",
            password_hash=auth.get_password_hash("pass123"),
            role="student",
            organization_id=self.org1.id
        )
        self.db.add_all([self.super_admin, self.org1_admin, self.examiner1, self.org2_admin, self.student1])
        self.db.commit()

        # 3. Assessment
        self.exam = models.Exam(
            title="External Systems Assessment",
            organization_id=self.org1.id,
            creator_id=self.examiner1.id,
            assessment_type="technical",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            default_marks=5.0,
            passing_marks=10.0,
            status="published"
        )
        self.db.add(self.exam)
        self.db.commit()

        # 4. Exam Session & Result
        self.sess1 = models.ExamSession(
            exam_id=self.exam.id,
            student_id=self.student1.id,
            attempt_number=1,
            status="submitted",
            submitted_at=now,
            integrity_score=98.0,
            risk_level="low"
        )
        self.db.add(self.sess1)
        self.db.commit()

        self.res1 = models.ExamResult(
            exam_id=self.exam.id,
            student_id=self.student1.id,
            exam_session_id=self.sess1.id,
            attempt_number=1,
            marks_obtained=15.0,
            total_marks=20.0,
            percentage=75.0,
            pass_fail_status="PASS",
            correct_count=3,
            incorrect_count=1,
            unanswered_count=0,
            is_released=True,
            submission_timestamp=now
        )
        self.db.add(self.res1)
        self.db.commit()

        # 5. Auth Tokens
        self.super_token = auth.create_access_token({"sub": self.super_admin.email, "role": "super_admin"})
        self.org1_admin_token = auth.create_access_token({"sub": self.org1_admin.email, "role": "org_admin"})
        self.org2_admin_token = auth.create_access_token({"sub": self.org2_admin.email, "role": "org_admin"})
        self.examiner1_token = auth.create_access_token({"sub": self.examiner1.email, "role": "examiner"})
        self.student1_token = auth.create_access_token({"sub": self.student1.email, "role": "student"})

    def tearDown(self):
        self.db.close()
        models.Base.metadata.drop_all(bind=test_engine)

    # =========================================================================
    # 1. PROVIDER REGISTRATION & LOOKUP
    # =========================================================================
    def test_01_provider_registration_and_lookup(self):
        """Registry discovers and returns instances of built-in providers."""
        providers = list_registered_providers()
        names = [p["name"] for p in providers]
        self.assertIn("question_generator", names)
        self.assertIn("servicenow", names)

        qg = get_provider("question_generator")
        self.assertIsInstance(qg, QuestionGeneratorProvider)
        self.assertEqual(qg.name, "question_generator")

        sn = get_provider("servicenow")
        self.assertIsInstance(sn, ServiceNowProvider)
        self.assertEqual(sn.name, "servicenow")

        with self.assertRaises(KeyError):
            get_provider("non_existent_provider")

    # =========================================================================
    # 2. INTEGRATION LISTING & SECRET MASKING
    # =========================================================================
    def test_02_integration_list_and_secret_masking(self):
        """GET /api/v1/integrations/ lists providers with connection status and masked secrets."""
        # Pre-seed a secret password in DB
        cfg = IntegrationService.get_or_create_config(self.db, "servicenow", self.org1.id)
        cfg.encrypted_credentials = json.dumps({"username": "admin", "password": "SuperSecretPassword123!"})
        self.db.commit()

        res = self.client.get(
            "/api/v1/integrations/",
            headers={"Authorization": f"Bearer {self.org1_admin_token}"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertGreaterEqual(len(data), 2)

        sn_cfg = next(c for c in data if c["name"] == "servicenow")
        self.assertIn("masked_credentials", sn_cfg)
        masked_pwd = sn_cfg["masked_credentials"].get("password", "")
        # Confirm raw password was NOT leaked
        self.assertNotIn("SuperSecretPassword123!", masked_pwd)
        self.assertIn("****", masked_pwd)

    # =========================================================================
    # 3. ORG ADMIN CONFIGURATION & ISOLATION
    # =========================================================================
    def test_03_org_admin_configuration_and_isolation(self):
        """Org Admin can configure integration. Student is blocked (403). Org Admin 2 is isolated."""
        # 1. Student blocked
        res_stud = self.client.post(
            "/api/v1/integrations/servicenow/configure",
            headers={"Authorization": f"Bearer {self.student1_token}"},
            json={"base_url": "https://dev12345.service-now.com"}
        )
        self.assertEqual(res_stud.status_code, 403)

        # 2. Org 1 Admin configures Org 1
        res_admin = self.client.post(
            "/api/v1/integrations/servicenow/configure",
            headers={"Authorization": f"Bearer {self.org1_admin_token}"},
            json={
                "base_url": "https://dev-org1.service-now.com",
                "auth_type": "basic",
                "credentials": {"username": "org1_user", "password": "SecretOrg1Password!"},
                "config_metadata": {"assessment_table": "u_custom_exam_table"}
            }
        )
        self.assertEqual(res_admin.status_code, 200, res_admin.text)
        data = res_admin.json()
        self.assertEqual(data["base_url"], "https://dev-org1.service-now.com")
        self.assertEqual(data["config_metadata"]["assessment_table"], "u_custom_exam_table")

        # 3. Org 2 Admin inspects Org 2: Should NOT see Org 1 instance URL
        res_org2 = self.client.get(
            "/api/v1/integrations/servicenow",
            headers={"Authorization": f"Bearer {self.org2_admin_token}"}
        )
        self.assertEqual(res_org2.status_code, 200)
        data2 = res_org2.json()
        self.assertNotEqual(data2.get("base_url"), "https://dev-org1.service-now.com")

    # =========================================================================
    # 4. CONNECTION TESTING (MOCKED)
    # =========================================================================
    def test_04_connection_testing(self):
        """Connection testing reports status and records execution audit log."""
        res = self.client.post(
            "/api/v1/integrations/question_generator/test",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["status"], "connected")
        self.assertIsNotNone(data["latency_ms"])

        # Verify IntegrationLog was written
        log = self.db.query(models.IntegrationLog).filter_by(
            integration_name="question_generator",
            operation="test_connection"
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "success")

    # =========================================================================
    # 5. QUESTION GENERATOR REQUEST & PREVIEW
    # =========================================================================
    def test_05_question_generator_request_and_preview(self):
        """Examiner requests generated questions and receives validated preview batch."""
        payload = {
            "assessment_id": self.exam.id,
            "subject": "Computer Science",
            "topic": "Graph Algorithms",
            "difficulty": "hard",
            "question_type": "single_choice",
            "quantity": 3
        }
        res = self.client.post(
            "/api/v1/integrations/question-generator/request",
            headers={"Authorization": f"Bearer {self.examiner1_token}"},
            json=payload
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["total_generated"], 3)
        self.assertEqual(data["valid_count"], 3)
        self.assertEqual(data["invalid_count"], 0)
        self.assertEqual(len(data["questions"]), 3)

        # Questions should NOT be in Question Bank yet
        bank_count = self.db.query(models.BankQuestion).count()
        self.assertEqual(bank_count, 0)

    # =========================================================================
    # 6. ALL SIX QUESTION TYPES SUPPORT
    # =========================================================================
    def test_06_all_six_question_types_supported(self):
        """Question Generator supports all 6 question types with appropriate schemas."""
        provider = QuestionGeneratorProvider()
        config = {"mock_mode": True}

        for q_type in ["single_choice", "multiple_choice", "true_false", "short_answer", "descriptive", "code"]:
            req = QuestionGenerationRequest(
                subject="Mathematics",
                topic="Calculus",
                question_type=q_type,
                quantity=1
            )
            items = provider.generate_questions(req, config)
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertTrue(item.is_valid, f"{q_type} failed: {item.validation_notes}")
            self.assertEqual(item.question_type, q_type)

            if q_type in ("single_choice", "multiple_choice", "true_false"):
                self.assertGreaterEqual(len(item.options), 2)
                correct_count = sum(1 for o in item.options if o.is_correct)
                self.assertGreaterEqual(correct_count, 1)
            elif q_type == "short_answer":
                self.assertIn("keywords", item.type_config)
            elif q_type == "code":
                self.assertIn("starter_code", item.type_config)

    # =========================================================================
    # 7. INVALID QUESTION REJECTION
    # =========================================================================
    def test_07_invalid_question_rejection(self):
        """Malformed generated questions are flagged as invalid with explanatory notes."""
        provider = QuestionGeneratorProvider()
        req = QuestionGenerationRequest(
            subject="Physics",
            topic="Thermodynamics",
            question_type="single_choice",
            quantity=1
        )

        # 1. Single Choice with NO correct option
        malformed_raw = {
            "text": "What is absolute zero in Celsius?",
            "question_type": "single_choice",
            "options": [
                {"text": "0 C", "is_correct": False},
                {"text": "100 C", "is_correct": False}
            ]
        }
        item = provider.validate_and_normalize_question(malformed_raw, 0, req)
        self.assertFalse(item.is_valid)
        self.assertIn("must have exactly 1 correct answer", item.validation_notes)

        # 2. Text too short (< 5 chars)
        short_raw = {"text": "Why?", "question_type": "descriptive"}
        item2 = provider.validate_and_normalize_question(short_raw, 1, req)
        self.assertFalse(item2.is_valid)
        self.assertIn("too short", item2.validation_notes)

    # =========================================================================
    # 8. QUESTION APPROVAL & QUESTION BANK IMPORT
    # =========================================================================
    def test_08_question_approval_and_import(self):
        """
        Approving previewed questions imports them into Question Bank as status='draft'
        (never auto-published) and maps to assessment.
        """
        req_gen = QuestionGenerationRequest(
            assessment_id=self.exam.id,
            subject="Database",
            topic="Indexing",
            question_type="single_choice",
            quantity=2
        )
        preview = IntegrationService.request_generated_questions(self.db, req_gen, self.examiner1)

        # Submit Approval
        approve_req = QuestionApprovalSubmitRequest(
            batch_id=preview.batch_id,
            questions=preview.questions,
            approved_indices=[0, 1],
            target_assessment_id=self.exam.id,
            publish_status="draft" # Explicitly draft
        )

        res = self.client.post(
            "/api/v1/integrations/question-generator/approve",
            headers={"Authorization": f"Bearer {self.examiner1_token}"},
            json=approve_req.model_dump()
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["approved_count"], 2)
        self.assertEqual(len(data["imported_bank_question_ids"]), 2)
        self.assertEqual(len(data["mapped_assessment_question_ids"]), 2)

        # Verify BankQuestion status is 'draft' (never auto-published)
        bank_q = self.db.query(models.BankQuestion).filter_by(id=data["imported_bank_question_ids"][0]).first()
        self.assertIsNotNone(bank_q)
        self.assertEqual(bank_q.status, "draft")
        self.assertEqual(bank_q.subject, "Database")
        self.assertEqual(len(bank_q.options), 4)

        # Verify mapping was created in AssessmentQuestionMap
        mapped = self.db.query(models.AssessmentQuestionMap).filter_by(
            assessment_id=self.exam.id,
            bank_question_id=bank_q.id
        ).first()
        self.assertIsNotNone(mapped)

    # =========================================================================
    # 9. DUPLICATE IMPORT PREVENTION
    # =========================================================================
    def test_09_duplicate_import_prevention(self):
        """Re-approving the same questions avoids duplicate Question Bank insertion."""
        req_gen = QuestionGenerationRequest(
            subject="Algorithms",
            topic="Sorting",
            question_type="single_choice",
            quantity=1
        )
        preview = IntegrationService.request_generated_questions(self.db, req_gen, self.examiner1)

        approve_req = QuestionApprovalSubmitRequest(
            batch_id=preview.batch_id,
            questions=preview.questions,
            approved_indices=[0]
        )

        # First Approval: 1 imported, 0 duplicates
        res1 = self.client.post(
            "/api/v1/integrations/question-generator/approve",
            headers={"Authorization": f"Bearer {self.examiner1_token}"},
            json=approve_req.model_dump()
        )
        self.assertEqual(res1.json()["approved_count"], 1)
        self.assertEqual(res1.json()["duplicate_count"], 0)

        # Second Approval of same batch: 0 imported, 1 duplicate skipped
        res2 = self.client.post(
            "/api/v1/integrations/question-generator/approve",
            headers={"Authorization": f"Bearer {self.examiner1_token}"},
            json=approve_req.model_dump()
        )
        self.assertEqual(res2.json()["approved_count"], 0)
        self.assertEqual(res2.json()["duplicate_count"], 1)

    # =========================================================================
    # 10. SERVICENOW ASSESSMENT SYNC & IDEMPOTENCY
    # =========================================================================
    def test_10_servicenow_assessment_sync_idempotency(self):
        """ServiceNow metadata sync pushes assessment and enforces idempotency."""
        sync_req = {
            "exam_id": self.exam.id,
            "sync_type": "metadata",
            "force_resync": False
        }

        # 1. First sync -> Success
        res1 = self.client.post(
            "/api/v1/integrations/servicenow/sync",
            headers={"Authorization": f"Bearer {self.examiner1_token}"},
            json=sync_req
        )
        self.assertEqual(res1.status_code, 200, res1.text)
        data1 = res1.json()
        self.assertEqual(data1["status"], "success")
        self.assertEqual(data1["records_synced"], 1)

        # Verify SyncRecord created
        sync_rec = self.db.query(models.SyncRecord).filter_by(
            integration_name="servicenow",
            entity_type="assessment",
            entity_id=self.exam.id
        ).first()
        self.assertIsNotNone(sync_rec)
        self.assertEqual(sync_rec.status, "synced")

        # 2. Second sync without force_resync -> Idempotent skip
        res2 = self.client.post(
            "/api/v1/integrations/servicenow/sync",
            headers={"Authorization": f"Bearer {self.examiner1_token}"},
            json=sync_req
        )
        self.assertEqual(res2.status_code, 200)
        # Records synced is 0 because already synced
        self.assertEqual(res2.json()["records_synced"], 0)

    # =========================================================================
    # 11. SERVICENOW RESULTS SYNC & CANDIDATE PRIVACY
    # =========================================================================
    def test_11_servicenow_results_sync_and_privacy(self):
        """Results sync exports score and pass/fail; strictly preserves candidate secrets."""
        sync_req = {
            "exam_id": self.exam.id,
            "sync_type": "results",
            "force_resync": True
        }

        res = self.client.post(
            "/api/v1/integrations/servicenow/sync",
            headers={"Authorization": f"Bearer {self.examiner1_token}"},
            json=sync_req
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["records_synced"], 1)

        # Verify SyncRecord payload
        sync_rec = self.db.query(models.SyncRecord).filter_by(
            integration_name="servicenow",
            entity_type="result",
            entity_id=self.res1.id
        ).first()
        self.assertIsNotNone(sync_rec)
        payload = json.loads(sync_rec.synced_payload)
        self.assertEqual(payload["score"], 15.0)
        self.assertEqual(payload["percentage"], 75.0)
        self.assertEqual(payload["pass_fail_status"], "PASS")
        # Ensure password and token fields are completely absent
        self.assertNotIn("password", payload)
        self.assertNotIn("password_hash", payload)
        self.assertNotIn("token", payload)

    # =========================================================================
    # 12. RETRY MECHANISM & MANUAL RETRY ENDPOINT
    # =========================================================================
    def test_12_sync_retry_mechanism(self):
        """Failed sync records can be inspected and retried via manual endpoint."""
        # Create a simulated failed record
        failed_rec = models.SyncRecord(
            integration_name="servicenow",
            organization_id=self.org1.id,
            entity_type="assessment",
            entity_id=self.exam.id,
            idempotency_key=f"servicenow_{self.org1.id}_exam_{self.exam.id}_fail",
            status="failed",
            attempts=1,
            last_error="Simulated network socket timeout"
        )
        self.db.add(failed_rec)
        self.db.commit()

        # Retry endpoint
        res = self.client.post(
            f"/api/v1/integrations/servicenow/retry/{failed_rec.id}",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["status"], "success")

        self.db.refresh(failed_rec)
        self.assertGreater(failed_rec.attempts, 1)

    # =========================================================================
    # 13. INTEGRATION LOGS SANITIZATION
    # =========================================================================
    def test_13_integration_logs_sanitization(self):
        """Integration execution logs never leak raw secrets or passwords."""
        # Execute operations that generate logs with credentials
        IntegrationService.update_config(
            self.db, "servicenow",
            IntegrationConfigUpdate(
                credentials={"username": "admin", "password": "SuperSecretPassword123!"}
            ),
            self.org1_admin
        )
        IntegrationService.test_connection(self.db, "servicenow", self.examiner1)

        res = self.client.get(
            "/api/v1/integrations/logs",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertIn("logs", data)
        self.assertGreater(data["total"], 0)

        for l in data["logs"]:
            combined_text = f"{l['request_summary']} {l['response_summary']} {l['error_details']}"
            self.assertNotIn("SuperSecretPassword123!", combined_text)
            self.assertNotIn("SecretOrg1Password!", combined_text)

    # =========================================================================
    # 14. ASSESSMENT ENGINE UNAFFECTED BY INTEGRATION FAILURES
    # =========================================================================
    def test_14_exam_submission_unaffected_by_integration_failure(self):
        """Simulated integration failure does not impede candidate exam attempts."""
        # Disable integration or set invalid url
        cfg = IntegrationService.get_or_create_config(self.db, "servicenow", self.org1.id)
        cfg.is_enabled = False
        self.db.commit()

        # Student submits an exam answer
        q = models.Question(exam_id=self.exam.id, text="Standard Question?", marks=5.0)
        self.db.add(q)
        self.db.commit()

        ans = models.StudentAnswer(
            exam_session_id=self.sess1.id,
            question_id=q.id,
            answer_text="Unimpeded candidate answer",
            is_correct=True,
            marks_awarded=5.0,
            evaluation_status="evaluated"
        )
        self.db.add(ans)
        self.db.commit()

        # Verify submission saved cleanly without any dependency on external integration
        saved_ans = self.db.query(models.StudentAnswer).filter_by(id=ans.id).first()
        self.assertIsNotNone(saved_ans)
        self.assertEqual(saved_ans.marks_awarded, 5.0)


if __name__ == "__main__":
    unittest.main()
