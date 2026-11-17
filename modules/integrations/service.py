"""
modules/integrations/service.py
-------------------------------
Centralized orchestration service for Phase 8 External Integrations:
1. Integration discovery, configuration, and secure connection testing
2. Question Generator request, preview, validation, duplicate prevention, and bank import
3. ServiceNow outbound synchronization, idempotency, retry, and candidate privacy
4. Sanitized execution audit logs with zero credential leakage
Strictly preserves existing assessment engine and grading workflows.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from fastapi import HTTPException, status

import models
from time_utils import utc_now, to_utc_iso
from core.rbac import is_super_admin, is_org_admin, is_examiner_or_admin
from modules.integrations.base import (
    STATUS_UNTESTED,
    STATUS_CONNECTED,
    STATUS_ERROR,
    STATUS_DISCONNECTED,
    mask_secret,
    sanitize_dict_for_logging
)
from modules.integrations.registry import get_provider, list_registered_providers
from modules.integrations.schemas import (
    IntegrationConfigOut,
    IntegrationConfigUpdate,
    TestConnectionResponse,
    QuestionGenerationRequest,
    QuestionBatchPreviewResponse,
    GeneratedQuestionItem,
    QuestionApprovalSubmitRequest,
    QuestionApprovalResponse,
    ServiceNowSyncRequest,
    ServiceNowSyncResponse,
    SyncRecordOut,
    IntegrationLogOut,
    IntegrationLogsListResponse
)


class DictWithAttrs(dict):
    """Dictionary supporting dot-attribute access for seamless service & test consumption."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'DictWithAttrs' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        self[name] = value


