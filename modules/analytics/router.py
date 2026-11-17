"""
modules/analytics/router.py
----------------------------
FastAPI endpoints for:
1. Examiner Dashboard Analytics & Metrics with multi-criteria filters
2. Candidate Performance Analytics & Topic Taxonomy
3. Assessment-Level Analytics & Question Accuracy
4. Question Bank Analytics
5. Organization-Scoped Admin Dashboard
6. Downloadable CSV and JSON Reports
Strictly enforces RBAC, organization boundaries, and candidate privacy.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.orm import Session

import database, models, auth
from modules.analytics.schemas import (
    ExaminerDashboardMetrics,
    AssessmentFilterParams,
    CandidatePerformanceSummary,
    AssessmentAnalyticsDetail,
    QuestionAccuracyItem,
    OrganizationDashboardMetrics
)
from modules.analytics.service import AnalyticsService

router = APIRouter(tags=["Analytics, Dashboards & Reporting"])


# =============================================================================
# 1. EXAMINER DASHBOARD ANALYTICS
# =============================================================================
@router.get(
    "/examiner/summary",
    response_model=ExaminerDashboardMetrics,
    status_code=status.HTTP_200_OK
)
def get_examiner_dashboard_summary(
    start_date: Optional[str] = Query(None, description="Start date ISO string filter"),
    end_date: Optional[str] = Query(None, description="End date ISO string filter"),
    assessment_type: Optional[str] = Query(None, description="Assessment type filter (academic, placement, technical, custom)"),
    assessment_status: Optional[str] = Query(None, alias="status", description="Assessment status (draft, published, scheduled, active, completed)"),
    assessment_id: Optional[int] = Query(None, description="Specific assessment ID"),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """
    Get aggregate metrics and status summaries for examiner's assessments.
    Supports filtering by date range, type, status, and specific assessment.
    """
    metrics = AnalyticsService.get_examiner_dashboard_metrics(
        db=db,
        examiner=current_user,
        start_date=start_date,
        end_date=end_date,
        assessment_type=assessment_type,
        status=assessment_status,
        assessment_id=assessment_id
    )
    return metrics


# =============================================================================
# 2. CANDIDATE PERFORMANCE ANALYTICS
# =============================================================================
@router.get(
    "/candidate/performance",
    response_model=CandidatePerformanceSummary,
    status_code=status.HTTP_200_OK
)
def get_candidate_performance(
    candidate_id: Optional[int] = Query(None, description="Candidate ID (defaults to current user if student)"),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """
    Aggregates performance analytics for a specific candidate.
    - If student: can only view their own performance. Unreleased results are hidden.
    - If examiner/admin: can view assigned or organization candidates.
    """
    target_id = candidate_id if candidate_id is not None else current_user.id

    # Students cannot view other candidates' metrics
    if current_user.role == "student" and target_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Students are not authorized to view another candidate's performance"
        )

    summary = AnalyticsService.get_candidate_performance_analytics(
        db=db,
        candidate_id=target_id,
        requesting_user=current_user
    )
    return summary


# =============================================================================
# 3. ASSESSMENT-LEVEL ANALYTICS
# =============================================================================
@router.get(
    "/assessments/{exam_id}",
    response_model=AssessmentAnalyticsDetail,
    status_code=status.HTTP_200_OK
)
def get_assessment_analytics(
    exam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """
    Deep-dive analytics for a single assessment including participation funnels,
    score distributions, question-level accuracy, and proctoring metrics.
    """
    analytics = AnalyticsService.get_assessment_analytics(
        db=db,
        exam_id=exam_id,
        requesting_user=current_user
    )
    return analytics


# =============================================================================
# 4. QUESTION BANK ANALYTICS
# =============================================================================
@router.get(
    "/assessments/{exam_id}/questions",
    response_model=List[QuestionAccuracyItem],
    status_code=status.HTTP_200_OK
)
def get_assessment_question_analytics(
    exam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """
    Retrieves item-level performance analytics for each question in an assessment.
    Protected against division by zero for unattempted questions.
    """
    exam = db.query(models.Exam).filter_by(id=exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if current_user.role != "super_admin":
        if current_user.organization_id and exam.organization_id and current_user.organization_id != exam.organization_id:
            raise HTTPException(status_code=403, detail="Not authorized for another organization")

    analytics = AnalyticsService.get_question_bank_analytics(
        db=db,
        exam_id=exam_id,
        requesting_user=current_user
    )
    return analytics


# =============================================================================
# 5. ORGANIZATION ADMIN DASHBOARD
# =============================================================================
@router.get(
    "/organization/summary",
    response_model=OrganizationDashboardMetrics,
    status_code=status.HTTP_200_OK
)
def get_organization_dashboard_summary(
    org_id: Optional[int] = Query(None, description="Target organization ID (Super Admin only)"),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_org_admin_api)
):
    """
    Organization-scoped dashboard metrics: total candidates, examiners, assessments,
    group-level performance, and 7-day activity trends.
    Strictly isolated to current user's organization unless Super Admin.
    """
    metrics = AnalyticsService.get_organization_dashboard_metrics(
        db=db,
        current_user=current_user,
        target_org_id=org_id
    )
    return metrics


# =============================================================================
# 6. DOWNLOADABLE CSV REPORTS
# =============================================================================
@router.get(
    "/reports/assessments/{exam_id}/results.csv",
    status_code=status.HTTP_200_OK
)
def export_assessment_results_csv(
    exam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Generates and downloads a CSV of all candidate attempts and scores for an assessment."""
    csv_content = AnalyticsService.generate_assessment_results_csv(
        db=db,
        exam_id=exam_id,
        current_user=current_user
    )
    filename = f"assessment_{exam_id}_results.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get(
    "/reports/candidates/{candidate_id}/performance.csv",
    status_code=status.HTTP_200_OK
)
def export_candidate_performance_csv(
    candidate_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    """
    Generates and downloads a CSV of a candidate's attempt history.
    Enforces privacy by omitting unreleased results for student requests.
    """
    # Enforce student self-only check
    if current_user.role == "student" and candidate_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Students cannot download another candidate's performance report"
        )
    # If not student, must be examiner or admin
    if current_user.role not in ["student", "teacher", "examiner", "admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    csv_content = AnalyticsService.generate_candidate_performance_csv(
        db=db,
        candidate_id=candidate_id,
        requesting_user=current_user
    )
    filename = f"candidate_{candidate_id}_performance.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get(
    "/reports/assessments/{exam_id}/questions.csv",
    status_code=status.HTTP_200_OK
)
def export_question_analytics_csv(
    exam_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_examiner_api)
):
    """Generates and downloads a CSV of question item performance and accuracy."""
    exam = db.query(models.Exam).filter_by(id=exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if current_user.role != "super_admin":
        if current_user.organization_id and exam.organization_id and current_user.organization_id != exam.organization_id:
            raise HTTPException(status_code=403, detail="Not authorized for another organization")

    csv_content = AnalyticsService.generate_question_analytics_csv(
        db=db,
        exam_id=exam_id,
        current_user=current_user
    )
    filename = f"assessment_{exam_id}_questions_analytics.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
