"""
modules/assessments/sections.py
-------------------------------
Service and validation logic for assessment sections:
- Mandatory vs optional section rules
- Sequential vs free section navigation
- Section-specific time limits
- Section completion and transition tracking in ExamSession
- Persistent section progress across browser refreshes
"""
from typing import List, Dict, Any, Optional
import json
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

import models
from time_utils import utc_now, to_utc


class SectionService:

    @staticmethod
    def get_sections(db: Session, exam_id: int) -> List[models.AssessmentSection]:
        return db.query(models.AssessmentSection).filter(
            models.AssessmentSection.exam_id == exam_id
        ).order_by(models.AssessmentSection.order_index.asc(), models.AssessmentSection.id.asc()).all()

    @staticmethod
    def get_completed_section_ids(exam_session: models.ExamSession) -> List[int]:
        if not exam_session.completed_sections:
            return []
        try:
            val = json.loads(exam_session.completed_sections)
            return val if isinstance(val, list) else []
        except Exception:
            return []

    @staticmethod
    def can_access_section(
        db: Session,
        exam_session: models.ExamSession,
        target_section_id: int
    ) -> Dict[str, Any]:
        """
        Check whether the candidate is allowed to view or submit answers in target_section_id.
        Rules:
        - If target_section_id is already marked completed:
          - If target_section's navigation_mode == "sequential": disallow backward navigation.
          - If navigation_mode == "free": allow viewing/reviewing.
        - If sequential mode is active: candidate must not skip previous mandatory sections.
        """
        sections = SectionService.get_sections(db, exam_session.exam_id)
        if not sections:
            return {"allowed": True, "reason": None}

        sec_map = {s.id: s for s in sections}
        target_sec = sec_map.get(target_section_id)
        if not target_sec:
            return {"allowed": False, "reason": "Section not found."}

        completed_ids = SectionService.get_completed_section_ids(exam_session)

        # 1. Check if section is already completed and in sequential mode
        if target_section_id in completed_ids:
            if target_sec.navigation_mode == "sequential":
                return {
                    "allowed": False,
                    "reason": "Sequential section completed. Backward navigation to completed sections is prohibited."
                }

        # 2. Sequential progression check:
        # If any section before target_section_id is mandatory and NOT completed, block skipping to target
        target_index = target_sec.order_index or 0
        for s in sections:
            s_idx = s.order_index or 0
            if s_idx < target_index:
                # If s is sequential or mandatory and not completed
                if (s.navigation_mode == "sequential" or s.is_mandatory) and s.id not in completed_ids:
                    return {
                        "allowed": False,
                        "reason": f"You must complete section '{s.name}' before proceeding to this section."
                    }

        return {"allowed": True, "reason": None}

    @staticmethod
    def complete_section(
        db: Session,
        exam_session: models.ExamSession,
        section_id: int
    ) -> models.ExamSession:
        """
        Mark a section as completed and advance current_section_id to the next available section.
        """
        completed = set(SectionService.get_completed_section_ids(exam_session))
        completed.add(section_id)
        exam_session.completed_sections = json.dumps(sorted(list(completed)))

        sections = SectionService.get_sections(db, exam_session.exam_id)
        # Find next uncompleted section
        next_sec = None
        for s in sections:
            if s.id not in completed:
                next_sec = s
                break

        exam_session.current_section_id = next_sec.id if next_sec else None
        db.commit()
        db.refresh(exam_session)
        return exam_session

    @staticmethod
    def get_active_section(db: Session, exam_session: models.ExamSession) -> Optional[models.AssessmentSection]:
        """Determine which section the candidate should be on."""
        sections = SectionService.get_sections(db, exam_session.exam_id)
        if not sections:
            return None

        completed = set(SectionService.get_completed_section_ids(exam_session))

        # If current_section_id is set and not completed, return it
        if exam_session.current_section_id:
            for s in sections:
                if s.id == exam_session.current_section_id and s.id not in completed:
                    return s

        # Otherwise pick the first uncompleted section
        for s in sections:
            if s.id not in completed:
                exam_session.current_section_id = s.id
                db.commit()
                return s

        # All completed
        return sections[-1] if sections else None
