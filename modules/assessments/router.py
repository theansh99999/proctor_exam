"""
modules/assessments/router.py
-----------------------------
API v1 endpoints for Assessment Management:
- Assessment CRUD
- Lifecycle transitions (Publish, Schedule, Archive)
- Candidate and Group Assignments
- Assignment details & statistics
"""
from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import database, auth, models
from modules.assessments.schemas import (
    AssessmentCreate,
    AssessmentUpdate,
    AssessmentOut,
    AssessmentScheduleRequest,
    CandidateAssignmentRequest,
    GroupAssignmentRequest,
    AssessmentAssignmentsDetail,
    AssessmentStatisticsOut
)
from modules.questions.schemas import (
    AssessmentQuestionMapRequest,
    AssessmentQuestionReorderRequest
)
from modules.assessments.service import AssessmentService
from modules.assessments.blueprints import (
    BlueprintService,
    BlueprintCreate,
    BlueprintUpdate,
    BlueprintOut,
    BlueprintValidationResult
)
from modules.assessments.templates import (
    TemplateService,
    TemplateCreate,
    TemplateUpdate,
    TemplateOut,
    CreateAssessmentFromTemplateRequest
)
from modules.assessments.adaptive import AdaptiveService
from modules.assessments.attempt_policies import AttemptPolicyService
from modules.assessments.sections import SectionService
from core.responses import success_response

class AdaptiveSubmitRequest(BaseModel):
    question_id: int
    selected_option_id: Optional[int] = None
    answer_text: Optional[str] = None

router = APIRouter(tags=["API v1 - Assessments"])

