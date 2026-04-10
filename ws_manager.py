from fastapi import WebSocket
from typing import Dict, List

class ConnectionManager:
    def __init__(self):
        # Maps teacher_id to a list of active websocket connections
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, teacher_id: int):
        await websocket.accept()
        if teacher_id not in self.active_connections:
            self.active_connections[teacher_id] = []
        self.active_connections[teacher_id].append(websocket)

    def disconnect(self, websocket: WebSocket, teacher_id: int):
        if teacher_id in self.active_connections:
            try:
                self.active_connections[teacher_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[teacher_id]:
                del self.active_connections[teacher_id]

    async def send_personal_message(self, message: dict, teacher_id: int):
        if teacher_id in self.active_connections:
            for connection in self.active_connections[teacher_id]:
                await connection.send_json(message)

manager = ConnectionManager()
