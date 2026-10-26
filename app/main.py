import time

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
    marketing_routes,
    warehouse_routes,
    payment_routes,
    checkout_routes,
    agents_routes,
    assistant_routes,
    support_routes,
    studio_routes,
    storefront_admin_routes,
    floor_routes,
)


class CachedStaticFiles(StaticFiles):
    """
    Static assets (CSS/JS/fonts) don't change between requests within a
    deploy, so tell the browser to hold onto them instead of re-fetching on
    every page view - aggressively (1 hour), since every <link>/<script>
    reference now carries ?v=ASSET_VERSION (below), which changes every
    time this process (re)starts. That means a browser that already has
    the OLD url?v=... cached keeps using its (correct, matching) cached
    copy, while the new deploy's HTML points at a NEW url?v=..., which the
    browser has never seen and has to fetch fresh. Without this, a
    visitor who loaded the site before a CSS/JS change can keep serving
    the stale file straight from disk cache for up to an hour after a
    redeploy, with no request to this server at all - which is exactly
    what happened the first time this site was redesigned.
    """
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response


# Changes every time this process starts (every deploy/restart recycles
# the container), so it's a free, zero-config cache-busting token - see
# CachedStaticFiles above.
ASSET_VERSION = str(int(time.time()))

app = FastAPI(title="Loomwell")

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

app.mount("/static", CachedStaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["asset_version"] = ASSET_VERSION

app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(chat_routes.router)
app.include_router(vision_routes.router)
app.include_router(design_routes.router)
app.include_router(mockup_routes.router)
app.include_router(public_routes.router)
app.include_router(marketing_routes.router)
app.include_router(warehouse_routes.router)
app.include_router(payment_routes.router)
app.include_router(checkout_routes.router)
app.include_router(agents_routes.router)
app.include_router(assistant_routes.router)
app.include_router(support_routes.router)
app.include_router(studio_routes.router)
app.include_router(storefront_admin_routes.router)
app.include_router(floor_routes.router)


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


@app.get("/shop/design/{design_id}", response_class=HTMLResponse)
def shop_design(design_id: int, request: Request):
    """One design's own page - detail view, not just the quick-look modal."""
    return templates.TemplateResponse("shop_design.html", {"request": request, "design_id": design_id})


@app.get("/studio", response_class=HTMLResponse)
def studio(request: Request):
    """Print-your-own: upload or generate artwork, pick a garment, preview, order."""
    return templates.TemplateResponse("studio.html", {"request": request})


@app.get("/checkout/{kind}/{item_id}", response_class=HTMLResponse)
def checkout_page(kind: str, item_id: int, request: Request):
    """Full-page demo checkout (address -> summary -> payment). kind = design | custom."""
    return templates.TemplateResponse("checkout.html", {"request": request, "kind": kind, "item_id": item_id})


@app.get("/floor", response_class=HTMLResponse)
def floor(request: Request):
    """Agent Floor: live workflow graph of every agent (admin only - the page checks /api/me)."""
    return templates.TemplateResponse("floor.html", {"request": request})


@app.get("/health")
def health():
    """App Service / Front Door health probe target."""
    return {"status": "ok"}
