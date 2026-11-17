"""
modules/assessments/schemas.py
------------------------------
Pydantic schemas for multi-purpose assessments (academic, placement, technical, custom),
scheduling, candidate/group assignments, lifecycle transitions, and statistics.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, Any, List
from datetime import datetime
import json
from time_utils import utc_now, to_utc

class AssessmentBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    instructions: Optional[str] = None
    assessment_type: str = Field("academic", description="academic, placement, technical, custom")
    group_id: Optional[int] = None
    organization_id: Optional[int] = None
    start_time: datetime
    end_time: datetime
    duration_minutes: int = Field(..., gt=0)
    timer_type: str = Field("overall", description="overall or per_question")
    default_marks: float = 1.0
    default_negative_marks: float = 0.0
    enable_negative_marking: bool = False
    randomize_questions: bool = False
    randomize_options: bool = False
    visibility: str = Field("group_only", description="public, private, group_only")
    passing_marks: float = 0.0
    passing_criteria: str = Field("marks", description="marks or percentage")
    passing_percentage: Optional[float] = None
    max_attempts: int = Field(1, ge=1)
    status: str = Field("draft", description="draft, published, scheduled, active, completed, archived")
    is_adaptive: bool = False
    adaptive_config: Optional[Dict[str, Any]] = None
    attempt_policy: Optional[Dict[str, Any]] = None
    blueprint_id: Optional[int] = None
    template_id: Optional[int] = None
    config_metadata: Optional[Dict[str, Any]] = None

class AssessmentCreate(AssessmentBase):
    pass

class AssessmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    assessment_type: Optional[str] = None
    group_id: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    timer_type: Optional[str] = None
    default_marks: Optional[float] = None
    default_negative_marks: Optional[float] = None
    enable_negative_marking: Optional[bool] = None
    randomize_questions: Optional[bool] = None
    randomize_options: Optional[bool] = None
    visibility: Optional[str] = None
    passing_marks: Optional[float] = None
    passing_criteria: Optional[str] = None
    passing_percentage: Optional[float] = None
    max_attempts: Optional[int] = None
    status: Optional[str] = None
    is_adaptive: Optional[bool] = None
    adaptive_config: Optional[Dict[str, Any]] = None
    attempt_policy: Optional[Dict[str, Any]] = None
    blueprint_id: Optional[int] = None
    template_id: Optional[int] = None
    config_metadata: Optional[Dict[str, Any]] = None

class AssessmentScheduleRequest(BaseModel):
    start_time: datetime
    end_time: datetime

class AssessmentStatusUpdate(BaseModel):
    status: str = Field(..., description="draft, published, scheduled, active, completed, archived")
    reason: Optional[str] = None

class AssessmentOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    instructions: Optional[str] = None
    assessment_type: str
    group_id: Optional[int] = None
    organization_id: Optional[int] = None
    creator_id: Optional[int] = None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    timer_type: str
    default_marks: float
    default_negative_marks: float
    enable_negative_marking: bool
    randomize_questions: bool
    randomize_options: bool = False
    visibility: str
    passing_marks: float
    passing_criteria: str
    passing_percentage: Optional[float] = None
    max_attempts: int
    status: str
    effective_status: str
    is_adaptive: bool = False
    adaptive_config: Optional[Dict[str, Any]] = None
    attempt_policy: Optional[Dict[str, Any]] = None
    blueprint_id: Optional[int] = None
    template_id: Optional[int] = None
    assigned_candidates_count: Optional[int] = 0
    assigned_groups_count: Optional[int] = 0
    config_metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, exam: Any, candidate_count: int = 0, group_count: int = 0) -> "AssessmentOut":
        """Helper to safely parse JSON config_metadata and compute dynamic effective status."""
        meta_dict = None
        if exam.config_metadata:
            try:
                meta_dict = json.loads(exam.config_metadata) if isinstance(exam.config_metadata, str) else exam.config_metadata
            except Exception:
                meta_dict = {"raw": exam.config_metadata}

        # Calculate dynamic effective status
        now = utc_now()
        base_status = exam.status or "draft"
        if base_status == "archived":
            eff_status = "archived"
        elif base_status == "draft":
            eff_status = "draft"
        else:
            st = to_utc(exam.start_time)
            et = to_utc(exam.end_time)
            if now < st:
                eff_status = "scheduled"
            elif st <= now <= et:
                eff_status = "active"
            else:
                eff_status = "completed"

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
            id=exam.id,
            title=exam.title,
            description=exam.description,
            instructions=exam.instructions,
            assessment_type=exam.assessment_type or "academic",
            group_id=exam.group_id,
            organization_id=exam.organization_id,
            creator_id=exam.creator_id,
            start_time=exam.start_time,
            end_time=exam.end_time,
            duration_minutes=exam.duration_minutes,
            timer_type=exam.timer_type or "overall",
            default_marks=exam.default_marks or 1.0,
            default_negative_marks=exam.default_negative_marks or 0.0,
            enable_negative_marking=bool(exam.enable_negative_marking),
            randomize_questions=bool(exam.randomize_questions),
            randomize_options=bool(getattr(exam, "randomize_options", False)),
            visibility=exam.visibility or "group_only",
            passing_marks=exam.passing_marks or 0.0,
            passing_criteria=exam.passing_criteria or "marks",
            passing_percentage=exam.passing_percentage,
            max_attempts=exam.max_attempts or 1,
            status=base_status,
            effective_status=eff_status,
            is_adaptive=bool(getattr(exam, "is_adaptive", False)),
            adaptive_config=_parse(getattr(exam, "adaptive_config", None)),
            attempt_policy=_parse(getattr(exam, "attempt_policy", None)),
            blueprint_id=getattr(exam, "blueprint_id", None),
            template_id=getattr(exam, "template_id", None),
            assigned_candidates_count=candidate_count,
            assigned_groups_count=group_count,
            config_metadata=meta_dict
        )

# ── Assignment Schemas ─────────────────────────────────────────────────────────
class CandidateAssignmentRequest(BaseModel):
    candidate_ids: Optional[List[int]] = None
    candidate_emails: Optional[List[EmailStr]] = None

class GroupAssignmentRequest(BaseModel):
    group_ids: List[int] = Field(..., min_items=1)

class AssignmentOut(BaseModel):
    id: int
    assessment_id: int
    candidate_id: Optional[int] = None
    candidate_email: Optional[str] = None
    candidate_name: Optional[str] = None
    group_id: Optional[int] = None
    group_name: Optional[str] = None
    assigned_by: Optional[int] = None
    assigned_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class AssessmentAssignmentsDetail(BaseModel):
    assessment_id: int
    assessment_title: str
    assigned_candidates: List[AssignmentOut]
    assigned_groups: List[AssignmentOut]
    total_candidate_count: int

# ── Statistics Schema ──────────────────────────────────────────────────────────
class AssessmentStatisticsOut(BaseModel):
    assessment_id: int
    title: str
    status: str
    effective_status: str
    total_assigned_candidates: int
    total_attempts: int
    completed_attempts: int
    average_score: float
    highest_score: float
    lowest_score: float
    pass_count: int
    fail_count: int
    pass_rate: float