# ── 1. Create Assessment ───────────────────────────────────────────────────────
@router.post("", status_code=status.HTTP_201_CREATED)
def create_assessment(
    payload: AssessmentCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.create_assessment(db, payload, current_user)
    return success_response(
        data=AssessmentOut.from_model(exam).model_dump(),
        message="Assessment created successfully",
        status_code=status.HTTP_201_CREATED
    )

# ── 2. List Assessments ────────────────────────────────────────────────────────
@router.get("", status_code=status.HTTP_200_OK)
def list_assessments(
    search: Optional[str] = Query(None),
    assessment_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    organization_id: Optional[int] = Query(None),
    sort_by: str = Query("start_time"),
    sort_order: str = Query("desc"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exams, total_count = AssessmentService.list_assessments(
        db, current_user,
        search=search,
        assessment_type=assessment_type,
        status_filter=status,
        organization_id=organization_id,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit
    )
    return success_response(
        data=[AssessmentOut.from_model(e).model_dump() for e in exams],
        meta={"total": total_count, "skip": skip, "limit": limit},
        message="Assessments retrieved successfully"
    )

# ── Blueprint Management Endpoints ──────────────────────────────────────────
@router.post("/blueprints", status_code=status.HTTP_201_CREATED)
def create_blueprint(
    payload: BlueprintCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    bp = BlueprintService.create_blueprint(db, payload, current_user)
    return success_response(
        data=BlueprintOut.from_model(bp).model_dump(),
        message="Assessment blueprint created successfully",
        status_code=status.HTTP_201_CREATED
    )

@router.get("/blueprints", status_code=status.HTTP_200_OK)
def list_blueprints(
    assessment_type: Optional[str] = Query(None),
    include_archived: bool = Query(False),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    bps = BlueprintService.list_blueprints(db, current_user, assessment_type=assessment_type, include_archived=include_archived)
    return success_response(
        data=[BlueprintOut.from_model(bp).model_dump() for bp in bps],
        message="Assessment blueprints retrieved successfully"
    )

@router.get("/blueprints/{blueprint_id}", status_code=status.HTTP_200_OK)
def get_blueprint(
    blueprint_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    bp = BlueprintService.get_blueprint(db, blueprint_id, current_user)
    return success_response(
        data=BlueprintOut.from_model(bp).model_dump(),
        message="Blueprint retrieved successfully"
    )

@router.put("/blueprints/{blueprint_id}", status_code=status.HTTP_200_OK)
def update_blueprint(
    blueprint_id: int,
    payload: BlueprintUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    bp = BlueprintService.update_blueprint(db, blueprint_id, payload, current_user)
    return success_response(
        data=BlueprintOut.from_model(bp).model_dump(),
        message="Blueprint updated successfully"
    )

@router.delete("/blueprints/{blueprint_id}", status_code=status.HTTP_200_OK)
def archive_blueprint(
    blueprint_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    bp = BlueprintService.archive_blueprint(db, blueprint_id, current_user)
    return success_response(
        data=BlueprintOut.from_model(bp).model_dump(),
        message="Blueprint archived successfully"
    )

@router.post("/blueprints/{blueprint_id}/validate", status_code=status.HTTP_200_OK)
def validate_blueprint(
    blueprint_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    res = BlueprintService.validate_blueprint(db, blueprint_id, current_user)
    return success_response(
        data=res.model_dump(),
        message="Blueprint validated against Question Bank"
    )

@router.post("/blueprints/{blueprint_id}/materialize/{assessment_id}", status_code=status.HTTP_200_OK)
def materialize_blueprint(
    blueprint_id: int,
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    result = BlueprintService.materialize_assessment_questions(db, blueprint_id, assessment_id, current_user)
    return success_response(
        data=result,
        message=f"Generated {result.get('questions_generated', 0)} questions from blueprint"
    )

# ── Template Management Endpoints ───────────────────────────────────────────
@router.post("/templates", status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    tmpl = TemplateService.create_template(db, payload, current_user)
    return success_response(
        data=TemplateOut.from_model(tmpl).model_dump(),
        message="Assessment template created successfully",
        status_code=status.HTTP_201_CREATED
    )

@router.get("/templates", status_code=status.HTTP_200_OK)
def list_templates(
    assessment_type: Optional[str] = Query(None),
    include_archived: bool = Query(False),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    tmpls = TemplateService.list_templates(db, current_user, assessment_type=assessment_type, include_archived=include_archived)
    return success_response(
        data=[TemplateOut.from_model(t).model_dump() for t in tmpls],
        message="Assessment templates retrieved successfully"
    )

@router.get("/templates/{template_id}", status_code=status.HTTP_200_OK)
def get_template(
    template_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    tmpl = TemplateService.get_template(db, template_id, current_user)
    return success_response(
        data=TemplateOut.from_model(tmpl).model_dump(),
        message="Template retrieved successfully"
    )

@router.put("/templates/{template_id}", status_code=status.HTTP_200_OK)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    tmpl = TemplateService.update_template(db, template_id, payload, current_user)
    return success_response(
        data=TemplateOut.from_model(tmpl).model_dump(),
        message="Template updated successfully"
    )

@router.delete("/templates/{template_id}", status_code=status.HTTP_200_OK)
def archive_template(
    template_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    tmpl = TemplateService.archive_template(db, template_id, current_user)
    return success_response(
        data=TemplateOut.from_model(tmpl).model_dump(),
        message="Template archived successfully"
    )

@router.post("/templates/{template_id}/duplicate", status_code=status.HTTP_201_CREATED)
def duplicate_template(
    template_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    clone = TemplateService.duplicate_template(db, template_id, current_user)
    return success_response(
        data=TemplateOut.from_model(clone).model_dump(),
        message="Template duplicated successfully",
        status_code=status.HTTP_201_CREATED
    )

@router.post("/templates/{template_id}/create-assessment", status_code=status.HTTP_201_CREATED)
def create_assessment_from_template(
    template_id: int,
    payload: CreateAssessmentFromTemplateRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = TemplateService.create_assessment_from_template(db, template_id, payload, current_user)
    return success_response(
        data=AssessmentOut.from_model(exam).model_dump(),
        message="Assessment created from template successfully",
        status_code=status.HTTP_201_CREATED
    )

# ── 3. Get Assessment by ID ────────────────────────────────────────────────────
@router.get("/{assessment_id}", status_code=status.HTTP_200_OK)
def get_assessment(
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.get_assessment(db, assessment_id, current_user)
    return success_response(
        data=AssessmentOut.from_model(exam).model_dump(),
        message="Assessment details retrieved"
    )

# ── 4. Update Assessment ───────────────────────────────────────────────────────
@router.put("/{assessment_id}", status_code=status.HTTP_200_OK)
def update_assessment(
    assessment_id: int,
    payload: AssessmentUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.update_assessment(db, assessment_id, payload, current_user)
    return success_response(
        data=AssessmentOut.from_model(exam).model_dump(),
        message="Assessment updated successfully"
    )

# ── 5. Delete Assessment ───────────────────────────────────────────────────────
@router.delete("/{assessment_id}", status_code=status.HTTP_200_OK)
def delete_assessment(
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    AssessmentService.delete_assessment(db, assessment_id, current_user)
    return success_response(
        data={"deleted": True, "assessment_id": assessment_id},
        message="Assessment deleted successfully"
    )

# ── 6. Lifecycle: Publish Assessment ───────────────────────────────────────────
@router.post("/{assessment_id}/publish", status_code=status.HTTP_200_OK)
def publish_assessment(
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.publish_assessment(db, assessment_id, current_user)
    return success_response(
        data=AssessmentOut.from_model(exam).model_dump(),
        message="Assessment published successfully"
    )

# ── 7. Lifecycle: Schedule Assessment ──────────────────────────────────────────
@router.post("/{assessment_id}/schedule", status_code=status.HTTP_200_OK)
def schedule_assessment(
    assessment_id: int,
    payload: AssessmentScheduleRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.schedule_assessment(db, assessment_id, payload, current_user)
    return success_response(
        data=AssessmentOut.from_model(exam).model_dump(),
        message="Assessment scheduled successfully"
    )

# ── 8. Lifecycle: Archive Assessment ───────────────────────────────────────────
@router.post("/{assessment_id}/archive", status_code=status.HTTP_200_OK)
def archive_assessment(
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.archive_assessment(db, assessment_id, current_user)
    return success_response(
        data=AssessmentOut.from_model(exam).model_dump(),
        message="Assessment archived successfully"
    )

# ── 9. Assignment: Assign Candidates ───────────────────────────────────────────
@router.post("/{assessment_id}/assign-candidates", status_code=status.HTTP_200_OK)
def assign_candidates(
    assessment_id: int,
    payload: CandidateAssignmentRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    result = AssessmentService.assign_candidates(db, assessment_id, payload, current_user)
    return success_response(
        data=result,
        message=f"Assigned {result['assigned_count']} candidates successfully."
    )

# ── 10. Assignment: Assign Groups ──────────────────────────────────────────────
@router.post("/{assessment_id}/assign-groups", status_code=status.HTTP_200_OK)
def assign_groups(
    assessment_id: int,
    payload: GroupAssignmentRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    result = AssessmentService.assign_groups(db, assessment_id, payload, current_user)
    return success_response(
        data=result,
        message=f"Assigned {result['assigned_groups_count']} groups successfully."
    )

# ── 11. Assignment: Get Assignment Details ─────────────────────────────────────
@router.get("/{assessment_id}/assignments", status_code=status.HTTP_200_OK)
def get_assignments(
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    details = AssessmentService.get_assignment_details(db, assessment_id, current_user)
    return success_response(
        data=details.model_dump(),
        message="Assignment details retrieved successfully"
    )

# ── 12. Statistics ─────────────────────────────────────────────────────────────
@router.get("/{assessment_id}/statistics", status_code=status.HTTP_200_OK)
def get_statistics(
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    stats = AssessmentService.get_assessment_statistics(db, assessment_id, current_user)
    return success_response(
        data=stats.model_dump(),
        message="Assessment statistics retrieved successfully"
    )

# ── 13. Assessment Question Bank Mappings ─────────────────────────────────────
@router.post("/{assessment_id}/questions", status_code=status.HTTP_200_OK)
def map_assessment_questions(
    assessment_id: int,
    payload: "AssessmentQuestionMapRequest",
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    from modules.questions.service import QuestionBankService
    result = QuestionBankService.map_questions_to_assessment(db, assessment_id, payload, current_user)
    return success_response(
        data=result.model_dump(),
        message=f"Mapped questions to assessment successfully."
    )

@router.get("/{assessment_id}/questions", status_code=status.HTTP_200_OK)
def list_assessment_questions(
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    from modules.questions.service import QuestionBankService
    result = QuestionBankService.list_assessment_questions(db, assessment_id, current_user)
    return success_response(
        data=result.model_dump(),
        message="Assessment mapped questions retrieved successfully"
    )

@router.delete("/{assessment_id}/questions/{bank_question_id}", status_code=status.HTTP_200_OK)
def remove_assessment_question(
    assessment_id: int,
    bank_question_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    from modules.questions.service import QuestionBankService
    QuestionBankService.remove_question_from_assessment(db, assessment_id, bank_question_id, current_user)
    return success_response(
        data={"removed": True, "bank_question_id": bank_question_id},
        message="Question removed from assessment successfully"
    )

@router.put("/{assessment_id}/questions/reorder", status_code=status.HTTP_200_OK)
def reorder_assessment_questions(
    assessment_id: int,
    payload: "AssessmentQuestionReorderRequest",
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    from modules.questions.service import QuestionBankService
    result = QuestionBankService.reorder_assessment_questions(db, assessment_id, payload, current_user)
    return success_response(
        data=result.model_dump(),
        message="Assessment questions reordered successfully"
    )

# ── Adaptive Testing Endpoints ───────────────────────────────────────────────
@router.post("/{assessment_id}/adaptive/start", status_code=status.HTTP_200_OK)
def start_adaptive_session(
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.get_assessment(db, assessment_id, current_user)
    if not exam.is_adaptive:
        raise HTTPException(status_code=400, detail="This assessment is not configured for adaptive testing.")
    from routers.student_r import get_or_create_exam_session
    session = get_or_create_exam_session(db, assessment_id, current_user.id, exam)
    state = AdaptiveService.initialize_adaptive_session(db, session, exam)
    return success_response(
        data=state,
        message="Adaptive assessment session initialized"
    )

@router.post("/{assessment_id}/adaptive/submit-next", status_code=status.HTTP_200_OK)
def submit_adaptive_answer_and_next(
    assessment_id: int,
    payload: AdaptiveSubmitRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.get_assessment(db, assessment_id, current_user)
    session = db.query(models.ExamSession).filter(
        models.ExamSession.exam_id == assessment_id,
        models.ExamSession.student_id == current_user.id,
        models.ExamSession.status == "in_progress"
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Active exam session not found.")
    res = AdaptiveService.submit_answer_and_advance(
        db=db,
        exam_session=session,
        exam=exam,
        question_id=payload.question_id,
        selected_option_id=payload.selected_option_id,
        answer_text=payload.answer_text
    )
    return success_response(
        data=res,
        message="Adaptive answer submitted"
    )

@router.get("/{assessment_id}/adaptive/state", status_code=status.HTTP_200_OK)
def get_adaptive_state(
    assessment_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    session = db.query(models.ExamSession).filter(
        models.ExamSession.exam_id == assessment_id,
        models.ExamSession.student_id == current_user.id
    ).order_by(models.ExamSession.started_at.desc()).first()
    if not session or not session.adaptive_state:
        raise HTTPException(status_code=404, detail="Adaptive session state not found.")
    import json
    state = json.loads(session.adaptive_state) if isinstance(session.adaptive_state, str) else session.adaptive_state
    return success_response(
        data=state,
        message="Adaptive session state retrieved"
    )

# ── Attempt Policy & Consolidated Grade Endpoints ───────────────────────────
@router.get("/{assessment_id}/eligibility", status_code=status.HTTP_200_OK)
def check_attempt_eligibility(
    assessment_id: int,
    student_id: Optional[int] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.get_assessment(db, assessment_id, current_user)
    target_student_id = student_id if (student_id and current_user.role in ("examiner", "teacher", "org_admin", "super_admin")) else current_user.id
    res = AttemptPolicyService.check_attempt_eligibility(db, exam, target_student_id)
    return success_response(
        data=res,
        message="Attempt eligibility evaluated"
    )

@router.get("/{assessment_id}/consolidated-grade", status_code=status.HTTP_200_OK)
def get_consolidated_grade(
    assessment_id: int,
    student_id: Optional[int] = Query(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    exam = AssessmentService.get_assessment(db, assessment_id, current_user)
    target_student_id = student_id if (student_id and current_user.role in ("examiner", "teacher", "org_admin", "super_admin")) else current_user.id
    res = AttemptPolicyService.compute_consolidated_grade(db, exam, target_student_id)
    return success_response(
        data=res,
        message="Consolidated grade computed"
    )

# ── Section Progression Endpoints ───────────────────────────────────────────
@router.post("/{assessment_id}/sections/{section_id}/complete", status_code=status.HTTP_200_OK)
def complete_assessment_section(
    assessment_id: int,
    section_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    session = db.query(models.ExamSession).filter(
        models.ExamSession.exam_id == assessment_id,
        models.ExamSession.student_id == current_user.id,
        models.ExamSession.status == "in_progress"
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Active exam session not found.")

    access_check = SectionService.can_access_section(db, session, section_id)
    if not access_check["allowed"]:
        raise HTTPException(status_code=403, detail=access_check["reason"])

    updated_session = SectionService.complete_section(db, session, section_id)
    return success_response(
        data={
            "completed_section_id": section_id,
            "next_section_id": updated_session.current_section_id,
            "completed_sections": SectionService.get_completed_section_ids(updated_session)
        },
        message="Section marked as completed successfully"
    )
