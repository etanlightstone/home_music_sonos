from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from contextlib import asynccontextmanager

from database import init_db
from routers import settings as settings_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SonosWeb", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
