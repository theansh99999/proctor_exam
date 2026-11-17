"""

modules/proctoring/service.py

-----------------------------

Core proctoring business logic:

- Configurable policies per assessment type

- Event ingestion with debouncing and policy-level filtering

- Severity evaluation and session integrity scoring

- Examiner review workflows without modifying candidate test marks

- Real-time examiner alert broadcasting via WebSocket

"""

import json

from typing import Optional, List, Dict, Any, Tuple

from datetime import timedelta

from sqlalchemy.orm import Session

from fastapi import HTTPException



import models

from time_utils import utc_now, to_utc, to_utc_iso

from ws_manager import manager

from modules.assessments.service import AssessmentService

from modules.proctoring.schemas import (

    ProctoringPolicyCreate,

    ProctoringPolicyUpdate,

    ProctoringEventIngest,

    ProctoringEventReview,

    ProctoringEventResponse,

    SessionIntegritySummary

)



# Severity score deduction weights

DEFAULT_RISK_WEIGHTS = {

    "low": 3.0,

    "medium": 7.0,

    "high": 15.0,

    "critical": 25.0

}



# Event type to default severity mapping

DEFAULT_EVENT_SEVERITY = {

    "tab_switch": "medium",

    "window_blur": "medium",

    "fullscreen_exit": "medium",

    "face_not_detected": "medium",

    "multiple_faces": "high",

    "camera_disconnected": "high",

    "microphone_disconnected": "medium",

    "copy_paste": "low",

    "suspicious_activity": "high",

    "repeated_violations": "critical"

}



