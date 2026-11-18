from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status
from ws_manager import manager
import auth
import database

router = APIRouter(tags=["WebSocket"])

@router.websocket("/ws/teacher/{teacher_id}")
async def websocket_teacher_endpoint(websocket: WebSocket, teacher_id: int):
    """
    Authenticated WebSocket endpoint for the teacher live-monitor.

    Authentication flow:
    1. Read 'access_token' cookie from the WebSocket handshake headers.
    2. Validate the JWT and confirm the user is a teacher.
    3. Verify teacher_id in the URL matches the authenticated user's id
       (prevents teacher A from listening on teacher B's channel).
    4. Accept the connection only after all checks pass.
    """
    # ── 1. Extract token from cookie, query param, or header ────────────────
    token = ""
    cookie_header = websocket.cookies.get("access_token", "")
    if cookie_header.startswith("Bearer "):
        token = cookie_header[7:]
    elif cookie_header:
        token = cookie_header

    if not token:
        # Check query parameters
        token = websocket.query_params.get("token", "")
        if token.startswith("Bearer "):
            token = token[7:]

    if not token:
        # Check authorization header
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # ── 2. Validate JWT ─────────────────────────────────────────────────────
    db_fn = getattr(websocket.app, "dependency_overrides", {}).get(database.get_db, database.get_db)
    db_gen = db_fn()
    db = next(db_gen) if hasattr(db_gen, "__next__") else db_gen
    try:
        user = auth.get_current_user_from_token(token, db)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        if hasattr(db, "close"):
            db.close()
        return

    # ── 3. Role + ownership check ────────────────────────────────────────────
    if not auth.is_examiner_or_admin(user) or (user.id != teacher_id and not auth.is_super_admin(user)):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        if hasattr(db, "close"):
            db.close()
        return

    # ── 3b. Maintenance mode enforcement ──────────────────────────────────────
    from core.maintenance import is_maintenance_mode
    if is_maintenance_mode(db) and not auth.is_super_admin(user):
        await websocket.close(code=1013, reason="Platform maintenance in progress")
        if hasattr(db, "close"):
            db.close()
        return

    if hasattr(db, "close"):
        db.close()

    # ── 4. Accept authenticated connection ───────────────────────────────────
    await manager.connect(websocket, teacher_id)
    try:
        while True:
            # Keep connection alive; messages are pushed from student submissions
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, teacher_id)
