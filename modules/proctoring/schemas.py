"""
modules/proctoring/schemas.py
-----------------------------
Pydantic schemas for Proctoring Policies, Events, Scoring, and Examiner Reviews.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

class ProctoringPolicyBase(BaseModel):
    webcam_required: bool = True
    microphone_required: bool = False
    face_detection: bool = True
    multiple_face_detection: bool = True
    tab_switch_detection: bool = True
    fullscreen_required: bool = True
    copy_paste_restricted: bool = True
    browser_focus_monitoring: bool = True
    warning_threshold: int = Field(default=3, ge=1, le=20)
    violation_threshold: int = Field(default=5, ge=1, le=50)
    auto_submit_threshold: Optional[int] = Field(default=0, ge=0, le=50) # 0 = disabled
    risk_weights: Optional[Dict[str, float]] = None

class ProctoringPolicyCreate(ProctoringPolicyBase):
    pass

class ProctoringPolicyUpdate(BaseModel):
    webcam_required: Optional[bool] = None
    microphone_required: Optional[bool] = None
    face_detection: Optional[bool] = None
    multiple_face_detection: Optional[bool] = None
    tab_switch_detection: Optional[bool] = None
    fullscreen_required: Optional[bool] = None
    copy_paste_restricted: Optional[bool] = None
    browser_focus_monitoring: Optional[bool] = None
    warning_threshold: Optional[int] = Field(default=None, ge=1, le=20)
    violation_threshold: Optional[int] = Field(default=None, ge=1, le=50)
    auto_submit_threshold: Optional[int] = Field(default=None, ge=0, le=50)
    risk_weights: Optional[Dict[str, float]] = None

class ProctoringPolicyResponse(BaseModel):
    id: int
    exam_id: int
    webcam_required: bool = True
    microphone_required: bool = False
    face_detection: bool = True
    multiple_face_detection: bool = True
    tab_switch_detection: bool = True
    fullscreen_required: bool = True
    copy_paste_restricted: bool = True
    browser_focus_monitoring: bool = True
    warning_threshold: int = 3
    violation_threshold: int = 5
    auto_submit_threshold: Optional[int] = 0
    risk_weights: Optional[Any] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        orm_mode = True

class ProctoringEventIngest(BaseModel):
    exam_id: int
    exam_session_id: Optional[int] = None
    event_type: str = "tab_switch"  # tab_switch, window_blur, fullscreen_exit, face_not_detected, multiple_faces, camera_disconnected, microphone_disconnected, suspicious_activity, repeated_violations
    description: Optional[str] = None
    severity: Optional[str] = None  # low, medium, high, critical
    metadata: Optional[Dict[str, Any]] = None

class ProctoringEventResponse(BaseModel):
    id: int
    exam_id: int
    student_id: int
    student_name: Optional[str] = None
    exam_session_id: Optional[int] = None
    timestamp: datetime
    event_type: str
    description: Optional[str] = None
    severity: str
    event_metadata: Optional[str] = None
    validation_status: str
    is_resolved: bool
    review_decision: Optional[str] = None
    reviewer_notes: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class ProctoringEventReview(BaseModel):
    review_decision: str  # legitimate, suspicious, inconclusive
    reviewer_notes: Optional[str] = None

class SessionIntegritySummary(BaseModel):
    session_id: int
    exam_id: int
    candidate_id: int
    candidate_name: str
    integrity_score: float
    risk_level: str
    proctoring_status: str
    attempt_number: int
    total_violations: int
    valid_violations: int
    unreviewed_count: int
    recent_events: List[ProctoringEventResponse] = []
