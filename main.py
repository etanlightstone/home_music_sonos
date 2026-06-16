import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from contextlib import asynccontextmanager

from database import init_db
from routers import settings as settings_router
from routers import index_router
from routers import proxy
from routers import files as files_router
from routers import sonos as sonos_router
from routers import spotify as spotify_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SonosWeb", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

jinja_env = Environment(loader=FileSystemLoader("templates"), autoescape=False)
jinja_env.cache = None
templates = Jinja2Templates(env=jinja_env)

app.include_router(settings_router.router, prefix="/api/settings",  tags=["settings"])
app.include_router(index_router.router,    prefix="/api/index",      tags=["index"])
app.include_router(proxy.router,           prefix="/api/proxy",      tags=["proxy"])
app.include_router(files_router.router,    prefix="/api/files",      tags=["files"])
app.include_router(sonos_router.router,    prefix="/api/sonos",      tags=["sonos"])
app.include_router(spotify_router.router,  prefix="/api/spotify",    tags=["spotify"])

# OAuth routes at root level (Spotify redirects back here)
@app.get("/spotify/login")
async def spotify_login_redirect():
    from routers.spotify import spotify_login
    return spotify_login()

@app.get("/spotify/callback")
async def spotify_callback_handler(code: str = None, error: str = None):
    from routers.spotify import spotify_callback
    return spotify_callback(code=code, error=error)

@app.get("/")
async def index(request: Request):
    # NOTE: TemplateResponse signature is (request, name, context) - request comes FIRST
    return templates.TemplateResponse(request, "index.html")
