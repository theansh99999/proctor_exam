"""
modules/assessments/blueprints.py
---------------------------------
Assessment Blueprint Engine for Phase 11:
- Rule-based question selection specification
- Difficulty distribution (easy, medium, hard)
- Subject, topic, and question-type filtering
- Question Bank availability validation with detailed deficit reporting
- Question generation and materialization into assessments
- Multi-tenant organization isolation
"""
import json
import random
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from fastapi import HTTPException, status
from pydantic import BaseModel, Field

import models
from time_utils import utc_now
from core.rbac import (
    is_super_admin,
    is_org_admin,
    enforce_org_access
)


# =============================================================================
# SCHEMAS
# =============================================================================

class BlueprintCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = None
    assessment_type: str = Field("academic", description="academic, placement, technical, custom")
    subject: str = Field(..., min_length=1, max_length=100)
    topics: Optional[List[str]] = None
    question_types: Optional[List[str]] = None
    difficulty_distribution: Dict[str, int] = Field(..., description="e.g. {'easy': 5, 'medium': 10, 'hard': 5}")
    total_questions: Optional[int] = None
    total_marks: Optional[float] = 0.0
    section_mapping: Optional[List[Dict[str, Any]]] = None
    negative_marking_rules: Optional[Dict[str, Any]] = None
    selection_constraints: Optional[Dict[str, Any]] = None
    organization_id: Optional[int] = None

class BlueprintUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assessment_type: Optional[str] = None
    subject: Optional[str] = None
    topics: Optional[List[str]] = None
    question_types: Optional[List[str]] = None
    difficulty_distribution: Optional[Dict[str, int]] = None
    total_marks: Optional[float] = None
    section_mapping: Optional[List[Dict[str, Any]]] = None
    negative_marking_rules: Optional[Dict[str, Any]] = None
    selection_constraints: Optional[Dict[str, Any]] = None

class BlueprintValidationResult(BaseModel):
    is_valid: bool
    total_required: int
    total_available: int
    by_difficulty: Dict[str, Dict[str, int]]
    by_topic: Dict[str, Dict[str, int]]
    errors: List[str]

class BlueprintOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    assessment_type: str
    subject: str
    topics: Optional[List[str]] = None
    question_types: Optional[List[str]] = None
    difficulty_distribution: Optional[Dict[str, int]] = None
    total_questions: int
    total_marks: float
    section_mapping: Optional[List[Dict[str, Any]]] = None
    negative_marking_rules: Optional[Dict[str, Any]] = None
    selection_constraints: Optional[Dict[str, Any]] = None
    organization_id: Optional[int] = None
    created_by: Optional[int] = None
    is_archived: bool
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, bp: models.AssessmentBlueprint) -> "BlueprintOut":
        def _parse(val):
            if val is None:
                return None
            if isinstance(val, (dict, list)):
                return val
            try:
                return json.loads(val)
            except Exception:
                return None

        return cls(
            id=bp.id,
            title=bp.title,
            description=bp.description,
            assessment_type=bp.assessment_type or "academic",
            subject=bp.subject,
            topics=_parse(bp.topics),
            question_types=_parse(bp.question_types),
            difficulty_distribution=_parse(bp.difficulty_distribution),
            total_questions=bp.total_questions or 0,
            total_marks=bp.total_marks or 0.0,
            section_mapping=_parse(bp.section_mapping),
            negative_marking_rules=_parse(bp.negative_marking_rules),
            selection_constraints=_parse(bp.selection_constraints),
            organization_id=bp.organization_id,
            created_by=bp.created_by,
            is_archived=bool(bp.is_archived),
            created_at=bp.created_at,
            updated_at=bp.updated_at
        )


# =============================================================================
# BLUEPRINT SERVICE
# =============================================================================

