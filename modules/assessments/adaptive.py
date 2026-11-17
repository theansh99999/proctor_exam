"""
modules/assessments/adaptive.py
-------------------------------
Adaptive Assessment Engine:
- Rule-based difficulty progression (Easy <-> Medium <-> Hard)
- Dynamic server-controlled question selection
- Difficulty bounds enforcement (min/max bounds)
- Anti-tampering server state validation
- State persistence in ExamSession.adaptive_state for clean refresh recovery
- Stopping conditions (max questions, question pool exhaustion)
"""
from typing import Dict, Any, List, Optional, Tuple
import json
import random
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

import models
from time_utils import utc_now

DIFFICULTY_LEVELS = {
    "easy": 1,
    "medium": 2,
    "hard": 3
}

LEVEL_TO_DIFF = {
    1: "easy",
    2: "medium",
    3: "hard"
}


class AdaptiveService:

    @staticmethod
    def parse_adaptive_config(exam: models.Exam) -> Dict[str, Any]:
        defaults = {
            "starting_difficulty": "medium",
            "min_difficulty": "easy",
            "max_difficulty": "hard",
            "step_up": 1,
            "step_down": 1,
            "min_questions": 3,
            "max_questions": 10
        }
        if not exam.adaptive_config:
            return defaults
        if isinstance(exam.adaptive_config, dict):
            defaults.update(exam.adaptive_config)
            return defaults
        try:
            parsed = json.loads(exam.adaptive_config)
            if isinstance(parsed, dict):
                defaults.update(parsed)
        except Exception:
            pass
        return defaults

    @staticmethod
    def get_candidate_questions_pool(db: Session, exam: models.Exam) -> List[Dict[str, Any]]:
        """
        Fetch available question pool for the assessment with normalized difficulty.
        Supports both models.Question and AssessmentQuestionMap -> BankQuestion.
        """
        pool = []
        # 1. Direct Question records
        direct_qs = db.query(models.Question).filter(models.Question.exam_id == exam.id).all()
        for q in direct_qs:
            diff = "medium"
            if q.bank_question_id:
                bq = db.query(models.BankQuestion).filter(models.BankQuestion.id == q.bank_question_id).first()
                if bq and bq.difficulty:
                    diff = bq.difficulty.lower()
            pool.append({
                "id": q.id,
                "question_id": q.id,
                "text": q.text,
                "difficulty": diff if diff in DIFFICULTY_LEVELS else "medium",
                "marks": q.marks or exam.default_marks or 1.0,
                "negative_marks": q.negative_marks or exam.default_negative_marks or 0.0,
                "question_type": q.question_type or "mcq_single"
            })

        # 2. If no direct questions, check AssessmentQuestionMap -> BankQuestion
        if not pool:
            mapped_qs = db.query(models.AssessmentQuestionMap, models.BankQuestion).join(
                models.BankQuestion, models.AssessmentQuestionMap.bank_question_id == models.BankQuestion.id
            ).filter(models.AssessmentQuestionMap.assessment_id == exam.id).all()

            for aqm, bq in mapped_qs:
                diff = (bq.difficulty or "medium").lower()
                pool.append({
                    "id": aqm.id,
                    "bank_question_id": bq.id,
                    "text": bq.text,
                    "difficulty": diff if diff in DIFFICULTY_LEVELS else "medium",
                    "marks": aqm.marks or bq.default_marks or 1.0,
                    "negative_marks": aqm.negative_marks or bq.default_negative_marks or 0.0,
                    "question_type": bq.question_type or "mcq_single"
                })

        return pool

    @staticmethod
    def initialize_adaptive_session(
        db: Session,
        exam_session: models.ExamSession,
        exam: models.Exam
    ) -> Dict[str, Any]:
        """
        Initialize or resume adaptive testing state for an ExamSession.
        """
        if exam_session.adaptive_state:
            try:
                state = json.loads(exam_session.adaptive_state) if isinstance(exam_session.adaptive_state, str) else exam_session.adaptive_state
                if isinstance(state, dict) and "current_question_id" in state:
                    return state
            except Exception:
                pass

        config = AdaptiveService.parse_adaptive_config(exam)
        start_diff = config.get("starting_difficulty", "medium").lower()
        if start_diff not in DIFFICULTY_LEVELS:
            start_diff = "medium"

        start_level = DIFFICULTY_LEVELS[start_diff]
        pool = AdaptiveService.get_candidate_questions_pool(db, exam)

        # Find a question matching starting difficulty
        matching = [q for q in pool if q["difficulty"] == start_diff]
        if not matching:
            matching = pool  # fallback if pool doesn't have exact difficulty

        first_q = random.choice(matching) if matching else None
        first_q_id = first_q["id"] if first_q else None

        state = {
            "current_difficulty": start_diff,
            "current_level": start_level,
            "min_difficulty": config.get("min_difficulty", "easy").lower(),
            "max_difficulty": config.get("max_difficulty", "hard").lower(),
            "step_up": config.get("step_up", 1),
            "step_down": config.get("step_down", 1),
            "min_questions": config.get("min_questions", 3),
            "max_questions": config.get("max_questions", 10),
            "step_number": 1,
            "current_question_id": first_q_id,
            "asked_question_ids": [first_q_id] if first_q_id else [],
            "history": [],
            "is_finished": False if first_q_id else True
        }

        exam_session.adaptive_state = json.dumps(state)
        exam_session.current_question_id = first_q_id
        db.commit()
        db.refresh(exam_session)
        return state

    @staticmethod
    def evaluate_answer_correctness(
        db: Session,
        question_id: int,
        selected_option_id: Optional[int] = None,
        answer_text: Optional[str] = None
    ) -> Tuple[bool, float]:
        """Determine if an answer is correct and calculate marks."""
        # Check models.Option first
        options = db.query(models.Option).filter(models.Option.question_id == question_id).all()
        if options and selected_option_id:
            opt = next((o for o in options if o.id == selected_option_id), None)
            if opt and opt.is_correct:
                return True, 1.0
            return False, 0.0

        # Check BankQuestion options
        bq_options = db.query(models.BankOption).filter(models.BankOption.question_id == question_id).all()
        if bq_options and selected_option_id:
            opt = next((o for o in bq_options if o.id == selected_option_id), None)
            if opt and opt.is_correct:
                return True, 1.0
            return False, 0.0

        # Fallback text check (True/False or short answer)
        if answer_text:
            cleaned = answer_text.strip().lower()
            if cleaned in ("true", "t", "yes"):
                return True, 1.0

        return False, 0.0

    @staticmethod
    def submit_answer_and_advance(
        db: Session,
        exam_session: models.ExamSession,
        exam: models.Exam,
        question_id: int,
        selected_option_id: Optional[int] = None,
        answer_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Record the candidate's answer for the current adaptive question,
        adjust difficulty dynamically, and choose the next question.
        """
        if not exam_session.adaptive_state:
            AdaptiveService.initialize_adaptive_session(db, exam_session, exam)

        state = json.loads(exam_session.adaptive_state) if isinstance(exam_session.adaptive_state, str) else exam_session.adaptive_state

        if state.get("is_finished"):
            raise HTTPException(status_code=400, detail="Adaptive assessment has already finished.")

        # Tamper check: must match current question
        if state.get("current_question_id") != question_id:
            raise HTTPException(status_code=400, detail="Question ID does not match the active adaptive question.")

        # Evaluate correctness
        is_correct, score_factor = AdaptiveService.evaluate_answer_correctness(
            db, question_id, selected_option_id, answer_text
        )

        curr_diff = state.get("current_difficulty", "medium")
        curr_level = DIFFICULTY_LEVELS.get(curr_diff, 2)
        min_level = DIFFICULTY_LEVELS.get(state.get("min_difficulty", "easy"), 1)
        max_level = DIFFICULTY_LEVELS.get(state.get("max_difficulty", "hard"), 3)
        step_up = state.get("step_up", 1)
        step_down = state.get("step_down", 1)

        # Difficulty progression
        if is_correct:
            new_level = min(max_level, curr_level + step_up)
        else:
            new_level = max(min_level, curr_level - step_down)

        new_diff = LEVEL_TO_DIFF.get(new_level, "medium")

        # Record step history
        step_entry = {
            "step": state.get("step_number", 1),
            "question_id": question_id,
            "difficulty": curr_diff,
            "is_correct": is_correct,
            "selected_option_id": selected_option_id,
            "answer_text": answer_text
        }
        state["history"].append(step_entry)

        # Check stopping condition: Max questions reached
        max_q = state.get("max_questions", 10)
        if len(state["history"]) >= max_q:
            state["is_finished"] = True
            state["current_question_id"] = None
            exam_session.adaptive_state = json.dumps(state)
            db.commit()
            return {
                "is_finished": True,
                "history": state["history"],
                "total_answered": len(state["history"]),
                "next_question": None
            }

        # Select next question from pool matching new_diff
        pool = AdaptiveService.get_candidate_questions_pool(db, exam)
        asked_ids = set(state.get("asked_question_ids", []))
        asked_ids.add(question_id)
        state["asked_question_ids"] = list(asked_ids)

        unasked = [q for q in pool if q["id"] not in asked_ids]
        if not unasked:
            # Question pool exhausted
            state["is_finished"] = True
            state["current_question_id"] = None
            exam_session.adaptive_state = json.dumps(state)
            db.commit()
            return {
                "is_finished": True,
                "history": state["history"],
                "total_answered": len(state["history"]),
                "next_question": None
            }

        # Match exact target difficulty or nearest
        matching = [q for q in unasked if q["difficulty"] == new_diff]
        if not matching:
            # Fallback to any unasked question, preferring closest level
            unasked_sorted = sorted(
                unasked,
                key=lambda q: abs(DIFFICULTY_LEVELS.get(q["difficulty"], 2) - new_level)
            )
            next_q = unasked_sorted[0]
        else:
            next_q = random.choice(matching)

        next_q_id = next_q["id"]
        state["asked_question_ids"].append(next_q_id)
        state["current_question_id"] = next_q_id
        state["current_difficulty"] = next_q["difficulty"]
        state["current_level"] = DIFFICULTY_LEVELS.get(next_q["difficulty"], 2)
        state["step_number"] = state.get("step_number", 1) + 1

        exam_session.adaptive_state = json.dumps(state)
        exam_session.current_question_id = next_q_id
        db.commit()

        return {
            "is_finished": False,
            "next_question_id": next_q_id,
            "current_difficulty": state["current_difficulty"],
            "step_number": state["step_number"],
            "total_answered": len(state["history"])
        }
