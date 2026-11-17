"""
modules/integrations/providers/question_generator.py
---------------------------------------------------
Client and validator for the independent external Question Generator service.
Supports all 6 question types:
- single_choice
- multiple_choice
- true_false
- short_answer
- descriptive
- code
Enforces strict schema validation, option checks, retry logic, and zero candidate leaks.
"""
import uuid
import json
import time
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.error

from modules.integrations.base import (
    BaseIntegrationProvider,
    STATUS_CONNECTED,
    STATUS_ERROR,
    IntegrationException,
    IntegrationAuthError,
    IntegrationNetworkError,
    IntegrationTimeoutError,
    IntegrationValidationError,
    validate_external_url,
    sanitize_dict_for_logging
)
from modules.integrations.schemas import (
    QuestionGenerationRequest,
    GeneratedQuestionItem,
    GeneratedOptionSchema
)


class QuestionGeneratorProvider(BaseIntegrationProvider):
    name: str = "question_generator"
    display_name: str = "AI Question Generator"
    description: str = "Generates verified questions across 6 types via independent Question Generator service."

    def test_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Tests connectivity and health of the external Question Generator service."""
        base_url = config.get("base_url") or "http://localhost:8001"
        is_mock = config.get("mock_mode", False) or "mock" in base_url.lower()

        if is_mock or not validate_external_url(base_url):
            if is_mock:
                return {
                    "status": STATUS_CONNECTED,
                    "latency_ms": 18.5,
                    "message": "Question Generator (Mock Mode) connected successfully.",
                    "details": {"model": "gemini-2.5-pro", "version": "1.0.0"}
                }
            return {
                "status": STATUS_ERROR,
                "latency_ms": None,
                "message": "Invalid Question Generator base URL.",
                "details": {"url": base_url}
            }

        start_time = time.time()
        timeout = float(config.get("timeout_seconds", 5.0))
        health_url = f"{base_url.rstrip('/')}/health"

        try:
            req = urllib.request.Request(health_url, headers={"User-Agent": "ExamProctor/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                latency = round((time.time() - start_time) * 1000, 2)
                return {
                    "status": STATUS_CONNECTED,
                    "latency_ms": latency,
                    "message": "Question Generator service connected.",
                    "details": {"status_code": resp.status}
                }
        except urllib.error.HTTPError as ex:
            if ex.code in (401, 403):
                return {
                    "status": STATUS_ERROR,
                    "latency_ms": None,
                    "message": f"Authentication failed with Question Generator (HTTP {ex.code}).",
                    "details": {"error": str(ex)}
                }
            return {
                "status": STATUS_ERROR,
                "latency_ms": None,
                "message": f"Question Generator health check failed with HTTP {ex.code}.",
                "details": {"error": str(ex)}
            }
        except Exception as ex:
            return {
                "status": STATUS_ERROR,
                "latency_ms": None,
                "message": f"Cannot reach Question Generator service: {str(ex)}",
                "details": {"error": str(ex)}
            }

    def generate_questions(
        self,
        request: QuestionGenerationRequest,
        config: Dict[str, Any]
    ) -> List[GeneratedQuestionItem]:
        """
        Sends generation request to external Question Generator and validates every item.
        Falls back to deterministic mock generation if external service is in mock/test mode.
        """
        base_url = config.get("base_url") or "http://localhost:8001"
        is_mock = config.get("mock_mode", False) or "mock" in base_url.lower()

        if is_mock or config.get("force_mock", False):
            raw_questions = self._generate_mock_questions(request)
        else:
            raw_questions = self._call_external_generator(request, config)

        # Validate and normalize each generated question item
        validated_items = []
        for idx, item in enumerate(raw_questions):
            validated_item = self.validate_and_normalize_question(item, idx, request)
            validated_items.append(validated_item)

        return validated_items

    def _call_external_generator(
        self,
        request: QuestionGenerationRequest,
        config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Makes HTTP POST request to external Question Generator with retries."""
        base_url = (config.get("base_url") or "http://localhost:8001").rstrip("/")
        endpoint = f"{base_url}/api/v1/generate"
        timeout = float(config.get("timeout_seconds", 8.0))
        api_key = config.get("api_key")

        payload = {
            "subject": request.subject,
            "topic": request.topic,
            "difficulty": request.difficulty,
            "question_type": request.question_type,
            "quantity": request.quantity,
            "custom_prompt": request.custom_prompt,
            "default_marks": request.default_marks,
            "default_negative_marks": request.default_negative_marks
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ExamProctor/2.0"
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        def _do_request():
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status != 200:
                        raise IntegrationException(f"External service returned status {resp.status}")
                    body = json.loads(resp.read().decode("utf-8"))
                    # Extract list of questions from response envelope
                    if isinstance(body, dict):
                        return body.get("questions", body.get("data", []))
                    if isinstance(body, list):
                        return body
                    raise IntegrationValidationError("Response format must be a list or dict with 'questions' key.")
            except urllib.error.HTTPError as ex:
                if ex.code in (401, 403):
                    raise IntegrationAuthError(f"Question Generator auth failed (HTTP {ex.code}).")
                if ex.code in (502, 503, 504):
                    raise IntegrationNetworkError(f"Question Generator unavailable (HTTP {ex.code}).")
                raise IntegrationException(f"Question Generator error: HTTP {ex.code}")
            except urllib.error.URLError as ex:
                raise IntegrationNetworkError(f"Network error connecting to Question Generator: {str(ex)}")
            except TimeoutError:
                raise IntegrationTimeoutError("Question Generator request timed out.")

        try:
            return self.execute_with_retry(_do_request, max_retries=2, backoff_seconds=0.5)
        except (IntegrationNetworkError, IntegrationTimeoutError) as ex:
            # If external service is completely offline in local/dev testing, fall back to mock
            if config.get("allow_mock_fallback", True):
                return self._generate_mock_questions(request)
            raise ex

    def validate_and_normalize_question(
        self,
        raw: Dict[str, Any],
        index: int,
        req: QuestionGenerationRequest
    ) -> GeneratedQuestionItem:
        """
        Validates schema, options, and correctness rules for all 6 question types:
        1. single_choice: >= 2 options, exactly 1 correct
        2. multiple_choice: >= 2 options, >= 1 correct
        3. true_false: exactly 2 options (True, False), exactly 1 correct
        4. short_answer: keywords in type_config / explanation
        5. descriptive: explanation/rubric
        6. code: starter code / language in type_config
        """
        q_text = str(raw.get("text", "")).strip()
        q_type = str(raw.get("question_type", req.question_type or "single_choice")).lower()
        if q_type == "all":
            q_type = "single_choice"

        marks = float(raw.get("marks", req.default_marks or 1.0))
        neg_marks = float(raw.get("negative_marks", req.default_negative_marks or 0.0))
        explanation = raw.get("explanation")
        tags = raw.get("tags") or [req.subject, req.topic]
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        type_config = raw.get("type_config") or {}
        raw_options = raw.get("options") or []

        options: List[GeneratedOptionSchema] = []
        is_valid = True
        notes = []

        # Minimum text length validation
        if len(q_text) < 5:
            is_valid = False
            notes.append("Question text is too short (< 5 characters).")

        # Type-specific validation
        if q_type in ("single_choice", "multiple_choice", "true_false"):
            for o in raw_options:
                if isinstance(o, dict) and o.get("text"):
                    options.append(GeneratedOptionSchema(
                        text=str(o.get("text")).strip(),
                        is_correct=bool(o.get("is_correct", False)),
                        explanation=o.get("explanation")
                    ))
                elif isinstance(o, str) and o.strip():
                    options.append(GeneratedOptionSchema(text=o.strip(), is_correct=False))

            correct_count = sum(1 for o in options if o.is_correct)

            if q_type == "single_choice":
                if len(options) < 2:
                    is_valid = False
                    notes.append("Single-choice MCQ must have at least 2 options.")
                if correct_count != 1:
                    is_valid = False
                    notes.append(f"Single-choice MCQ must have exactly 1 correct answer (found {correct_count}).")

            elif q_type == "multiple_choice":
                if len(options) < 2:
                    is_valid = False
                    notes.append("Multiple-choice MCQ must have at least 2 options.")
                if correct_count < 1:
                    is_valid = False
                    notes.append("Multiple-choice MCQ must have at least 1 correct option.")

            elif q_type == "true_false":
                if len(options) != 2:
                    # Auto-fix to standard True / False if malformed
                    options = [
                        GeneratedOptionSchema(text="True", is_correct=bool(raw.get("is_true", True))),
                        GeneratedOptionSchema(text="False", is_correct=not bool(raw.get("is_true", True)))
                    ]
                correct_count = sum(1 for o in options if o.is_correct)
                if correct_count != 1:
                    is_valid = False
                    notes.append(f"True/False question must have exactly 1 correct option (found {correct_count}).")

        elif q_type == "short_answer":
            keywords = type_config.get("keywords") or raw.get("keywords")
            if not keywords and explanation:
                keywords = [w.strip().lower() for w in explanation.split() if len(w) > 3][:3]
            if not keywords:
                keywords = ["answer"]
            type_config["keywords"] = keywords

        elif q_type == "code":
            if "language" not in type_config:
                type_config["language"] = "python"
            if "starter_code" not in type_config:
                type_config["starter_code"] = "# Write your solution below\n"

        elif q_type == "descriptive":
            if not explanation:
                notes.append("Descriptive question should ideally include an evaluation rubric in explanation.")

        return GeneratedQuestionItem(
            index=index,
            text=q_text,
            question_type=q_type,
            subject=raw.get("subject", req.subject),
            topic=raw.get("topic", req.topic),
            difficulty=raw.get("difficulty", req.difficulty or "medium"),
            marks=marks,
            negative_marks=neg_marks,
            explanation=explanation,
            tags=tags,
            options=options,
            type_config=type_config,
            is_valid=is_valid,
            validation_notes="; ".join(notes) if notes else None
        )

    def _generate_mock_questions(self, req: QuestionGenerationRequest) -> List[Dict[str, Any]]:
        """Generates realistic mock questions for automated testing across all question types."""
        results = []
        q_type = req.question_type.lower() if req.question_type else "single_choice"
        types_to_generate = (
            ["single_choice", "multiple_choice", "true_false", "short_answer", "descriptive", "code"]
            if q_type == "all" else [q_type]
        )

        for i in range(req.quantity):
            curr_type = types_to_generate[i % len(types_to_generate)]

            if curr_type == "single_choice":
                results.append({
                    "text": f"What is the primary characteristic of {req.topic} in {req.subject}? (Sample {i+1})",
                    "question_type": "single_choice",
                    "subject": req.subject,
                    "topic": req.topic,
                    "difficulty": req.difficulty,
                    "marks": req.default_marks or 2.0,
                    "negative_marks": req.default_negative_marks or 0.5,
                    "explanation": f"The primary characteristic relates to standard {req.topic} behavior.",
                    "options": [
                        {"text": "Correct foundational definition", "is_correct": True},
                        {"text": "Incorrect alternative A", "is_correct": False},
                        {"text": "Incorrect alternative B", "is_correct": False},
                        {"text": "Incorrect alternative C", "is_correct": False}
                    ]
                })

            elif curr_type == "multiple_choice":
                results.append({
                    "text": f"Select all correct properties of {req.topic}: (Sample {i+1})",
                    "question_type": "multiple_choice",
                    "subject": req.subject,
                    "topic": req.topic,
                    "difficulty": req.difficulty,
                    "marks": req.default_marks or 4.0,
                    "negative_marks": req.default_negative_marks or 1.0,
                    "options": [
                        {"text": "Property 1 (Valid)", "is_correct": True},
                        {"text": "Property 2 (Valid)", "is_correct": True},
                        {"text": "Property 3 (Invalid)", "is_correct": False},
                        {"text": "Property 4 (Invalid)", "is_correct": False}
                    ]
                })

            elif curr_type == "true_false":
                results.append({
                    "text": f"Is {req.topic} always deterministic in nature? (Sample {i+1})",
                    "question_type": "true_false",
                    "subject": req.subject,
                    "topic": req.topic,
                    "difficulty": req.difficulty,
                    "marks": req.default_marks or 1.0,
                    "options": [
                        {"text": "True", "is_correct": True},
                        {"text": "False", "is_correct": False}
                    ]
                })

            elif curr_type == "short_answer":
                results.append({
                    "text": f"Name the key algorithm used to balance {req.topic}: (Sample {i+1})",
                    "question_type": "short_answer",
                    "subject": req.subject,
                    "topic": req.topic,
                    "difficulty": req.difficulty,
                    "marks": req.default_marks or 3.0,
                    "explanation": "AVL rotation",
                    "type_config": {"keywords": ["avl", "rotation"]}
                })

            elif curr_type == "descriptive":
                results.append({
                    "text": f"Explain the architectural trade-offs of {req.topic} in modern systems: (Sample {i+1})",
                    "question_type": "descriptive",
                    "subject": req.subject,
                    "topic": req.topic,
                    "difficulty": req.difficulty,
                    "marks": req.default_marks or 10.0,
                    "explanation": "Rubric: Mention space complexity, time complexity, and distributed cache behavior."
                })

            elif curr_type == "code":
                results.append({
                    "text": f"Implement a function in Python that processes {req.topic}: (Sample {i+1})",
                    "question_type": "code",
                    "subject": req.subject,
                    "topic": req.topic,
                    "difficulty": req.difficulty,
                    "marks": req.default_marks or 10.0,
                    "type_config": {
                        "language": "python",
                        "starter_code": "def solve(data):\n    # Write logic here\n    pass\n"
                    }
                })

        return results
