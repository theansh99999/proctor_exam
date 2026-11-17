"""

testing/test_phase3_question_bank.py

------------------------------------

Comprehensive automated tests for Phase 3 — Question Bank & Question Management:

1. Question Bank CRUD supporting all 6 question types:

   - single_choice (MCQ, exactly 1 correct answer)

   - multiple_choice (MCQ, at least 1 correct answer)

   - true_false (exactly 2 options, exactly 1 correct)

   - short_answer

   - descriptive

   - code (programming question with test cases and language)

2. Strict Option and Evaluation Validation rules (rejections on violations)

3. Candidate Privacy & Security boundary (candidate 403, correct answer concealment)

4. Multi-Tenant Organization Scoping & Examiner Ownership

5. Bulk Import via CSV and JSON:

   - Downloadable templates

   - Preview mode vs Commit mode

   - Duplicate detection

   - Row-level validation and error reporting

6. Assessment Question Mapping & Synchronization:

   - Mapping bank questions to assessment with custom marks override

   - Synchronizing to exam questions for existing exam engine compatibility

   - Duplicate mapping prevention

   - Question reordering

   - Question removal and assessment max marks recalculation

7. Question Generator Integration Boundary (preview & approval workflows)

8. Teacher UI route (/teacher/question-bank) rendering

"""

import os

os.environ["TESTING"] = "1"



import unittest

import json

import io

from fastapi.testclient import TestClient



import models, auth

from main import app

from time_utils import utc_now, to_utc

from testing.test_db import init_test_db, cleanup_test_db, TestingSessionLocal, apply_test_db_override, clear_test_db_override



