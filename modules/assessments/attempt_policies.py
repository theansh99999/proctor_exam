"""
modules/assessments/attempt_policies.py
---------------------------------------
Service and logic for advanced attempt policies:
- Max attempts enforcement
- Cooldown timer enforcement between consecutive attempts
- Retake eligibility rules (always vs on_failure_only)
- Multi-attempt score aggregation (best, latest, first, average)
- Interrupted attempt restoration
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import json
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

import models
from time_utils import utc_now, to_utc


class AttemptPolicyService:

    @staticmethod
    def parse_policy(exam: models.Exam) -> Dict[str, Any]:
        """Safely parse attempt_policy from exam model with default fallbacks."""
        defaults = {
            "cooldown_minutes": 0,
            "retake_eligibility": "always",  # "always" | "on_failure_only"
            "score_policy": "best"          # "best" | "latest" | "first" | "average"
        }
        if not exam.attempt_policy:
            return defaults
        if isinstance(exam.attempt_policy, dict):
            defaults.update(exam.attempt_policy)
            return defaults
        try:
            parsed = json.loads(exam.attempt_policy)
            if isinstance(parsed, dict):
                defaults.update(parsed)
        except Exception:
            pass
        return defaults

    @staticmethod
    def check_attempt_eligibility(db: Session, exam: models.Exam, student_id: int) -> Dict[str, Any]:
        """
        Evaluate if candidate can start a new attempt or resume an active one.
        Returns:
            {
                "eligible": bool,
                "reason": Optional[str],
                "active_session_id": Optional[int],
                "remaining_cooldown_seconds": int,
                "completed_attempts": int,
                "max_attempts": int,
                "policy": Dict[str, Any]
            }
        """
        policy = AttemptPolicyService.parse_policy(exam)
        max_attempts = exam.max_attempts or 1

        # 1. Interrupted attempt restoration: If candidate has an active session, they can resume it!
        active_session = db.query(models.ExamSession).filter(
            models.ExamSession.exam_id == exam.id,
            models.ExamSession.student_id == student_id,
            models.ExamSession.status == "in_progress"
        ).first()

        if active_session:
            return {
                "eligible": True,
                "reason": "Resuming existing active session",
                "active_session_id": active_session.id,
                "remaining_cooldown_seconds": 0,
                "completed_attempts": 0,
                "max_attempts": max_attempts,
                "policy": policy
            }

        # 2. Query completed attempts
        completed_sessions = db.query(models.ExamSession).filter(
            models.ExamSession.exam_id == exam.id,
            models.ExamSession.student_id == student_id,
            models.ExamSession.status.in_(["completed", "submitted", "auto_submitted", "expired"])
        ).order_by(models.ExamSession.submitted_at.desc(), models.ExamSession.started_at.desc()).all()

        completed_count = len(completed_sessions)

        # Check maximum attempts
        if completed_count >= max_attempts:
            return {
                "eligible": False,
                "reason": f"Maximum assessment attempts reached ({completed_count}/{max_attempts}).",
                "active_session_id": None,
                "remaining_cooldown_seconds": 0,
                "completed_attempts": completed_count,
                "max_attempts": max_attempts,
                "policy": policy
            }

        # If there are prior attempts, enforce cooldown and retake rules
        if completed_sessions:
            last_session = completed_sessions[0]
            last_end = last_session.submitted_at or last_session.started_at
            if last_end:
                last_end_utc = to_utc(last_end)
                cooldown_sec = policy.get("cooldown_minutes", 0) * 60
                elapsed_sec = (utc_now() - last_end_utc).total_seconds()
                remaining_sec = max(0, int(cooldown_sec - elapsed_sec))

                if remaining_sec > 0:
                    mins = (remaining_sec + 59) // 60
                    return {
                        "eligible": False,
                        "reason": f"Attempt cooldown active. Please wait {mins} minute(s) before attempting again.",
                        "active_session_id": None,
                        "remaining_cooldown_seconds": remaining_sec,
                        "completed_attempts": completed_count,
                        "max_attempts": max_attempts,
                        "policy": policy
                    }

            # Enforce retake eligibility (on_failure_only)
            retake_rule = policy.get("retake_eligibility", "always")
            if retake_rule == "on_failure_only":
                # Check if candidate passed in any or the latest attempt
                # If passing_criteria == "percentage", compare score %; otherwise score vs passing_marks
                last_score = last_session.score if last_session.score is not None else 0.0
                passing_marks = exam.passing_marks or 0.0
                passed = last_score >= passing_marks
                if passed and passing_marks > 0:
                    return {
                        "eligible": False,
                        "reason": "Retake is only permitted upon failure. You have already achieved a passing score.",
                        "active_session_id": None,
                        "remaining_cooldown_seconds": 0,
                        "completed_attempts": completed_count,
                        "max_attempts": max_attempts,
                        "policy": policy
                    }

        return {
            "eligible": True,
            "reason": None,
            "active_session_id": None,
            "remaining_cooldown_seconds": 0,
            "completed_attempts": completed_count,
            "max_attempts": max_attempts,
            "policy": policy
        }

    @staticmethod
    def compute_consolidated_grade(db: Session, exam: models.Exam, student_id: int) -> Dict[str, Any]:
        """
        Calculate candidate's consolidated final score across attempts based on score_policy.
        Policies:
        - "best": highest score
        - "latest": most recent completed attempt score
        - "first": earliest completed attempt score
        - "average": arithmetic mean of scores
        """
        policy = AttemptPolicyService.parse_policy(exam)
        score_policy = policy.get("score_policy", "best")

        completed_sessions = db.query(models.ExamSession).filter(
            models.ExamSession.exam_id == exam.id,
            models.ExamSession.student_id == student_id,
            models.ExamSession.status.in_(["completed", "submitted", "auto_submitted", "expired"])
        ).order_by(models.ExamSession.started_at.asc()).all()

        if not completed_sessions:
            return {
                "score": 0.0,
                "policy": score_policy,
                "attempts_evaluated": 0,
                "passed": False,
                "attempts_scores": []
            }

        scores = [s.score if s.score is not None else 0.0 for s in completed_sessions]

        if score_policy == "best":
            final_score = max(scores)
        elif score_policy == "latest":
            final_score = scores[-1]
        elif score_policy == "first":
            final_score = scores[0]
        elif score_policy == "average":
            final_score = round(sum(scores) / len(scores), 2)
        else:
            final_score = max(scores)

        passing_marks = exam.passing_marks or 0.0
        passed = final_score >= passing_marks if passing_marks > 0 else True

        return {
            "score": final_score,
            "policy": score_policy,
            "attempts_evaluated": len(scores),
            "passed": passed,
            "attempts_scores": scores
        }
