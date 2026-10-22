from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import init_db, get_db, User
from .auth import get_current_user
from .routes import (
    auth_routes,
    admin_routes,
    chat_routes,
    vision_routes,
    design_routes,
    mockup_routes,
    public_routes,
)


class CachedStaticFiles(StaticFiles):
    """
    Static assets (CSS/JS/fonts) don't change between requests within a
    deploy, so tell the browser to hold onto them instead of re-fetching on
    every page view. A new deploy gets a new container anyway, so there's no
    stale-cache risk worth a cache-busting scheme here.
    """
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response


app = FastAPI(title="Loomwell")

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

app.mount("/static", CachedStaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(chat_routes.router)
app.include_router(vision_routes.router)
app.include_router(design_routes.router)
app.include_router(mockup_routes.router)
app.include_router(public_routes.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/shop", response_class=HTMLResponse)
def shop(request: Request):
    """Public storefront - no login required."""
    return templates.TemplateResponse("shop.html", {"request": request})


@app.get("/health")
def health():
    """App Service / Front Door health probe target."""
    return {"status": "ok"}
