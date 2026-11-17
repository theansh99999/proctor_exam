"""
modules/analytics/service.py
----------------------------
Comprehensive Analytics Service for:
1. Examiner Dashboard Analytics with filters
2. Candidate Performance Analytics & Topic Taxonomy
3. Assessment-Level Analytics & Question Accuracy
4. Question Bank Analytics with Zero-Division Safety
5. Organization-Scoped Admin Dashboard
6. Downloadable CSV and JSON Reports
Strictly enforces RBAC, organization isolation, and unreleased result privacy.
"""
import csv
import io
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import func, distinct, case, desc, asc
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException

import models
from time_utils import utc_now, to_utc, to_utc_iso


class AnalyticsService:

    # =========================================================================
    # 1. EXAMINER DASHBOARD ANALYTICS
    # =========================================================================
    @staticmethod
    def get_examiner_dashboard_metrics(
        db: Session,
        examiner: models.User,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        assessment_type: Optional[str] = None,
        status: Optional[str] = None,
        assessment_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Computes aggregate metrics for an examiner's dashboard with multi-criteria filters.
        Enforces organization-level isolation.
        """
        # Base query for exams authorized for this examiner
        query = db.query(models.Exam)
        if examiner.role != "super_admin":
            if examiner.organization_id:
                query = query.filter(models.Exam.organization_id == examiner.organization_id)
            else:
                query = query.filter(
                    (models.Exam.creator_id == examiner.id) |
                    (models.Exam.group.has(teacher_id=examiner.id))
                )

        # Apply filters
        if assessment_id:
            query = query.filter(models.Exam.id == assessment_id)
        if assessment_type:
            query = query.filter(models.Exam.assessment_type == assessment_type)
        if status:
            query = query.filter(models.Exam.status == status)
        if start_date:
            try:
                sd = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                query = query.filter(models.Exam.start_time >= sd)
            except Exception:
                pass
        if end_date:
            try:
                ed = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                query = query.filter(models.Exam.start_time <= ed)
            except Exception:
                pass

        exams = query.all()
        exam_ids = [e.id for e in exams]

        if not exam_ids:
            return {
                "total_assessments": 0,
                "status_counts": {"draft": 0, "published": 0, "scheduled": 0, "active": 0, "completed": 0, "archived": 0},
                "total_candidates_assigned": 0,
                "total_attempts": 0,
                "average_score": 0.0,
                "average_percentage": 0.0,
                "pass_rate": 0.0,
                "fail_rate": 0.0,
                "pending_grading_count": 0,
                "awaiting_release_count": 0,
                "recent_assessments": []
            }

        # Status counts
        status_counts = {"draft": 0, "published": 0, "scheduled": 0, "active": 0, "completed": 0, "archived": 0}
        for e in exams:
            st = e.status or "published"
            status_counts[st] = status_counts.get(st, 0) + 1

        # Candidates assigned
        assigned_candidates_count = db.query(distinct(models.AssessmentAssignment.candidate_id)).filter(
            models.AssessmentAssignment.assessment_id.in_(exam_ids),
            models.AssessmentAssignment.candidate_id.isnot(None)
        ).count()
        if assigned_candidates_count == 0:
            # Fallback to group members for group-assigned exams
            group_ids = [e.group_id for e in exams if e.group_id]
            if group_ids:
                assigned_candidates_count = db.query(distinct(models.GroupMember.student_id)).filter(
                    models.GroupMember.group_id.in_(group_ids),
                    models.GroupMember.student_id.isnot(None)
                ).count()

        # Attempts & Results aggregation
        results_agg = db.query(
            func.count(models.ExamResult.id).label("total_attempts"),
            func.avg(models.ExamResult.marks_obtained).label("avg_score"),
            func.avg(models.ExamResult.percentage).label("avg_percentage"),
            func.sum(case((models.ExamResult.pass_fail_status == "PASS", 1), else_=0)).label("passed_count"),
            func.sum(case((models.ExamResult.pass_fail_status == "FAIL", 1), else_=0)).label("failed_count"),
            func.sum(case((models.ExamResult.is_released.is_(False), 1), else_=0)).label("awaiting_release")
        ).filter(models.ExamResult.exam_id.in_(exam_ids)).first()

        total_attempts = results_agg.total_attempts or 0
        avg_score = round(float(results_agg.avg_score or 0.0), 2)
        avg_percentage = round(float(results_agg.avg_percentage or 0.0), 2)
        passed_count = int(results_agg.passed_count or 0)
        failed_count = int(results_agg.failed_count or 0)
        awaiting_release = int(results_agg.awaiting_release or 0)

        evaluated_total = passed_count + failed_count
        pass_rate = round((passed_count / evaluated_total * 100.0), 2) if evaluated_total > 0 else 0.0
        fail_rate = round((failed_count / evaluated_total * 100.0), 2) if evaluated_total > 0 else 0.0

        # Pending manual grading count
        pending_grading_count = db.query(models.StudentAnswer).join(models.StudentAnswer.question).filter(
            models.Question.exam_id.in_(exam_ids),
            models.StudentAnswer.evaluation_status.in_(["pending", "in_progress"])
        ).count()

        # Recent assessments performance summary
        recent_assessments = []
        for e in exams[:10]:
            e_res = db.query(
                func.count(models.ExamResult.id).label("attempts"),
                func.avg(models.ExamResult.percentage).label("avg_pct")
            ).filter(models.ExamResult.exam_id == e.id).first()
            recent_assessments.append({
                "id": e.id,
                "title": e.title,
                "assessment_type": e.assessment_type or "academic",
                "status": e.status,
                "attempts": e_res.attempts or 0,
                "average_percentage": round(float(e_res.avg_pct or 0.0), 2)
            })

        return {
            "total_assessments": len(exams),
            "status_counts": status_counts,
            "total_candidates_assigned": assigned_candidates_count,
            "total_attempts": total_attempts,
            "average_score": avg_score,
            "average_percentage": avg_percentage,
            "pass_rate": pass_rate,
            "fail_rate": fail_rate,
            "pending_grading_count": pending_grading_count,
            "awaiting_release_count": awaiting_release,
            "recent_assessments": recent_assessments
        }

    # =========================================================================
    # 2. CANDIDATE PERFORMANCE ANALYTICS & TOPIC TAXONOMY
    # =========================================================================
    @staticmethod
    def get_candidate_performance_analytics(
        db: Session,
        candidate_id: int,
        requesting_user: models.User
    ) -> Dict[str, Any]:
        """
        Aggregates performance analytics for a specific candidate.
        Enforces candidate privacy (unreleased results hidden from students).
        """
        student = db.query(models.User).filter_by(id=candidate_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Candidate not found")

        is_self = (requesting_user.id == candidate_id)

        # Scoping check for non-self users
        if not is_self and requesting_user.role != "super_admin":
            if requesting_user.organization_id and student.organization_id and requesting_user.organization_id != student.organization_id:
                raise HTTPException(status_code=403, detail="Not authorized to access another organization's candidate")

        # Query all candidate results
        res_query = db.query(models.ExamResult).join(models.ExamResult.exam).filter(
            models.ExamResult.student_id == candidate_id
        ).order_by(models.ExamResult.attempt_number.asc())

        all_results = res_query.all()

        # For student self-view, filter to released results
        visible_results = []
        pending_release_count = 0
        for r in all_results:
            is_released = r.is_released or (r.exam.results_released is True)
            if is_self and not is_released:
                pending_release_count += 1
                continue
            visible_results.append(r)

        total_attempted = len(all_results)
        if not visible_results:
            return {
                "candidate_id": student.id,
                "candidate_name": student.name,
                "candidate_email": student.email,
                "total_assessments_attempted": total_attempted,
                "average_percentage": 0.0,
                "best_percentage": 0.0,
                "latest_percentage": 0.0,
                "pass_count": 0,
                "fail_count": 0,
                "pending_count": pending_release_count,
                "improvement_trend": "insufficient_data",
                "attempts_history": [],
                "topic_performance": []
            }

        percentages = [r.percentage for r in visible_results if r.percentage is not None]
        avg_pct = round(sum(percentages) / len(percentages), 2) if percentages else 0.0
        best_pct = max(percentages) if percentages else 0.0
        latest_pct = percentages[-1] if percentages else 0.0

        pass_count = sum(1 for r in visible_results if r.pass_fail_status == "PASS")
        fail_count = sum(1 for r in visible_results if r.pass_fail_status == "FAIL")

        # Improvement / Decline Trend calculation
        if len(percentages) >= 2:
            delta = percentages[-1] - percentages[0]
            if delta > 2.0:
                trend = "improving"
            elif delta < -2.0:
                trend = "declining"
            else:
                trend = "consistent"
        else:
            trend = "insufficient_data"

        # Attempt History List
        attempts_history = []
        for r in visible_results:
            attempts_history.append({
                "session_id": r.exam_session_id,
                "attempt_number": r.attempt_number,
                "assessment_id": r.exam_id,
                "assessment_title": r.exam.title,
                "assessment_type": r.exam.assessment_type or "academic",
                "score": r.marks_obtained,
                "total_marks": r.total_marks,
                "percentage": r.percentage,
                "pass_fail_status": r.pass_fail_status,
                "is_released": r.is_released,
                "submitted_at": to_utc_iso(r.submission_timestamp) if r.submission_timestamp else None
            })

        # Topic & Subject Performance Breakdown (using question taxonomy)
        student_answers = db.query(models.StudentAnswer).join(models.StudentAnswer.question).filter(
            models.StudentAnswer.exam_session_id.in_([r.exam_session_id for r in visible_results])
        ).all()

        topic_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for sa in student_answers:
            q = sa.question
            subject = "General"
            topic = "Core"

            # Check linked bank question taxonomy if available
            if q.bank_question_id:
                bq = db.query(models.BankQuestion).filter_by(id=q.bank_question_id).first()
                if bq:
                    subject = bq.subject or subject
                    topic = bq.topic or topic
            elif q.explanation:
                # Check if subject/topic tagged
                topic = q.question_type or topic

            key = (subject, topic)
            if key not in topic_map:
                topic_map[key] = {"total": 0, "answered": 0, "correct": 0}

            topic_map[key]["total"] += 1
            if sa.selected_option_id is not None or (sa.answer_text and sa.answer_text.strip()):
                topic_map[key]["answered"] += 1
            if sa.is_correct:
                topic_map[key]["correct"] += 1

        topic_performance = []
        for (subj, top), stats in topic_map.items():
            tot = stats["total"]
            corr = stats["correct"]
            acc = round((corr / tot * 100.0), 2) if tot > 0 else 0.0
            topic_performance.append({
                "subject": subj,
                "topic": top,
                "total_questions": tot,
                "total_answered": stats["answered"],
                "correct_count": corr,
                "accuracy_percentage": acc
            })

        return {
            "candidate_id": student.id,
            "candidate_name": student.name,
            "candidate_email": student.email,
            "total_assessments_attempted": total_attempted,
            "average_percentage": avg_pct,
            "best_percentage": best_pct,
            "latest_percentage": latest_pct,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "pending_count": pending_release_count,
            "improvement_trend": trend,
            "attempts_history": attempts_history,
            "topic_performance": topic_performance
        }

    # =========================================================================
    # 3. ASSESSMENT ANALYTICS & QUESTION ACCURACY
    # =========================================================================
    @staticmethod
    def get_assessment_analytics(
        db: Session,
        exam_id: int,
        requesting_user: models.User
    ) -> Dict[str, Any]:
        """
        Deep-dive analytics for a single assessment including started/completed ratios,
        score distribution, question accuracy metrics, and separated proctoring summary.
        """
        exam = db.query(models.Exam).filter_by(id=exam_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found")

        # Scoping validation
        if requesting_user.role != "super_admin":
            if requesting_user.organization_id and exam.organization_id and requesting_user.organization_id != exam.organization_id:
                raise HTTPException(status_code=403, detail="Not authorized to access another organization's assessment")

        # Candidate participation counts
        assigned_count = db.query(distinct(models.AssessmentAssignment.candidate_id)).filter_by(
            assessment_id=exam.id
        ).count()
        if assigned_count == 0 and exam.group_id:
            assigned_count = db.query(distinct(models.GroupMember.student_id)).filter_by(
                group_id=exam.group_id
            ).count()

        started_count = db.query(distinct(models.ExamSession.student_id)).filter_by(
            exam_id=exam.id,
            status="in_progress"
        ).count()

        completed_count = db.query(distinct(models.ExamSession.student_id)).filter(
            models.ExamSession.exam_id == exam.id,
            models.ExamSession.status.in_(["submitted", "auto_submitted", "completed"])
        ).count()

        not_started_count = max(0, assigned_count - (started_count + completed_count))

        # Results aggregation
        results = db.query(models.ExamResult).filter_by(exam_id=exam.id).all()
        total_attempts = len(results)

        if total_attempts > 0:
            scores = [r.marks_obtained for r in results]
            percentages = [r.percentage for r in results]
            avg_score = round(sum(scores) / total_attempts, 2)
            high_score = round(max(scores), 2)
            low_score = round(min(scores), 2)
            avg_pct = round(sum(percentages) / total_attempts, 2)

            passed_count = sum(1 for r in results if r.pass_fail_status == "PASS")
            pass_percentage = round((passed_count / total_attempts * 100.0), 2)

            correct_count = sum(r.correct_count for r in results)
            incorrect_count = sum(r.incorrect_count for r in results)
            unanswered_count = sum(r.unanswered_count for r in results)
        else:
            avg_score = high_score = low_score = avg_pct = pass_percentage = 0.0
            correct_count = incorrect_count = unanswered_count = 0

        # Pending manual grading count
        pending_grading_count = db.query(models.StudentAnswer).join(models.StudentAnswer.question).filter(
            models.Question.exam_id == exam.id,
            models.StudentAnswer.evaluation_status.in_(["pending", "in_progress"])
        ).count()
        grading_status = "pending" if pending_grading_count > 0 else "completed"

        # Section-wise performance
        sections = db.query(models.AssessmentSection).filter_by(exam_id=exam.id).order_by(models.AssessmentSection.order_index).all()
        section_performance = []
        for sec in sections:
            sec_questions = db.query(models.Question).filter_by(section_id=sec.id).all()
            q_ids = [q.id for q in sec_questions]
            sec_max = sum(q.marks or exam.default_marks for q in sec_questions)

            if q_ids and total_attempts > 0:
                sec_answers = db.query(models.StudentAnswer).filter(
                    models.StudentAnswer.question_id.in_(q_ids)
                ).all()
                total_awarded = sum(a.marks_awarded or 0.0 for a in sec_answers)
                avg_obtained = round(total_awarded / total_attempts, 2)
                avg_pct = round((avg_obtained / sec_max * 100.0), 2) if sec_max > 0 else 0.0
            else:
                avg_obtained = avg_pct = 0.0

            section_performance.append({
                "section_id": sec.id,
                "name": sec.name,
                "max_marks": sec_max,
                "passing_percentage": sec.passing_percentage,
                "average_marks_obtained": avg_obtained,
                "average_percentage": avg_pct
            })

        # Question-wise Accuracy Analytics (Safe against zero division)
        questions = db.query(models.Question).filter_by(exam_id=exam.id).order_by(models.Question.order_index).all()
        question_analytics = []
        for q in questions:
            q_max = float(q.marks if q.marks is not None else (exam.default_marks or 1.0))
            answers = db.query(models.StudentAnswer).filter_by(question_id=q.id).all()
            q_attempts = len(answers)

            if q_attempts > 0:
                c_count = sum(1 for a in answers if a.is_correct)
                u_count = sum(1 for a in answers if a.selected_option_id is None and (not a.answer_text or not a.answer_text.strip()))
                i_count = max(0, q_attempts - (c_count + u_count))
                c_pct = round((c_count / q_attempts * 100.0), 2)
                i_pct = round((i_count / q_attempts * 100.0), 2)
                u_pct = round((u_count / q_attempts * 100.0), 2)
                avg_m = round(sum(a.marks_awarded or 0.0 for a in answers) / q_attempts, 2)
            else:
                c_count = i_count = u_count = 0
                c_pct = i_pct = u_pct = avg_m = 0.0

            question_analytics.append({
                "question_id": q.id,
                "question_text": q.text,
                "question_type": q.question_type or "single_choice",
                "topic": q.explanation or "Core",
                "subject": "Assessment Subject",
                "difficulty": "medium",
                "max_marks": q_max,
                "total_attempts": q_attempts,
                "correct_count": c_count,
                "incorrect_count": i_count,
                "unanswered_count": u_count,
                "correct_percentage": c_pct,
                "incorrect_percentage": i_pct,
                "unanswered_percentage": u_pct,
                "average_marks_obtained": avg_m
            })

        # Proctoring Integrity Summary (Separated from Academic Marks)
        sessions = db.query(models.ExamSession).filter_by(exam_id=exam.id).all()
        if sessions:
            avg_integrity = round(sum(s.integrity_score for s in sessions) / len(sessions), 1)
            risk_dist = {"low": 0, "medium": 0, "high": 0, "critical": 0}
            for s in sessions:
                rk = s.risk_level or "low"
                risk_dist[rk] = risk_dist.get(rk, 0) + 1
            total_flags = db.query(models.CheatFlag).filter_by(exam_id=exam.id).count()
            proctoring_summary = {
                "average_integrity_score": avg_integrity,
                "risk_distribution": risk_dist,
                "total_violations": total_flags
            }
        else:
            proctoring_summary = {
                "average_integrity_score": 100.0,
                "risk_distribution": {"low": 0, "medium": 0, "high": 0, "critical": 0},
                "total_violations": 0
            }

        return {
            "assessment_id": exam.id,
            "assessment_title": exam.title,
            "assessment_type": exam.assessment_type or "academic",
            "total_assigned": assigned_count,
            "started_count": started_count,
            "completed_count": completed_count,
            "not_started_count": not_started_count,
            "total_attempts": total_attempts,
            "average_score": avg_score,
            "highest_score": high_score,
            "lowest_score": low_score,
            "average_percentage": avg_pct,
            "pass_percentage": pass_percentage,
            "correct_count": correct_count,
            "incorrect_count": incorrect_count,
            "unanswered_count": unanswered_count,
            "manual_grading_status": grading_status,
            "pending_manual_grading_count": pending_grading_count,
            "section_performance": section_performance,
            "question_analytics": question_analytics,
            "proctoring_summary": proctoring_summary
        }

    # =========================================================================
    # 4. QUESTION BANK ANALYTICS
    # =========================================================================
    @staticmethod
    def get_question_bank_analytics(
        db: Session,
        exam_id: Optional[int] = None,
        requesting_user: Optional[models.User] = None
    ) -> List[Dict[str, Any]]:
        """
        Calculates performance analytics per question with zero-division safety.
        Flags questions frequently answered incorrectly (accuracy < 40%).
        """
        query = db.query(models.Question)
        if exam_id:
            query = query.filter(models.Question.exam_id == exam_id)
        if requesting_user and requesting_user.role != "super_admin":
            if requesting_user.organization_id:
                query = query.join(models.Question.exam).filter(models.Exam.organization_id == requesting_user.organization_id)

        questions = query.all()
        results = []
        for q in questions:
            exam = q.exam
            q_max = float(q.marks if q.marks is not None else (exam.default_marks if exam else 1.0))
            answers = db.query(models.StudentAnswer).filter_by(question_id=q.id).all()
            attempts = len(answers)

            if attempts > 0:
                c_count = sum(1 for a in answers if a.is_correct)
                u_count = sum(1 for a in answers if a.selected_option_id is None and (not a.answer_text or not a.answer_text.strip()))
                i_count = max(0, attempts - (c_count + u_count))
                c_pct = round((c_count / attempts * 100.0), 2)
                i_pct = round((i_count / attempts * 100.0), 2)
                u_pct = round((u_count / attempts * 100.0), 2)
                avg_m = round(sum(a.marks_awarded or 0.0 for a in answers) / attempts, 2)
            else:
                c_count = i_count = u_count = 0
                c_pct = i_pct = u_pct = avg_m = 0.0

            results.append({
                "question_id": q.id,
                "question_text": q.text,
                "question_type": q.question_type or "single_choice",
                "topic": q.explanation or "General",
                "subject": "General",
                "difficulty": "medium",
                "max_marks": q_max,
                "total_attempts": attempts,
                "correct_count": c_count,
                "incorrect_count": i_count,
                "unanswered_count": u_count,
                "correct_percentage": c_pct,
                "incorrect_percentage": i_pct,
                "unanswered_percentage": u_pct,
                "average_marks_obtained": avg_m,
                "frequently_incorrect": bool(attempts > 0 and c_pct < 40.0)
            })
        return results

    # =========================================================================
    # 5. ORGANIZATION ADMIN DASHBOARD
    # =========================================================================
    @staticmethod
    def get_organization_dashboard_metrics(
        db: Session,
        current_user: models.User,
        target_org_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Computes organization-scoped analytics for Org Admin and Super Admin.
        Enforces strict multi-tenant boundary.
        """
        # Determine effective organization
        if current_user.role == "super_admin":
            org_id = target_org_id
        else:
            if target_org_id and current_user.organization_id != target_org_id:
                raise HTTPException(status_code=403, detail="Not authorized to access another organization's dashboard")
            org_id = current_user.organization_id

        org = db.query(models.Organization).filter_by(id=org_id).first() if org_id else None
        org_name = org.name if org else "All Organizations (Super Admin View)"

        # User counts
        users_query = db.query(models.User)
        if org_id:
            users_query = users_query.filter(models.User.organization_id == org_id)

        total_examiners = users_query.filter(models.User.role.in_(["teacher", "examiner", "admin"])).count()
        total_candidates = users_query.filter(models.User.role == "student").count()

        # Assessment counts
        exam_query = db.query(models.Exam)
        if org_id:
            exam_query = exam_query.filter(models.Exam.organization_id == org_id)

        exams = exam_query.all()
        exam_ids = [e.id for e in exams]

        active_exams = sum(1 for e in exams if e.status == "active")
        completed_exams = sum(1 for e in exams if e.status == "completed")

        # Assessment type distribution
        type_dist = {"academic": 0, "placement": 0, "technical": 0, "custom": 0}
        for e in exams:
            t = e.assessment_type or "academic"
            type_dist[t] = type_dist.get(t, 0) + 1

        # Results aggregation
        if exam_ids:
            res_agg = db.query(
                func.count(models.ExamResult.id).label("total_attempts"),
                func.avg(models.ExamResult.percentage).label("avg_pct"),
                func.sum(case((models.ExamResult.pass_fail_status == "PASS", 1), else_=0)).label("passed")
            ).filter(models.ExamResult.exam_id.in_(exam_ids)).first()

            total_attempts = res_agg.total_attempts or 0
            avg_org_pct = round(float(res_agg.avg_pct or 0.0), 2)
            passed = int(res_agg.passed or 0)
            pass_rate = round((passed / total_attempts * 100.0), 2) if total_attempts > 0 else 0.0
        else:
            total_attempts = 0
            avg_org_pct = 0.0
            pass_rate = 0.0

        # Group/Department performance
        group_perf = []
        groups_query = db.query(models.Group)
        if org_id:
            groups_query = groups_query.filter(models.Group.organization_id == org_id)
        groups = groups_query.all()

        for g in groups:
            g_exams = [e.id for e in exams if e.group_id == g.id]
            if g_exams:
                g_res = db.query(
                    func.count(models.ExamResult.id).label("attempts"),
                    func.avg(models.ExamResult.percentage).label("avg_pct")
                ).filter(models.ExamResult.exam_id.in_(g_exams)).first()
                att = g_res.attempts or 0
                g_pct = round(float(g_res.avg_pct or 0.0), 2)
            else:
                att = 0
                g_pct = 0.0

            group_perf.append({
                "group_id": g.id,
                "name": g.name,
                "total_attempts": att,
                "average_percentage": g_pct
            })

        # Activity Trend (Recent 7 days attempts)
        activity_trend = []
        now = utc_now()
        for i in range(6, -1, -1):
            day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            cnt = db.query(models.ExamSession).filter(
                models.ExamSession.exam_id.in_(exam_ids) if exam_ids else False,
                models.ExamSession.submitted_at >= day_start,
                models.ExamSession.submitted_at < day_end
            ).count()
            activity_trend.append({
                "date": day_start.strftime("%Y-%m-%d"),
                "attempts_count": cnt
            })

        return {
            "organization_id": org_id,
            "organization_name": org_name,
            "total_examiners": total_examiners,
            "total_candidates": total_candidates,
            "total_assessments": len(exams),
            "active_assessments": active_exams,
            "completed_assessments": completed_exams,
            "total_attempts": total_attempts,
            "average_organization_percentage": avg_org_pct,
            "pass_rate": pass_rate,
            "group_performance": group_perf,
            "assessment_type_distribution": type_dist,
            "activity_trend": activity_trend
        }

    # =========================================================================
    # 6. REPORTING AND CSV/JSON EXPORTS
    # =========================================================================
    @staticmethod
    def generate_assessment_results_csv(
        db: Session,
        exam_id: int,
        current_user: models.User
    ) -> str:
        """Generates downloadable CSV for all candidate results of an assessment."""
        exam = db.query(models.Exam).filter_by(id=exam_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Assessment not found")

        if current_user.role != "super_admin":
            if current_user.organization_id and exam.organization_id and current_user.organization_id != exam.organization_id:
                raise HTTPException(status_code=403, detail="Not authorized for another organization")

        results = db.query(models.ExamResult).filter_by(exam_id=exam.id).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Candidate ID", "Candidate Name", "Candidate Email",
            "Assessment ID", "Assessment Title", "Attempt Number",
            "Marks Obtained", "Total Marks", "Percentage",
            "Pass/Fail Status", "Manual Grading Status", "Released", "Submission Timestamp"
        ])

        for r in results:
            stud = r.student
            writer.writerow([
                r.student_id,
                stud.name if stud else "",
                stud.email if stud else "",
                exam.id,
                exam.title,
                r.attempt_number,
                r.marks_obtained,
                r.total_marks,
                r.percentage,
                r.pass_fail_status,
                r.manual_grading_status,
                r.is_released,
                to_utc_iso(r.submission_timestamp) if r.submission_timestamp else ""
            ])

        return output.getvalue()

    @staticmethod
    def generate_candidate_performance_csv(
        db: Session,
        candidate_id: int,
        requesting_user: models.User
    ) -> str:
        """
        Generates downloadable CSV of candidate performance history.
        Enforces candidate privacy (unreleased results hidden from students).
        """
        student = db.query(models.User).filter_by(id=candidate_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Candidate not found")

        is_self = (requesting_user.id == candidate_id)
        if not is_self and requesting_user.role != "super_admin":
            if requesting_user.organization_id and student.organization_id and requesting_user.organization_id != student.organization_id:
                raise HTTPException(status_code=403, detail="Not authorized for another organization")

        results = db.query(models.ExamResult).join(models.ExamResult.exam).filter(
            models.ExamResult.student_id == student.id
        ).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Assessment ID", "Assessment Title", "Attempt Number",
            "Marks Obtained", "Total Marks", "Percentage", "Pass/Fail Status", "Submitted At"
        ])

        for r in results:
            is_released = r.is_released or (r.exam.results_released is True)
            if is_self and not is_released:
                # Privacy: skip unreleased results in student download
                continue
            writer.writerow([
                r.exam_id,
                r.exam.title,
                r.attempt_number,
                r.marks_obtained,
                r.total_marks,
                r.percentage,
                r.pass_fail_status,
                to_utc_iso(r.submission_timestamp) if r.submission_timestamp else ""
            ])

        return output.getvalue()

    @staticmethod
    def generate_question_analytics_csv(
        db: Session,
        exam_id: int,
        current_user: models.User
    ) -> str:
        """Generates downloadable CSV of question performance analytics."""
        analytics = AnalyticsService.get_question_bank_analytics(db, exam_id, current_user)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Question ID", "Question Text", "Type", "Max Marks",
            "Attempts", "Correct Count", "Incorrect Count", "Unanswered Count",
            "Correct %", "Incorrect %", "Unanswered %", "Avg Marks", "Frequently Incorrect"
        ])

        for a in analytics:
            writer.writerow([
                a["question_id"],
                a["question_text"],
                a["question_type"],
                a["max_marks"],
                a["total_attempts"],
                a["correct_count"],
                a["incorrect_count"],
                a["unanswered_count"],
                a["correct_percentage"],
                a["incorrect_percentage"],
                a["unanswered_percentage"],
                a["average_marks_obtained"],
                a["frequently_incorrect"]
            ])

        return output.getvalue()