class ProctoringService:

    @staticmethod

    def get_or_create_policy(db: Session, exam: models.Exam) -> models.ProctoringPolicy:

        """Retrieves existing policy or initializes category-tailored default policy."""

        policy = db.query(models.ProctoringPolicy).filter_by(exam_id=exam.id).first()

        if policy:

            return policy



        cat = (exam.assessment_type or "academic").lower()

        now = utc_now()



        # Category-tailored presets

        if cat == "placement":

            policy = models.ProctoringPolicy(

                exam_id=exam.id,

                webcam_required=True,

                microphone_required=True,

                face_detection=True,

                multiple_face_detection=True,

                tab_switch_detection=True,

                fullscreen_required=True,

                copy_paste_restricted=True,

                browser_focus_monitoring=True,

                warning_threshold=2,

                violation_threshold=4,

                auto_submit_threshold=6,

                risk_weights=json.dumps(DEFAULT_RISK_WEIGHTS),

                created_at=now,

                updated_at=now

            )

        elif cat == "technical":

            policy = models.ProctoringPolicy(

                exam_id=exam.id,

                webcam_required=True,

                microphone_required=False,

                face_detection=True,

                multiple_face_detection=True,

                tab_switch_detection=True,

                fullscreen_required=False,  # Allows secondary editor/reference if desired

                copy_paste_restricted=True,

                browser_focus_monitoring=True,

                warning_threshold=4,

                violation_threshold=6,

                auto_submit_threshold=0,    # Disabled auto-submit for technical assessments

                risk_weights=json.dumps(DEFAULT_RISK_WEIGHTS),

                created_at=now,

                updated_at=now

            )

        else:

            # Academic & Custom default

            policy = models.ProctoringPolicy(

                exam_id=exam.id,

                webcam_required=True,

                microphone_required=False,

                face_detection=True,

                multiple_face_detection=True,

                tab_switch_detection=True,

                fullscreen_required=True,

                copy_paste_restricted=True,

                browser_focus_monitoring=True,

                warning_threshold=3,

                violation_threshold=5,

                auto_submit_threshold=0,    # Default disabled auto-submit

                risk_weights=json.dumps(DEFAULT_RISK_WEIGHTS),

                created_at=now,

                updated_at=now

            )



        db.add(policy)

        db.commit()

        db.refresh(policy)

        return policy



    @staticmethod

    def update_policy(

        db: Session,

        exam: models.Exam,

        policy_in: ProctoringPolicyUpdate,

        current_user: models.User

    ) -> models.ProctoringPolicy:

        """Updates proctoring policy for an assessment with examiner/admin ownership check."""

        policy = ProctoringService.get_or_create_policy(db, exam)



        # Scoping check

        if current_user.role != "super_admin":

            if current_user.organization_id and exam.organization_id and current_user.organization_id != exam.organization_id:

                raise HTTPException(status_code=403, detail="Not authorized to configure proctoring for another organization")



        update_data = policy_in.model_dump(exclude_unset=True) if hasattr(policy_in, "model_dump") else policy_in.dict(exclude_unset=True)

        if "risk_weights" in update_data and update_data["risk_weights"] is not None:

            update_data["risk_weights"] = json.dumps(update_data["risk_weights"])



        for field, val in update_data.items():

            setattr(policy, field, val)



        policy.updated_at = utc_now()

        db.commit()

        db.refresh(policy)

        return policy



    @staticmethod

    def is_feature_enabled(policy: models.ProctoringPolicy, event_type: str) -> bool:

        """Determines whether a given event type is actively monitored under current policy."""

        mapping = {

            "tab_switch": policy.tab_switch_detection,

            "window_blur": policy.browser_focus_monitoring,

            "fullscreen_exit": policy.fullscreen_required,

            "face_not_detected": policy.face_detection,

            "multiple_faces": policy.multiple_face_detection,

            "camera_disconnected": policy.webcam_required,

            "microphone_disconnected": policy.microphone_required,

            "copy_paste": policy.copy_paste_restricted,

            "suspicious_activity": True,

            "repeated_violations": True

        }

        return mapping.get(event_type, True)



    @staticmethod

    def calculate_integrity_score(

        flags: List[models.CheatFlag],

        policy: Optional[models.ProctoringPolicy] = None

    ) -> Tuple[float, str]:

        """

        Calculates session integrity score (0.0 to 100.0) and categorical risk level.

        Flags marked 'legitimate' or 'ignored' do not incur penalties.

        """

        weights = DEFAULT_RISK_WEIGHTS.copy()

        if policy and policy.risk_weights:

            try:

                custom_w = json.loads(policy.risk_weights)

                weights.update(custom_w)

            except Exception:

                pass



        score = 100.0

        for f in flags:

            # Skip ignored, duplicate, or examiner-validated legitimate events

            if f.validation_status in ("ignored", "duplicate"):

                continue

            if f.review_decision == "legitimate":

                continue



            sev = f.severity or "medium"

            deduction = weights.get(sev, 7.0)

            score -= deduction



        score = max(0.0, min(100.0, round(score, 1)))



        if score >= 85.0:

            risk = "low"

        elif score >= 65.0:

            risk = "medium"

        elif score >= 40.0:

            risk = "high"

        else:

            risk = "critical"



        return score, risk



    @staticmethod

    async def ingest_event(

        db: Session,

        candidate: models.User,

        event_in: ProctoringEventIngest

    ) -> Dict[str, Any]:

        """

        Ingests a proctoring violation event with debouncing, policy filtering,

        integrity scoring, and WebSocket alert broadcast.

        """

        exam = db.query(models.Exam).filter_by(id=event_in.exam_id).first()

        if not exam:

            raise HTTPException(status_code=404, detail="Assessment not found")



        # Eligibility check

        if not AssessmentService.is_candidate_eligible(db, exam, candidate):

            raise HTTPException(status_code=403, detail="Student not enrolled in this exam")



        now = utc_now()

        st = to_utc(exam.start_time)

        et = to_utc(exam.end_time)

        if st and now < st:

            raise HTTPException(status_code=400, detail="Exam has not started yet")

        if et and now > et:

            raise HTTPException(status_code=400, detail="Exam has already ended")



        policy = ProctoringService.get_or_create_policy(db, exam)



        # Retrieve active session

        exam_session = None

        if event_in.exam_session_id:

            exam_session = db.query(models.ExamSession).filter_by(id=event_in.exam_session_id, student_id=candidate.id).first()

        if not exam_session:

            exam_session = db.query(models.ExamSession).filter_by(

                exam_id=exam.id,

                student_id=candidate.id,

                status="in_progress"

            ).order_by(models.ExamSession.attempt_number.desc()).first()



        # Check if already submitted

        sub = db.query(models.Submission).filter_by(exam_id=exam.id, student_id=candidate.id).first()

        if sub:

            return {"status": "ignored", "reason": "already_submitted"}



        event_type = event_in.event_type or "tab_switch"

        severity = event_in.severity or DEFAULT_EVENT_SEVERITY.get(event_type, "medium")

        desc = event_in.description or f"Proctoring violation: {event_type.replace('_', ' ').title()}"

        meta_str = json.dumps(event_in.metadata) if event_in.metadata else None



        # 1. Policy Feature Check: if feature is disabled by examiner policy, mark ignored

        is_enabled = ProctoringService.is_feature_enabled(policy, event_type)

        if not is_enabled:

            flag = models.CheatFlag(

                exam_id=exam.id,

                student_id=candidate.id,

                exam_session_id=exam_session.id if exam_session else None,

                timestamp=now,

                description=desc,

                event_type=event_type,

                severity=severity,

                event_metadata=meta_str,

                validation_status="ignored",

                is_resolved=False,

                review_decision="unreviewed"

            )

            db.add(flag)

            db.commit()

            return {"status": "ignored", "reason": "feature_disabled_by_policy", "flag_id": flag.id}



        # 2. Debounce Check: ignore identical event within 4 seconds

        cutoff = now - timedelta(seconds=4)

        recent_flag = db.query(models.CheatFlag).filter(

            models.CheatFlag.exam_id == exam.id,

            models.CheatFlag.student_id == candidate.id,

            models.CheatFlag.event_type == event_type,

            models.CheatFlag.timestamp >= cutoff

        ).first()



        if recent_flag:

            return {"status": "duplicate", "flag_id": recent_flag.id}



        # 3. Create Valid CheatFlag Record

        flag = models.CheatFlag(

            exam_id=exam.id,

            student_id=candidate.id,

            exam_session_id=exam_session.id if exam_session else None,

            timestamp=now,

            description=desc,

            event_type=event_type,

            severity=severity,

            event_metadata=meta_str,

            validation_status="valid",

            is_resolved=False,

            review_decision="unreviewed"

        )

        db.add(flag)

        db.flush()



        # 4. Update ExamSession Integrity Score & Risk Level

        should_auto_submit = False

        if exam_session:

            all_flags = db.query(models.CheatFlag).filter_by(

                exam_id=exam.id,

                student_id=candidate.id

            ).all()



            score, risk = ProctoringService.calculate_integrity_score(all_flags, policy)

            exam_session.integrity_score = score

            exam_session.risk_level = risk



            valid_count = sum(1 for f in all_flags if f.validation_status == "valid" and f.review_decision != "legitimate")



            # Threshold statuses

            if policy.auto_submit_threshold and policy.auto_submit_threshold > 0 and valid_count >= policy.auto_submit_threshold:

                exam_session.proctoring_status = "auto_submitted"

                should_auto_submit = True

            elif valid_count >= policy.violation_threshold:

                exam_session.proctoring_status = "flagged"

            elif valid_count >= policy.warning_threshold:

                exam_session.proctoring_status = "warned"



        db.commit()

        db.refresh(flag)



        # 5. Broadcast to Authorized Examiner via WebSocket

        teacher_id = exam.creator_id or (exam.group.teacher_id if exam.group else None)

        if teacher_id:

            try:

                await manager.send_personal_message({

                    "type": "cheat_alert",

                    "event_category": "proctoring_event",

                    "flag_id": flag.id,

                    "exam_id": exam.id,

                    "exam_title": exam.title,

                    "student_id": candidate.id,

                    "student_name": candidate.name,

                    "event_type": flag.event_type,

                    "description": flag.description,

                    "severity": flag.severity,

                    "integrity_score": exam_session.integrity_score if exam_session else 100.0,

                    "risk_level": exam_session.risk_level if exam_session else "low",

                    "validation_status": flag.validation_status,

                    "should_auto_submit": should_auto_submit,

                    "timestamp": to_utc_iso(flag.timestamp)

                }, teacher_id)

            except Exception as ws_err:

                print(f"[PROCTORING WS] Warning: failed to send live event: {ws_err}")



        return {

            "status": "logged",

            "flag_id": flag.id,

            "event_type": flag.event_type,

            "severity": flag.severity,

            "validation_status": flag.validation_status,

            "integrity_score": exam_session.integrity_score if exam_session else 100.0,

            "risk_level": exam_session.risk_level if exam_session else "low",

            "should_auto_submit": should_auto_submit

        }



    @staticmethod

    def review_event(

        db: Session,

        event_id: int,

        review_in: ProctoringEventReview,

        reviewer: models.User

    ) -> models.CheatFlag:

        """Examiner review action: mark event as legitimate, suspicious or inconclusive with notes."""

        flag = db.query(models.CheatFlag).filter_by(id=event_id).first()

        if not flag:

            raise HTTPException(status_code=404, detail="Proctoring event not found")



        # Scoping check

        exam = db.query(models.Exam).filter_by(id=flag.exam_id).first()

        if reviewer.role != "super_admin":

            if reviewer.organization_id and exam.organization_id and reviewer.organization_id != exam.organization_id:

                raise HTTPException(status_code=403, detail="Not authorized to review events outside your organization")



        flag.review_decision = review_in.review_decision

        flag.reviewer_notes = review_in.reviewer_notes

        flag.reviewed_by = reviewer.id

        flag.reviewed_at = utc_now()

        flag.is_resolved = True



        # Recalculate session integrity score if exam_session exists

        if flag.exam_session_id:

            sess = db.query(models.ExamSession).filter_by(id=flag.exam_session_id).first()

            if sess:

                policy = ProctoringService.get_or_create_policy(db, exam)

                all_flags = db.query(models.CheatFlag).filter_by(exam_id=exam.id, student_id=flag.student_id).all()

                score, risk = ProctoringService.calculate_integrity_score(all_flags, policy)

                sess.integrity_score = score

                sess.risk_level = risk



        db.commit()

        db.refresh(flag)

        return flag



    @staticmethod

    def get_live_exam_status(

        db: Session,

        exam_id: int,

        current_user: models.User

    ) -> Dict[str, Any]:

        """Provides real-time proctoring monitoring payload for examiner dashboard."""

        exam = db.query(models.Exam).filter_by(id=exam_id).first()

        if not exam:

            raise HTTPException(status_code=404, detail="Assessment not found")



        if current_user.role != "super_admin":

            if current_user.organization_id and exam.organization_id and current_user.organization_id != exam.organization_id:

                raise HTTPException(status_code=403, detail="Not authorized to view assessment outside your organization")



        policy = ProctoringService.get_or_create_policy(db, exam)

        now = utc_now()



        # Fetch candidate sessions

        sessions = db.query(models.ExamSession).filter(

            models.ExamSession.exam_id == exam_id

        ).order_by(models.ExamSession.started_at.desc()).all()



        candidate_ids = [s.student_id for s in sessions]

        users = {u.id: u for u in db.query(models.User).filter(models.User.id.in_(candidate_ids)).all()} if candidate_ids else {}



        # Fetch recent flags

        flags = db.query(models.CheatFlag).filter_by(exam_id=exam_id).order_by(models.CheatFlag.timestamp.desc()).limit(100).all()



        active_candidates = []

        for s in sessions:

            cand = users.get(s.student_id)

            rem_sec = max(0, int((to_utc(s.overall_deadline) - now).total_seconds())) if s.overall_deadline else None

            active_candidates.append({

                "session_id": s.id,

                "student_id": s.student_id,

                "student_name": cand.name if cand else "Unknown",

                "student_email": cand.email if cand else "",

                "status": s.status,

                "attempt_number": s.attempt_number,

                "started_at": to_utc_iso(s.started_at) if s.started_at else None,

                "remaining_seconds": rem_sec,

                "current_question_index": s.current_question_index,

                "integrity_score": s.integrity_score if s.integrity_score is not None else 100.0,

                "risk_level": s.risk_level or "low",

                "proctoring_status": s.proctoring_status or "normal"

            })



        recent_events = []

        for f in flags:

            cand = users.get(f.student_id)

            recent_events.append({

                "id": f.id,

                "student_id": f.student_id,

                "student_name": cand.name if cand else "Candidate",

                "event_type": f.event_type,

                "description": f.description,

                "severity": f.severity,

                "validation_status": f.validation_status,

                "review_decision": f.review_decision or "unreviewed",

                "timestamp": to_utc_iso(f.timestamp) if f.timestamp else None

            })



        return {

            "exam_id": exam.id,

            "title": exam.title,

            "policy": {

                "webcam_required": policy.webcam_required,

                "microphone_required": policy.microphone_required,

                "face_detection": policy.face_detection,

                "multiple_face_detection": policy.multiple_face_detection,

                "tab_switch_detection": policy.tab_switch_detection,

                "fullscreen_required": policy.fullscreen_required,

                "warning_threshold": policy.warning_threshold,

                "violation_threshold": policy.violation_threshold,

                "auto_submit_threshold": policy.auto_submit_threshold

            },

            "active_candidates": active_candidates,

            "recent_events": recent_events,

            "total_candidates": len(active_candidates),

            "total_violations": len(flags)

        }