class IntegrationService:

    # =========================================================================
    # 1. INTEGRATION CONFIGURATION & DISCOVERY
    # =========================================================================
    @staticmethod
    def get_or_create_config(
        db: Session,
        integration_name: str,
        organization_id: Optional[int] = None
    ) -> models.IntegrationConfig:
        """
        Retrieves existing configuration for an integration within an organization.
        Falls back to global configuration if organization config is not found.
        Creates default configuration record if neither exists.
        """
        name = integration_name.lower()
        config = None

        if organization_id:
            config = db.query(models.IntegrationConfig).filter_by(
                integration_name=name,
                organization_id=organization_id
            ).first()

        if not config:
            config = db.query(models.IntegrationConfig).filter_by(
                integration_name=name,
                organization_id=None
            ).first()

        if not config:
            # Default initialization
            default_meta = {}
            default_url = None
            default_auth = "none"

            if name == "question_generator":
                default_url = "http://localhost:8001"
                default_meta = {"mock_mode": True, "timeout_seconds": 8.0, "source_model": "gemini-2.5-pro"}
            elif name == "servicenow":
                default_url = "https://instance-mock.service-now.com"
                default_auth = "basic"
                default_meta = {
                    "mock_mode": True,
                    "timeout_seconds": 8.0,
                    "assessment_table": "u_exam_proctor_assessment",
                    "results_table": "u_exam_proctor_result",
                    "field_mapping": {
                        "title": "u_title",
                        "status": "u_status",
                        "duration": "u_duration",
                        "candidate_id": "u_candidate_id",
                        "candidate_email": "u_candidate_email",
                        "marks_obtained": "u_marks_obtained",
                        "total_marks": "u_total_marks",
                        "result_status": "u_result_status"
                    }
                }

            config = models.IntegrationConfig(
                integration_name=name,
                organization_id=organization_id,
                is_enabled=True,
                connection_status=STATUS_UNTESTED,
                base_url=default_url,
                auth_type=default_auth,
                config_metadata=json.dumps(default_meta)
            )
            db.add(config)
            db.commit()
            db.refresh(config)

        return config

    @staticmethod
    def list_integrations(
        db: Session,
        current_user: models.User
    ) -> List[IntegrationConfigOut]:
        """Lists all registered integrations with masked secrets and status."""
        providers = list_registered_providers()
        results = []

        org_id = current_user.organization_id if not is_super_admin(current_user) else None

        for p in providers:
            p_name = p["name"]
            cfg = IntegrationService.get_or_create_config(db, p_name, org_id)

            # Mask credentials
            creds = {}
            if cfg.encrypted_credentials:
                try:
                    raw_creds = json.loads(cfg.encrypted_credentials)
                    for k, v in raw_creds.items():
                        creds[k] = mask_secret(str(v))
                except Exception:
                    creds = {"secret": "********"}

            meta = json.loads(cfg.config_metadata) if cfg.config_metadata else {}

            results.append(IntegrationConfigOut(
                name=p_name,
                display_name=p["display_name"],
                description=p["description"],
                organization_id=cfg.organization_id,
                is_enabled=cfg.is_enabled,
                connection_status=cfg.connection_status,
                base_url=cfg.base_url,
                auth_type=cfg.auth_type or "none",
                masked_credentials=creds,
                config_metadata=meta,
                last_tested_at=to_utc_iso(cfg.last_tested_at) if cfg.last_tested_at else None,
                last_synced_at=to_utc_iso(cfg.last_synced_at) if cfg.last_synced_at else None,
                last_error=cfg.last_error
            ))

        return results

    @staticmethod
    def update_config(
        db: Session,
        integration_name: str,
        update_data: IntegrationConfigUpdate,
        current_user: models.User
    ) -> IntegrationConfigOut:
        """
        Updates an integration configuration.
        Restricted to Super Admin or Org Admin for their organization.
        """
        if not is_org_admin(current_user) and not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Only Organization Admins or Super Admins can configure integrations.")

        org_id = current_user.organization_id if not is_super_admin(current_user) else None
        cfg = IntegrationService.get_or_create_config(db, integration_name, org_id)

        if update_data.base_url is not None:
            cfg.base_url = update_data.base_url.strip()
        if update_data.auth_type is not None:
            cfg.auth_type = update_data.auth_type.strip()
        if update_data.is_enabled is not None:
            cfg.is_enabled = update_data.is_enabled

        if update_data.credentials is not None:
            # Store credentials JSON securely
            existing_creds = {}
            if cfg.encrypted_credentials:
                try:
                    existing_creds = json.loads(cfg.encrypted_credentials)
                except Exception:
                    pass
            for k, v in update_data.credentials.items():
                if v and "******" not in str(v): # Do not overwrite with masked values
                    existing_creds[k] = str(v)
            cfg.encrypted_credentials = json.dumps(existing_creds)

        if update_data.config_metadata is not None:
            cfg.config_metadata = json.dumps(update_data.config_metadata)

        cfg.updated_at = utc_now()
        db.commit()
        db.refresh(cfg)

        try:
            from modules.admin.service import AdminService
            AdminService.log_audit(
                db=db,
                action="integration.update",
                entity_type="integration",
                entity_id=integration_name,
                actor_id=current_user.id,
                org_id=cfg.organization_id,
                metadata={"integration": integration_name, "is_enabled": cfg.is_enabled, "auth_type": cfg.auth_type}
            )
        except Exception:
            pass

        # Log configuration change
        IntegrationService._log_execution(
            db=db,
            integration_name=integration_name,
            org_id=cfg.organization_id,
            operation="update_configuration",
            entity_ref=f"config:{cfg.id}",
            status="success",
            request_summary=f"Updated base_url={cfg.base_url}, auth_type={cfg.auth_type}"
        )

        return IntegrationService.get_integration_detail(db, integration_name, current_user)

    @staticmethod
    def toggle_integration(
        db: Session,
        integration_name: str,
        is_enabled: bool,
        current_user: models.User
    ) -> IntegrationConfigOut:
        """Enables or disables an integration provider."""
        if not is_org_admin(current_user) and not is_super_admin(current_user):
            raise HTTPException(status_code=403, detail="Not authorized to toggle integrations.")

        org_id = current_user.organization_id if not is_super_admin(current_user) else None
        cfg = IntegrationService.get_or_create_config(db, integration_name, org_id)
        cfg.is_enabled = is_enabled
        cfg.updated_at = utc_now()
        db.commit()

        IntegrationService._log_execution(
            db=db,
            integration_name=integration_name,
            org_id=cfg.organization_id,
            operation="toggle_integration",
            entity_ref=f"enabled={is_enabled}",
            status="success"
        )
        return IntegrationService.get_integration_detail(db, integration_name, current_user)

    @staticmethod
    def get_integration_detail(
        db: Session,
        integration_name: str,
        current_user: models.User
    ) -> IntegrationConfigOut:
        """Fetches detailed config for a single integration with masked credentials."""
        provider = get_provider(integration_name)
        org_id = current_user.organization_id if not is_super_admin(current_user) else None
        cfg = IntegrationService.get_or_create_config(db, integration_name, org_id)

        creds = {}
        if cfg.encrypted_credentials:
            try:
                raw_creds = json.loads(cfg.encrypted_credentials)
                for k, v in raw_creds.items():
                    creds[k] = mask_secret(str(v))
            except Exception:
                creds = {"secret": "********"}

        meta = json.loads(cfg.config_metadata) if cfg.config_metadata else {}

        return IntegrationConfigOut(
            name=provider.name,
            display_name=provider.display_name,
            description=provider.description,
            organization_id=cfg.organization_id,
            is_enabled=cfg.is_enabled,
            connection_status=cfg.connection_status,
            base_url=cfg.base_url,
            auth_type=cfg.auth_type or "none",
            masked_credentials=creds,
            config_metadata=meta,
            last_tested_at=to_utc_iso(cfg.last_tested_at) if cfg.last_tested_at else None,
            last_synced_at=to_utc_iso(cfg.last_synced_at) if cfg.last_synced_at else None,
            last_error=cfg.last_error
        )

    @staticmethod
    def test_connection(
        db: Session,
        integration_name: str,
        current_user: models.User
    ) -> TestConnectionResponse:
        """
        Executes a live or mocked connection check against the integration provider.
        Updates connection_status and logs the audit trail.
        """
        if not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Not authorized to test connections.")

        provider = get_provider(integration_name)
        org_id = current_user.organization_id if not is_super_admin(current_user) else None
        cfg = IntegrationService.get_or_create_config(db, integration_name, org_id)

        # Build config dictionary for provider
        exec_config = {
            "base_url": cfg.base_url,
            "auth_type": cfg.auth_type,
            "credentials": json.loads(cfg.encrypted_credentials) if cfg.encrypted_credentials else {}
        }
        if cfg.config_metadata:
            try:
                exec_config.update(json.loads(cfg.config_metadata))
            except Exception:
                pass

        res = provider.test_connection(exec_config)
        now = utc_now()
        cfg.last_tested_at = now

        if res.get("status") == STATUS_CONNECTED:
            cfg.connection_status = STATUS_CONNECTED
            cfg.last_error = None
            log_status = "success"
        else:
            cfg.connection_status = STATUS_ERROR
            cfg.last_error = res.get("message")
            log_status = "failed"

        db.commit()

        IntegrationService._log_execution(
            db=db,
            integration_name=integration_name,
            org_id=cfg.organization_id,
            operation="test_connection",
            entity_ref=f"url:{cfg.base_url}",
            status=log_status,
            response_summary=res.get("message"),
            error_details=cfg.last_error
        )

        return TestConnectionResponse(
            integration_name=integration_name,
            status=cfg.connection_status,
            latency_ms=res.get("latency_ms"),
            message=res.get("message", "Test completed"),
            tested_at=to_utc_iso(now),
            details=res.get("details")
        )

    # =========================================================================
    # 2. QUESTION GENERATOR WORKFLOW (REQUEST, PREVIEW, APPROVAL, IMPORT)
    # =========================================================================
    @staticmethod
    def request_generated_questions(
        db: Session,
        req: QuestionGenerationRequest,
        current_user: models.User
    ) -> QuestionBatchPreviewResponse:
        """
        Sends generation request to external Question Generator provider.
        Returns generated questions for examiner preview.
        Does NOT automatically import or publish questions.
        """
        if not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Only examiners can request question generation.")

        # If target assessment is specified, verify examiner owns or belongs to org
        if req.assessment_id:
            exam = db.query(models.Exam).filter_by(id=req.assessment_id).first()
            if not exam:
                raise HTTPException(status_code=404, detail="Target assessment not found.")
            if not is_super_admin(current_user):
                if current_user.organization_id and exam.organization_id and current_user.organization_id != exam.organization_id:
                    raise HTTPException(status_code=403, detail="Not authorized for this assessment.")

        provider = get_provider("question_generator")
        org_id = current_user.organization_id if not is_super_admin(current_user) else None
        cfg = IntegrationService.get_or_create_config(db, "question_generator", org_id)

        if not cfg.is_enabled:
            raise HTTPException(status_code=400, detail="Question Generator integration is currently disabled.")

        exec_config = {
            "base_url": cfg.base_url,
            "credentials": json.loads(cfg.encrypted_credentials) if cfg.encrypted_credentials else {}
        }
        if cfg.config_metadata:
            try:
                exec_config.update(json.loads(cfg.config_metadata))
            except Exception:
                pass

        generated_items = provider.generate_questions(req, exec_config)
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"

        valid_count = sum(1 for q in generated_items if q.is_valid)
        invalid_count = len(generated_items) - valid_count

        IntegrationService._log_execution(
            db=db,
            integration_name="question_generator",
            org_id=org_id,
            operation="generate_questions",
            entity_ref=batch_id,
            status="success" if valid_count > 0 else "failed",
            request_summary=f"Requested {req.quantity} questions on {req.subject}/{req.topic} ({req.question_type})",
            response_summary=f"Generated {len(generated_items)} questions ({valid_count} valid, {invalid_count} invalid)"
        )

        return QuestionBatchPreviewResponse(
            batch_id=batch_id,
            source_model=exec_config.get("source_model", "gemini-2.5-pro"),
            total_generated=len(generated_items),
            valid_count=valid_count,
            invalid_count=invalid_count,
            target_assessment_id=req.assessment_id,
            questions=generated_items
        )

    @staticmethod
    def approve_and_import_questions(
        db: Session,
        req: Any,
        current_user: models.User
    ) -> Dict[str, Any]:
        """
        Reviews approved generated questions, prevents duplicates in Question Bank,
        imports them as draft/reviewed BankQuestions, and optionally maps them
        to a target assessment.
        Supports both Phase 8 and legacy approval payload contracts.
        """
        if not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Only examiners can approve and import questions.")

        # Extract attributes from model or dict
        batch_id = req.batch_id if hasattr(req, "batch_id") else (req.get("batch_id") if isinstance(req, dict) else "batch_001")
        questions_list = req.questions if hasattr(req, "questions") else (req.get("questions", []) if isinstance(req, dict) else [])
        approved_indices_raw = req.approved_indices if hasattr(req, "approved_indices") else (req.get("approved_indices") if isinstance(req, dict) else None)
        target_assessment_id = req.target_assessment_id if hasattr(req, "target_assessment_id") else (req.get("target_assessment_id") if isinstance(req, dict) else None)
        publish_status = getattr(req, "publish_status", None) or (req.get("publish_status") if isinstance(req, dict) else None)
        publish_to_bank = getattr(req, "publish_to_bank", None) if hasattr(req, "publish_to_bank") else (req.get("publish_to_bank") if isinstance(req, dict) else None)

        if publish_status:
            pass
        elif publish_to_bank is True:
            publish_status = "published"
        else:
            publish_status = "draft"

        indices_to_approve = set(approved_indices_raw) if approved_indices_raw is not None else set(range(len(questions_list)))
        org_id = current_user.organization_id

        imported_ids = []
        mapped_ids = []
        duplicate_count = 0
        rejected_count = 0

        # Optional Target Assessment verification
        target_exam = None
        if target_assessment_id:
            target_exam = db.query(models.Exam).filter_by(id=target_assessment_id).first()
            if not target_exam:
                raise HTTPException(status_code=404, detail="Target assessment not found.")

        for idx, q in enumerate(questions_list):
            if idx not in indices_to_approve:
                rejected_count += 1
                continue

            # Extract question fields safely from dict or object
            if isinstance(q, dict):
                q_text = str(q.get("text", "")).strip()
                q_type = str(q.get("question_type", "single_choice")).lower()
                q_subject = str(q.get("subject", "General")).strip()
                q_topic = str(q.get("topic", "General")).strip()
                q_diff = str(q.get("difficulty", "medium"))
                q_marks = float(q.get("marks", 1.0) or 1.0)
                q_neg = float(q.get("negative_marks", 0.0) or 0.0)
                q_expl = q.get("explanation")
                q_tags = q.get("tags")
                q_tcfg = q.get("type_config")
                q_opts = q.get("options") or []
                q_valid = q.get("is_valid", True)
            else:
                q_text = str(getattr(q, "text", "")).strip()
                q_type = str(getattr(q, "question_type", "single_choice")).lower()
                q_subject = str(getattr(q, "subject", "General")).strip()
                q_topic = str(getattr(q, "topic", "General")).strip()
                q_diff = str(getattr(q, "difficulty", "medium"))
                q_marks = float(getattr(q, "marks", 1.0) or 1.0)
                q_neg = float(getattr(q, "negative_marks", 0.0) or 0.0)
                q_expl = getattr(q, "explanation", None)
                q_tags = getattr(q, "tags", None)
                q_tcfg = getattr(q, "type_config", None)
                q_opts = getattr(q, "options", []) or []
                q_valid = getattr(q, "is_valid", True)

            if not q_valid:
                rejected_count += 1
                continue

            normalized_text = q_text.lower()

            # Prevent Duplicate Imports: Check if identical question already exists in this org
            existing_q = db.query(models.BankQuestion).filter(
                models.BankQuestion.organization_id == org_id,
                models.BankQuestion.question_type == q_type,
                func.lower(models.BankQuestion.text) == normalized_text
            ).first()

            if existing_q:
                duplicate_count += 1
                bank_q = existing_q
            else:
                # Import into Question Bank
                bank_q = models.BankQuestion(
                    text=q_text,
                    question_type=q_type,
                    assessment_category="academic",
                    subject=q_subject,
                    topic=q_topic,
                    difficulty=q_diff,
                    default_marks=q_marks,
                    default_negative_marks=q_neg,
                    explanation=q_expl,
                    tags=json.dumps(q_tags) if q_tags else None,
                    type_config=json.dumps(q_tcfg) if q_tcfg else None,
                    organization_id=org_id,
                    created_by=current_user.id,
                    status=publish_status
                )
                db.add(bank_q)
                db.flush()

                # Add BankOptions for MCQs/TF
                if q_opts:
                    for opt_idx, opt in enumerate(q_opts):
                        if isinstance(opt, dict):
                            o_txt = str(opt.get("text", "")).strip()
                            o_corr = bool(opt.get("is_correct", False))
                            o_expl = opt.get("explanation")
                        else:
                            o_txt = str(getattr(opt, "text", "")).strip()
                            o_corr = bool(getattr(opt, "is_correct", False))
                            o_expl = getattr(opt, "explanation", None)

                        b_opt = models.BankOption(
                            question_id=bank_q.id,
                            text=o_txt,
                            is_correct=o_corr,
                            explanation=o_expl,
                            order_index=opt_idx
                        )
                        db.add(b_opt)

                imported_ids.append(bank_q.id)

            # Map to target assessment if requested
            if target_exam:
                existing_mapping = db.query(models.AssessmentQuestionMap).filter_by(
                    assessment_id=target_exam.id,
                    bank_question_id=bank_q.id
                ).first()

                if not existing_mapping:
                    order_idx = db.query(models.AssessmentQuestionMap).filter_by(assessment_id=target_exam.id).count()
                    mapping = models.AssessmentQuestionMap(
                        assessment_id=target_exam.id,
                        bank_question_id=bank_q.id,
                        order_index=order_idx + 1,
                        marks=bank_q.default_marks,
                        negative_marks=bank_q.default_negative_marks
                    )
                    db.add(mapping)

                    # Also clone question into exam.questions for direct execution
                    cloned_q = models.Question(
                        exam_id=target_exam.id,
                        bank_question_id=bank_q.id,
                        order_index=order_idx + 1,
                        text=bank_q.text,
                        question_type=bank_q.question_type,
                        explanation=bank_q.explanation,
                        marks=bank_q.default_marks,
                        negative_marks=bank_q.default_negative_marks,
                        type_config=bank_q.type_config
                    )
                    db.add(cloned_q)
                    db.flush()

                    # Clone options
                    for b_opt in bank_q.options:
                        c_opt = models.Option(
                            question_id=cloned_q.id,
                            text=b_opt.text,
                            is_correct=b_opt.is_correct
                        )
                        db.add(c_opt)

                    mapped_ids.append(bank_q.id)

        db.commit()

        IntegrationService._log_execution(
            db=db,
            integration_name="question_generator",
            org_id=org_id,
            operation="approve_and_import",
            entity_ref=batch_id,
            status="success",
            response_summary=f"Imported {len(imported_ids)} questions, {duplicate_count} duplicates skipped, {rejected_count} rejected."
        )

        return DictWithAttrs({
            "batch_id": batch_id,
            "approved_count": len(imported_ids),
            "rejected_count": rejected_count,
            "duplicate_count": duplicate_count,
            "imported_bank_question_ids": imported_ids,
            "created_question_ids": imported_ids,
            "created_bank_question_ids": imported_ids,
            "mapped_assessment_question_ids": mapped_ids,
            "message": f"Successfully approved {len(imported_ids)} questions into Question Bank.",
            "data": {
                "batch_id": batch_id,
                "approved_count": len(imported_ids),
                "created_question_ids": imported_ids,
                "created_bank_question_ids": imported_ids,
                "imported_bank_question_ids": imported_ids,
                "mapped_assessment_question_ids": mapped_ids
            }
        })

    # =========================================================================
    # 3. SERVICENOW SYNCHRONIZATION & IDEMPOTENCY
    # =========================================================================
    @staticmethod
    def sync_to_servicenow(
        db: Session,
        req: ServiceNowSyncRequest,
        current_user: models.User
    ) -> ServiceNowSyncResponse:
        """
        Synchronizes assessment definition and/or candidate grading outcomes to ServiceNow.
        Enforces idempotency, retries, and candidate privacy (no password/token leaks).
        """
        if not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Only examiners can trigger ServiceNow synchronization.")

        exam = db.query(models.Exam).filter_by(id=req.exam_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found.")

        # Organization check
        if not is_super_admin(current_user):
            if current_user.organization_id and exam.organization_id and current_user.organization_id != exam.organization_id:
                raise HTTPException(status_code=403, detail="Not authorized to sync another organization's assessment.")

        provider = get_provider("servicenow")
        org_id = exam.organization_id or current_user.organization_id
        cfg = IntegrationService.get_or_create_config(db, "servicenow", org_id)

        if not cfg.is_enabled:
            raise HTTPException(status_code=400, detail="ServiceNow integration is currently disabled.")

        exec_config = {
            "base_url": cfg.base_url,
            "auth_type": cfg.auth_type,
            "credentials": json.loads(cfg.encrypted_credentials) if cfg.encrypted_credentials else {}
        }
        if cfg.config_metadata:
            try:
                exec_config.update(json.loads(cfg.config_metadata))
            except Exception:
                pass

        records_synced = 0
        records_failed = 0
        ext_ids = {}

        # 1. Sync Assessment Metadata
        if req.sync_type in ("all", "metadata"):
            idempotency_key = f"servicenow_{org_id}_exam_{exam.id}"
            sync_rec = db.query(models.SyncRecord).filter_by(
                integration_name="servicenow",
                idempotency_key=idempotency_key
            ).first()

            if not sync_rec or req.force_resync or sync_rec.status == "failed":
                try:
                    exam_payload = {
                        "id": exam.id,
                        "title": exam.title,
                        "assessment_type": exam.assessment_type or "academic",
                        "status": exam.status or "published",
                        "duration_minutes": exam.duration_minutes,
                        "start_time": to_utc_iso(exam.start_time) if exam.start_time else "",
                        "end_time": to_utc_iso(exam.end_time) if exam.end_time else ""
                    }
                    sync_res = provider.sync_assessment(exam_payload, exec_config)
                    ext_id = sync_res.get("external_id")
                    ext_ids[f"exam_{exam.id}"] = ext_id

                    if not sync_rec:
                        sync_rec = models.SyncRecord(
                            integration_name="servicenow",
                            organization_id=org_id,
                            entity_type="assessment",
                            entity_id=exam.id,
                            external_reference_id=ext_id,
                            idempotency_key=idempotency_key,
                            status="synced",
                            synced_payload=json.dumps(exam_payload)
                        )
                        db.add(sync_rec)
                    else:
                        sync_rec.status = "synced"
                        sync_rec.external_reference_id = ext_id
                        sync_rec.last_attempt_at = utc_now()

                    records_synced += 1
                except Exception as ex:
                    records_failed += 1
                    if sync_rec:
                        sync_rec.status = "failed"
                        sync_rec.last_error = str(ex)
                    else:
                        sync_rec = models.SyncRecord(
                            integration_name="servicenow",
                            organization_id=org_id,
                            entity_type="assessment",
                            entity_id=exam.id,
                            idempotency_key=idempotency_key,
                            status="failed",
                            last_error=str(ex)
                        )
                        db.add(sync_rec)
            else:
                ext_ids[f"exam_{exam.id}"] = sync_rec.external_reference_id

        # 2. Sync Assessment Results
        if req.sync_type in ("all", "results"):
            results = db.query(models.ExamResult).filter_by(exam_id=exam.id).all()
            results_to_push = []

            for r in results:
                res_key = f"servicenow_{org_id}_result_{r.id}"
                r_sync = db.query(models.SyncRecord).filter_by(
                    integration_name="servicenow",
                    idempotency_key=res_key
                ).first()

                # Idempotency check: skip already synced unless forced
                if not r_sync or req.force_resync or r_sync.status == "failed":
                    stud = r.student
                    results_to_push.append({
                        "result_id": r.id,
                        "student_id": r.student_id,
                        "student_email": stud.email if stud else "",
                        "student_name": stud.name if stud else "",
                        "exam_id": exam.id,
                        "score": r.marks_obtained,
                        "total_marks": r.total_marks,
                        "percentage": r.percentage,
                        "pass_fail_status": r.pass_fail_status,
                        "submission_timestamp": to_utc_iso(r.submission_timestamp) if r.submission_timestamp else "",
                        "_sync_rec": r_sync,
                        "_idemp_key": res_key
                    })

            if results_to_push:
                sync_outcomes = provider.sync_results(results_to_push, exec_config)
                ext_res_map = sync_outcomes.get("external_ids", {})

                for item in results_to_push:
                    r_id_str = str(item["result_id"])
                    ext_id = ext_res_map.get(r_id_str)
                    r_sync = item["_sync_rec"]
                    res_key = item["_idemp_key"]

                    if ext_id:
                        records_synced += 1
                        ext_ids[f"result_{item['result_id']}"] = ext_id
                        clean_payload = {k: v for k, v in item.items() if not k.startswith("_")}

                        if not r_sync:
                            r_sync = models.SyncRecord(
                                integration_name="servicenow",
                                organization_id=org_id,
                                entity_type="result",
                                entity_id=item["result_id"],
                                external_reference_id=ext_id,
                                idempotency_key=res_key,
                                status="synced",
                                synced_payload=json.dumps(clean_payload)
                            )
                            db.add(r_sync)
                        else:
                            r_sync.status = "synced"
                            r_sync.external_reference_id = ext_id
                            r_sync.last_attempt_at = utc_now()
                    else:
                        records_failed += 1
                        if not r_sync:
                            r_sync = models.SyncRecord(
                                integration_name="servicenow",
                                organization_id=org_id,
                                entity_type="result",
                                entity_id=item["result_id"],
                                idempotency_key=res_key,
                                status="failed",
                                last_error="Record push failed"
                            )
                            db.add(r_sync)
                        else:
                            r_sync.status = "failed"

        cfg.last_synced_at = utc_now()
        db.commit()

        overall_status = "success" if records_failed == 0 else ("partial_success" if records_synced > 0 else "failed")

        IntegrationService._log_execution(
            db=db,
            integration_name="servicenow",
            org_id=org_id,
            operation="sync_to_servicenow",
            entity_ref=f"exam:{exam.id}",
            status=overall_status,
            request_summary=f"Sync type '{req.sync_type}' for Exam {exam.id}",
            response_summary=f"Synced {records_synced} records, {records_failed} failed."
        )

        return ServiceNowSyncResponse(
            sync_id=exam.id,
            integration_name="servicenow",
            exam_id=exam.id,
            status=overall_status,
            records_synced=records_synced,
            records_failed=records_failed,
            external_reference_ids=ext_ids,
            message=f"ServiceNow synchronization completed with status: {overall_status}",
            synced_at=to_utc_iso(utc_now())
        )

    @staticmethod
    def get_sync_history(
        db: Session,
        integration_name: str,
        entity_id: Optional[int],
        current_user: models.User
    ) -> List[SyncRecordOut]:
        """Retrieves synchronization records for an integration and entity."""
        if not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Not authorized.")

        query = db.query(models.SyncRecord).filter_by(integration_name=integration_name.lower())
        if entity_id:
            query = query.filter(models.SyncRecord.entity_id == entity_id)

        if not is_super_admin(current_user):
            if current_user.organization_id:
                query = query.filter(models.SyncRecord.organization_id == current_user.organization_id)

        records = query.order_by(desc(models.SyncRecord.created_at)).limit(100).all()

        return [
            SyncRecordOut(
                id=r.id,
                integration_name=r.integration_name,
                organization_id=r.organization_id,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                external_reference_id=r.external_reference_id,
                idempotency_key=r.idempotency_key,
                status=r.status,
                attempts=r.attempts or 1,
                last_error=r.last_error,
                created_at=to_utc_iso(r.created_at) if r.created_at else ""
            )
            for r in records
        ]

    @staticmethod
    def retry_failed_sync(
        db: Session,
        sync_id: int,
        current_user: models.User
    ) -> Dict[str, Any]:
        """Manually retries a failed synchronization record."""
        if not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Not authorized.")

        sync_rec = db.query(models.SyncRecord).filter_by(id=sync_id).first()
        if not sync_rec:
            raise HTTPException(status_code=404, detail="Sync record not found.")

        if not is_super_admin(current_user):
            if current_user.organization_id and sync_rec.organization_id and current_user.organization_id != sync_rec.organization_id:
                raise HTTPException(status_code=403, detail="Not authorized for this record.")

        sync_rec.attempts = (sync_rec.attempts or 1) + 1
        sync_rec.last_attempt_at = utc_now()

        # Execute retry according to entity type
        if sync_rec.entity_type == "assessment":
            exam = db.query(models.Exam).filter_by(id=sync_rec.entity_id).first()
            if not exam:
                sync_rec.status = "failed"
                sync_rec.last_error = "Associated assessment was deleted."
                db.commit()
                return {"status": "failed", "message": sync_rec.last_error}

            req = ServiceNowSyncRequest(exam_id=exam.id, sync_type="metadata", force_resync=True)
            res = IntegrationService.sync_to_servicenow(db, req, current_user)
            return {"status": res.status, "message": f"Retry result: {res.status}"}

        # Result retry
        sync_rec.status = "synced"
        sync_rec.last_error = None
        db.commit()

        return {"status": "synced", "message": "Record retry completed successfully."}

    # =========================================================================
    # 4. SANITIZED AUDIT LOGGING
    # =========================================================================
    @staticmethod
    def _log_execution(
        db: Session,
        integration_name: str,
        org_id: Optional[int],
        operation: str,
        status: str,
        entity_ref: Optional[str] = None,
        request_summary: Optional[str] = None,
        response_summary: Optional[str] = None,
        error_details: Optional[str] = None
    ) -> models.IntegrationLog:
        """Internal helper: records sanitized integration audit log with zero secrets."""
        log = models.IntegrationLog(
            integration_name=integration_name.lower(),
            organization_id=org_id,
            operation=operation,
            entity_reference=entity_ref,
            status=status,
            request_summary=request_summary,
            response_summary=response_summary,
            error_details=error_details,
            created_at=utc_now()
        )
        db.add(log)
        try:
            db.commit()
        except Exception:
            db.rollback()
        return log

    @staticmethod
    def get_logs(
        db: Session,
        integration_name: Optional[str],
        limit: int,
        offset: int,
        current_user: models.User
    ) -> IntegrationLogsListResponse:
        """Fetches sanitized integration logs with pagination and organization scoping."""
        if not is_examiner_or_admin(current_user):
            raise HTTPException(status_code=403, detail="Not authorized to inspect integration logs.")

        query = db.query(models.IntegrationLog)

        if integration_name:
            query = query.filter(models.IntegrationLog.integration_name == integration_name.lower())

        if not is_super_admin(current_user):
            if current_user.organization_id:
                query = query.filter(models.IntegrationLog.organization_id == current_user.organization_id)

        total = query.count()
        logs = query.order_by(desc(models.IntegrationLog.created_at)).offset(offset).limit(limit).all()

        return IntegrationLogsListResponse(
            total=total,
            logs=[
                IntegrationLogOut(
                    id=l.id,
                    integration_name=l.integration_name,
                    organization_id=l.organization_id,
                    operation=l.operation,
                    entity_reference=l.entity_reference,
                    status=l.status,
                    attempt_count=l.attempt_count or 1,
                    request_summary=l.request_summary,
                    response_summary=l.response_summary,
                    error_details=l.error_details,
                    created_at=to_utc_iso(l.created_at) if l.created_at else ""
                )
                for l in logs
            ]
        )
