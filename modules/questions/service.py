"""
modules/questions/service.py
----------------------------
Business logic, validation, bulk imports, and assessment mapping
for the central reusable Question Bank.
"""
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc, asc, func
from fastapi import HTTPException, status
from typing import List, Optional, Dict, Any, Tuple, Set
import json
import csv
import io

import models
from modules.questions.schemas import (
    BankQuestionCreate,
    BankQuestionUpdate,
    BankQuestionOut,
    QuestionImportResponse,
    ImportRowError,
    AssessmentQuestionMapRequest,
    AssessmentQuestionReorderRequest,
    AssessmentQuestionMapOut,
    AssessmentQuestionsListResponse,
    SUPPORTED_QUESTION_TYPES,
    SUPPORTED_CATEGORIES,
    SUPPORTED_DIFFICULTIES,
    SUPPORTED_STATUSES
)
from core.rbac import (
    is_super_admin,
    is_org_admin,
    is_examiner_or_admin,
    is_candidate,
    enforce_org_access
)

class QuestionBankService:
    # =========================================================================
    # 1. QUESTION VALIDATION & CRUD
    # =========================================================================
    @staticmethod
    def validate_question_data(data: Any, is_update: bool = False) -> None:
        """Enforce strict question-type and option validation rules."""
        q_type = getattr(data, "question_type", None)
        if q_type and q_type not in SUPPORTED_QUESTION_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid question_type '{q_type}'. Must be one of {SUPPORTED_QUESTION_TYPES}.")

        cat = getattr(data, "assessment_category", None)
        if cat and cat not in SUPPORTED_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Invalid assessment_category '{cat}'. Must be one of {SUPPORTED_CATEGORIES}.")

        diff = getattr(data, "difficulty", None)
        if diff and diff not in SUPPORTED_DIFFICULTIES:
            raise HTTPException(status_code=400, detail=f"Invalid difficulty '{diff}'. Must be one of {SUPPORTED_DIFFICULTIES}.")

        stat = getattr(data, "status", None)
        if stat and stat not in SUPPORTED_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status '{stat}'. Must be one of {SUPPORTED_STATUSES}.")

        options = getattr(data, "options", None)
        if options is not None:
            correct_count = sum(1 for o in options if getattr(o, "is_correct", False))

            if q_type == "single_choice":
                if len(options) < 2:
                    raise HTTPException(status_code=400, detail="Single-choice questions require at least 2 options.")
                if correct_count != 1:
                    raise HTTPException(status_code=400, detail=f"Single-choice questions must have exactly 1 correct answer (found {correct_count}).")

            elif q_type == "multiple_choice":
                if len(options) < 2:
                    raise HTTPException(status_code=400, detail="Multiple-choice questions require at least 2 options.")
                if correct_count < 1:
                    raise HTTPException(status_code=400, detail="Multiple-choice questions must have at least 1 correct answer.")

            elif q_type == "true_false":
                if len(options) != 2:
                    raise HTTPException(status_code=400, detail="True/False questions must have exactly 2 options ('True' and 'False').")
                if correct_count != 1:
                    raise HTTPException(status_code=400, detail="True/False questions must have exactly 1 correct answer.")

    @staticmethod
    def create_question(db: Session, data: BankQuestionCreate, current_user: models.User) -> models.BankQuestion:
        if not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Only Examiners and Admins can add questions to the Question Bank.")

        QuestionBankService.validate_question_data(data)

        # Scoping
        target_org_id = data.organization_id
        if is_super_admin(current_user):
            pass
        elif is_org_admin(current_user):
            target_org_id = current_user.organization_id
        else:
            if current_user.organization_id is not None:
                if target_org_id and target_org_id != current_user.organization_id:
                    raise HTTPException(status_code=403, detail="Cannot create question for another organization.")
                target_org_id = current_user.organization_id

        tags_str = json.dumps(data.tags) if data.tags else None
        config_str = json.dumps(data.type_config) if data.type_config else None

        q = models.BankQuestion(
            text=data.text.strip(),
            question_type=data.question_type,
            assessment_category=data.assessment_category,
            subject=data.subject.strip(),
            topic=data.topic.strip(),
            subtopic=data.subtopic.strip() if data.subtopic else None,
            difficulty=data.difficulty,
            default_marks=data.default_marks,
            default_negative_marks=data.default_negative_marks,
            explanation=data.explanation,
            tags=tags_str,
            organization_id=target_org_id,
            created_by=current_user.id,
            status=data.status,
            type_config=config_str
        )
        db.add(q)
        db.commit()
        db.refresh(q)

        # Add options if provided
        if data.options:
            for idx, opt_in in enumerate(data.options):
                opt = models.BankOption(
                    question_id=q.id,
                    text=opt_in.text.strip(),
                    is_correct=opt_in.is_correct,
                    explanation=opt_in.explanation,
                    order_index=opt_in.order_index if opt_in.order_index else idx
                )
                db.add(opt)
            db.commit()
            db.refresh(q)

        return q

    @staticmethod
    def get_question(db: Session, question_id: int, current_user: models.User) -> models.BankQuestion:
        # Candidate access to question-bank management APIs is strictly blocked
        if is_candidate(current_user) and not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Candidates cannot access the Question Bank.")

        q = db.query(models.BankQuestion).filter(models.BankQuestion.id == question_id).first()
        if not q:
            raise HTTPException(status_code=404, detail="Question not found.")

        enforce_org_access(current_user, q.organization_id, resource_name="question")
        return q

    @staticmethod
    def list_questions(
        db: Session,
        current_user: models.User,
        search: Optional[str] = None,
        assessment_category: Optional[str] = None,
        subject: Optional[str] = None,
        topic: Optional[str] = None,
        difficulty: Optional[str] = None,
        question_type: Optional[str] = None,
        status_filter: Optional[str] = None,
        organization_id: Optional[int] = None,
        sort_by: str = "id",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[models.BankQuestion], int]:
        if is_candidate(current_user) and not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Candidates cannot access the Question Bank.")

        query = db.query(models.BankQuestion)

        # Scoping by role
        if is_super_admin(current_user):
            if organization_id is not None:
                query = query.filter(models.BankQuestion.organization_id == organization_id)
        elif is_org_admin(current_user):
            query = query.filter(models.BankQuestion.organization_id == current_user.organization_id)
        else:
            # Examiner
            if current_user.organization_id is not None:
                query = query.filter(models.BankQuestion.organization_id == current_user.organization_id)
            else:
                # Unaffiliated examiner
                query = query.filter(
                    or_(
                        models.BankQuestion.created_by == current_user.id,
                        models.BankQuestion.organization_id.is_(None)
                    )
                )

        # Filters
        if search:
            s = f"%{search.strip()}%"
            query = query.filter(or_(models.BankQuestion.text.ilike(s), models.BankQuestion.subject.ilike(s), models.BankQuestion.topic.ilike(s)))
        if assessment_category:
            query = query.filter(models.BankQuestion.assessment_category == assessment_category)
        if subject:
            query = query.filter(models.BankQuestion.subject == subject)
        if topic:
            query = query.filter(models.BankQuestion.topic == topic)
        if difficulty:
            query = query.filter(models.BankQuestion.difficulty == difficulty)
        if question_type:
            query = query.filter(models.BankQuestion.question_type == question_type)
        if status_filter:
            query = query.filter(models.BankQuestion.status == status_filter)

        total_count = query.count()

        sort_col = getattr(models.BankQuestion, sort_by, models.BankQuestion.id)
        query = query.order_by(desc(sort_col) if sort_order == "desc" else asc(sort_col))
        query = query.offset(skip).limit(limit)

        return query.all(), total_count

    @staticmethod
    def get_overview_counts(db: Session, current_user: models.User) -> Dict[str, int]:
        if is_candidate(current_user) and not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Candidates cannot access the Question Bank.")

        query = db.query(models.BankQuestion)
        if is_super_admin(current_user):
            pass
        elif is_org_admin(current_user):
            query = query.filter(models.BankQuestion.organization_id == current_user.organization_id)
        else:
            if current_user.organization_id is not None:
                query = query.filter(models.BankQuestion.organization_id == current_user.organization_id)
            else:
                query = query.filter(
                    or_(
                        models.BankQuestion.created_by == current_user.id,
                        models.BankQuestion.organization_id.is_(None)
                    )
                )

        all_qs = query.all()
        return {
            "total": len(all_qs),
            "published": sum(1 for q in all_qs if q.status == "published"),
            "draft": sum(1 for q in all_qs if q.status == "draft"),
            "reviewed": sum(1 for q in all_qs if q.status == "reviewed"),
            "archived": sum(1 for q in all_qs if q.status == "archived")
        }

    @staticmethod
    def update_question(db: Session, question_id: int, data: BankQuestionUpdate, current_user: models.User) -> models.BankQuestion:
        q = QuestionBankService.get_question(db, question_id, current_user)

        if not (is_super_admin(current_user) or is_org_admin(current_user)):
            if q.created_by != current_user.id:
                raise HTTPException(status_code=403, detail="You can only update questions you created.")

        QuestionBankService.validate_question_data(data, is_update=True)

        if data.text is not None:
            q.text = data.text.strip()
        if data.question_type is not None:
            q.question_type = data.question_type
        if data.assessment_category is not None:
            q.assessment_category = data.assessment_category
        if data.subject is not None:
            q.subject = data.subject.strip()
        if data.topic is not None:
            q.topic = data.topic.strip()
        if data.subtopic is not None:
            q.subtopic = data.subtopic.strip()
        if data.difficulty is not None:
            q.difficulty = data.difficulty
        if data.default_marks is not None:
            q.default_marks = data.default_marks
        if data.default_negative_marks is not None:
            q.default_negative_marks = data.default_negative_marks
        if data.explanation is not None:
            q.explanation = data.explanation
        if data.tags is not None:
            q.tags = json.dumps(data.tags)
        if data.status is not None:
            q.status = data.status
        if data.type_config is not None:
            q.type_config = json.dumps(data.type_config)

        if data.options is not None:
            # Replace options
            db.query(models.BankOption).filter(models.BankOption.question_id == q.id).delete()
            for idx, opt_in in enumerate(data.options):
                opt = models.BankOption(
                    question_id=q.id,
                    text=opt_in.text.strip(),
                    is_correct=opt_in.is_correct,
                    explanation=opt_in.explanation,
                    order_index=opt_in.order_index if opt_in.order_index else idx
                )
                db.add(opt)

        db.commit()
        db.refresh(q)
        return q

    @staticmethod
    def archive_question(db: Session, question_id: int, current_user: models.User) -> models.BankQuestion:
        q = QuestionBankService.get_question(db, question_id, current_user)
        q.status = "archived"
        db.commit()
        db.refresh(q)
        return q

    @staticmethod
    def delete_question(db: Session, question_id: int, current_user: models.User) -> None:
        q = QuestionBankService.get_question(db, question_id, current_user)
        if not (is_super_admin(current_user) or is_org_admin(current_user)):
            if q.created_by != current_user.id:
                raise HTTPException(status_code=403, detail="You can only delete questions you created.")
        db.delete(q)
        db.commit()

    # =========================================================================
    # 2. BULK QUESTION IMPORT (JSON & CSV)
    # =========================================================================
    @staticmethod
    def import_questions_from_json(
        db: Session,
        items: List[Dict[str, Any]],
        current_user: models.User,
        preview: bool = True
    ) -> QuestionImportResponse:
        errors: List[ImportRowError] = []
        valid_questions: List[Dict[str, Any]] = []
        duplicate_count = 0

        target_org_id = current_user.organization_id

        for idx, item in enumerate(items, start=1):
            text = (item.get("text") or "").strip()
            if not text:
                errors.append(ImportRowError(row_number=idx, error="Question text is missing."))
                continue

            # Duplicate check by text within organization
            dup_query = db.query(models.BankQuestion).filter(
                models.BankQuestion.text == text
            )
            if target_org_id is not None:
                dup_query = dup_query.filter(models.BankQuestion.organization_id == target_org_id)
            if dup_query.first():
                duplicate_count += 1
                errors.append(ImportRowError(row_number=idx, question_text=text[:50], error="Duplicate question text in organization."))
                continue

            q_type = item.get("question_type", "single_choice")
            if q_type not in SUPPORTED_QUESTION_TYPES:
                errors.append(ImportRowError(row_number=idx, question_text=text[:50], error=f"Invalid question_type '{q_type}'."))
                continue

            subject = (item.get("subject") or "General").strip()
            topic = (item.get("topic") or "General").strip()

            options = item.get("options", [])
            correct_count = sum(1 for o in options if o.get("is_correct"))

            if q_type == "single_choice":
                if len(options) < 2:
                    errors.append(ImportRowError(row_number=idx, question_text=text[:50], error="Single-choice requires at least 2 options."))
                    continue
                if correct_count != 1:
                    errors.append(ImportRowError(row_number=idx, question_text=text[:50], error=f"Single-choice must have exactly 1 correct answer (found {correct_count})."))
                    continue
            elif q_type == "multiple_choice":
                if len(options) < 2:
                    errors.append(ImportRowError(row_number=idx, question_text=text[:50], error="Multiple-choice requires at least 2 options."))
                    continue
                if correct_count < 1:
                    errors.append(ImportRowError(row_number=idx, question_text=text[:50], error="Multiple-choice requires at least 1 correct answer."))
                    continue
            elif q_type == "true_false":
                if len(options) != 2:
                    errors.append(ImportRowError(row_number=idx, question_text=text[:50], error="True/False must have exactly 2 options."))
                    continue
                if correct_count != 1:
                    errors.append(ImportRowError(row_number=idx, question_text=text[:50], error="True/False must have exactly 1 correct answer."))
                    continue

            valid_questions.append(item)

        imported_count = 0
        if not preview and valid_questions:
            try:
                for v in valid_questions:
                    tags_val = json.dumps(v.get("tags")) if v.get("tags") else None
                    conf_val = json.dumps(v.get("type_config")) if v.get("type_config") else None
                    q = models.BankQuestion(
                        text=v["text"].strip(),
                        question_type=v.get("question_type", "single_choice"),
                        assessment_category=v.get("assessment_category", "academic"),
                        subject=v["subject"].strip(),
                        topic=v["topic"].strip(),
                        subtopic=v.get("subtopic"),
                        difficulty=v.get("difficulty", "medium"),
                        default_marks=float(v.get("marks", 1.0)),
                        default_negative_marks=float(v.get("negative_marks", 0.0)),
                        explanation=v.get("explanation"),
                        tags=tags_val,
                        organization_id=target_org_id,
                        created_by=current_user.id,
                        status="published",
                        type_config=conf_val
                    )
                    db.add(q)
                    db.flush()

                    for idx, opt in enumerate(v.get("options", [])):
                        bo = models.BankOption(
                            question_id=q.id,
                            text=opt["text"].strip(),
                            is_correct=bool(opt.get("is_correct", False)),
                            explanation=opt.get("explanation"),
                            order_index=idx
                        )
                        db.add(bo)
                db.commit()
                imported_count = len(valid_questions)
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=500, detail=f"Database error during import: {str(e)}")

        return QuestionImportResponse(
            success=len(errors) == 0,
            is_preview=preview,
            total_rows=len(items),
            valid_count=len(valid_questions),
            error_count=len(errors),
            duplicate_count=duplicate_count,
            imported_count=imported_count,
            errors=errors,
            preview_questions=valid_questions[:10] if preview else []
        )

    @staticmethod
    def import_questions_from_csv(
        db: Session,
        csv_content: str,
        current_user: models.User,
        preview: bool = True
    ) -> QuestionImportResponse:
        f = io.StringIO(csv_content)
        reader = csv.DictReader(f)

        rows: List[Dict[str, Any]] = []
        for r in reader:
            # Map standard CSV fields:
            options = []
            if r.get("options") and "|" in r["options"]:
                for opt_text in r["options"].split("|"):
                    if opt_text.strip():
                        options.append({"text": opt_text.strip(), "is_correct": False})
            else:
                for i in range(1, 7):
                    opt_key = f"option_{i}"
                    if r.get(opt_key) and r[opt_key].strip():
                        options.append({"text": r[opt_key].strip(), "is_correct": False})

            # Parse correct option: e.g. "1" or "1,2" or "A" or text
            correct_raw = (r.get("correct_option") or r.get("correct_options") or "").strip().lower()
            correct_indices = set()
            for part in correct_raw.split(","):
                part = part.strip()
                if part.isdigit():
                    correct_indices.add(int(part) - 1)
                elif part in ("a", "b", "c", "d", "e", "f"):
                    correct_indices.add(ord(part) - ord("a"))

            for idx, opt in enumerate(options):
                if idx in correct_indices:
                    opt["is_correct"] = True

            marks_val = r.get("marks") or r.get("default_marks")
            neg_marks_val = r.get("negative_marks") or r.get("default_negative_marks")

            rows.append({
                "text": r.get("text", ""),
                "question_type": r.get("question_type", "single_choice").strip(),
                "assessment_category": r.get("assessment_category", "academic").strip(),
                "subject": (r.get("subject") or "General").strip(),
                "topic": (r.get("topic") or "General").strip(),
                "subtopic": r.get("subtopic", "").strip() or None,
                "difficulty": r.get("difficulty", "medium").strip(),
                "marks": float(marks_val) if marks_val else 1.0,
                "negative_marks": float(neg_marks_val) if neg_marks_val else 0.0,
                "explanation": r.get("explanation"),
                "tags": [t.strip() for t in r.get("tags", "").split(",") if t.strip()],
                "options": options
            })

        return QuestionBankService.import_questions_from_json(db, rows, current_user, preview=preview)

    @staticmethod
    def get_sample_csv_template() -> str:
        return (
            "text,question_type,assessment_category,subject,topic,subtopic,difficulty,marks,negative_marks,explanation,option_1,option_2,option_3,option_4,correct_option,tags\n"
            "\"What is the time complexity of binary search?\",single_choice,technical,Computer Science,Algorithms,Searching,medium,2.0,0.5,\"Binary search cuts the search space in half each step.\",\"O(1)\",\"O(N)\",\"O(log N)\",\"O(N^2)\",3,\"algorithms,complexity\"\n"
            "\"Which of the following are prime numbers?\",multiple_choice,academic,Mathematics,Number Theory,Primes,medium,3.0,1.0,\"2, 3, and 5 are prime.\",\"2\",\"3\",\"4\",\"5\",\"1,2,4\",\"math,primes\"\n"
            "\"Python is a statically typed language.\",true_false,technical,Computer Science,Python,,easy,1.0,0.0,\"Python is dynamically typed.\",\"True\",\"False\",,2,\"python,basics\"\n"
        )

    @staticmethod
    def get_sample_json_template() -> List[Dict[str, Any]]:
        return [
            {
                "text": "What does ACID stand for in databases?",
                "question_type": "single_choice",
                "assessment_category": "technical",
                "subject": "Computer Science",
                "topic": "Databases",
                "difficulty": "medium",
                "marks": 2.0,
                "negative_marks": 0.5,
                "explanation": "Atomicity, Consistency, Isolation, Durability",
                "tags": ["db", "rdbms"],
                "options": [
                    {"text": "Atomicity, Consistency, Isolation, Durability", "is_correct": True},
                    {"text": "Accuracy, Completeness, Integrity, Durability", "is_correct": False},
                    {"text": "Atomicity, Concurrency, Isolation, Durability", "is_correct": False}
                ]
            }
        ]

    # =========================================================================
    # 3. ASSESSMENT QUESTION MAPPING
    # =========================================================================
    @staticmethod
    def map_questions_to_assessment(
        db: Session,
        assessment_id: int,
        req: AssessmentQuestionMapRequest,
        current_user: models.User
    ) -> AssessmentQuestionsListResponse:
        exam = db.query(models.Exam).filter(models.Exam.id == assessment_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found.")

        enforce_org_access(current_user, exam.organization_id, resource_name="assessment")

        # Verify examiner authorization
        if not (is_super_admin(current_user) or is_org_admin(current_user)):
            if exam.creator_id != current_user.id:
                raise HTTPException(status_code=403, detail="You can only map questions to assessments you manage.")

        mapped_results: List[models.AssessmentQuestionMap] = []

        for item in req.questions:
            bank_q = db.query(models.BankQuestion).filter(models.BankQuestion.id == item.bank_question_id).first()
            if not bank_q:
                raise HTTPException(status_code=404, detail=f"Bank question {item.bank_question_id} not found.")

            # Validate organization boundary
            enforce_org_access(current_user, bank_q.organization_id, resource_name="question")

            # Check duplicate mapping
            existing = db.query(models.AssessmentQuestionMap).filter(
                models.AssessmentQuestionMap.assessment_id == exam.id,
                models.AssessmentQuestionMap.bank_question_id == bank_q.id
            ).first()

            assigned_marks = item.marks if item.marks is not None else bank_q.default_marks
            assigned_neg = item.negative_marks if item.negative_marks is not None else bank_q.default_negative_marks

            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Bank question {bank_q.id} is already mapped to this assessment."
                )

            mapping = models.AssessmentQuestionMap(
                assessment_id=exam.id,
                bank_question_id=bank_q.id,
                order_index=item.order_index or 0,
                marks=assigned_marks,
                negative_marks=assigned_neg
            )
            db.add(mapping)
            mapped_results.append(mapping)

            # Sync cloned question into exam.questions so exam engine runs directly
            cloned_q = models.Question(
                exam_id=exam.id,
                bank_question_id=bank_q.id,
                text=bank_q.text,
                marks=assigned_marks,
                negative_marks=assigned_neg,
                order_index=item.order_index or 0,
                question_type=bank_q.question_type,
                explanation=bank_q.explanation
            )
            db.add(cloned_q)
            db.flush()

            for opt in bank_q.options:
                cloned_opt = models.Option(
                    question_id=cloned_q.id,
                    text=opt.text,
                    is_correct=opt.is_correct
                )
                db.add(cloned_opt)

        db.commit()
        return QuestionBankService.list_assessment_questions(db, assessment_id, current_user)

    @staticmethod
    def remove_question_from_assessment(
        db: Session,
        assessment_id: int,
        bank_question_id: int,
        current_user: models.User
    ) -> None:
        exam = db.query(models.Exam).filter(models.Exam.id == assessment_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found.")

        enforce_org_access(current_user, exam.organization_id, resource_name="assessment")

        # Delete mapping
        db.query(models.AssessmentQuestionMap).filter(
            models.AssessmentQuestionMap.assessment_id == exam.id,
            models.AssessmentQuestionMap.bank_question_id == bank_question_id
        ).delete()

        # Delete synced question in exam.questions
        db.query(models.Question).filter(
            models.Question.exam_id == exam.id,
            models.Question.bank_question_id == bank_question_id
        ).delete()

        db.commit()

    @staticmethod
    def reorder_assessment_questions(
        db: Session,
        assessment_id: int,
        req: AssessmentQuestionReorderRequest,
        current_user: models.User
    ) -> AssessmentQuestionsListResponse:
        exam = db.query(models.Exam).filter(models.Exam.id == assessment_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found.")

        enforce_org_access(current_user, exam.organization_id, resource_name="assessment")

        for item in req.reorder_list:
            db.query(models.AssessmentQuestionMap).filter(
                models.AssessmentQuestionMap.assessment_id == exam.id,
                models.AssessmentQuestionMap.bank_question_id == item.bank_question_id
            ).update({"order_index": item.order_index})

            db.query(models.Question).filter(
                models.Question.exam_id == exam.id,
                models.Question.bank_question_id == item.bank_question_id
            ).update({"order_index": item.order_index})

        db.commit()
        return QuestionBankService.list_assessment_questions(db, assessment_id, current_user)

    @staticmethod
    def list_assessment_questions(
        db: Session,
        assessment_id: int,
        current_user: models.User
    ) -> AssessmentQuestionsListResponse:
        exam = db.query(models.Exam).filter(models.Exam.id == assessment_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found.")

        enforce_org_access(current_user, exam.organization_id, resource_name="assessment")

        mappings = db.query(models.AssessmentQuestionMap).filter(
            models.AssessmentQuestionMap.assessment_id == exam.id
        ).order_by(models.AssessmentQuestionMap.order_index.asc()).all()

        total_marks = sum((m.marks or 0.0) for m in mappings)

        out_list = []
        for m in mappings:
            q_out = BankQuestionOut.from_model(m.bank_question) if m.bank_question else None
            out_list.append(AssessmentQuestionMapOut(
                id=m.id,
                assessment_id=m.assessment_id,
                bank_question_id=m.bank_question_id,
                order_index=m.order_index,
                marks=m.marks or 1.0,
                negative_marks=m.negative_marks or 0.0,
                created_at=m.created_at,
                question=q_out
            ))

        return AssessmentQuestionsListResponse(
            assessment_id=exam.id,
            assessment_title=exam.title,
            total_questions=len(mappings),
            total_max_marks=total_marks,
            questions=out_list
        )