class BlueprintService:

    @staticmethod
    def create_blueprint(db: Session, data: BlueprintCreate, current_user: models.User) -> models.AssessmentBlueprint:
        # Org isolation
        if is_super_admin(current_user):
            target_org_id = data.organization_id
        elif is_org_admin(current_user):
            target_org_id = current_user.organization_id
        else:
            target_org_id = current_user.organization_id

        # Calculate total questions from distribution
        total_q = sum(max(0, count) for count in data.difficulty_distribution.values())
        if total_q <= 0:
            raise HTTPException(status_code=400, detail="Difficulty distribution must require at least 1 question.")

        bp = models.AssessmentBlueprint(
            title=data.title.strip(),
            description=data.description,
            assessment_type=data.assessment_type,
            subject=data.subject.strip(),
            topics=json.dumps(data.topics) if data.topics else None,
            question_types=json.dumps(data.question_types) if data.question_types else None,
            difficulty_distribution=json.dumps(data.difficulty_distribution),
            total_questions=total_q,
            total_marks=data.total_marks or float(total_q),
            section_mapping=json.dumps(data.section_mapping) if data.section_mapping else None,
            negative_marking_rules=json.dumps(data.negative_marking_rules) if data.negative_marking_rules else None,
            selection_constraints=json.dumps(data.selection_constraints) if data.selection_constraints else None,
            organization_id=target_org_id,
            created_by=current_user.id,
            is_archived=False,
            created_at=utc_now(),
            updated_at=utc_now()
        )
        db.add(bp)
        db.commit()
        db.refresh(bp)
        return bp

    @staticmethod
    def get_blueprint(db: Session, blueprint_id: int, current_user: models.User) -> models.AssessmentBlueprint:
        bp = db.query(models.AssessmentBlueprint).filter_by(id=blueprint_id).first()
        if not bp:
            raise HTTPException(status_code=404, detail="Assessment blueprint not found.")
        enforce_org_access(current_user, bp.organization_id, resource_name="blueprint")
        return bp

    @staticmethod
    def list_blueprints(
        db: Session,
        current_user: models.User,
        subject: Optional[str] = None,
        org_id: Optional[int] = None
    ) -> List[models.AssessmentBlueprint]:
        query = db.query(models.AssessmentBlueprint).filter(models.AssessmentBlueprint.is_archived == False)

        if is_super_admin(current_user):
            if org_id is not None:
                query = query.filter(models.AssessmentBlueprint.organization_id == org_id)
        elif is_org_admin(current_user):
            query = query.filter(
                or_(
                    models.AssessmentBlueprint.organization_id == current_user.organization_id,
                    models.AssessmentBlueprint.organization_id.is_(None)
                )
            )
        else:
            query = query.filter(
                or_(
                    models.AssessmentBlueprint.organization_id == current_user.organization_id,
                    models.AssessmentBlueprint.created_by == current_user.id,
                    models.AssessmentBlueprint.organization_id.is_(None)
                )
            )

        if subject:
            query = query.filter(func.lower(models.AssessmentBlueprint.subject) == subject.strip().lower())

        return query.order_by(models.AssessmentBlueprint.title).all()

    @staticmethod
    def update_blueprint(
        db: Session,
        blueprint_id: int,
        data: BlueprintUpdate,
        current_user: models.User
    ) -> models.AssessmentBlueprint:
        bp = BlueprintService.get_blueprint(db, blueprint_id, current_user)

        if data.title is not None:
            bp.title = data.title.strip()
        if data.description is not None:
            bp.description = data.description
        if data.assessment_type is not None:
            bp.assessment_type = data.assessment_type
        if data.subject is not None:
            bp.subject = data.subject.strip()
        if data.topics is not None:
            bp.topics = json.dumps(data.topics)
        if data.question_types is not None:
            bp.question_types = json.dumps(data.question_types)
        if data.difficulty_distribution is not None:
            bp.difficulty_distribution = json.dumps(data.difficulty_distribution)
            bp.total_questions = sum(max(0, count) for count in data.difficulty_distribution.values())
        if data.total_marks is not None:
            bp.total_marks = data.total_marks
        if data.section_mapping is not None:
            bp.section_mapping = json.dumps(data.section_mapping)
        if data.negative_marking_rules is not None:
            bp.negative_marking_rules = json.dumps(data.negative_marking_rules)
        if data.selection_constraints is not None:
            bp.selection_constraints = json.dumps(data.selection_constraints)

        bp.updated_at = utc_now()
        db.commit()
        db.refresh(bp)
        return bp

    @staticmethod
    def archive_blueprint(db: Session, blueprint_id: int, current_user: models.User) -> models.AssessmentBlueprint:
        bp = BlueprintService.get_blueprint(db, blueprint_id, current_user)
        bp.is_archived = True
        bp.updated_at = utc_now()
        db.commit()
        db.refresh(bp)
        return bp

    @staticmethod
    def validate_blueprint(
        db: Session,
        blueprint_id: int,
        current_user: models.User,
        target_org_id: Optional[int] = None
    ) -> BlueprintValidationResult:
        """
        Validates if the Question Bank contains sufficient eligible questions
        to satisfy the blueprint requirements.
        Returns clear deficits per difficulty level and topic.
        """
        bp = BlueprintService.get_blueprint(db, blueprint_id, current_user)
        effective_org_id = target_org_id or bp.organization_id or current_user.organization_id

        diff_dist = json.loads(bp.difficulty_distribution) if bp.difficulty_distribution else {}
        topics_req = json.loads(bp.topics) if bp.topics else []
        types_req = json.loads(bp.question_types) if bp.question_types else []

        errors = []
        by_diff = {}
        by_topic = {}
        total_req = sum(diff_dist.values())
        total_avail = 0

        # Base Bank Question Query
        base_query = db.query(models.BankQuestion).filter(
            models.BankQuestion.status.in_(["published", "reviewed", "draft"]),
            func.lower(models.BankQuestion.subject) == bp.subject.lower()
        )
        if effective_org_id is not None:
            base_query = base_query.filter(
                or_(
                    models.BankQuestion.organization_id == effective_org_id,
                    models.BankQuestion.organization_id.is_(None)
                )
            )

        if types_req:
            base_query = base_query.filter(models.BankQuestion.question_type.in_(types_req))

        # Check by difficulty
        for diff, req_count in diff_dist.items():
            avail_count = base_query.filter(func.lower(models.BankQuestion.difficulty) == diff.lower()).count()
            deficit = max(0, req_count - avail_count)
            by_diff[diff] = {"required": req_count, "available": avail_count, "deficit": deficit}
            total_avail += avail_count
            if avail_count < req_count:
                errors.append(
                    f"Insufficient '{diff}' questions for subject '{bp.subject}': required {req_count}, available {avail_count} (deficit: {deficit})"
                )

        # Check by topic if specified
        if topics_req:
            for top in topics_req:
                t_count = base_query.filter(func.lower(models.BankQuestion.topic) == top.lower()).count()
                by_topic[top] = {"required": 1, "available": t_count}
                if t_count == 0:
                    errors.append(f"Question Bank has 0 eligible questions for requested topic '{top}'.")

        is_valid = (len(errors) == 0)
        return BlueprintValidationResult(
            is_valid=is_valid,
            total_required=total_req,
            total_available=total_avail,
            by_difficulty=by_diff,
            by_topic=by_topic,
            errors=errors
        )

    @staticmethod
    def generate_questions_from_blueprint(
        db: Session,
        blueprint: models.AssessmentBlueprint,
        exam: models.Exam,
        current_user: models.User
    ) -> List[models.Question]:
        """
        Materializes questions from Question Bank into the assessment according to blueprint specifications.
        Prevents duplicate questions.
        """
        val = BlueprintService.validate_blueprint(db, blueprint.id, current_user, target_org_id=exam.organization_id)
        if not val.is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot generate questions: blueprint validation failed. Errors: {'; '.join(val.errors)}"
            )

        diff_dist = json.loads(blueprint.difficulty_distribution) if blueprint.difficulty_distribution else {}
        topics_req = json.loads(blueprint.topics) if blueprint.topics else []
        types_req = json.loads(blueprint.question_types) if blueprint.question_types else []
        constraints = json.loads(blueprint.selection_constraints) if blueprint.selection_constraints else {}

        selected_bank_ids = set()
        materialized_questions = []

        # 1. Check if fixed bank question IDs are specified in constraints
        fixed_ids = constraints.get("fixed_question_ids", [])
        if fixed_ids:
            fixed_qs = db.query(models.BankQuestion).filter(models.BankQuestion.id.in_(fixed_ids)).all()
            for bq in fixed_qs:
                selected_bank_ids.add(bq.id)
                q_inst = BlueprintService._copy_bank_question_to_exam(db, bq, exam, is_fixed=True)
                materialized_questions.append(q_inst)

        # 2. Select remaining questions for each difficulty level
        for diff, req_count in diff_dist.items():
            # Account for any fixed questions already chosen at this difficulty
            fixed_at_diff = sum(1 for q in materialized_questions if getattr(q, "_diff", None) == diff.lower())
            needed = max(0, req_count - fixed_at_diff)
            if needed == 0:
                continue

            query = db.query(models.BankQuestion).filter(
                models.BankQuestion.status.in_(["published", "reviewed", "draft"]),
                func.lower(models.BankQuestion.subject) == blueprint.subject.lower(),
                func.lower(models.BankQuestion.difficulty) == diff.lower(),
                ~models.BankQuestion.id.in_(selected_bank_ids) if selected_bank_ids else True
            )

            if exam.organization_id is not None:
                query = query.filter(
                    or_(
                        models.BankQuestion.organization_id == exam.organization_id,
                        models.BankQuestion.organization_id.is_(None)
                    )
                )

            if topics_req:
                query = query.filter(models.BankQuestion.topic.in_(topics_req))
            if types_req:
                query = query.filter(models.BankQuestion.question_type.in_(types_req))

            eligible_pool = query.all()
            sampled = random.sample(eligible_pool, min(needed, len(eligible_pool)))

            for bq in sampled:
                selected_bank_ids.add(bq.id)
                q_inst = BlueprintService._copy_bank_question_to_exam(db, bq, exam, is_fixed=False)
                materialized_questions.append(q_inst)

        # Set order index on questions
        for idx, q in enumerate(materialized_questions, start=1):
            q.order_index = idx

        db.commit()
        return materialized_questions

    @staticmethod
    def materialize_assessment_questions(
        db: Session,
        blueprint_id: int,
        assessment_id: int,
        current_user: models.User
    ) -> Dict[str, Any]:
        bp = BlueprintService.get_blueprint(db, blueprint_id, current_user)
        exam = db.query(models.Exam).filter(models.Exam.id == assessment_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found")
        created_qs = BlueprintService.generate_questions_from_blueprint(db, bp, exam, current_user)
        # Create AssessmentQuestionMap entries for mapped questions
        for q in created_qs:
            if q.bank_question_id:
                existing_map = db.query(models.AssessmentQuestionMap).filter(
                    models.AssessmentQuestionMap.assessment_id == exam.id,
                    models.AssessmentQuestionMap.bank_question_id == q.bank_question_id
                ).first()
                if not existing_map:
                    aqm = models.AssessmentQuestionMap(
                        assessment_id=exam.id,
                        bank_question_id=q.bank_question_id,
                        order_index=q.order_index,
                        marks=q.marks
                    )
                    db.add(aqm)
        db.commit()
        return {
            "assessment_id": exam.id,
            "blueprint_id": bp.id,
            "questions_generated": len(created_qs)
        }

    @staticmethod
    def _copy_bank_question_to_exam(
        db: Session,
        bank_q: models.BankQuestion,
        exam: models.Exam,
        is_fixed: bool = False
    ) -> models.Question:
        q = models.Question(
            exam_id=exam.id,
            bank_question_id=bank_q.id,
            text=bank_q.text,
            question_type=bank_q.question_type,
            explanation=bank_q.explanation,
            marks=bank_q.default_marks if bank_q.default_marks is not None else exam.default_marks,
            negative_marks=bank_q.default_negative_marks if bank_q.default_negative_marks is not None else exam.default_negative_marks,
            type_config=bank_q.type_config,
            is_mandatory=is_fixed
        )
        q._diff = bank_q.difficulty.lower() if bank_q.difficulty else "medium"
        db.add(q)
        db.flush()

        # Copy options
        for bo in bank_q.options:
            opt = models.Option(
                question_id=q.id,
                text=bo.text,
                is_correct=bo.is_correct
            )
            db.add(opt)

        db.flush()
        return q
