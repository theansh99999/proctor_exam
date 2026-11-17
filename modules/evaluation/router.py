"""
modules/evaluation/router.py
----------------------------
FastAPI endpoints for:
1. Assessment Sections Management
2. Unified Evaluation & Manual Grading
3. Regrading with Audit Trail
4. Results Release Controls & Candidate Results Portal
5. Results Export (JSON / CSV ready)
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

import database, models, auth
from modules.evaluation.schemas import (
    AssessmentSectionCreate,
    AssessmentSectionUpdate,
    AssessmentSectionResponse,
    ManualGradeSubmit,
    AnswerRegradeSubmit,
    PendingGradingItem,
    CandidateResultResponse,
    ResultReleaseToggle,
    ResultExportItem
)
from modules.evaluation.service import EvaluationService

router = APIRouter(tags=["Evaluation, Grading & Results"])


# =============================================================================
# 1. ASSESSMENT SECTIONS MANAGEMENT
# =============================================================================
@router.post(
    "/api/v1/assessments/{exam_id}/sections",
    response_model=AssessmentSectionResponse,
    status_code=status.HTTP_201_CREATED
)
def create_assessment_section(
    exam_id: int,
    section_in: AssessmentSectionCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Examiner adds an optional section to an assessment."""
    exam = db.query(models.Exam).filter_by(id=exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if current_user.role != "super_admin":
        if current_user.organization_id and exam.organization_id and current_user.organization_id != exam.organization_id:
            raise HTTPException(status_code=403, detail="Not authorized for another organization")

    sec = models.AssessmentSection(
        exam_id=exam.id,
        name=section_in.name,
        description=section_in.description,
        order_index=section_in.order_index,
        max_marks=section_in.max_marks,
        passing_percentage=section_in.passing_percentage
    )
    db.add(sec)
    db.commit()
    db.refresh(sec)
    return sec


@router.get(
    "/api/v1/assessments/{exam_id}/sections",
    response_model=List[AssessmentSectionResponse]
)
def list_assessment_sections(
    exam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Lists sections for an assessment."""
    exam = db.query(models.Exam).filter_by(id=exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Assessment not found")

    sections = db.query(models.AssessmentSection).filter_by(exam_id=exam.id).order_by(models.AssessmentSection.order_index).all()
    return sections


@router.delete(
    "/api/v1/assessments/{exam_id}/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_assessment_section(
    exam_id: int,
    section_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Removes a section from an assessment."""
    sec = db.query(models.AssessmentSection).filter_by(id=section_id, exam_id=exam_id).first()
    if not sec:
        raise HTTPException(status_code=404, detail="Section not found")

    db.delete(sec)
    db.commit()
    return None


# =============================================================================
# 2. EVALUATION & MANUAL GRADING
# =============================================================================
@router.post(
    "/api/v1/evaluation/sessions/{session_id}/evaluate",
    status_code=status.HTTP_200_OK
)
def evaluate_session_endpoint(
    session_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Triggers unified evaluation of an attempt session."""
    sess = db.query(models.ExamSession).filter_by(id=session_id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Exam session not found")

    if current_user.role == "student" and sess.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to evaluate another student's session")

    res = EvaluationService.evaluate_attempt(db, sess)
    return {
        "status": "evaluated",
        "result_id": res.id,
        "score": res.marks_obtained,
        "total_marks": res.total_marks,
        "percentage": res.percentage,
        "pass_fail_status": res.pass_fail_status,
        "manual_grading_status": res.manual_grading_status
    }


@router.get(
    "/api/v1/evaluation/grading-queue",
    response_model=List[PendingGradingItem]
)
def get_grading_queue(
    exam_id: Optional[int] = Query(None, description="Optional assessment filter"),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Retrieves pending descriptive and manually reviewed answers requiring grading."""
    return EvaluationService.get_pending_grading_queue(db, current_user, exam_id)


@router.post(
    "/api/v1/evaluation/answers/{answer_id}/grade",
    status_code=status.HTTP_200_OK
)
def grade_answer_endpoint(
    answer_id: int,
    grade_in: ManualGradeSubmit,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Examiner scores a descriptive answer (draft or final). Enforces maximum marks."""
    ans = EvaluationService.grade_answer(
        db=db,
        answer_id=answer_id,
        marks_awarded=grade_in.marks_awarded,
        examiner_feedback=grade_in.examiner_feedback,
        is_draft=grade_in.is_draft,
        grader=current_user
    )
    return {
        "status": "success",
        "answer_id": ans.id,
        "marks_awarded": ans.marks_awarded,
        "evaluation_status": ans.evaluation_status,
        "is_draft": grade_in.is_draft
    }


@router.post(
    "/api/v1/evaluation/answers/{answer_id}/regrade",
    status_code=status.HTTP_200_OK
)
def regrade_answer_endpoint(
    answer_id: int,
    regrade_in: AnswerRegradeSubmit,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Examiner regrades an answer with mandatory justification; records audit trail."""
    ans = EvaluationService.regrade_answer(
        db=db,
        answer_id=answer_id,
        marks_awarded=regrade_in.marks_awarded,
        examiner_feedback=regrade_in.examiner_feedback,
        reason=regrade_in.reason,
        grader=current_user
    )
    return {
        "status": "regraded",
        "answer_id": ans.id,
        "marks_awarded": ans.marks_awarded,
        "evaluation_status": ans.evaluation_status
    }


# =============================================================================
# 3. RESULTS & RELEASE CONTROLS
# =============================================================================
@router.post(
    "/api/v1/results/assessments/{exam_id}/release-control",
    status_code=status.HTTP_200_OK
)
def toggle_results_release(
    exam_id: int,
    payload: ResultReleaseToggle,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Examiner releases or holds results for an assessment."""
    return EvaluationService.toggle_result_release(db, exam_id, payload.is_released, current_user)


@router.get(
    "/api/v1/results/sessions/{session_id}"
)
def get_session_result(
    session_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Retrieves consolidated result for an attempt. Unreleased results hidden from students."""
    return EvaluationService.get_candidate_result_summary(db, session_id, current_user)


@router.get(
    "/api/v1/results/assessments/{exam_id}/my-results"
)
def get_my_assessment_results(
    exam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """Candidate retrieves their attempt history and released results."""
    sessions = db.query(models.ExamSession).filter_by(
        exam_id=exam_id,
        student_id=current_user.id
    ).order_by(models.ExamSession.attempt_number.asc()).all()

    results = []
    for s in sessions:
        summary = EvaluationService.get_candidate_result_summary(db, s.id, current_user)
        results.append(summary)

    return {"exam_id": exam_id, "attempts": results}


@router.get(
    "/api/v1/results/assessments/{exam_id}/export",
    response_model=List[ResultExportItem]
)
def export_assessment_results(
    exam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Exports standardized assessment results for reporting and institutional integration."""
    return EvaluationService.get_assessment_results_export(db, exam_id, current_user)
