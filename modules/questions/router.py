"""
modules/questions/router.py
---------------------------
API v1 endpoints for Question Bank management, bulk imports,
and assessment question mappings.
"""
from fastapi import APIRouter, Depends, status, Query, UploadFile, File, Response
from fastapi.responses import PlainTextResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import json

import database, auth, models
from modules.questions.schemas import (
    BankQuestionCreate,
    BankQuestionUpdate,
    BankQuestionOut,
    QuestionImportResponse,
    AssessmentQuestionMapRequest,
    AssessmentQuestionReorderRequest,
    AssessmentQuestionsListResponse
)
from modules.questions.service import QuestionBankService
from core.responses import success_response, error_response

router = APIRouter(tags=["API v1 - Question Bank"])

# ── 1. Create Question in Bank ─────────────────────────────────────────────────
@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/questions", status_code=status.HTTP_201_CREATED)
def create_question(
    payload: BankQuestionCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    q = QuestionBankService.create_question(db, payload, current_user)
    return success_response(
        data=BankQuestionOut.from_model(q).model_dump(),
        message="Question added to Question Bank successfully",
        status_code=status.HTTP_201_CREATED
    )

# ── 2. List Questions (Search, Filters, Pagination) ────────────────────────────
@router.get("", status_code=status.HTTP_200_OK)
@router.get("/questions", status_code=status.HTTP_200_OK)
def list_questions(
    search: Optional[str] = Query(None),
    assessment_category: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    question_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    organization_id: Optional[int] = Query(None),
    sort_by: str = Query("id"),
    sort_order: str = Query("desc"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    questions, total = QuestionBankService.list_questions(
        db, current_user,
        search=search,
        assessment_category=assessment_category,
        subject=subject,
        topic=topic,
        difficulty=difficulty,
        question_type=question_type,
        status_filter=status,
        organization_id=organization_id,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit
    )
    return success_response(
        data=[BankQuestionOut.from_model(q).model_dump() for q in questions],
        meta={"total": total, "skip": skip, "limit": limit},
        message="Questions retrieved successfully"
    )

# ── 3. Download Sample Templates ───────────────────────────────────────────────
@router.get("/templates/csv")
def download_csv_template():
    csv_data = QuestionBankService.get_sample_csv_template()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=question_bank_template.csv"}
    )

@router.get("/templates/json")
def download_json_template():
    json_data = QuestionBankService.get_sample_json_template()
    return JSONResponse(
        content=json_data,
        headers={"Content-Disposition": "attachment; filename=question_bank_template.json"}
    )

# ── 4. Bulk Question Import ───────────────────────────────────────────────────
@router.post("/import/json", status_code=status.HTTP_200_OK)
def import_questions_json(
    items: List[Dict[str, Any]],
    preview: bool = Query(True),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    result = QuestionBankService.import_questions_from_json(db, items, current_user, preview=preview)
    return success_response(
        data=result.model_dump(),
        message="Questions previewed successfully" if preview else f"Imported {result.imported_count} questions successfully"
    )

@router.post("/import/csv", status_code=status.HTTP_200_OK)
async def import_questions_csv(
    file: UploadFile = File(...),
    preview: bool = Query(True),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    # Validate extension and size
    if not file.filename.endswith(".csv"):
        return error_response(message="Only .csv files are supported.", code="INVALID_FILE_TYPE", status_code=400)

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        return error_response(message="File size exceeds maximum 5MB limit.", code="FILE_TOO_LARGE", status_code=400)

    try:
        csv_text = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
        return error_response(message="Failed to decode CSV as UTF-8.", code="DECODE_ERROR", status_code=400)

    result = QuestionBankService.import_questions_from_csv(db, csv_text, current_user, preview=preview)
    return success_response(
        data=result.model_dump(),
        message="CSV preview generated" if preview else f"Imported {result.imported_count} questions successfully"
    )

# ── 5. Question Detail, Update, Archive, Delete ────────────────────────────────
@router.get("/questions/{question_id}", status_code=status.HTTP_200_OK)
@router.get("/{question_id}", status_code=status.HTTP_200_OK)
def get_question(
    question_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    q = QuestionBankService.get_question(db, question_id, current_user)
    return success_response(
        data=BankQuestionOut.from_model(q).model_dump(),
        message="Question details retrieved"
    )

@router.put("/questions/{question_id}", status_code=status.HTTP_200_OK)
@router.put("/{question_id}", status_code=status.HTTP_200_OK)
def update_question(
    question_id: int,
    payload: BankQuestionUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    q = QuestionBankService.update_question(db, question_id, payload, current_user)
    return success_response(
        data=BankQuestionOut.from_model(q).model_dump(),
        message="Question updated successfully"
    )

@router.post("/questions/{question_id}/archive", status_code=status.HTTP_200_OK)
@router.post("/{question_id}/archive", status_code=status.HTTP_200_OK)
def archive_question(
    question_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    q = QuestionBankService.archive_question(db, question_id, current_user)
    return success_response(
        data=BankQuestionOut.from_model(q).model_dump(),
        message="Question archived successfully"
    )

@router.delete("/questions/{question_id}", status_code=status.HTTP_200_OK)
@router.delete("/{question_id}", status_code=status.HTTP_200_OK)
def delete_question(
    question_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_auth_api)
):
    QuestionBankService.delete_question(db, question_id, current_user)
    return success_response(
        data={"deleted": True, "question_id": question_id},
        message="Question deleted successfully"
    )
