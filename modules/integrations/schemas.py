"""
modules/integrations/schemas.py
-------------------------------
Pydantic v2 schemas for:
1. Integration discovery, configuration, and connection testing
2. Question Generator request, preview, validation, and approval
3. ServiceNow outbound synchronization, idempotency, and retry
4. Integration execution logs and audit trail
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime


# =============================================================================
# 1. INTEGRATION CONFIGURATION & CONNECTION SCHEMAS
# =============================================================================
class IntegrationConfigOut(BaseModel):
    name: str
    display_name: str
    description: str
    organization_id: Optional[int] = None
    is_enabled: bool = True
    connection_status: str = "untested"
    base_url: Optional[str] = None
    auth_type: str = "none"
    masked_credentials: Dict[str, str] = {}
    config_metadata: Dict[str, Any] = {}
    last_tested_at: Optional[str] = None
    last_synced_at: Optional[str] = None
    last_error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class IntegrationConfigUpdate(BaseModel):
    base_url: Optional[str] = None
    auth_type: Optional[str] = None # none, api_key, basic, bearer
    credentials: Optional[Dict[str, str]] = None
    config_metadata: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class IntegrationToggleRequest(BaseModel):
    is_enabled: bool


class TestConnectionResponse(BaseModel):
    integration_name: str
    status: str # connected, error
    latency_ms: Optional[float] = None
    message: str
    tested_at: str
    details: Optional[Dict[str, Any]] = None


# =============================================================================
# 2. QUESTION GENERATOR SCHEMAS
# =============================================================================
class QuestionGenerationRequest(BaseModel):
    assessment_id: Optional[int] = None
    subject: str = Field(..., min_length=1, description="Subject domain, e.g. Computer Science")
    topic: str = Field(..., min_length=1, description="Topic, e.g. Binary Search Trees")
    difficulty: str = Field("medium", description="easy, medium, hard")
    question_type: str = Field("single_choice", description="single_choice, multiple_choice, true_false, short_answer, descriptive, code, all")
    quantity: int = Field(5, ge=1, le=50, description="Number of questions to generate (1-50)")
    custom_prompt: Optional[str] = None
    default_marks: Optional[float] = 1.0
    default_negative_marks: Optional[float] = 0.0


class GeneratedOptionSchema(BaseModel):
    text: str = Field(..., min_length=1)
    is_correct: bool = False
    explanation: Optional[str] = None


class GeneratedQuestionItem(BaseModel):
    index: int
    text: str = Field(..., min_length=3)
    question_type: str = "single_choice"
    subject: str
    topic: str
    difficulty: str = "medium"
    marks: float = 1.0
    negative_marks: float = 0.0
    explanation: Optional[str] = None
    tags: Optional[List[str]] = []
    options: Optional[List[GeneratedOptionSchema]] = []
    type_config: Optional[Dict[str, Any]] = {}
    is_valid: bool = True
    validation_notes: Optional[str] = None


class QuestionBatchPreviewResponse(BaseModel):
    batch_id: str
    source_model: str
    total_generated: int
    valid_count: int
    invalid_count: int
    target_assessment_id: Optional[int] = None
    questions: List[GeneratedQuestionItem]


class QuestionApprovalSubmitRequest(BaseModel):
    batch_id: str
    questions: List[GeneratedQuestionItem]
    approved_indices: Optional[List[int]] = None # None means approve all valid
    target_assessment_id: Optional[int] = None
    publish_status: Optional[str] = "draft" # Default to 'draft'; never automatically published


class QuestionApprovalResponse(BaseModel):
    batch_id: str
    approved_count: int
    rejected_count: int
    duplicate_count: int
    imported_bank_question_ids: List[int]
    mapped_assessment_question_ids: List[int] = []
    message: str


# =============================================================================
# 3. SERVICENOW SYNCHRONIZATION SCHEMAS
# =============================================================================
class ServiceNowSyncRequest(BaseModel):
    exam_id: int
    sync_type: str = Field("all", description="metadata, results, all")
    force_resync: bool = False


class ServiceNowSyncResponse(BaseModel):
    sync_id: Optional[int] = None
    integration_name: str = "servicenow"
    exam_id: int
    status: str # success, partial_success, failed
    records_synced: int
    records_failed: int
    external_reference_ids: Dict[str, str] = {}
    message: str
    synced_at: str


class SyncRecordOut(BaseModel):
    id: int
    integration_name: str
    organization_id: Optional[int] = None
    entity_type: str
    entity_id: int
    external_reference_id: Optional[str] = None
    idempotency_key: str
    status: str
    attempts: int
    last_error: Optional[str] = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class SyncRetryRequest(BaseModel):
    sync_id: int


# =============================================================================
# 4. INTEGRATION LOGS SCHEMAS
# =============================================================================
class IntegrationLogOut(BaseModel):
    id: int
    integration_name: str
    organization_id: Optional[int] = None
    operation: str
    entity_reference: Optional[str] = None
    status: str
    attempt_count: int
    request_summary: Optional[str] = None
    response_summary: Optional[str] = None
    error_details: Optional[str] = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class IntegrationLogsListResponse(BaseModel):
    total: int
    logs: List[IntegrationLogOut]
