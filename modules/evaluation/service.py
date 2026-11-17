"""

modules/evaluation/service.py

-----------------------------

Unified Evaluation, Manual Grading, Pass/Fail, Sections, and Results Engine.

Preserves strict separation between academic performance and proctoring metrics.

"""

import json

from datetime import datetime

from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy.orm import Session, joinedload

from fastapi import HTTPException



import models

from time_utils import utc_now, to_utc_iso





class EvaluationService:



    # =========================================================================

    # 1. QUESTION EVALUATION LOGIC ACROSS SIX TYPES

    # =========================================================================

    @staticmethod

    def evaluate_question_response(

        q: models.Question,

        exam: models.Exam,

        selected_option_id: Optional[int],

        answer_text: Optional[str]

    ) -> Tuple[bool, float, str]:

        """

        Evaluates candidate response across all 6 question types.

        Returns:

            (is_correct: bool, marks_awarded: float, evaluation_status: str)

            evaluation_status: 'evaluated', 'pending', 'in_progress', 'graded'

        """

        q_marks = q.marks if q.marks is not None else (exam.default_marks if exam else 1.0)

        q_neg = q.negative_marks if q.negative_marks is not None else (

            exam.default_negative_marks if (exam and exam.enable_negative_marking) else 0.0

        )

        q_type = q.question_type or "single_choice"



        # 1. Single Choice & True/False

        if q_type in ("single_choice", "true_false"):

            if not selected_option_id:

                return False, 0.0, "evaluated"

            opt = next((o for o in q.options if o.id == selected_option_id), None)

            if opt and opt.is_correct:

                return True, float(q_marks), "evaluated"

            else:

                return False, -float(q_neg), "evaluated"



        # 2. Multiple Choice (Multi-select)

        elif q_type == "multiple_choice":

            selected_ids = set()

            if answer_text and answer_text.strip().startswith("["):

                try:

                    selected_ids = set(json.loads(answer_text))

                except Exception:

                    pass

            elif selected_option_id:

                selected_ids = {selected_option_id}



            if not selected_ids:

                return False, 0.0, "evaluated"



            correct_ids = {o.id for o in q.options if o.is_correct}



            # Check for partial marking configuration in type_config

            cfg = {}

            if q.type_config:

                try:

                    cfg = json.loads(q.type_config) if isinstance(q.type_config, str) else q.type_config

                except Exception:

                    pass



            if cfg.get("partial_marking", False) and len(correct_ids) > 0:

                # Proportional partial credit

                correct_selected = len(selected_ids.intersection(correct_ids))

                incorrect_selected = len(selected_ids - correct_ids)



                credit_ratio = correct_selected / len(correct_ids)

                penalty_ratio = (incorrect_selected / len(q.options)) if len(q.options) > 0 else 0.0



                awarded = max(0.0, round((credit_ratio * q_marks) - (penalty_ratio * q_neg), 2))

                is_correct = (selected_ids == correct_ids)

                return is_correct, awarded, "evaluated"

            else:

                # Exact match scoring

                if selected_ids == correct_ids:

                    return True, float(q_marks), "evaluated"

                else:

                    return False, -float(q_neg), "evaluated"



        # 3. Short Answer

        elif q_type == "short_answer":

            if not answer_text or not answer_text.strip():

                return False, 0.0, "evaluated"



            cand_ans = answer_text.strip().lower()

            cfg = {}

            if q.type_config:

                try:

                    cfg = json.loads(q.type_config) if isinstance(q.type_config, str) else q.type_config

                except Exception:

                    pass



            # Keyword / Expected answer matching

            expected_answers = [o.text.strip().lower() for o in q.options if o.is_correct and o.text]

            if q.explanation:

                expected_answers.append(q.explanation.strip().lower())

            if "expected_answers" in cfg:

                expected_answers.extend([str(a).strip().lower() for a in cfg["expected_answers"]])



            keywords = [str(k).strip().lower() for k in cfg.get("keywords", cfg.get("expected_keywords", []))]



            # Check exact match first

            if any(cand_ans == exp for exp in expected_answers):

                return True, float(q_marks), "evaluated"



            # Check keyword match

            if keywords and all(kw in cand_ans for kw in keywords):

                return True, float(q_marks), "evaluated"



            # If manual review is mandated or no automated match in keyword mode

            if cfg.get("require_manual_review", False):

                return False, 0.0, "pending"



            return False, 0.0, "evaluated"



        # 4. Descriptive Answer

        elif q_type == "descriptive":

            has_ans = bool(answer_text and len(answer_text.strip()) > 0)

            if not has_ans:

                return False, 0.0, "evaluated"

            # Submitted descriptive answer recorded and queued for examiner manual grading

            return True, 0.0, "pending"



        # 5. Programming / Code

        elif q_type == "code":

            has_ans = bool(answer_text and len(answer_text.strip()) > 0)

            if not has_ans:

                return False, 0.0, "evaluated"

            # Retain code answer; queue for manual evaluation in this phase

            return True, 0.0, "pending"



        # Fallback for unexpected question types

        if selected_option_id:

            opt = next((o for o in q.options if o.id == selected_option_id), None)

            if opt and opt.is_correct:

                return True, float(q_marks), "evaluated"

            else:

                return False, -float(q_neg), "evaluated"

        return False, 0.0, "evaluated"



    # =========================================================================

    # 2. ATTEMPT-LEVEL UNIFIED EVALUATION & RESULT GENERATION

    # =========================================================================

    @staticmethod

    def evaluate_attempt(

        db: Session,

        exam_session: models.ExamSession

    ) -> models.ExamResult:

        """

        Consolidated evaluation for an ExamSession attempt:

        - Evaluates objective answers.

        - Preserves manual grades for descriptive answers.

        - Calculates section-wise scores.

        - Applies overall, section, and mandatory pass/fail rules.

        - Generates or updates ExamResult and synchronizes Submission.

        """

        exam = exam_session.exam or db.query(models.Exam).filter_by(id=exam_session.exam_id).first()

        student = exam_session.student or db.query(models.User).filter_by(id=exam_session.student_id).first()



        # Load questions with options and sections

        questions = db.query(models.Question).options(

            joinedload(models.Question.options),

            joinedload(models.Question.section)

        ).filter(models.Question.exam_id == exam.id).order_by(models.Question.order_index).all()



        # Build dictionary of candidate responses from question sessions

        saved_qs = {qs.question_id: qs for qs in exam_session.question_sessions}



        # Retrieve existing student answers for this session

        existing_answers = {

            sa.question_id: sa

            for sa in db.query(models.StudentAnswer).filter_by(exam_session_id=exam_session.id).all()

        }



        # Also link submission record for backwards compatibility

        sub = db.query(models.Submission).filter_by(

            exam_id=exam.id,

            student_id=student.id

        ).first()



        correct_count = 0

        incorrect_count = 0

        unanswered_count = 0

        pending_count = 0

        in_progress_count = 0

        graded_count = 0

        total_max_marks = 0.0

        marks_obtained = 0.0



        section_data: Dict[Optional[int], Dict[str, Any]] = {}

        # Pre-seed configured sections

        sections = db.query(models.AssessmentSection).filter_by(exam_id=exam.id).order_by(models.AssessmentSection.order_index).all()

        for sec in sections:

            section_data[sec.id] = {

                "section_id": sec.id,

                "name": sec.name,

                "marks_obtained": 0.0,

                "max_marks": 0.0,

                "percentage": 0.0,

                "passing_percentage": sec.passing_percentage,

                "passed": True

            }



        mandatory_failed = False



        for q in questions:

            q_max = float(q.marks if q.marks is not None else (exam.default_marks or 1.0))

            total_max_marks += q_max

            sec_id = q.section_id



            if sec_id and sec_id in section_data:

                section_data[sec_id]["max_marks"] += q_max



            qs = saved_qs.get(q.id)

            sa = existing_answers.get(q.id)



            selected_opt_id = (

                qs.selected_option_id if (qs and qs.selected_option_id is not None)

                else (sa.selected_option_id if sa else None)

            )

            ans_text = (

                qs.answer_text if (qs and qs.answer_text is not None)

                else (sa.answer_text if sa else None)

            )



            # Get or create StudentAnswer

            if not sa:

                sa = models.StudentAnswer(

                    submission_id=sub.id if sub else None,

                    exam_session_id=exam_session.id,

                    question_id=q.id,

                    selected_option_id=selected_opt_id,

                    answer_text=ans_text

                )

                db.add(sa)

                existing_answers[q.id] = sa



            # Determine whether question was unanswered

            is_unanswered = (selected_opt_id is None and (not ans_text or not ans_text.strip()))

            if is_unanswered:

                unanswered_count += 1



            # Check if answer was already manually graded or in draft or pre-evaluated

            if sa.evaluation_status in ("graded", "in_progress") or (sa.evaluation_status == "evaluated" and selected_opt_id is None and ans_text is None and (sa.marks_awarded or 0.0) > 0):

                if sa.evaluation_status in ("graded", "evaluated"):

                    graded_count += 1

                else:

                    in_progress_count += 1



                awarded = sa.marks_awarded or 0.0

                marks_obtained += awarded

                if sec_id and sec_id in section_data:

                    section_data[sec_id]["marks_obtained"] += awarded



                if sa.is_correct:

                    correct_count += 1

                elif not is_unanswered:

                    incorrect_count += 1



                # Check mandatory violation

                if q.is_mandatory and awarded <= 0.0:

                    mandatory_failed = True

                continue



            # Perform automated evaluation

            is_corr, awarded, eval_status = EvaluationService.evaluate_question_response(

                q, exam, selected_opt_id, ans_text

            )



            sa.selected_option_id = selected_opt_id

            sa.answer_text = ans_text

            sa.is_correct = is_corr

            sa.marks_awarded = awarded

            sa.evaluation_status = eval_status



            if eval_status == "pending":

                pending_count += 1

            else:

                marks_obtained += awarded

                if sec_id and sec_id in section_data:

                    section_data[sec_id]["marks_obtained"] += awarded



                if is_corr:

                    correct_count += 1

                elif not is_unanswered:

                    incorrect_count += 1



            # Check mandatory violation

            if q.is_mandatory and (eval_status != "pending" and awarded <= 0.0):

                mandatory_failed = True



        marks_obtained = max(0.0, round(marks_obtained, 2))

        percentage = round((marks_obtained / total_max_marks * 100.0), 2) if total_max_marks > 0 else 0.0



        # Section-wise pass/fail calculation

        section_cutoff_failed = False

        section_results_list = []

        for sec_id, s_info in section_data.items():

            s_max = s_info["max_marks"]

            s_obt = max(0.0, round(s_info["marks_obtained"], 2))

            s_pct = round((s_obt / s_max * 100.0), 2) if s_max > 0 else 100.0

            s_info["percentage"] = s_pct



            if s_info["passing_percentage"] is not None:

                if s_pct < s_info["passing_percentage"]:

                    s_info["passed"] = False

                    section_cutoff_failed = True

                else:

                    s_info["passed"] = True

            else:

                s_info["passed"] = True



            section_results_list.append(s_info)



        # Overall manual grading status

        if pending_count > 0:

            manual_status = "pending"

        elif in_progress_count > 0:

            manual_status = "in_progress"

        elif graded_count > 0:

            manual_status = "graded"

        else:

            manual_status = "not_required"



        # Pass / Fail Determination

        if pending_count > 0 or in_progress_count > 0:

            # Rule 3: Do not mark assessment as PASS or FAIL until required grading is complete

            pass_fail_status = "PENDING"

        else:

            if mandatory_failed or section_cutoff_failed:

                pass_fail_status = "FAIL"

            else:

                # Assessment cutoff check

                if exam.passing_criteria == "percentage" or exam.passing_percentage is not None:

                    cutoff = exam.passing_percentage or 0.0

                    pass_fail_status = "PASS" if percentage >= cutoff else "FAIL"

                else:

                    cutoff = exam.passing_marks or 0.0

                    pass_fail_status = "PASS" if marks_obtained >= cutoff else "FAIL"



        # Update or create ExamResult

        res = db.query(models.ExamResult).filter_by(exam_session_id=exam_session.id).first()

        now = utc_now()

        if not res:

            res = models.ExamResult(

                exam_id=exam.id,

                student_id=student.id,

                exam_session_id=exam_session.id,

                attempt_number=exam_session.attempt_number or 1,

                total_marks=total_max_marks,

                marks_obtained=marks_obtained,

                percentage=percentage,

                pass_fail_status=pass_fail_status,

                correct_count=correct_count,

                incorrect_count=incorrect_count,

                unanswered_count=unanswered_count,

                manual_grading_status=manual_status,

                is_released=exam.results_released or False,

                released_at=now if exam.results_released else None,

                section_scores=json.dumps(section_results_list),

                submission_timestamp=exam_session.submitted_at or now,

                evaluated_at=now

            )

            db.add(res)

        else:

            res.total_marks = total_max_marks

            res.marks_obtained = marks_obtained

            res.percentage = percentage

            res.pass_fail_status = pass_fail_status

            res.correct_count = correct_count

            res.incorrect_count = incorrect_count

            res.unanswered_count = unanswered_count

            res.manual_grading_status = manual_status

            res.section_scores = json.dumps(section_results_list)

            res.evaluated_at = now

            if exam.results_released and not res.is_released:

                res.is_released = True

                res.released_at = now



        # Synchronize score with ExamSession

        exam_session.score = marks_obtained



        # Synchronize with Submission

        if sub:

            sub.score = marks_obtained

            sub.submitted_at = exam_session.submitted_at or now



        db.commit()

        db.refresh(res)

        return res



    # =========================================================================

    # 3. MANUAL GRADING WORKFLOW

    # =========================================================================

    @staticmethod

    def get_pending_grading_queue(

        db: Session,

        examiner: models.User,

        exam_id: Optional[int] = None

    ) -> List[Dict[str, Any]]:

        """

        Retrieves pending or in-progress answers requiring examiner evaluation.

        Scoped to examiner's created exams or organization.

        """

        query = db.query(models.StudentAnswer).join(models.StudentAnswer.question).join(models.Question.exam)



        if exam_id:

            query = query.filter(models.Question.exam_id == exam_id)



        # Scoping check

        if examiner.role != "super_admin":

            if examiner.organization_id:

                query = query.filter(models.Exam.organization_id == examiner.organization_id)

            else:

                query = query.filter(models.Exam.creator_id == examiner.id)



        # Filter for pending or in_progress status

        answers = query.filter(

            models.StudentAnswer.evaluation_status.in_(["pending", "in_progress"])

        ).all()



        queue = []

        for a in answers:

            q = a.question

            sess = a.exam_session

            stud = sess.student if sess else None

            exam = q.exam



            q_max = float(q.marks if q.marks is not None else (exam.default_marks or 1.0))

            marking_guidelines = q.explanation

            if q.type_config:

                try:

                    cfg = json.loads(q.type_config) if isinstance(q.type_config, str) else q.type_config

                    marking_guidelines = cfg.get("guidelines", cfg.get("marking_guidelines", marking_guidelines))

                except Exception:

                    pass



            queue.append({

                "answer_id": a.id,

                "exam_session_id": a.exam_session_id,

                "attempt_number": sess.attempt_number if sess else 1,

                "exam_id": exam.id,

                "exam_title": exam.title,

                "student_id": stud.id if stud else 0,

                "student_name": stud.name if stud else "Unknown",

                "question_id": q.id,

                "question_text": q.text,

                "question_type": q.question_type,

                "max_marks": q_max,

                "answer_text": a.answer_text,

                "evaluation_status": a.evaluation_status,

                "marks_awarded": a.marks_awarded or 0.0,

                "examiner_feedback": a.examiner_feedback,

                "marking_guidelines": marking_guidelines,

                "submitted_at": sess.submitted_at if sess else None

            })

        return queue



    @staticmethod

    def grade_answer(

        db: Session,

        answer_id: int,

        marks_awarded: float,

        examiner_feedback: Optional[str],

        is_draft: bool,

        grader: models.User

    ) -> models.StudentAnswer:

        """

        Examiner grades a descriptive or manual answer.

        Enforces maximum marks boundary. Draft or final submission.

        """

        sa = db.query(models.StudentAnswer).filter_by(id=answer_id).first()

        if not sa:

            raise HTTPException(status_code=404, detail="Student answer not found")



        q = sa.question

        exam = q.exam



        # Scoping validation

        if grader.role != "super_admin":

            if grader.organization_id and exam.organization_id and grader.organization_id != exam.organization_id:

                raise HTTPException(status_code=403, detail="Not authorized to grade answers for another organization")



        q_max = float(q.marks if q.marks is not None else (exam.default_marks or 1.0))

        if marks_awarded < 0.0 or marks_awarded > q_max:

            raise HTTPException(

                status_code=400,

                detail=f"Awarded marks ({marks_awarded}) must be between 0.0 and maximum marks ({q_max})"

            )



        now = utc_now()

        sa.marks_awarded = marks_awarded

        sa.examiner_feedback = examiner_feedback

        sa.evaluation_status = "in_progress" if is_draft else "graded"

        sa.is_correct = (marks_awarded > 0)

        sa.graded_by = grader.id

        sa.graded_at = now



        db.commit()



        # If final submission, recalculate consolidated attempt results

        if not is_draft and sa.exam_session:

            EvaluationService.evaluate_attempt(db, sa.exam_session)



        db.refresh(sa)

        return sa



    # =========================================================================

    # 4. REGRADING & AUDIT TRAIL

    # =========================================================================

    @staticmethod

    def regrade_answer(

        db: Session,

        answer_id: int,

        marks_awarded: float,

        examiner_feedback: Optional[str],

        reason: str,

        grader: models.User

    ) -> models.StudentAnswer:

        """

        Regrades an already evaluated answer, recording full audit history.

        """

        sa = db.query(models.StudentAnswer).filter_by(id=answer_id).first()

        if not sa:

            raise HTTPException(status_code=404, detail="Student answer not found")



        q = sa.question

        exam = q.exam



        # Scoping validation

        if grader.role != "super_admin":

            if grader.organization_id and exam.organization_id and grader.organization_id != exam.organization_id:

                raise HTTPException(status_code=403, detail="Not authorized to regrade answers for another organization")



        q_max = float(q.marks if q.marks is not None else (exam.default_marks or 1.0))

        if marks_awarded < 0.0 or marks_awarded > q_max:

            raise HTTPException(

                status_code=400,

                detail=f"Awarded marks ({marks_awarded}) must be between 0.0 and maximum marks ({q_max})"

            )



        now = utc_now()



        # Record audit trail

        audit = models.GradingAudit(

            student_answer_id=sa.id,

            exam_session_id=sa.exam_session_id or 0,

            previous_marks=sa.marks_awarded,

            new_marks=marks_awarded,

            previous_feedback=sa.examiner_feedback,

            new_feedback=examiner_feedback,

            changed_by=grader.id,

            changed_at=now,

            reason=reason

        )

        db.add(audit)



        # Update answer

        sa.marks_awarded = marks_awarded

        sa.examiner_feedback = examiner_feedback

        sa.evaluation_status = "graded"

        sa.is_correct = (marks_awarded > 0)

        sa.graded_by = grader.id

        sa.graded_at = now



        db.commit()



        try:

            from modules.admin.service import AdminService

            AdminService.log_audit(

                db=db,

                action="result.regrade",

                entity_type="student_answer",

                entity_id=str(sa.id),

                actor_id=grader.id,

                org_id=exam.organization_id if exam else None,

                metadata={"reason": reason, "previous_marks": audit.previous_marks, "new_marks": marks_awarded}

            )

        except Exception:

            pass



        # Recalculate consolidated result

        if sa.exam_session:

            EvaluationService.evaluate_attempt(db, sa.exam_session)

            # Phase 9: Automated regrade notification (only dispatched if released)

            try:

                from modules.notifications.service import NotificationService

                stud_id = sa.exam_session.student_id or (sa.submission.student_id if sa.submission else None)

                if stud_id:

                    NotificationService.trigger_evaluation_event(

                        db=db,

                        event_type="result_revised",

                        exam_id=sa.exam_session.exam_id,

                        student_id=stud_id

                    )

            except Exception as notif_err:

                print(f"[NOTIF_WARN] Could not dispatch result_revised notification: {notif_err}")



        db.refresh(sa)

        return sa



    # =========================================================================

    # 5. RESULT RELEASE & ACCESS CONTROL

    # =========================================================================

    @staticmethod

    def toggle_result_release(

        db: Session,

        exam_id: int,

        is_released: bool,

        examiner: models.User

    ) -> Dict[str, Any]:

        """Examiner releases or holds results for an assessment."""

        exam = db.query(models.Exam).filter_by(id=exam_id).first()

        if not exam:

            raise HTTPException(status_code=404, detail="Assessment not found")



        if examiner.role != "super_admin":

            if examiner.organization_id and exam.organization_id and examiner.organization_id != exam.organization_id:

                raise HTTPException(status_code=403, detail="Not authorized to modify results for another organization")



        exam.results_released = is_released

        now = utc_now()



        results = db.query(models.ExamResult).filter_by(exam_id=exam.id).all()

        for r in results:

            r.is_released = is_released

            r.released_at = now if is_released else None



        db.commit()



        try:

            from modules.admin.service import AdminService

            AdminService.log_audit(

                db=db,

                action="result.release" if is_released else "result.unrelease",

                entity_type="exam",

                entity_id=str(exam.id),

                actor_id=examiner.id,

                org_id=exam.organization_id,

                metadata={"results_count": len(results), "is_released": is_released}

            )

        except Exception:

            pass



        # Phase 9: Automated result release notifications

        if is_released:

            try:

                from modules.notifications.service import NotificationService

                for r in results:

                    NotificationService.trigger_evaluation_event(

                        db=db,

                        event_type="result_released",

                        exam_id=exam.id,

                        student_id=r.student_id

                    )

            except Exception as notif_err:

                print(f"[NOTIF_WARN] Could not dispatch result_released notification: {notif_err}")



        return {

            "exam_id": exam.id,

            "results_released": exam.results_released,

            "results_updated": len(results)

        }



    @staticmethod

    def get_candidate_result_summary(

        db: Session,

        session_id: int,

        current_user: models.User

    ) -> Dict[str, Any]:

        """

        Retrieves consolidated result for an attempt.

        Strictly enforces release status for candidates.

        Separates academic marks from proctoring metrics.

        """

        sess = db.query(models.ExamSession).filter_by(id=session_id).first()

        if not sess:

            raise HTTPException(status_code=404, detail="Exam session not found")



        exam = sess.exam

        is_student = (current_user.role == "student")



        # Student authorization

        if is_student and sess.student_id != current_user.id:

            raise HTTPException(status_code=403, detail="Not authorized to view another candidate's results")



        # Examiner scoping

        if not is_student and current_user.role != "super_admin":

            if current_user.organization_id and exam.organization_id and current_user.organization_id != exam.organization_id:

                raise HTTPException(status_code=403, detail="Not authorized to view results for another organization")



        # Ensure result exists; calculate if missing

        res = db.query(models.ExamResult).filter_by(exam_session_id=sess.id).first()

        if not res:

            res = EvaluationService.evaluate_attempt(db, sess)



        # Candidate privacy: do not expose unreleased results to candidates

        if is_student and not res.is_released and not exam.results_released:

            return {

                "status": "held",

                "message": "Results for this assessment have not been released by the examiner yet.",

                "exam_title": exam.title,

                "attempt_number": sess.attempt_number

            }



        section_scores = []

        if res.section_scores:

            try:

                section_scores = json.loads(res.section_scores)

            except Exception:

                pass



        answers_summary = []

        if res.is_released or not is_student:

            for sa in sess.student_answers:

                q = sa.question

                q_max = float(q.marks if q.marks is not None else (exam.default_marks or 1.0))

                answers_summary.append({

                    "question_id": q.id,

                    "question_text": q.text,

                    "question_type": q.question_type,

                    "max_marks": q_max,

                    "marks_awarded": sa.marks_awarded or 0.0,

                    "is_correct": sa.is_correct,

                    "evaluation_status": sa.evaluation_status,

                    "examiner_feedback": sa.examiner_feedback

                })



        response_data = {

            "result_id": res.id,

            "exam_id": exam.id,

            "exam_title": exam.title,

            "assessment_type": exam.assessment_type or "academic",

            "student_id": sess.student_id,

            "student_name": sess.student.name if sess.student else "Candidate",

            "exam_session_id": sess.id,

            "attempt_number": sess.attempt_number,

            "total_marks": res.total_marks,

            "marks_obtained": res.marks_obtained,

            "percentage": res.percentage,

            "pass_fail_status": res.pass_fail_status,

            "correct_count": res.correct_count,

            "incorrect_count": res.incorrect_count,

            "unanswered_count": res.unanswered_count,

            "manual_grading_status": res.manual_grading_status,

            "is_released": res.is_released,

            "released_at": res.released_at,

            "section_scores": section_scores,

            "answers": answers_summary

        }



        # Separated proctoring summary exposed only to authorized examiners

        if not is_student:

            flag_count = len(sess.cheat_flags) if hasattr(sess, "cheat_flags") else 0

            response_data["proctoring_summary"] = {

                "integrity_score": sess.integrity_score,

                "risk_level": sess.risk_level,

                "proctoring_status": sess.proctoring_status,

                "total_violations": flag_count

            }



        return response_data



    # =========================================================================

    # 6. RESULTS EXPORT FORMATTING

    # =========================================================================

    @staticmethod

    def get_assessment_results_export(

        db: Session,

        exam_id: int,

        examiner: models.User

    ) -> List[Dict[str, Any]]:

        """

        Exports all candidate results for an assessment in standardized flat dictionary format.

        Ready for future CSV, XLSX, JSON and external integration pipelines.

        """

        exam = db.query(models.Exam).filter_by(id=exam_id).first()

        if not exam:

            raise HTTPException(status_code=404, detail="Assessment not found")



        if examiner.role != "super_admin":

            if examiner.organization_id and exam.organization_id and examiner.organization_id != exam.organization_id:

                raise HTTPException(status_code=403, detail="Not authorized to export results for another organization")



        results = db.query(models.ExamResult).filter_by(exam_id=exam.id).all()

        export_rows = []

        for r in results:

            stud = r.student

            sess = r.exam_session

            export_rows.append({

                "candidate_id": r.student_id,

                "candidate_name": stud.name if stud else "Unknown",

                "candidate_email": stud.email if stud else "",

                "assessment_id": exam.id,

                "assessment_title": exam.title,

                "assessment_type": exam.assessment_type or "academic",

                "attempt_number": r.attempt_number,

                "total_marks": r.total_marks,

                "marks_obtained": r.marks_obtained,

                "percentage": r.percentage,

                "pass_fail_status": r.pass_fail_status,

                "manual_grading_status": r.manual_grading_status,

                "is_released": r.is_released,

                "submission_timestamp": to_utc_iso(r.submission_timestamp) if r.submission_timestamp else None,

                "evaluated_at": to_utc_iso(r.evaluated_at) if r.evaluated_at else None,

                "integrity_score": sess.integrity_score if sess else 100.0,

                "risk_level": sess.risk_level if sess else "low"

            })

        return export_rows
