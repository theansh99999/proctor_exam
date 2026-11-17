"""
modules/questions/schemas.py
----------------------------
Pydantic schemas for Question Bank, Question Options, Bulk Imports,
and Assessment Question Mappings.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import json

SUPPORTED_QUESTION_TYPES = {"single_choice", "multiple_choice", "true_false", "short_answer", "descriptive", "code"}
SUPPORTED_CATEGORIES = {"academic", "placement", "technical", "custom"}
SUPPORTED_DIFFICULTIES = {"easy", "medium", "hard"}
SUPPORTED_STATUSES = {"draft", "reviewed", "published", "archived"}

# ── 1. Option Schemas ──────────────────────────────────────────────────────────
class BankOptionCreate(BaseModel):
    text: str = Field(..., min_length=1)
    is_correct: bool = False
    explanation: Optional[str] = None
    order_index: int = 0

class BankOptionOut(BaseModel):
    id: int
    text: str
    is_correct: bool
    explanation: Optional[str] = None
    order_index: int

    class Config:
        from_attributes = True

class BankOptionCandidateOut(BaseModel):
    """Secure option view for candidates — NEVER exposes is_correct or explanation before submission."""
    id: int
    text: str
    order_index: int

    class Config:
        from_attributes = True

# ── 2. Question Bank Schemas ───────────────────────────────────────────────────
class BankQuestionBase(BaseModel):
    text: str = Field(..., min_length=1)
    question_type: str = Field("single_choice", description="single_choice, multiple_choice, true_false, short_answer, descriptive, code")
    assessment_category: str = Field("academic", description="academic, placement, technical, custom")
    subject: str = Field("General", min_length=1)
    topic: str = Field("General", min_length=1)
    subtopic: Optional[str] = None
    difficulty: str = Field("medium", description="easy, medium, hard")
    default_marks: float = Field(1.0, gt=0)
    default_negative_marks: float = Field(0.0, ge=0)
    explanation: Optional[str] = None
    tags: Optional[List[str]] = None
    status: str = Field("draft", description="draft, reviewed, published, archived")
    type_config: Optional[Dict[str, Any]] = None
    options: Optional[List[BankOptionCreate]] = None

class BankQuestionCreate(BankQuestionBase):
    organization_id: Optional[int] = None

class BankQuestionUpdate(BaseModel):
    text: Optional[str] = None
    question_type: Optional[str] = None
    assessment_category: Optional[str] = None
    subject: Optional[str] = None
    topic: Optional[str] = None
    subtopic: Optional[str] = None
    difficulty: Optional[str] = None
    default_marks: Optional[float] = None
    default_negative_marks: Optional[float] = None
    explanation: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None
    type_config: Optional[Dict[str, Any]] = None
    options: Optional[List[BankOptionCreate]] = None

class BankQuestionOut(BaseModel):
    id: int
    text: str
    question_type: str
    assessment_category: str
    subject: str
    topic: str
    subtopic: Optional[str] = None
    difficulty: str
    default_marks: float
    default_negative_marks: float
    explanation: Optional[str] = None
    tags: Optional[List[str]] = None
    organization_id: Optional[int] = None
    created_by: Optional[int] = None
    status: str
    type_config: Optional[Dict[str, Any]] = None
    options: List[BankOptionOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_model(cls, q: Any) -> "BankQuestionOut":
        parsed_tags = None
        if q.tags:
            try:
                parsed_tags = json.loads(q.tags) if isinstance(q.tags, str) and q.tags.startswith("[") else [t.strip() for t in q.tags.split(",") if t.strip()]
            except Exception:
                parsed_tags = [q.tags]

        parsed_config = None
        if q.type_config:
            try:
                parsed_config = json.loads(q.type_config) if isinstance(q.type_config, str) else q.type_config
            except Exception:
                parsed_config = {"raw": q.type_config}

        return cls(
            id=q.id,
            text=q.text,
            question_type=q.question_type or "single_choice",
            assessment_category=q.assessment_category or "academic",
            subject=q.subject,
            topic=q.topic,
            subtopic=q.subtopic,
            difficulty=q.difficulty or "medium",
            default_marks=q.default_marks or 1.0,
            default_negative_marks=q.default_negative_marks or 0.0,
            explanation=q.explanation,
            tags=parsed_tags,
            organization_id=q.organization_id,
            created_by=q.created_by,
            status=q.status or "draft",
            type_config=parsed_config,
            options=[BankOptionOut.model_validate(o) for o in (q.options or [])],
            created_at=q.created_at,
            updated_at=q.updated_at
        )

# ── 3. Bulk Import Schemas ─────────────────────────────────────────────────────
class QuestionImportRow(BaseModel):
    text: str
    question_type: str = "single_choice"
    assessment_category: str = "academic"
    subject: str = "General"
    topic: str = "General"
    subtopic: Optional[str] = None
    difficulty: str = "medium"
    marks: float = 1.0
    negative_marks: float = 0.0
    explanation: Optional[str] = None
    tags: Optional[str] = None
    options: Optional[List[Dict[str, Any]]] = None # list of {"text": "...", "is_correct": bool}
    # For CSV option columns: option_1, option_2, option_3, option_4, correct_option
    type_config: Optional[Dict[str, Any]] = None

class ImportRowError(BaseModel):
    row_number: int
    question_text: Optional[str] = None
    error: str

class QuestionImportResponse(BaseModel):
    success: bool
    is_preview: bool
    total_rows: int
    valid_count: int
    error_count: int
    duplicate_count: int
    imported_count: int
    errors: List[ImportRowError] = []
    preview_questions: List[Dict[str, Any]] = []

# ── 4. Assessment Question Mapping Schemas ─────────────────────────────────────
class MapQuestionItem(BaseModel):
    bank_question_id: int
    order_index: Optional[int] = 0
    marks: Optional[float] = None
    negative_marks: Optional[float] = None

class AssessmentQuestionMapRequest(BaseModel):
    questions: List[MapQuestionItem] = Field(..., min_items=1)

class AssessmentQuestionReorderItem(BaseModel):
    bank_question_id: int
    order_index: int

class AssessmentQuestionReorderRequest(BaseModel):
    reorder_list: List[AssessmentQuestionReorderItem] = Field(..., min_items=1)

class AssessmentQuestionMapOut(BaseModel):
    id: int
    assessment_id: int
    bank_question_id: int
    order_index: int
    marks: float
    negative_marks: float
    created_at: Optional[datetime] = None
    question: Optional[BankQuestionOut] = None

    class Config:
        from_attributes = True

class AssessmentQuestionsListResponse(BaseModel):
    assessment_id: int
    assessment_title: str
    total_questions: int
    total_max_marks: float
    questions: List[AssessmentQuestionMapOut]
