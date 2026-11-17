"""
modules/assessments/service.py
------------------------------
Comprehensive business logic and authorization for Assessment Management:
- Multi-purpose assessment CRUD (Academic, Placement, Technical, Custom)
- Assessment Scheduling with backend datetime boundary enforcement
- Candidate and Group Assignment (individual, groups, bulk, deduplication, org isolation)
- Assessment Lifecycle State Machine (Draft -> Published -> Scheduled -> Active -> Completed -> Archived)
- Candidate Eligibility & Visibility Verification
- Assessment Statistics and Examiner Dashboard aggregation
"""
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc, asc, func
from fastapi import HTTPException, status
from typing import List, Optional, Dict, Any, Set, Tuple
import json
from datetime import datetime

import models
from modules.assessments.schemas import (
    AssessmentCreate,
    AssessmentUpdate,
    AssessmentScheduleRequest,
    CandidateAssignmentRequest,
    GroupAssignmentRequest,
    AssignmentOut,
    AssessmentAssignmentsDetail,
    AssessmentStatisticsOut
)
from core.rbac import (
    is_super_admin,
    is_org_admin,
    is_examiner_or_admin,
    is_candidate,
    enforce_org_access,
    verify_org_access
)
from time_utils import to_utc, utc_now

ALLOWED_TYPES = {"academic", "placement", "technical", "custom"}
ALLOWED_STATUSES = {"draft", "published", "scheduled", "active", "completed", "archived"}
ALLOWED_CRITERIA = {"marks", "percentage"}
ALLOWED_VISIBILITIES = {"public", "private", "group_only"}

# Valid status transitions
VALID_TRANSITIONS: Dict[str, Set[str]] = {
    "draft": {"published", "scheduled", "archived"},
    "scheduled": {"published", "active", "completed", "archived"},
    "published": {"scheduled", "active", "completed", "archived"},
    "active": {"completed", "archived"},
    "completed": {"archived"},
    "archived": set()  # Terminal state
}

