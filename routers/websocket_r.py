from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
import models, database, auth
from ws_manager import manager

router = APIRouter(tags=["WebSocket"])

@router.websocket("/ws/teacher/{teacher_id}")
async def websocket_teacher_endpoint(websocket: WebSocket, teacher_id: int):
    await manager.connect(websocket, teacher_id)
    try:
        while True:
            # Keep the connection alive; messages are pushed from student side
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(teacher_id)
