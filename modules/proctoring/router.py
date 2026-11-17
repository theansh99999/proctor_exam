"""
modules/proctoring/router.py
----------------------------
FastAPI endpoints for:
1. Assessment Proctoring Policies (CRUD)
2. Real-time Proctoring Event Ingestion (Debounced & Scored)
3. Examiner Live-Status Monitoring
4. Examiner Violation Review Workflow
"""
import json
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import database, models, auth
from modules.proctoring.schemas import (
    ProctoringPolicyResponse,
    ProctoringPolicyUpdate,
    ProctoringEventIngest,
    ProctoringEventReview,
    ProctoringEventResponse,
    SessionIntegritySummary
)
from modules.proctoring.service import ProctoringService

router = APIRouter(tags=["Proctoring & Exam Integrity"])

def to_policy_response(p: models.ProctoringPolicy) -> ProctoringPolicyResponse:
    rw = None
    if p.risk_weights:
        try:
            rw = json.loads(p.risk_weights) if isinstance(p.risk_weights, str) else p.risk_weights
        except Exception:
            rw = None
    return ProctoringPolicyResponse(
        id=p.id,
        exam_id=p.exam_id,
        webcam_required=p.webcam_required,
        microphone_required=p.microphone_required,
        face_detection=p.face_detection,
        multiple_face_detection=p.multiple_face_detection,
        tab_switch_detection=p.tab_switch_detection,
        fullscreen_required=p.fullscreen_required,
        copy_paste_restricted=p.copy_paste_restricted,
        browser_focus_monitoring=p.browser_focus_monitoring,
        warning_threshold=p.warning_threshold,
        violation_threshold=p.violation_threshold,
        auto_submit_threshold=p.auto_submit_threshold or 0,
        risk_weights=rw,
        created_at=p.created_at,
        updated_at=p.updated_at
    )

# ── 1. Policy Management ───────────────────────────────────────────────────────
@router.get("/api/v1/assessments/{exam_id}/proctoring-policy", response_model=ProctoringPolicyResponse)
def get_assessment_proctoring_policy(
    exam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Retrieves proctoring policy for assessment."""
    exam = db.query(models.Exam).filter_by(id=exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Assessment not found")
    p = ProctoringService.get_or_create_policy(db, exam)
    return to_policy_response(p)

@router.put("/api/v1/assessments/{exam_id}/proctoring-policy", response_model=ProctoringPolicyResponse)
def update_assessment_proctoring_policy(
    exam_id: int,
    policy_in: ProctoringPolicyUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Updates proctoring policy for assessment (Examiners / Admins only)."""
    exam = db.query(models.Exam).filter_by(id=exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Assessment not found")
    p = ProctoringService.update_policy(db, exam, policy_in, current_user)
    return to_policy_response(p)

# ── 2. Event Ingestion ─────────────────────────────────────────────────────────
@router.post("/api/v1/proctoring/events")
async def ingest_proctoring_event(
    event_in: ProctoringEventIngest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_student_api)
):
    """Ingests a proctoring violation from the candidate browser during exam."""
    return await ProctoringService.ingest_event(db, current_user, event_in)

# ── 3. Live Monitoring ─────────────────────────────────────────────────────────
@router.get("/api/v1/proctoring/assessments/{exam_id}/live-status")
def get_live_monitoring_status(
    exam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Returns active candidate sessions, violation counts, and risk levels."""
    return ProctoringService.get_live_exam_status(db, exam_id, current_user)

# ── 4. Session Event History & Timeline ───────────────────────────────────────
@router.get("/api/v1/proctoring/sessions/{session_id}/events", response_model=List[ProctoringEventResponse])
def get_session_proctoring_events(
    session_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Retrieves all proctoring events for a specific candidate exam session."""
    sess = db.query(models.ExamSession).filter_by(id=session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Exam session not found")

    flags = db.query(models.CheatFlag).filter_by(
        exam_id=sess.exam_id,
        student_id=sess.student_id
    ).order_by(models.CheatFlag.timestamp.asc()).all()

    cand = db.query(models.User).filter_by(id=sess.student_id).first()
    results = []
    for f in flags:
        resp = ProctoringEventResponse(
            id=f.id,
            exam_id=f.exam_id,
            student_id=f.student_id,
            student_name=cand.name if cand else "Candidate",
            exam_session_id=f.exam_session_id,
            timestamp=f.timestamp,
            event_type=f.event_type or "tab_switch",
            description=f.description,
            severity=f.severity or "medium",
            event_metadata=f.event_metadata,
            validation_status=f.validation_status or "valid",
            is_resolved=f.is_resolved or False,
            review_decision=f.review_decision or "unreviewed",
            reviewer_notes=f.reviewer_notes,
            reviewed_by=f.reviewed_by,
            reviewed_at=f.reviewed_at
        )
        results.append(resp)
    return results

# ── 5. Examiner Review Action ─────────────────────────────────────────────────
@router.put("/api/v1/proctoring/events/{event_id}/review")
def review_proctoring_event(
    event_id: int,
    review_in: ProctoringEventReview,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Examiner marks event as legitimate, suspicious or inconclusive with notes."""
    flag = ProctoringService.review_event(db, event_id, review_in, current_user)
    return {
        "status": "reviewed",
        "flag_id": flag.id,
        "review_decision": flag.review_decision,
        "reviewer_notes": flag.reviewer_notes,
        "reviewed_by": flag.reviewed_by
    }
