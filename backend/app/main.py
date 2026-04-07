from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from app.config import get_stripe_configuration_status, settings, validate_runtime_configuration
from app.database import engine
from app.routers import admin, auth, bookings, rooms, staff, users, webhooks
from app.monitoring import record_request, render_metrics, time_request
from sqlalchemy import text

try:
    import redis
except ImportError:  # pragma: no cover - runtime dependency
    redis = None


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
FRONTEND_PAGES = {
    "/": "index.html",
    "/account": "account.html",
    "/contact": "contact.html",
    "/faq": "faq.html",
    "/info": "info.html",
    "/rooms": "rooms.html",
    "/room": "room.html",
    "/reserve": "reserve.html",
    "/staff": "staff.html",
    "/bookings": "bookings.html",
    "/booking": "booking.html",
    "/admin": "admin.html",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_runtime_configuration()
    yield


app = FastAPI(
    title="StudioBookingSoftware",
    version="0.1.0",
    description="Room booking platform for studios",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_metrics_middleware(request, call_next):
    started_at = time_request()
    response = await call_next(request)
    record_request(time_request() - started_at)
    return response

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(staff.router)
app.include_router(bookings.router)
app.include_router(admin.router)
app.include_router(webhooks.router)

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="frontend-assets")

    def build_frontend_handler(filename: str):
        def handler():
            return FileResponse(FRONTEND_DIR / filename)

        return handler

    for route_path, filename in FRONTEND_PAGES.items():
        app.add_api_route(route_path, build_frontend_handler(filename), methods=["GET"], include_in_schema=False)


@app.get("/metrics", include_in_schema=False)
def metrics():
    return PlainTextResponse(render_metrics())


@app.get("/api/public/config", include_in_schema=False)
def public_config():
    stripe_status = get_stripe_configuration_status()
    return {
        "app_env": settings.APP_ENV,
        "payment_backend": settings.PAYMENT_BACKEND,
        "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY if stripe_status["stripe_checkout_ready"] else None,
        "stripe_checkout_ready": stripe_status["stripe_checkout_ready"],
        "stripe_webhooks_ready": stripe_status["stripe_webhooks_ready"],
        "stripe_fully_ready": stripe_status["stripe_fully_ready"],
        "app_base_url": settings.APP_BASE_URL,
        "default_currency": settings.DEFAULT_CURRENCY,
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "StudioBookingSoftware"}


@app.get("/ready", include_in_schema=False)
def ready():
    checks = {"database": False, "redis": False}

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    checks["database"] = True

    if redis is not None:
        redis.Redis.from_url(settings.REDIS_URL, decode_responses=True).ping()
        checks["redis"] = True

    stripe_status = get_stripe_configuration_status()
    checks["stripe"] = True if not stripe_status["stripe_requested"] else stripe_status["stripe_fully_ready"]

    status = "ready" if all(checks.values()) else "degraded"
    return {"status": status, "checks": checks}
