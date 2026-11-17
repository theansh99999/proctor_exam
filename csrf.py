"""

csrf.py — CSRF Protection Utility

-----------------------------------

Uses itsdangerous.URLSafeTimedSerializer to sign a session-bound token.

The token is embedded in every state-changing form as a hidden field and

verified server-side before processing the request.



Usage (in a route that renders a form):

    from csrf import generate_csrf_token, csrf_protect

    token = generate_csrf_token(request)

    # Pass token to template: {"csrf_token": token}



Usage (in a POST route):

    from csrf import csrf_protect

    csrf_protect(request, csrf_token)   # raises HTTPException 403 on failure

"""



import os

import hashlib

from dotenv import load_dotenv

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from fastapi import HTTPException, Request, status



load_dotenv()



# ── Config ─────────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("SECRET_KEY", "csrf-default-secret-key-32-chars-long-minimum")

# CSRF tokens expire after 1 hour (3600 seconds)

CSRF_TOKEN_MAX_AGE = 3600



def _get_serializer() -> URLSafeTimedSerializer:

    key = os.getenv("SECRET_KEY") or SECRET_KEY

    return URLSafeTimedSerializer(key, salt="csrf-token")





def _get_session_id(request: Request) -> str:

    """

    Derive a stable per-session identifier from the JWT cookie so that

    tokens are bound to the authenticated session. For unauthenticated

    sessions (e.g. login/register), derive from client IP and User-Agent.

    """

    cookie = request.cookies.get("access_token", "")

    if cookie:

        return hashlib.sha256(cookie.encode()).hexdigest()[:16]



    # Fallback for unauthenticated forms (login/register)

    client_ip = request.client.host if request.client else "unknown"

    user_agent = request.headers.get("user-agent", "unknown")

    raw = f"{client_ip}:{user_agent}"

    return hashlib.sha256(raw.encode()).hexdigest()[:16]





def generate_csrf_token(request: Request) -> str:

    """Generate a signed CSRF token bound to the current session."""

    session_id = _get_session_id(request)

    return _get_serializer().dumps(session_id)





def verify_csrf_token(request: Request, token: str | None = None) -> bool:

    """

    Verify a submitted CSRF token.

    Checks parameter token, or X-CSRF-Token header.

    Returns True on success, False on any failure.

    """

    if not token:

        token = request.headers.get("X-CSRF-Token") or request.headers.get("x-csrf-token")

    if not token:

        return False

    try:

        expected_session_id = _get_session_id(request)

        submitted_session_id = _get_serializer().loads(token, max_age=CSRF_TOKEN_MAX_AGE)

        return submitted_session_id == expected_session_id

    except (BadSignature, SignatureExpired):

        return False

    except Exception:

        return False





def csrf_protect(request: Request, csrf_token: str | None = None) -> None:

    """

    Raise HTTP 403 if the CSRF token is missing or invalid.

    Call this at the top of every state-changing POST route.

    """

    if not verify_csrf_token(request, csrf_token):

        raise HTTPException(

            status_code=status.HTTP_403_FORBIDDEN,

            detail="Invalid or expired CSRF token. Please refresh the page and try again."

        )
