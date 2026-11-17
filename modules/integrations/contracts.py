"""
modules/integrations/contracts.py
---------------------------------
Pydantic boundary contracts and schemas for external integrations:
1. Independent Question Generator application
2. Independent ExamProctor AI proctoring application
3. Future ServiceNow enterprise integration
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

# ── 1. Question Generator Contract ─────────────────────────────────────────────
class GeneratedOptionContract(BaseModel):
    text: str = Field(..., min_length=1)
    is_correct: bool = False
    explanation: Optional[str] = None

class GeneratedQuestionContract(BaseModel):
    text: str = Field(..., min_length=1)
    question_type: str = Field("single_choice", description="single_choice, multiple_choice, true_false, code")
    subject: str = Field("General", min_length=1)
    topic: str = Field("General", min_length=1)
    difficulty: Optional[str] = Field("medium", description="easy, medium, hard")
    marks: Optional[float] = 1.0
    negative_marks: Optional[float] = 0.0
    explanation: Optional[str] = None
    tags: Optional[List[str]] = None
    options: List[GeneratedOptionContract] = Field(..., min_items=2)

class QuestionGeneratorBatch(BaseModel):
    batch_id: str = Field(..., min_length=1)
    source_model: str = Field("gemini-2.5-pro", description="AI generator model name")
    subject: str = Field("General", min_length=1)
    topic: str = Field("General", min_length=1)
    questions: List[GeneratedQuestionContract] = Field(..., min_items=1)

class QuestionGeneratorImportPayload(BaseModel):
    assessment_id: int
    source_model: Optional[str] = Field("gemini-2.5-pro", description="AI generator model name")
    batch_id: Optional[str] = None
    questions: List[GeneratedQuestionContract] = Field(..., min_items=1)

class QuestionApprovalRequest(BaseModel):
    batch_id: str
    questions: List[GeneratedQuestionContract]
    approved_indices: Optional[List[int]] = None # None means approve all
    target_assessment_id: Optional[int] = None
    publish_to_bank: bool = True

# ── 2. Independent ExamProctor AI Engine Contract ──────────────────────────────
class ProctoringEventContract(BaseModel):
    exam_id: int
    student_id: int
    event_type: str = Field(..., description="multiple_faces, no_face, gaze_away, audio_detected, tab_switch, unauthorized_device")
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    timestamp: datetime
    snapshot_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ProctoringSessionSyncPayload(BaseModel):
    session_id: str
    events: List[ProctoringEventContract]

# ── 3. ServiceNow Integration Contract ─────────────────────────────────────────
class ServiceNowAssessmentSyncContract(BaseModel):
    assessment_id: int
    servicenow_course_sys_id: str
    auto_sync_grades: bool = True
    incident_webhook_url: Optional[str] = None

class ServiceNowGradeExportPayload(BaseModel):
    assessment_id: int
    student_email: str
    score: float
    max_score: float
    passed: bool
    sys_id: Optional[str] = None
