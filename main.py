from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import models
from database import engine

# Create Database Tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Exam Proctoring App")

# Static files and Templates
app.mount("/static", StaticFiles(directory="static"), name="static")

from routers import auth_r, teacher_r, student_r, websocket_r

app.include_router(auth_r.router)
app.include_router(teacher_r.router)
app.include_router(student_r.router)
app.include_router(websocket_r.router)

@app.get("/")
def home(request: Request):
    return RedirectResponse(url="/login")
