from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from contextlib import asynccontextmanager

from database import init_db
from routers import settings as settings_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SonosWeb", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

jinja_env = Environment(loader=FileSystemLoader("templates"), autoescape=False)
jinja_env.cache = None
templates = Jinja2Templates(env=jinja_env)

app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])

@app.get("/")
async def index(request: Request):
    # NOTE: TemplateResponse signature is (request, name, context) - request comes FIRST
    return templates.TemplateResponse(request, "index.html")