class AssessmentService:
    # =========================================================================
    # 1. ASSESSMENT CRUD
    # =========================================================================
    @staticmethod
    def create_assessment(db: Session, data: AssessmentCreate, current_user: models.User) -> models.Exam:
        if not is_examiner_or_admin(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Examiners, Org Admins, and Super Admins can create assessments."
            )

        # ── Backend Validation ───────────────────────────────────────────────
        if data.assessment_type not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid assessment_type '{data.assessment_type}'.")

        if data.passing_criteria not in ALLOWED_CRITERIA:
            raise HTTPException(status_code=400, detail=f"Invalid passing_criteria '{data.passing_criteria}'.")

        if data.visibility not in ALLOWED_VISIBILITIES:
            raise HTTPException(status_code=400, detail=f"Invalid visibility '{data.visibility}'.")

        if data.status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status '{data.status}'.")

        st = to_utc(data.start_time)
        et = to_utc(data.end_time)
        if not st or not et:
            raise HTTPException(status_code=400, detail="Invalid start_time or end_time.")
        if st >= et:
            raise HTTPException(status_code=400, detail="start_time must be strictly before end_time.")

        if data.duration_minutes <= 0:
            raise HTTPException(status_code=400, detail="duration_minutes must be greater than 0.")

        if data.passing_criteria == "percentage" and data.passing_percentage is not None:
            if not (0 <= data.passing_percentage <= 100):
                raise HTTPException(status_code=400, detail="passing_percentage must be between 0 and 100.")

        # Organization scoping
        target_org_id = data.organization_id
        if is_super_admin(current_user):
            pass
        elif is_org_admin(current_user):
            target_org_id = current_user.organization_id
        else:
            if current_user.organization_id is not None:
                if target_org_id and target_org_id != current_user.organization_id:
                    raise HTTPException(status_code=403, detail="Cannot create assessment for another organization.")
                target_org_id = current_user.organization_id

        # Group verification if provided
        if data.group_id:
            group = db.query(models.Group).filter(models.Group.id == data.group_id).first()
            if not group:
                raise HTTPException(status_code=400, detail="Specified group not found.")
            if not is_super_admin(current_user):
                if is_org_admin(current_user) and group.organization_id != current_user.organization_id:
                    raise HTTPException(status_code=403, detail="Group does not belong to your organization.")
                if not is_org_admin(current_user) and group.teacher_id != current_user.id:
                    raise HTTPException(status_code=403, detail="You do not own the specified group.")

        metadata_str = json.dumps(data.config_metadata) if data.config_metadata else None
        adaptive_cfg_str = json.dumps(data.adaptive_config) if data.adaptive_config else None
        attempt_pol_str = json.dumps(data.attempt_policy) if data.attempt_policy else None

        exam = models.Exam(
            title=data.title.strip(),
            description=data.description,
            instructions=data.instructions,
            assessment_type=data.assessment_type,
            group_id=data.group_id,
            organization_id=target_org_id,
            creator_id=current_user.id,
            start_time=st,
            end_time=et,
            duration_minutes=data.duration_minutes,
            timer_type=data.timer_type,
            default_marks=data.default_marks,
            default_negative_marks=data.default_negative_marks,
            enable_negative_marking=data.enable_negative_marking,
            randomize_questions=data.randomize_questions,
            randomize_options=data.randomize_options,
            visibility=data.visibility,
            passing_marks=data.passing_marks,
            passing_criteria=data.passing_criteria,
            passing_percentage=data.passing_percentage,
            max_attempts=data.max_attempts,
            status=data.status,
            is_adaptive=data.is_adaptive,
            adaptive_config=adaptive_cfg_str,
            attempt_policy=attempt_pol_str,
            blueprint_id=data.blueprint_id,
            template_id=data.template_id,
            config_metadata=metadata_str
        )
        db.add(exam)
        db.commit()
        db.refresh(exam)
        try:
            from modules.admin.service import AdminService
            AdminService.log_audit(
                db=db,
                action="assessment.create",
                entity_type="assessment",
                entity_id=str(exam.id),
                actor_id=current_user.id,
                org_id=exam.organization_id,
                metadata={"title": exam.title, "type": exam.assessment_type}
            )
        except Exception:
            pass
        return exam

    @staticmethod
    def get_assessment(db: Session, assessment_id: int, current_user: models.User) -> models.Exam:
        exam = db.query(models.Exam).filter(models.Exam.id == assessment_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found.")

        # Organization isolation
        enforce_org_access(current_user, exam.organization_id, resource_name="assessment")

        # Examiner authorization check
        if not is_super_admin(current_user) and not is_org_admin(current_user):
            if is_examiner_or_admin(current_user):
                if exam.creator_id and exam.creator_id != current_user.id and exam.organization_id != current_user.organization_id:
                    raise HTTPException(status_code=403, detail="Not authorized to view this assessment.")
            else:
                # Candidate: must not view draft assessments or assessments not assigned to them
                if exam.status in ("draft", "archived"):
                    raise HTTPException(status_code=403, detail="Assessment is not available.")
                if not AssessmentService.is_candidate_eligible(db, exam, current_user):
                    raise HTTPException(status_code=403, detail="You are not assigned to this assessment.")

        return exam

    @staticmethod
    def list_assessments(
        db: Session,
        current_user: models.User,
        search: Optional[str] = None,
        assessment_type: Optional[str] = None,
        status_filter: Optional[str] = None,
        organization_id: Optional[int] = None,
        sort_by: str = "start_time",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[models.Exam], int]:
        query = db.query(models.Exam)

        # ── Scope by role ───────────────────────────────────────────────────
        if is_super_admin(current_user):
            if organization_id is not None:
                query = query.filter(models.Exam.organization_id == organization_id)
        elif is_org_admin(current_user):
            query = query.filter(models.Exam.organization_id == current_user.organization_id)
        elif is_examiner_or_admin(current_user):
            if current_user.organization_id is not None:
                query = query.filter(models.Exam.organization_id == current_user.organization_id)
            else:
                # Unaffiliated examiner
                query = query.filter(
                    or_(
                        models.Exam.creator_id == current_user.id,
                        models.Exam.group.has(teacher_id=current_user.id)
                    )
                )
        else:
            # Candidate: only see eligible assessments (exclude draft & archived)
            eligible_ids = AssessmentService.get_eligible_assessment_ids_for_candidate(db, current_user)
            query = query.filter(
                models.Exam.id.in_(eligible_ids),
                models.Exam.status.notin_(["draft", "archived"])
            )

        # ── Search & Filter ─────────────────────────────────────────────────
        if search:
            s = f"%{search.strip()}%"
            query = query.filter(or_(models.Exam.title.ilike(s), models.Exam.description.ilike(s)))
        if assessment_type:
            query = query.filter(models.Exam.assessment_type == assessment_type)
        if status_filter:
            query = query.filter(models.Exam.status == status_filter)

        total_count = query.count()

        # ── Sorting ─────────────────────────────────────────────────────────
        sort_col = getattr(models.Exam, sort_by, models.Exam.start_time)
        query = query.order_by(desc(sort_col) if sort_order == "desc" else asc(sort_col))
        query = query.offset(skip).limit(limit)

        return query.all(), total_count

    @staticmethod
    def update_assessment(db: Session, assessment_id: int, data: AssessmentUpdate, current_user: models.User) -> models.Exam:
        exam = AssessmentService.get_assessment(db, assessment_id, current_user)

        if not (is_super_admin(current_user) or is_org_admin(current_user)):
            if exam.creator_id != current_user.id:
                raise HTTPException(status_code=403, detail="You can only update assessments you created.")

        if data.title is not None:
            exam.title = data.title.strip()
        if data.description is not None:
            exam.description = data.description
        if data.instructions is not None:
            exam.instructions = data.instructions
        if data.assessment_type is not None:
            if data.assessment_type not in ALLOWED_TYPES:
                raise HTTPException(status_code=400, detail="Invalid assessment_type.")
            exam.assessment_type = data.assessment_type

        # Validate start & end time
        new_st = to_utc(data.start_time) if data.start_time is not None else exam.start_time
        new_et = to_utc(data.end_time) if data.end_time is not None else exam.end_time
        if new_st >= new_et:
            raise HTTPException(status_code=400, detail="start_time must be strictly before end_time.")
        exam.start_time = new_st
        exam.end_time = new_et

        if data.duration_minutes is not None:
            if data.duration_minutes <= 0:
                raise HTTPException(status_code=400, detail="duration_minutes must be > 0.")
            exam.duration_minutes = data.duration_minutes
        if data.timer_type is not None:
            exam.timer_type = data.timer_type
        if data.default_marks is not None:
            exam.default_marks = data.default_marks
        if data.default_negative_marks is not None:
            exam.default_negative_marks = data.default_negative_marks
        if data.enable_negative_marking is not None:
            exam.enable_negative_marking = data.enable_negative_marking
        if data.randomize_questions is not None:
            exam.randomize_questions = data.randomize_questions
        if data.randomize_options is not None:
            exam.randomize_options = data.randomize_options
        if data.is_adaptive is not None:
            exam.is_adaptive = data.is_adaptive
        if data.adaptive_config is not None:
            exam.adaptive_config = json.dumps(data.adaptive_config)
        if data.attempt_policy is not None:
            exam.attempt_policy = json.dumps(data.attempt_policy)
        if data.blueprint_id is not None:
            exam.blueprint_id = data.blueprint_id
        if data.template_id is not None:
            exam.template_id = data.template_id
        if data.visibility is not None:
            if data.visibility not in ALLOWED_VISIBILITIES:
                raise HTTPException(status_code=400, detail="Invalid visibility.")
            exam.visibility = data.visibility
        if data.passing_marks is not None:
            exam.passing_marks = data.passing_marks
        if data.passing_criteria is not None:
            if data.passing_criteria not in ALLOWED_CRITERIA:
                raise HTTPException(status_code=400, detail="Invalid passing_criteria.")
            exam.passing_criteria = data.passing_criteria
        if data.passing_percentage is not None:
            exam.passing_percentage = data.passing_percentage
        if data.max_attempts is not None:
            exam.max_attempts = data.max_attempts
        if data.status is not None:
            AssessmentService.transition_status(exam, data.status, current_user)
        if data.config_metadata is not None:
            exam.config_metadata = json.dumps(data.config_metadata)

        db.commit()
        db.refresh(exam)
        return exam

    @staticmethod
    def delete_assessment(db: Session, assessment_id: int, current_user: models.User) -> None:
        exam = AssessmentService.get_assessment(db, assessment_id, current_user)
        if not (is_super_admin(current_user) or is_org_admin(current_user)):
            if exam.creator_id != current_user.id:
                raise HTTPException(status_code=403, detail="You can only delete assessments you created.")
        db.delete(exam)
        db.commit()

    # =========================================================================
    # 2. LIFECYCLE TRANSITIONS
    # =========================================================================
    @staticmethod
    def transition_status(exam: models.Exam, target_status: str, current_user: models.User) -> str:
        current_status = exam.status or "draft"
        if target_status == current_status:
            return current_status

        if target_status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail=f"Unknown target status '{target_status}'.")

        allowed = VALID_TRANSITIONS.get(current_status, set())
        # Super Admin can force any transition; others must adhere to lifecycle rules
        if not is_super_admin(current_user) and target_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status transition from '{current_status}' to '{target_status}'. Allowed: {list(allowed)}."
            )

        exam.status = target_status
        return target_status

    @staticmethod
    def publish_assessment(db: Session, assessment_id: int, current_user: models.User) -> models.Exam:
        exam = AssessmentService.get_assessment(db, assessment_id, current_user)
        AssessmentService.transition_status(exam, "published", current_user)
        db.commit()
        db.refresh(exam)
        # Phase 9: Automated lifecycle notification
        try:
            from modules.notifications.service import NotificationService
            NotificationService.trigger_assessment_lifecycle_event(
                db=db,
                event_type="assessment_published",
                exam_id=exam.id
            )
        except Exception as e:
            print(f"[NOTIF_WARN] Could not trigger assessment_published: {e}")
        try:
            from modules.admin.service import AdminService
            AdminService.log_audit(
                db=db,
                action="assessment.publish",
                entity_type="assessment",
                entity_id=str(exam.id),
                actor_id=current_user.id,
                org_id=exam.organization_id,
                metadata={"title": exam.title}
            )
        except Exception:
            pass
        return exam

    @staticmethod
    def schedule_assessment(db: Session, assessment_id: int, req: AssessmentScheduleRequest, current_user: models.User) -> models.Exam:
        exam = AssessmentService.get_assessment(db, assessment_id, current_user)
        st = to_utc(req.start_time)
        et = to_utc(req.end_time)
        if st >= et:
            raise HTTPException(status_code=400, detail="start_time must be strictly before end_time.")

        prev_st = exam.start_time
        exam.start_time = st
        exam.end_time = et
        event_name = "assessment_rescheduled" if prev_st else "assessment_scheduled"
        AssessmentService.transition_status(exam, "scheduled", current_user)
        db.commit()
        db.refresh(exam)
        # Phase 9: Automated lifecycle notification
        try:
            from modules.notifications.service import NotificationService
            NotificationService.trigger_assessment_lifecycle_event(
                db=db,
                event_type=event_name,
                exam_id=exam.id
            )
        except Exception as e:
            print(f"[NOTIF_WARN] Could not trigger {event_name}: {e}")
        return exam

    @staticmethod
    def archive_assessment(db: Session, assessment_id: int, current_user: models.User) -> models.Exam:
        exam = AssessmentService.get_assessment(db, assessment_id, current_user)
        AssessmentService.transition_status(exam, "archived", current_user)
        db.commit()
        db.refresh(exam)
        # Phase 9: Automated lifecycle notification
        try:
            from modules.notifications.service import NotificationService
            NotificationService.trigger_assessment_lifecycle_event(
                db=db,
                event_type="assessment_cancelled",
                exam_id=exam.id
            )
        except Exception as e:
            print(f"[NOTIF_WARN] Could not trigger assessment_cancelled: {e}")
        try:
            from modules.admin.service import AdminService
            AdminService.log_audit(
                db=db,
                action="assessment.archive",
                entity_type="assessment",
                entity_id=str(exam.id),
                actor_id=current_user.id,
                org_id=exam.organization_id,
                metadata={"title": exam.title}
            )
        except Exception:
            pass
        return exam

    # =========================================================================
    # 3. CANDIDATE & GROUP ASSIGNMENTS
    # =========================================================================
    @staticmethod
    def assign_candidates(
        db: Session,
        assessment_id: int,
        req: CandidateAssignmentRequest,
        current_user: models.User
    ) -> Dict[str, Any]:
        exam = AssessmentService.get_assessment(db, assessment_id, current_user)

        target_candidates: List[models.User] = []

        if req.candidate_ids:
            candidates_by_id = db.query(models.User).filter(models.User.id.in_(req.candidate_ids)).all()
            target_candidates.extend(candidates_by_id)

        if req.candidate_emails:
            emails = [e.strip().lower() for e in req.candidate_emails]
            candidates_by_email = db.query(models.User).filter(models.User.email.in_(emails)).all()
            target_candidates.extend(candidates_by_email)

        # Deduplicate candidates
        candidate_map = {c.id: c for c in target_candidates}

        assigned_count = 0
        skipped_count = 0

        for cand in candidate_map.values():
            # Organization isolation validation: candidate must belong to assessment's organization
            if exam.organization_id is not None and cand.organization_id is not None:
                if cand.organization_id != exam.organization_id and not is_super_admin(current_user):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Candidate {cand.email} belongs to a different organization."
                    )

            # Prevent duplicate assignment
            existing = db.query(models.AssessmentAssignment).filter(
                models.AssessmentAssignment.assessment_id == exam.id,
                models.AssessmentAssignment.candidate_id == cand.id
            ).first()

            if existing:
                skipped_count += 1
                continue

            assignment = models.AssessmentAssignment(
                assessment_id=exam.id,
                candidate_id=cand.id,
                assigned_by=current_user.id
            )
            db.add(assignment)
            assigned_count += 1

        db.commit()
        return {
            "assessment_id": exam.id,
            "assigned_count": assigned_count,
            "skipped_count": skipped_count,
            "total_candidates": len(candidate_map)
        }

    @staticmethod
    def assign_groups(
        db: Session,
        assessment_id: int,
        req: GroupAssignmentRequest,
        current_user: models.User
    ) -> Dict[str, Any]:
        exam = AssessmentService.get_assessment(db, assessment_id, current_user)

        groups = db.query(models.Group).filter(models.Group.id.in_(req.group_ids)).all()
        if not groups:
            raise HTTPException(status_code=404, detail="None of the specified groups were found.")

        assigned_count = 0
        skipped_count = 0

        for grp in groups:
            # Org check on group
            if exam.organization_id is not None and grp.organization_id is not None:
                if grp.organization_id != exam.organization_id and not is_super_admin(current_user):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Group '{grp.name}' belongs to a different organization."
                    )

            # Check duplicate
            existing = db.query(models.AssessmentAssignment).filter(
                models.AssessmentAssignment.assessment_id == exam.id,
                models.AssessmentAssignment.group_id == grp.id
            ).first()

            if existing:
                skipped_count += 1
                continue

            assignment = models.AssessmentAssignment(
                assessment_id=exam.id,
                group_id=grp.id,
                assigned_by=current_user.id
            )
            db.add(assignment)
            assigned_count += 1

        db.commit()
        return {
            "assessment_id": exam.id,
            "assigned_groups_count": assigned_count,
            "skipped_count": skipped_count
        }

    @staticmethod
    def get_assignment_details(db: Session, assessment_id: int, current_user: models.User) -> AssessmentAssignmentsDetail:
        exam = AssessmentService.get_assessment(db, assessment_id, current_user)

        assignments = db.query(models.AssessmentAssignment).filter(
            models.AssessmentAssignment.assessment_id == exam.id
        ).all()

        cand_assignments: List[AssignmentOut] = []
        grp_assignments: List[AssignmentOut] = []
        unique_candidate_ids: Set[int] = set()

        for a in assignments:
            if a.candidate_id:
                cand = a.candidate
                unique_candidate_ids.add(a.candidate_id)
                cand_assignments.append(AssignmentOut(
                    id=a.id,
                    assessment_id=a.assessment_id,
                    candidate_id=a.candidate_id,
                    candidate_email=cand.email if cand else None,
                    candidate_name=cand.name if cand else None,
                    assigned_by=a.assigned_by,
                    assigned_at=a.assigned_at
                ))
            elif a.group_id:
                grp = a.group
                # Resolve members of this group
                members = db.query(models.GroupMember).filter(models.GroupMember.group_id == a.group_id).all()
                for m in members:
                    if m.student_id:
                        unique_candidate_ids.add(m.student_id)
                grp_assignments.append(AssignmentOut(
                    id=a.id,
                    assessment_id=a.assessment_id,
                    group_id=a.group_id,
                    group_name=grp.name if grp else None,
                    assigned_by=a.assigned_by,
                    assigned_at=a.assigned_at
                ))

        # Include legacy exam.group_id members if set
        if exam.group_id:
            legacy_members = db.query(models.GroupMember).filter(models.GroupMember.group_id == exam.group_id).all()
            for lm in legacy_members:
                if lm.student_id:
                    unique_candidate_ids.add(lm.student_id)

        return AssessmentAssignmentsDetail(
            assessment_id=exam.id,
            assessment_title=exam.title,
            assigned_candidates=cand_assignments,
            assigned_groups=grp_assignments,
            total_candidate_count=len(unique_candidate_ids)
        )

    # =========================================================================
    # 4. CANDIDATE ELIGIBILITY & VISIBILITY
    # =========================================================================
    @staticmethod
    def get_eligible_assessment_ids_for_candidate(db: Session, candidate: models.User) -> Set[int]:
        """Find all assessment IDs this candidate is eligible to see or take."""
        eligible_ids: Set[int] = set()

        # 1. Direct candidate assignments
        direct_asmnts = db.query(models.AssessmentAssignment.assessment_id).filter(
            models.AssessmentAssignment.candidate_id == candidate.id
        ).all()
        for r in direct_asmnts:
            eligible_ids.add(r[0])

        # 2. Candidate's enrolled groups
        group_memberships = db.query(models.GroupMember.group_id).filter(
            or_(
                models.GroupMember.student_id == candidate.id,
                models.GroupMember.student_email == candidate.email
            )
        ).all()
        cand_group_ids = [gm[0] for gm in group_memberships]

        if cand_group_ids:
            # Group assignments via AssessmentAssignment
            grp_asmnts = db.query(models.AssessmentAssignment.assessment_id).filter(
                models.AssessmentAssignment.group_id.in_(cand_group_ids)
            ).all()
            for r in grp_asmnts:
                eligible_ids.add(r[0])

            # Legacy exam.group_id
            legacy_asmnts = db.query(models.Exam.id).filter(
                models.Exam.group_id.in_(cand_group_ids)
            ).all()
            for r in legacy_asmnts:
                eligible_ids.add(r[0])

        # 3. Public visibility assessments within candidate's organization
        public_query = db.query(models.Exam.id).filter(models.Exam.visibility == "public")
        if candidate.organization_id is not None:
            public_query = public_query.filter(
                or_(
                    models.Exam.organization_id == candidate.organization_id,
                    models.Exam.organization_id.is_(None)
                )
            )
        for r in public_query.all():
            eligible_ids.add(r[0])

        return eligible_ids

    @staticmethod
    def is_candidate_eligible(db: Session, exam: models.Exam, candidate: models.User) -> bool:
        eligible_ids = AssessmentService.get_eligible_assessment_ids_for_candidate(db, candidate)
        return exam.id in eligible_ids

    # =========================================================================
    # 5. ASSESSMENT STATISTICS & EXAMINER AGGREGATION
    # =========================================================================
    @staticmethod
    def get_assessment_statistics(db: Session, assessment_id: int, current_user: models.User) -> AssessmentStatisticsOut:
        exam = AssessmentService.get_assessment(db, assessment_id, current_user)
        assignments_detail = AssessmentService.get_assignment_details(db, assessment_id, current_user)

        # Submissions
        subs = db.query(models.Submission).filter(models.Submission.exam_id == exam.id).all()
        sessions = db.query(models.ExamSession).filter(models.ExamSession.exam_id == exam.id).all()

        total_assigned = assignments_detail.total_candidate_count
        total_attempts = len(sessions) or len(subs)
        completed_attempts = len(subs)

        scores = [s.score for s in subs]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
        high_score = max(scores) if scores else 0.0
        low_score = min(scores) if scores else 0.0

        pass_count = 0
        fail_count = 0
        for s in subs:
            is_passed = False
            if exam.passing_criteria == "percentage" and exam.passing_percentage is not None:
                # Calculate total possible marks
                q_marks = [q.marks if q.marks is not None else exam.default_marks for q in exam.questions]
                total_possible = sum(q_marks) if q_marks else 1.0
                pct = (s.score / total_possible) * 100
                is_passed = (pct >= exam.passing_percentage)
            else:
                is_passed = (s.score >= exam.passing_marks)

            if is_passed:
                pass_count += 1
            else:
                fail_count += 1

        pass_rate = round((pass_count / completed_attempts * 100), 2) if completed_attempts > 0 else 0.0

        # Calculate dynamic effective status
        now = utc_now()
        base_status = exam.status or "draft"
        if base_status in ("archived", "draft"):
            eff_status = base_status
        else:
            st = to_utc(exam.start_time)
            et = to_utc(exam.end_time)
            if now < st:
                eff_status = "scheduled"
            elif st <= now <= et:
                eff_status = "active"
            else:
                eff_status = "completed"

        return AssessmentStatisticsOut(
            assessment_id=exam.id,
            title=exam.title,
            status=base_status,
            effective_status=eff_status,
            total_assigned_candidates=total_assigned,
            total_attempts=total_attempts,
            completed_attempts=completed_attempts,
            average_score=avg_score,
            highest_score=high_score,
            lowest_score=low_score,
            pass_count=pass_count,
            fail_count=fail_count,
            pass_rate=pass_rate
        )

    @staticmethod
    def get_examiner_overview_counts(db: Session, current_user: models.User) -> Dict[str, int]:
        """Aggregate assessment counts by lifecycle status for examiner dashboard."""
        exams, total = AssessmentService.list_assessments(db, current_user, limit=1000)

        now = utc_now()
        draft_count = 0
        scheduled_count = 0
        active_count = 0
        completed_count = 0
        archived_count = 0

        for e in exams:
            status_val = e.status or "draft"
            if status_val == "archived":
                archived_count += 1
            elif status_val == "draft":
                draft_count += 1
            else:
                st = to_utc(e.start_time)
                et = to_utc(e.end_time)
                if now < st:
                    scheduled_count += 1
                elif st <= now <= et:
                    active_count += 1
                else:
                    completed_count += 1

        return {
            "total_assessments": len(exams),
            "draft_count": draft_count,
            "scheduled_count": scheduled_count,
            "active_count": active_count,
            "completed_count": completed_count,
            "archived_count": archived_count
        }