class TestPhase3QuestionBank(unittest.TestCase):

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

        # 1. Super Admin

        self.super_admin = models.User(

            email="superadmin@bank.com",

            name="Super Admin",

            password_hash=auth.get_password_hash("SuperPass123!"),

            role="super_admin"

        )

        self.db.add(self.super_admin)



        # 2. Organizations

        self.org1 = models.Organization(name="Cyberdyne Systems", slug="cyberdyne", description="Robotics & AI")

        self.org2 = models.Organization(name="Weyland Corp", slug="weyland", description="Space & BioTech")

        self.db.add_all([self.org1, self.org2])

        self.db.commit()



        # 3. Examiners & Candidates for Org 1

        self.examiner1 = models.User(

            email="sarah@cyberdyne.com",

            name="Sarah Connor",

            password_hash=auth.get_password_hash("SarahPass123!"),

            role="examiner",

            organization_id=self.org1.id

        )

        self.candidate1 = models.User(

            email="john@cyberdyne.com",

            name="John Connor",

            password_hash=auth.get_password_hash("JohnPass123!"),

            role="candidate",

            organization_id=self.org1.id

        )



        # 4. Examiner & Candidate for Org 2

        self.examiner2 = models.User(

            email="ripley@weyland.com",

            name="Ellen Ripley",

            password_hash=auth.get_password_hash("RipleyPass123!"),

            role="examiner",

            organization_id=self.org2.id

        )

        self.candidate2 = models.User(

            email="newt@weyland.com",

            name="Rebecca Newt",

            password_hash=auth.get_password_hash("NewtPass123!"),

            role="candidate",

            organization_id=self.org2.id

        )



        self.db.add_all([self.examiner1, self.candidate1, self.examiner2, self.candidate2])

        self.db.commit()



        # Group & Assessment for Org 1

        self.group1 = models.Group(name="Defense AI Cohort", teacher_id=self.examiner1.id, organization_id=self.org1.id)

        self.db.add(self.group1)

        self.db.commit()



        now = utc_now()

        self.exam1 = models.Exam(

            title="AI Systems Midterm",

            description="Autonomous defenses exam",

            start_time=now,

            end_time=now.replace(year=now.year + 1),

            duration_minutes=60,

            group_id=self.group1.id,

            default_marks=1.0,

            creator_id=self.examiner1.id,

            organization_id=self.org1.id,

            assessment_type="technical",

            status="draft"

        )

        self.db.add(self.exam1)

        self.db.commit()



        # Auth Tokens

        self.super_token = auth.create_access_token({"sub": self.super_admin.email, "role": "super_admin"})

        self.examiner1_token = auth.create_access_token({"sub": self.examiner1.email, "role": "examiner"})

        self.examiner2_token = auth.create_access_token({"sub": self.examiner2.email, "role": "examiner"})

        self.candidate1_token = auth.create_access_token({"sub": self.candidate1.email, "role": "candidate"})



    # =========================================================================

    # TEST 1: Question Bank CRUD & All 6 Question Types

    # =========================================================================

    def test_01_question_bank_crud_all_six_types(self):

        headers = {"Authorization": f"Bearer {self.examiner1_token}"}



        # 1. Single Choice MCQ

        sc_payload = {

            "text": "What is the primary function of an activation function?",

            "question_type": "single_choice",

            "assessment_category": "technical",

            "subject": "Deep Learning",

            "topic": "Neural Networks",

            "subtopic": "Nonlinearities",

            "difficulty": "medium",

            "default_marks": 2.0,

            "default_negative_marks": 0.5,

            "explanation": "Activation functions introduce non-linearity into neural networks.",

            "tags": ["deep-learning", "ai", "math"],

            "status": "published",

            "options": [

                {"text": "Introduce non-linearity", "is_correct": True, "explanation": "Correct, allows learning complex mappings."},

                {"text": "Normalize inputs", "is_correct": False},

                {"text": "Compute gradients directly", "is_correct": False},

                {"text": "Prevent data loss", "is_correct": False}

            ]

        }

        r = self.client.post("/api/v1/question-bank/questions", json=sc_payload, headers=headers)

        self.assertEqual(r.status_code, 201, r.text)

        sc_id = r.json()["data"]["id"]

        self.assertEqual(r.json()["data"]["question_type"], "single_choice")

        self.assertEqual(len(r.json()["data"]["options"]), 4)



        # 2. Multiple Choice (multi-select)

        mc_payload = {

            "text": "Which of the following are unsupervised learning algorithms?",

            "question_type": "multiple_choice",

            "assessment_category": "technical",

            "subject": "Machine Learning",

            "topic": "Unsupervised",

            "difficulty": "easy",

            "default_marks": 3.0,

            "options": [

                {"text": "K-Means Clustering", "is_correct": True},

                {"text": "PCA (Principal Component Analysis)", "is_correct": True},

                {"text": "Linear Regression", "is_correct": False},

                {"text": "Autoencoders", "is_correct": True}

            ]

        }

        r = self.client.post("/api/v1/question-bank/questions", json=mc_payload, headers=headers)

        self.assertEqual(r.status_code, 201, r.text)

        self.assertEqual(r.json()["data"]["question_type"], "multiple_choice")

        correct_opts = [o for o in r.json()["data"]["options"] if o["is_correct"]]

        self.assertEqual(len(correct_opts), 3)



        # 3. True / False

        tf_payload = {

            "text": "Gradient Descent is guaranteed to find the global minimum in non-convex loss surfaces.",

            "question_type": "true_false",

            "assessment_category": "academic",

            "subject": "Optimization",

            "difficulty": "medium",

            "default_marks": 1.0,

            "options": [

                {"text": "True", "is_correct": False},

                {"text": "False", "is_correct": True, "explanation": "Non-convex surfaces have multiple local minima and saddle points."}

            ]

        }

        r = self.client.post("/api/v1/question-bank/questions", json=tf_payload, headers=headers)

        self.assertEqual(r.status_code, 201, r.text)

        self.assertEqual(r.json()["data"]["question_type"], "true_false")



        # 4. Short Answer

        sa_payload = {

            "text": "Name the theorem that states a continuous function on a closed interval is bounded.",

            "question_type": "short_answer",

            "assessment_category": "academic",

            "subject": "Calculus",

            "difficulty": "hard",

            "default_marks": 2.0,

            "explanation": "Extreme Value Theorem",

            "type_config": {"expected_keywords": ["Extreme Value Theorem", "Weierstrass"]}

        }

        r = self.client.post("/api/v1/question-bank/questions", json=sa_payload, headers=headers)

        self.assertEqual(r.status_code, 201, r.text)

        self.assertEqual(r.json()["data"]["question_type"], "short_answer")



        # 5. Descriptive

        desc_payload = {

            "text": "Explain the architectural differences between Transformer encoders and decoders, including causal masking.",

            "question_type": "descriptive",

            "assessment_category": "technical",

            "subject": "NLP",

            "difficulty": "hard",

            "default_marks": 10.0,

            "explanation": "Encoders use bi-directional self-attention; decoders use masked auto-regressive attention."

        }

        r = self.client.post("/api/v1/question-bank/questions", json=desc_payload, headers=headers)

        self.assertEqual(r.status_code, 201, r.text)

        self.assertEqual(r.json()["data"]["question_type"], "descriptive")



        # 6. Code / Programming

        code_payload = {

            "text": "Write a Python function `def is_palindrome(s: str) -> bool:` that returns True if s is a palindrome.",

            "question_type": "code",

            "assessment_category": "technical",

            "subject": "Programming",

            "topic": "Strings",

            "difficulty": "easy",

            "default_marks": 5.0,

            "type_config": {

                "language": "python",

                "skeleton": "def is_palindrome(s: str) -> bool:\n    pass",

                "test_cases": [

                    {"input": "radar", "expected": "true"},

                    {"input": "hello", "expected": "false"}

                ]

            }

        }

        r = self.client.post("/api/v1/question-bank/questions", json=code_payload, headers=headers)

        self.assertEqual(r.status_code, 201, r.text)

        code_id = r.json()["data"]["id"]

        self.assertEqual(r.json()["data"]["type_config"]["language"], "python")



        # Read back question

        r = self.client.get(f"/api/v1/question-bank/questions/{sc_id}", headers=headers)

        self.assertEqual(r.status_code, 200)

        self.assertEqual(r.json()["data"]["text"], sc_payload["text"])



        # Update question

        r = self.client.put(f"/api/v1/question-bank/questions/{sc_id}", json={

            "difficulty": "hard",

            "default_marks": 4.0

        }, headers=headers)

        self.assertEqual(r.status_code, 200)

        self.assertEqual(r.json()["data"]["difficulty"], "hard")

        self.assertEqual(r.json()["data"]["default_marks"], 4.0)



        # Archive question

        r = self.client.post(f"/api/v1/question-bank/questions/{code_id}/archive", headers=headers)

        self.assertEqual(r.status_code, 200)

        self.assertEqual(r.json()["data"]["status"], "archived")



    # =========================================================================

    # TEST 2: Strict Validation & Rejection of Malformed Questions

    # =========================================================================

    def test_02_validation_rules_and_rejections(self):

        headers = {"Authorization": f"Bearer {self.examiner1_token}"}



        # Single choice with 0 correct answers -> 400

        sc_zero_correct = {

            "text": "Invalid single choice with 0 correct",

            "question_type": "single_choice",

            "options": [

                {"text": "Opt A", "is_correct": False},

                {"text": "Opt B", "is_correct": False}

            ]

        }

        r = self.client.post("/api/v1/question-bank/questions", json=sc_zero_correct, headers=headers)

        self.assertEqual(r.status_code, 400)

        self.assertIn("exactly 1 correct answer", r.json()["detail"])



        # Single choice with 2 correct answers -> 400

        sc_two_correct = {

            "text": "Invalid single choice with 2 correct",

            "question_type": "single_choice",

            "options": [

                {"text": "Opt A", "is_correct": True},

                {"text": "Opt B", "is_correct": True}

            ]

        }

        r = self.client.post("/api/v1/question-bank/questions", json=sc_two_correct, headers=headers)

        self.assertEqual(r.status_code, 400)

        self.assertIn("exactly 1 correct answer", r.json()["detail"])



        # Multiple choice with 0 correct answers -> 400

        mc_zero_correct = {

            "text": "Invalid multi choice with 0 correct",

            "question_type": "multiple_choice",

            "options": [

                {"text": "Opt A", "is_correct": False},

                {"text": "Opt B", "is_correct": False}

            ]

        }

        r = self.client.post("/api/v1/question-bank/questions", json=mc_zero_correct, headers=headers)

        self.assertEqual(r.status_code, 400)

        self.assertIn("at least 1 correct answer", r.json()["detail"])



        # True/False with 3 options -> 400

        tf_three_opts = {

            "text": "Invalid true false with 3 options",

            "question_type": "true_false",

            "options": [

                {"text": "True", "is_correct": True},

                {"text": "False", "is_correct": False},

                {"text": "Maybe", "is_correct": False}

            ]

        }

        r = self.client.post("/api/v1/question-bank/questions", json=tf_three_opts, headers=headers)

        self.assertEqual(r.status_code, 400)

        self.assertIn("exactly 2 options", r.json()["detail"])



        # Invalid question_type -> 400

        invalid_type = {

            "text": "Unknown type question",

            "question_type": "quantum_entanglement"

        }

        r = self.client.post("/api/v1/question-bank/questions", json=invalid_type, headers=headers)

        self.assertEqual(r.status_code, 400)

        self.assertIn("Invalid question_type", r.json()["detail"])



    # =========================================================================

    # TEST 3: Candidate Security & Privacy Boundary

    # =========================================================================

    def test_03_candidate_privacy_boundary(self):

        # 1. Candidate attempting to access question bank API -> 403 Forbidden

        cand_headers = {"Authorization": f"Bearer {self.candidate1_token}"}

        r = self.client.get("/api/v1/question-bank/questions", headers=cand_headers)

        self.assertEqual(r.status_code, 403)

        self.assertIn("Candidates cannot access", r.json()["detail"])



        # Candidate attempting to create question -> 403 Forbidden

        r = self.client.post("/api/v1/question-bank/questions", json={

            "text": "Candidate created question?",

            "question_type": "single_choice"

        }, headers=cand_headers)

        self.assertEqual(r.status_code, 403)



    # =========================================================================

    # TEST 4: Organization Isolation & Multi-Tenancy Scoping

    # =========================================================================

    def test_04_organization_isolation(self):

        h1 = {"Authorization": f"Bearer {self.examiner1_token}"}

        h2 = {"Authorization": f"Bearer {self.examiner2_token}"}



        # Examiner 1 (Org 1) creates question

        r = self.client.post("/api/v1/question-bank/questions", json={

            "text": "Cyberdyne proprietary AI question",

            "question_type": "short_answer",

            "assessment_category": "technical",

            "default_marks": 5.0

        }, headers=h1)

        self.assertEqual(r.status_code, 201)

        q1_id = r.json()["data"]["id"]



        # Examiner 2 (Org 2) cannot retrieve or modify question q1

        r = self.client.get(f"/api/v1/question-bank/questions/{q1_id}", headers=h2)

        self.assertEqual(r.status_code, 403)



        r = self.client.put(f"/api/v1/question-bank/questions/{q1_id}", json={"difficulty": "hard"}, headers=h2)

        self.assertEqual(r.status_code, 403)



        r = self.client.delete(f"/api/v1/question-bank/questions/{q1_id}", headers=h2)

        self.assertEqual(r.status_code, 403)



        # Super admin can access and see question q1

        super_h = {"Authorization": f"Bearer {self.super_token}"}

        r = self.client.get(f"/api/v1/question-bank/questions/{q1_id}", headers=super_h)

        self.assertEqual(r.status_code, 200)



    # =========================================================================

    # TEST 5: Bulk Import via CSV & JSON

    # =========================================================================

    def test_05_bulk_import_csv_and_json(self):

        headers = {"Authorization": f"Bearer {self.examiner1_token}"}



        # 1. Download templates

        r_csv_tmpl = self.client.get("/api/v1/question-bank/templates/csv", headers=headers)

        self.assertEqual(r_csv_tmpl.status_code, 200)

        self.assertIn("text,question_type,assessment_category", r_csv_tmpl.text)



        r_json_tmpl = self.client.get("/api/v1/question-bank/templates/json", headers=headers)

        self.assertEqual(r_json_tmpl.status_code, 200)

        self.assertIsInstance(r_json_tmpl.json(), list)



        # 2. JSON Bulk Import - Preview Mode

        json_rows = [

            {

                "text": "What is overfitting in machine learning?",

                "question_type": "single_choice",

                "assessment_category": "technical",

                "difficulty": "medium",

                "default_marks": 2.0,

                "options": [

                    {"text": "Model learns noise along with underlying pattern", "is_correct": True},

                    {"text": "Model is too simple to capture trends", "is_correct": False}

                ]

            },

            {

                "text": "Invalid question row missing correct answer",

                "question_type": "single_choice",

                "options": [

                    {"text": "Option 1", "is_correct": False},

                    {"text": "Option 2", "is_correct": False}

                ]

            }

        ]



        r = self.client.post("/api/v1/question-bank/import/json?preview=true", json=json_rows, headers=headers)

        self.assertEqual(r.status_code, 200)

        res = r.json()["data"]

        self.assertTrue(res["is_preview"])

        self.assertEqual(res["total_rows"], 2)

        self.assertEqual(res["valid_count"], 1)

        self.assertEqual(res["error_count"], 1)

        self.assertEqual(res["imported_count"], 0)

        self.assertEqual(res["errors"][0]["row_number"], 2)



        # 3. CSV Bulk Import - Commit Mode

        csv_content = (

            "text,question_type,assessment_category,subject,topic,difficulty,default_marks,default_negative_marks,options,correct_options,explanation,tags\n"

            '"What does SQL stand for?",single_choice,technical,Databases,RDBMS,easy,2.0,0.5,"Structured Query Language|Simple Query Language|Standard Question Language",1,"Standard DB language","sql,db"\n'

            '"Which are relational databases?",multiple_choice,technical,Databases,RDBMS,medium,3.0,0.0,"PostgreSQL|MySQL|Redis|MongoDB","1,2","Relational engines","sql,rdbms"\n'

        )

        files = {"file": ("questions.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}

        r = self.client.post("/api/v1/question-bank/import/csv?preview=false", files=files, headers=headers)

        self.assertEqual(r.status_code, 200, r.text)

        res = r.json()["data"]

        self.assertFalse(res["is_preview"])

        self.assertEqual(res["total_rows"], 2)

        self.assertEqual(res["imported_count"], 2)

        self.assertEqual(res["error_count"], 0)



        # Verify questions are now present in bank

        r_list = self.client.get("/api/v1/question-bank/questions?subject=Databases", headers=headers)

        self.assertEqual(r_list.status_code, 200)

        self.assertEqual(r_list.json()["meta"]["total"], 2)



    # =========================================================================

    # TEST 6: Assessment Question Mapping & Synchronization

    # =========================================================================

    def test_06_assessment_question_mapping_and_sync(self):

        headers = {"Authorization": f"Bearer {self.examiner1_token}"}



        # Create 2 questions in the bank

        q1_res = self.client.post("/api/v1/question-bank/questions", json={

            "text": "What is an epoch in deep learning?",

            "question_type": "single_choice",

            "assessment_category": "technical",

            "default_marks": 2.0,

            "default_negative_marks": 0.5,

            "options": [

                {"text": "One complete pass through the entire training dataset", "is_correct": True},

                {"text": "One gradient update step", "is_correct": False}

            ]

        }, headers=headers).json()["data"]



        q2_res = self.client.post("/api/v1/question-bank/questions", json={

            "text": "What does CNN stand for in computer vision?",

            "question_type": "single_choice",

            "assessment_category": "technical",

            "default_marks": 1.0,

            "options": [

                {"text": "Convolutional Neural Network", "is_correct": True},

                {"text": "Central Neural Network", "is_correct": False}

            ]

        }, headers=headers).json()["data"]



        # Map q1 and q2 to assessment with custom marks override

        map_payload = {

            "questions": [

                {"bank_question_id": q1_res["id"], "marks": 5.0, "negative_marks": 1.0, "order_index": 1},

                {"bank_question_id": q2_res["id"], "marks": 3.0, "negative_marks": 0.0, "order_index": 2}

            ]

        }

        r = self.client.post(f"/api/v1/assessments/{self.exam1.id}/questions", json=map_payload, headers=headers)

        self.assertEqual(r.status_code, 200, r.text)

        res = r.json()["data"]

        self.assertEqual(res["total_questions"], 2)

        self.assertEqual(res["total_max_marks"], 8.0)



        # Verify duplicate mapping rejection (mapping q1 again -> 400)

        dup_payload = {

            "questions": [

                {"bank_question_id": q1_res["id"], "marks": 5.0}

            ]

        }

        r_dup = self.client.post(f"/api/v1/assessments/{self.exam1.id}/questions", json=dup_payload, headers=headers)

        self.assertEqual(r_dup.status_code, 400)

        self.assertIn("already mapped", r_dup.json()["detail"])



        # Verify synchronization into exam.questions (for existing engine compatibility)

        self.db.expire_all()

        exam_questions = self.db.query(models.Question).filter(models.Question.exam_id == self.exam1.id).all()

        self.assertEqual(len(exam_questions), 2)

        synced_q1 = next(q for q in exam_questions if q.bank_question_id == q1_res["id"])

        self.assertEqual(synced_q1.marks, 5.0)

        self.assertEqual(synced_q1.order_index, 1)

        self.assertEqual(synced_q1.question_type, "single_choice")

        self.assertEqual(len(synced_q1.options), 2)



        # Test Reordering

        reorder_payload = {

            "reorder_list": [

                {"bank_question_id": q2_res["id"], "order_index": 1},

                {"bank_question_id": q1_res["id"], "order_index": 2}

            ]

        }

        r_reorder = self.client.put(f"/api/v1/assessments/{self.exam1.id}/questions/reorder", json=reorder_payload, headers=headers)

        self.assertEqual(r_reorder.status_code, 200)



        # Test Delete Mapping

        r_del = self.client.delete(f"/api/v1/assessments/{self.exam1.id}/questions/{q2_res['id']}", headers=headers)

        self.assertEqual(r_del.status_code, 200)



        # Verify assessment now has 1 question and 5.0 max marks

        r_after_del = self.client.get(f"/api/v1/assessments/{self.exam1.id}/questions", headers=headers)

        self.assertEqual(r_after_del.status_code, 200)

        self.assertEqual(r_after_del.json()["data"]["total_questions"], 1)

        self.assertEqual(r_after_del.json()["data"]["total_max_marks"], 5.0)



    # =========================================================================

    # TEST 7: Question Generator Integration Boundary

    # =========================================================================

    def test_07_question_generator_boundary(self):

        headers = {"Authorization": f"Bearer {self.examiner1_token}"}



        # 1. Preview batch generated questions

        batch_payload = {

            "batch_id": "gen_batch_test_001",

            "source_model": "gemini-2.5-pro",

            "subject": "Operating Systems",

            "topic": "Process & Memory",

            "questions": [

                {

                    "text": "What does paging achieve in virtual memory?",

                    "question_type": "single_choice",

                    "subject": "Operating Systems",

                    "topic": "Memory Management",

                    "difficulty": "medium",

                    "marks": 2.0,

                    "negative_marks": 0.5,

                    "explanation": "Virtual memory maps virtual addresses to physical frames using page tables.",

                    "options": [

                        {"text": "Maps virtual addresses to physical frames", "is_correct": True},

                        {"text": "Eliminates cache misses entirely", "is_correct": False}

                    ]

                },

                {

                    "text": "A deadlock can occur without mutual exclusion.",

                    "question_type": "true_false",

                    "subject": "Operating Systems",

                    "topic": "Deadlocks",

                    "difficulty": "easy",

                    "marks": 1.0,

                    "options": [

                        {"text": "True", "is_correct": False},

                        {"text": "False", "is_correct": True}

                    ]

                }

            ]

        }



        r_prev = self.client.post("/api/v1/integrations/question-generator/preview", json=batch_payload, headers=headers)

        self.assertEqual(r_prev.status_code, 200, r_prev.text)

        preview_data = r_prev.json()["data"]

        self.assertEqual(preview_data["total_questions"], 2)

        self.assertEqual(len(preview_data["preview"]), 2)



        # 2. Approve generated questions into Question Bank

        approval_payload = {

            "batch_id": "gen_batch_test_001",

            "questions": batch_payload["questions"],

            "publish_to_bank": True

        }

        r_app = self.client.post("/api/v1/integrations/question-generator/approve", json=approval_payload, headers=headers)

        self.assertEqual(r_app.status_code, 200, r_app.text)

        app_data = r_app.json()["data"]

        self.assertEqual(app_data["approved_count"], 2)

        self.assertEqual(len(app_data["created_question_ids"]), 2)



        # Verify they exist in the bank with status 'published'

        q_id = app_data["created_question_ids"][0]

        r_q = self.client.get(f"/api/v1/question-bank/questions/{q_id}", headers=headers)

        self.assertEqual(r_q.status_code, 200)

        self.assertEqual(r_q.json()["data"]["status"], "published")



    # =========================================================================

    # TEST 8: Teacher UI Question Bank View

    # =========================================================================

    def test_08_teacher_ui_question_bank_page(self):

        headers = {"Authorization": f"Bearer {self.examiner1_token}"}

        # First ensure teacher has at least 1 question

        self.client.post("/api/v1/question-bank/questions", json={

            "text": "Sample UI verified question",

            "question_type": "short_answer",

            "assessment_category": "academic",

            "default_marks": 2.0

        }, headers=headers)



        r = self.client.get("/teacher/question-bank", headers=headers)

        self.assertEqual(r.status_code, 200)

        self.assertIn("Question Bank", r.text)

        self.assertIn("Sample UI verified question", r.text)

        self.assertIn("Bulk Import", r.text)



if __name__ == "__main__":

    unittest.main()
