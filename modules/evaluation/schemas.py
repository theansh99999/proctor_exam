"""
modules/evaluation/schemas.py
-----------------------------
Pydantic v2 schemas for Evaluation, Grading, Sections, Results, and Audits.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class AssessmentSectionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = None
    order_index: int = 0
    max_marks: float = Field(0.0, ge=0.0)
    passing_percentage: Optional[float] = Field(None, ge=0.0, le=100.0)


class AssessmentSectionCreate(AssessmentSectionBase):
    pass


class AssessmentSectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    order_index: Optional[int] = None
    max_marks: Optional[float] = None
    passing_percentage: Optional[float] = None


class AssessmentSectionResponse(AssessmentSectionBase):
    id: int
    exam_id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ManualGradeSubmit(BaseModel):
    marks_awarded: float = Field(..., ge=0.0)
    examiner_feedback: Optional[str] = None
    is_draft: bool = False # True = in_progress, False = graded


class AnswerRegradeSubmit(BaseModel):
    marks_awarded: float = Field(..., ge=0.0)
    examiner_feedback: Optional[str] = None
    reason: str = Field(..., min_length=3, description="Justification for regrading")


class PendingGradingItem(BaseModel):
    answer_id: int
    exam_session_id: int
    attempt_number: int
    exam_id: int
    exam_title: str
    student_id: int
    student_name: str
    question_id: int
    question_text: str
    question_type: str
    max_marks: float
    answer_text: Optional[str] = None
    evaluation_status: str # pending, in_progress, graded
    marks_awarded: float
    examiner_feedback: Optional[str] = None
    marking_guidelines: Optional[str] = None
    submitted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SectionScore(BaseModel):
    section_id: Optional[int] = None
    name: str
    marks_obtained: float
    max_marks: float
    percentage: float
    passing_percentage: Optional[float] = None
    passed: bool


class CandidateAnswerSummary(BaseModel):
    question_id: int
    question_text: str
    question_type: str
    max_marks: float
    marks_awarded: float
    is_correct: bool
    evaluation_status: str
    examiner_feedback: Optional[str] = None


class CandidateResultResponse(BaseModel):
    result_id: Optional[int] = None
    exam_id: int
    exam_title: str
    assessment_type: str
    student_id: int
    student_name: str
    exam_session_id: int
    attempt_number: int
    total_marks: float
    marks_obtained: float
    percentage: float
    pass_fail_status: str # PASS, FAIL, PENDING
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    manual_grading_status: str # not_required, pending, in_progress, graded
    is_released: bool
    released_at: Optional[datetime] = None
    section_scores: List[SectionScore] = []
    answers: Optional[List[CandidateAnswerSummary]] = None
    proctoring_summary: Optional[Dict[str, Any]] = None # Examiner-only: integrity_score, risk_level

    model_config = ConfigDict(from_attributes=True)


class ResultReleaseToggle(BaseModel):
    is_released: bool


class ResultExportItem(BaseModel):
    candidate_id: int
    candidate_name: str
    candidate_email: str
    assessment_id: int
    assessment_title: str
    assessment_type: str
    attempt_number: int
    total_marks: float
    marks_obtained: float
    percentage: float
    pass_fail_status: str
    manual_grading_status: str
    is_released: bool
    submission_timestamp: Optional[str] = None
    evaluated_at: Optional[str] = None
    integrity_score: Optional[float] = None
    risk_level: Optional[str] = None
