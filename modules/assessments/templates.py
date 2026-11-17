"""
modules/assessments/templates.py
---------------------------------
Service and schemas for Reusable Assessment Templates:
- Standard assessment configuration templates
- Organization-specific vs Platform-wide (System) templates
- Duplication and archiving
- Template-to-Assessment cloning (decoupled instantiation)
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import json
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
from fastapi import HTTPException, status

import models
from core.rbac import (
    is_super_admin,
    is_org_admin,
    is_examiner_or_admin,
    verify_org_access
)
from time_utils import utc_now, to_utc


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class TemplateBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    assessment_type: str = Field("academic", description="academic, placement, technical, custom")
    duration_minutes: int = Field(60, gt=0)
    timer_type: str = Field("overall", description="overall or per_question")
    default_marks: float = 1.0
    default_negative_marks: float = 0.0
    enable_negative_marking: bool = False
    randomize_questions: bool = False
    randomize_options: bool = False
    passing_marks: float = 0.0
    passing_criteria: str = Field("marks", description="marks or percentage")
    passing_percentage: Optional[float] = None
    max_attempts: int = Field(1, ge=1)
    is_adaptive: bool = False
    adaptive_config: Optional[Dict[str, Any]] = None
    attempt_policy: Optional[Dict[str, Any]] = None
    blueprint_id: Optional[int] = None
    config_metadata: Optional[Dict[str, Any]] = None
    section_config: Optional[List[Dict[str, Any]]] = None
    is_system: bool = False


class TemplateCreate(TemplateBase):
    organization_id: Optional[int] = None


class TemplateUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assessment_type: Optional[str] = None
    duration_minutes: Optional[int] = None
    timer_type: Optional[str] = None
    default_marks: Optional[float] = None
    default_negative_marks: Optional[float] = None
    enable_negative_marking: Optional[bool] = None
    randomize_questions: Optional[bool] = None
    randomize_options: Optional[bool] = None
    passing_marks: Optional[float] = None
    passing_criteria: Optional[str] = None
    passing_percentage: Optional[float] = None
    max_attempts: Optional[int] = None
    is_adaptive: Optional[bool] = None
    adaptive_config: Optional[Dict[str, Any]] = None
    attempt_policy: Optional[Dict[str, Any]] = None
    blueprint_id: Optional[int] = None
    config_metadata: Optional[Dict[str, Any]] = None
    section_config: Optional[List[Dict[str, Any]]] = None
    is_system: Optional[bool] = None


class TemplateOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    assessment_type: str
    duration_minutes: int
    timer_type: str
    default_marks: float
    default_negative_marks: float
    enable_negative_marking: bool
    randomize_questions: bool
    randomize_options: bool
    passing_marks: float
    passing_criteria: str
    passing_percentage: Optional[float] = None
    max_attempts: int
    is_adaptive: bool
    adaptive_config: Optional[Dict[str, Any]] = None
    attempt_policy: Optional[Dict[str, Any]] = None
    blueprint_id: Optional[int] = None
    config_metadata: Optional[Dict[str, Any]] = None
    section_config: Optional[List[Dict[str, Any]]] = None
    is_system: bool
    is_archived: bool
    organization_id: Optional[int] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, t: models.AssessmentTemplate) -> "TemplateOut":
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
            id=t.id,
            title=t.title,
            description=t.description,
            assessment_type=t.assessment_type or "academic",
            duration_minutes=t.duration_minutes or 60,
            timer_type=t.timer_type or "overall",
            default_marks=t.default_marks or 1.0,
            default_negative_marks=t.default_negative_marks or 0.0,
            enable_negative_marking=bool(t.enable_negative_marking),
            randomize_questions=bool(t.randomize_questions),
            randomize_options=bool(t.randomize_options),
            passing_marks=t.passing_marks or 0.0,
            passing_criteria=t.passing_criteria or "marks",
            passing_percentage=t.passing_percentage,
            max_attempts=t.max_attempts or 1,
            is_adaptive=bool(t.is_adaptive),
            adaptive_config=_parse(t.adaptive_config),
            attempt_policy=_parse(t.attempt_policy),
            blueprint_id=t.blueprint_id,
            config_metadata=_parse(t.config_metadata),
            section_config=_parse(t.section_config),
            is_system=bool(t.is_system),
            is_archived=bool(t.is_archived),
            organization_id=t.organization_id,
            created_by=t.created_by,
            created_at=t.created_at,
            updated_at=t.updated_at
        )


class CreateAssessmentFromTemplateRequest(BaseModel):
    title: Optional[str] = None
    start_time: datetime
    end_time: datetime
    group_id: Optional[int] = None
    visibility: str = Field("group_only", description="public, private, group_only")
    generate_blueprint_questions: bool = True


# ── Template Service ──────────────────────────────────────────────────────────

class TemplateService:

    @staticmethod
    def create_template(db: Session, data: TemplateCreate, current_user: models.User) -> models.AssessmentTemplate:
        if not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Permission denied to create assessment templates.")

        # System templates can only be created by Super Admins
        is_system = False
        if data.is_system:
            if not is_super_admin(current_user):
                raise HTTPException(status_code=403, detail="Only Super Admins can create platform-wide system templates.")
            is_system = True

        target_org_id = None
        if not is_system:
            if is_super_admin(current_user):
                target_org_id = data.organization_id
            else:
                target_org_id = current_user.organization_id

        # Verify blueprint if provided
        if data.blueprint_id:
            bp = db.query(models.AssessmentBlueprint).filter(models.AssessmentBlueprint.id == data.blueprint_id).first()
            if not bp or bp.is_archived:
                raise HTTPException(status_code=400, detail="Referenced blueprint not found or is archived.")
            if not is_system and target_org_id and bp.organization_id and bp.organization_id != target_org_id:
                raise HTTPException(status_code=403, detail="Blueprint belongs to another organization.")

        def _dump(val):
            return json.dumps(val) if val is not None else None

        template = models.AssessmentTemplate(
            title=data.title.strip(),
            description=data.description,
            assessment_type=data.assessment_type,
            organization_id=target_org_id,
            created_by=current_user.id,
            is_system=is_system,
            is_archived=False,
            duration_minutes=data.duration_minutes,
            timer_type=data.timer_type,
            default_marks=data.default_marks,
            default_negative_marks=data.default_negative_marks,
            enable_negative_marking=data.enable_negative_marking,
            randomize_questions=data.randomize_questions,
            randomize_options=data.randomize_options,
            passing_marks=data.passing_marks,
            passing_criteria=data.passing_criteria,
            passing_percentage=data.passing_percentage,
            max_attempts=data.max_attempts,
            is_adaptive=data.is_adaptive,
            adaptive_config=_dump(data.adaptive_config),
            attempt_policy=_dump(data.attempt_policy),
            blueprint_id=data.blueprint_id,
            config_metadata=_dump(data.config_metadata),
            section_config=_dump(data.section_config)
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        return template

    @staticmethod
    def get_template(db: Session, template_id: int, current_user: models.User) -> models.AssessmentTemplate:
        template = db.query(models.AssessmentTemplate).filter(models.AssessmentTemplate.id == template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Assessment template not found.")

        # Access check: system templates accessible to all examiners/admins.
        # Org templates accessible to same org members or super admin.
        if not template.is_system and not is_super_admin(current_user):
            if current_user.organization_id != template.organization_id:
                raise HTTPException(status_code=403, detail="Access denied to this template.")

        return template

    @staticmethod
    def list_templates(
        db: Session,
        current_user: models.User,
        assessment_type: Optional[str] = None,
        include_archived: bool = False
    ) -> List[models.AssessmentTemplate]:
        query = db.query(models.AssessmentTemplate)

        if not include_archived:
            query = query.filter(models.AssessmentTemplate.is_archived == False)

        if not is_super_admin(current_user):
            # Show system templates OR org templates matching user's org
            query = query.filter(
                or_(
                    models.AssessmentTemplate.is_system == True,
                    models.AssessmentTemplate.organization_id == current_user.organization_id
                )
            )

        if assessment_type:
            query = query.filter(models.AssessmentTemplate.assessment_type == assessment_type)

        return query.order_by(models.AssessmentTemplate.is_system.desc(), desc(models.AssessmentTemplate.created_at)).all()

    @staticmethod
    def update_template(db: Session, template_id: int, data: TemplateUpdate, current_user: models.User) -> models.AssessmentTemplate:
        template = TemplateService.get_template(db, template_id, current_user)

        if template.is_system and not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Only Super Admins can update platform-wide system templates.")

        if not template.is_system and not is_super_admin(current_user):
            if not is_org_admin(current_user) and template.created_by != current_user.id:
                raise HTTPException(status_code=403, detail="Permission denied to update this template.")

        def _dump(val):
            return json.dumps(val) if val is not None else None

        if data.title is not None:
            template.title = data.title.strip()
        if data.description is not None:
            template.description = data.description
        if data.assessment_type is not None:
            template.assessment_type = data.assessment_type
        if data.duration_minutes is not None:
            template.duration_minutes = data.duration_minutes
        if data.timer_type is not None:
            template.timer_type = data.timer_type
        if data.default_marks is not None:
            template.default_marks = data.default_marks
        if data.default_negative_marks is not None:
            template.default_negative_marks = data.default_negative_marks
        if data.enable_negative_marking is not None:
            template.enable_negative_marking = data.enable_negative_marking
        if data.randomize_questions is not None:
            template.randomize_questions = data.randomize_questions
        if data.randomize_options is not None:
            template.randomize_options = data.randomize_options
        if data.passing_marks is not None:
            template.passing_marks = data.passing_marks
        if data.passing_criteria is not None:
            template.passing_criteria = data.passing_criteria
        if data.passing_percentage is not None:
            template.passing_percentage = data.passing_percentage
        if data.max_attempts is not None:
            template.max_attempts = data.max_attempts
        if data.is_adaptive is not None:
            template.is_adaptive = data.is_adaptive
        if data.adaptive_config is not None:
            template.adaptive_config = _dump(data.adaptive_config)
        if data.attempt_policy is not None:
            template.attempt_policy = _dump(data.attempt_policy)
        if data.blueprint_id is not None:
            template.blueprint_id = data.blueprint_id
        if data.config_metadata is not None:
            template.config_metadata = _dump(data.config_metadata)
        if data.section_config is not None:
            template.section_config = _dump(data.section_config)
        if data.is_system is not None and is_super_admin(current_user):
            template.is_system = data.is_system

        template.updated_at = utc_now()
        db.commit()
        db.refresh(template)
        return template

    @staticmethod
    def duplicate_template(db: Session, template_id: int, current_user: models.User) -> models.AssessmentTemplate:
        source = TemplateService.get_template(db, template_id, current_user)

        target_org_id = current_user.organization_id if not is_super_admin(current_user) else source.organization_id

        clone = models.AssessmentTemplate(
            title=f"{source.title} (Copy)",
            description=source.description,
            assessment_type=source.assessment_type,
            organization_id=target_org_id,
            created_by=current_user.id,
            is_system=False,  # Duplicates are default user/org owned
            is_archived=False,
            duration_minutes=source.duration_minutes,
            timer_type=source.timer_type,
            default_marks=source.default_marks,
            default_negative_marks=source.default_negative_marks,
            enable_negative_marking=source.enable_negative_marking,
            randomize_questions=source.randomize_questions,
            randomize_options=source.randomize_options,
            passing_marks=source.passing_marks,
            passing_criteria=source.passing_criteria,
            passing_percentage=source.passing_percentage,
            max_attempts=source.max_attempts,
            is_adaptive=source.is_adaptive,
            adaptive_config=source.adaptive_config,
            attempt_policy=source.attempt_policy,
            blueprint_id=source.blueprint_id,
            config_metadata=source.config_metadata,
            section_config=source.section_config
        )
        db.add(clone)
        db.commit()
        db.refresh(clone)
        return clone

    @staticmethod
    def archive_template(db: Session, template_id: int, current_user: models.User) -> models.AssessmentTemplate:
        template = TemplateService.get_template(db, template_id, current_user)
        if template.is_system and not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Only Super Admins can archive system templates.")
        if not template.is_system and not is_super_admin(current_user) and not is_org_admin(current_user):
            if template.created_by != current_user.id:
                raise HTTPException(status_code=403, detail="Permission denied to archive this template.")

        template.is_archived = True
        template.updated_at = utc_now()
        db.commit()
        db.refresh(template)
        return template

    @staticmethod
    def create_assessment_from_template(
        db: Session,
        template_id: int,
        req: CreateAssessmentFromTemplateRequest,
        current_user: models.User
    ) -> models.Exam:
        template = TemplateService.get_template(db, template_id, current_user)

        st = to_utc(req.start_time)
        et = to_utc(req.end_time)
        if not st or not et or st >= et:
            raise HTTPException(status_code=400, detail="start_time must be strictly before end_time.")

        target_org_id = current_user.organization_id if not is_super_admin(current_user) else template.organization_id

        # Verify group if specified
        if req.group_id:
            group = db.query(models.Group).filter(models.Group.id == req.group_id).first()
            if not group:
                raise HTTPException(status_code=400, detail="Specified group not found.")
            if not is_super_admin(current_user):
                if is_org_admin(current_user) and group.organization_id != current_user.organization_id:
                    raise HTTPException(status_code=403, detail="Group does not belong to your organization.")

        assessment_title = req.title.strip() if req.title and req.title.strip() else template.title

        # Create decoupled Exam instance cloning template configuration
        exam = models.Exam(
            title=assessment_title,
            description=template.description,
            instructions=f"Created from template: {template.title}",
            assessment_type=template.assessment_type or "academic",
            group_id=req.group_id,
            organization_id=target_org_id,
            creator_id=current_user.id,
            start_time=st,
            end_time=et,
            duration_minutes=template.duration_minutes,
            timer_type=template.timer_type,
            default_marks=template.default_marks,
            default_negative_marks=template.default_negative_marks,
            enable_negative_marking=template.enable_negative_marking,
            randomize_questions=template.randomize_questions,
            randomize_options=template.randomize_options,
            visibility=req.visibility,
            passing_marks=template.passing_marks,
            passing_criteria=template.passing_criteria,
            passing_percentage=template.passing_percentage,
            max_attempts=template.max_attempts,
            status="draft",
            is_adaptive=template.is_adaptive,
            adaptive_config=template.adaptive_config,
            attempt_policy=template.attempt_policy,
            blueprint_id=template.blueprint_id,
            template_id=template.id,
            config_metadata=template.config_metadata
        )
        db.add(exam)
        db.commit()
        db.refresh(exam)

        # Clone sections if configured in template
        if template.section_config:
            try:
                sections_data = json.loads(template.section_config) if isinstance(template.section_config, str) else template.section_config
                for idx, s_data in enumerate(sections_data):
                    sec = models.AssessmentSection(
                        exam_id=exam.id,
                        name=s_data.get("name", f"Section {idx + 1}"),
                        description=s_data.get("description"),
                        order_index=s_data.get("order_index", idx + 1),
                        max_marks=float(s_data.get("max_marks", 0.0)),
                        passing_percentage=float(s_data.get("passing_percentage", 0.0)) if s_data.get("passing_percentage") else None,
                        is_mandatory=s_data.get("is_mandatory", True),
                        time_limit_minutes=s_data.get("time_limit_minutes"),
                        navigation_mode=s_data.get("navigation_mode", "free"),
                        instructions=s_data.get("instructions"),
                        randomize_questions=s_data.get("randomize_questions", False)
                    )
                    db.add(sec)
                db.commit()
            except Exception as e:
                # Sections parsing error shouldn't abort exam creation, but log/save
                pass

        # If blueprint is configured and question generation requested, materialize questions
        if template.blueprint_id and req.generate_blueprint_questions:
            from modules.assessments.blueprints import BlueprintService
            try:
                BlueprintService.materialize_assessment_questions(db, template.blueprint_id, exam.id, current_user)
            except Exception:
                # Blueprint materialization might fail if bank lacks questions, keep draft exam
                pass

        return exam
