"""

modules/integrations/router.py

------------------------------

FastAPI endpoints for Phase 8 External Integrations & Interoperability:

1. Integration discovery, configuration, and connection testing

2. Question Generator request, preview, validation, and approval

3. ServiceNow outbound synchronization, idempotency, and retries

4. External proctoring telemetry contract boundaries

5. Integration execution logs and audit trail

Mounted under /api/v1/integrations/

"""

from typing import List, Optional, Dict, Any, Union

from fastapi import APIRouter, Depends, HTTPException, status, Query

from sqlalchemy.orm import Session



import database, models, auth

from core.responses import success_response

from modules.integrations.contracts import (

    QuestionGeneratorImportPayload,

    QuestionGeneratorBatch,

    QuestionApprovalRequest,

    ProctoringSessionSyncPayload,

    ServiceNowAssessmentSyncContract

)

from modules.integrations.schemas import (

    IntegrationConfigOut,

    IntegrationConfigUpdate,

    IntegrationToggleRequest,

    TestConnectionResponse,

    QuestionGenerationRequest,

    QuestionBatchPreviewResponse,

    QuestionApprovalSubmitRequest,

    QuestionApprovalResponse,

    ServiceNowSyncRequest,

    ServiceNowSyncResponse,

    SyncRecordOut,

    IntegrationLogsListResponse

)

from modules.integrations.service import IntegrationService



router = APIRouter(tags=["API v1 - Integrations"])





# =============================================================================

# 1. INTEGRATION DISCOVERY

# =============================================================================

@router.get(

    "/",

    response_model=List[IntegrationConfigOut],

    status_code=status.HTTP_200_OK

)

def list_integrations(

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth_api)

):

    """List all available external integrations, their connection states, and masked configs."""

    return IntegrationService.list_integrations(db, current_user)





# =============================================================================

# 2. INTEGRATION AUDIT LOGS (Defined before wildcard routes)

# =============================================================================

@router.get(

    "/logs",

    response_model=IntegrationLogsListResponse,

    status_code=status.HTTP_200_OK

)

def get_integration_logs(

    integration_name: Optional[str] = Query(None, description="Filter by integration name"),

    limit: int = Query(50, ge=1, le=200),

    offset: int = Query(0, ge=0),

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_examiner_api)

):

    """

    Fetches sanitized execution logs for integration operations.

    Contains zero sensitive credentials or passwords.

    """

    return IntegrationService.get_logs(db, integration_name, limit, offset, current_user)





# =============================================================================

# 3. QUESTION GENERATOR WORKFLOW & CONTRACT BOUNDARIES

# =============================================================================

@router.post("/question-generator/validate", status_code=status.HTTP_200_OK)

def validate_question_generator_payload(

    payload: QuestionGeneratorImportPayload,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth_api)

):

    """Validate question generator boundary contract and ensure target assessment exists."""

    exam = db.query(models.Exam).filter(models.Exam.id == payload.assessment_id).first()

    if not exam:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target assessment not found.")



    return success_response(

        data={

            "valid": True,

            "assessment_id": payload.assessment_id,

            "assessment_title": exam.title,

            "question_count": len(payload.questions),

            "source_model": payload.source_model

        },

        message="Question Generator payload validated successfully against contract boundary."

    )





@router.post("/question-generator/preview", status_code=status.HTTP_200_OK)

def preview_generated_questions(

    batch: QuestionGeneratorBatch,

    current_user: models.User = Depends(auth.require_auth_api)

):

    """Preview AI-generated questions before committing to the Question Bank."""

    formatted_preview = []

    for idx, q in enumerate(batch.questions):

        correct_count = sum(1 for o in q.options if o.is_correct)

        formatted_preview.append({

            "index": idx,

            "text": q.text,

            "subject": q.subject,

            "topic": q.topic,

            "difficulty": q.difficulty,

            "options_count": len(q.options),

            "correct_count": correct_count,

            "valid": correct_count >= 1

        })



    return success_response(

        data={

            "batch_id": batch.batch_id,

            "source_model": batch.source_model,

            "total_questions": len(batch.questions),

            "preview": formatted_preview

        },

        message="Question generator preview prepared successfully."

    )





@router.post(

    "/question-generator/request",

    response_model=QuestionBatchPreviewResponse,

    status_code=status.HTTP_200_OK

)

def request_generated_questions(

    req: QuestionGenerationRequest,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_examiner_api)

):

    """

    Requests AI-generated questions from external Question Generator service.

    Returns preview batch with validation checks across all 6 question types.

    """

    return IntegrationService.request_generated_questions(db, req, current_user)





@router.post(

    "/question-generator/approve",

    status_code=status.HTTP_200_OK

)

def approve_generated_questions(

    payload: Dict[str, Any],

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_examiner_api)

):

    """

    Approves validated questions, prevents duplicates in Question Bank,

    imports them with status 'draft' (never auto-published), and optionally

    maps them to an active assessment.

    """

    res = IntegrationService.approve_and_import_questions(db, payload, current_user)

    return res





# =============================================================================

# 4. EXTERNAL PROCTORING TELEMETRY BOUNDARY

# =============================================================================

@router.post("/exam-proctor/validate-event", status_code=status.HTTP_200_OK)

def validate_proctoring_event(

    payload: ProctoringSessionSyncPayload,

    current_user: models.User = Depends(auth.require_auth_api)

):

    """Validate external proctoring telemetry contract."""

    return success_response(

        data={

            "valid": True,

            "session_id": payload.session_id,

            "event_count": len(payload.events)

        },

        message="Proctoring telemetry contract validated successfully."

    )





# =============================================================================

# 5. SERVICENOW SYNCHRONIZATION

# =============================================================================

@router.post("/servicenow/validate-sync", status_code=status.HTTP_200_OK)

def validate_servicenow_sync(

    payload: ServiceNowAssessmentSyncContract,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth_api)

):

    """Validate ServiceNow enterprise integration contract."""

    exam = db.query(models.Exam).filter(models.Exam.id == payload.assessment_id).first()

    if not exam:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target assessment not found.")



    return success_response(

        data={

            "valid": True,

            "assessment_id": payload.assessment_id,

            "servicenow_course_sys_id": payload.servicenow_course_sys_id,

            "auto_sync_grades": payload.auto_sync_grades

        },

        message="ServiceNow contract boundary validated successfully."

    )





@router.post(

    "/servicenow/sync",

    response_model=ServiceNowSyncResponse,

    status_code=status.HTTP_200_OK

)

def sync_to_servicenow(

    req: ServiceNowSyncRequest,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_examiner_api)

):

    """

    Triggers outbound synchronization of assessment metadata and candidate scores

    to ServiceNow REST tables. Enforces idempotency and candidate data privacy.

    """

    return IntegrationService.sync_to_servicenow(db, req, current_user)





@router.get(

    "/servicenow/history",

    response_model=List[SyncRecordOut],

    status_code=status.HTTP_200_OK

)

def get_servicenow_sync_history(

    exam_id: Optional[int] = Query(None, description="Optional assessment ID filter"),

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_examiner_api)

):

    """Retrieves ServiceNow synchronization history and idempotency records."""

    return IntegrationService.get_sync_history(db, "servicenow", exam_id, current_user)





@router.post(

    "/servicenow/retry/{sync_id}",

    status_code=status.HTTP_200_OK

)

def retry_failed_sync(

    sync_id: int,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_examiner_api)

):

    """Manually retries a failed synchronization record."""

    return IntegrationService.retry_failed_sync(db, sync_id, current_user)





# =============================================================================

# 6. PARAMETERIZED PROVIDER ENDPOINTS (Defined after all specific routes)

# =============================================================================

@router.get(

    "/{name}",

    response_model=IntegrationConfigOut,

    status_code=status.HTTP_200_OK

)

def get_integration(

    name: str,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_auth_api)

):

    """Retrieve detailed configuration for a specific integration provider."""

    return IntegrationService.get_integration_detail(db, name, current_user)





@router.post(

    "/{name}/configure",

    response_model=IntegrationConfigOut,

    status_code=status.HTTP_200_OK

)

def configure_integration(

    name: str,

    payload: IntegrationConfigUpdate,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_org_admin_api)

):

    """

    Configures an external integration provider (instance URL, auth credentials, mappings).

    Restricted to Organization Admins and Super Admins.

    """

    return IntegrationService.update_config(db, name, payload, current_user)





@router.post(

    "/{name}/toggle",

    response_model=IntegrationConfigOut,

    status_code=status.HTTP_200_OK

)

def toggle_integration(

    name: str,

    payload: IntegrationToggleRequest,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_org_admin_api)

):

    """Enables or disables an integration provider."""

    return IntegrationService.toggle_integration(db, name, payload.is_enabled, current_user)





@router.post(

    "/{name}/test",

    response_model=TestConnectionResponse,

    status_code=status.HTTP_200_OK

)

def test_connection(

    name: str,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_examiner_api)

):

    """Tests live or mocked connectivity and authentication to the external service."""

    return IntegrationService.test_connection(db, name, current_user)
