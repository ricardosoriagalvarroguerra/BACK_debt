"""Sistema de Endeudamiento - Backend API.

VP Finanzas - Gestion integral de deuda corporativa.
FastAPI + SQLAlchemy + PostgreSQL
"""
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import get_settings
from app.api.v1 import dashboard, creditors, contracts, disbursements, covenants, payments, scenarios, reports, auth, exchange_rates, projections, admin, audit, notifications, approvals, tasks, annual_planning, snapshots

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description=(
        "API para la gestion del portafolio de endeudamiento. "
        "Reemplaza el sistema Excel con ~2,078 USD MM en 66 instrumentos."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- Global exception handlers ---

@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    logger.error(f"Integrity error on {request.method} {request.url}: {exc.orig}")
    return JSONResponse(
        status_code=409,
        content={"detail": "Conflicto de datos: registro duplicado o restriccion violada."},
    )

@app.exception_handler(OperationalError)
async def db_operational_error_handler(request: Request, exc: OperationalError):
    logger.error(f"Database error on {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=503,
        content={"detail": "Error de conexion a la base de datos. Intente nuevamente."},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor."},
    )


# CORS - permitir frontend
cors_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "https://frontdebt-production.up.railway.app",
]
if settings.FRONTEND_URL and settings.FRONTEND_URL not in cors_origins:
    cors_origins.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)

# Registrar routers
app.include_router(dashboard.router, prefix=settings.API_PREFIX)
app.include_router(creditors.router, prefix=settings.API_PREFIX)
app.include_router(contracts.router, prefix=settings.API_PREFIX)
app.include_router(disbursements.router, prefix=settings.API_PREFIX)
app.include_router(covenants.router, prefix=settings.API_PREFIX)
app.include_router(payments.router, prefix=settings.API_PREFIX)
app.include_router(scenarios.router, prefix=settings.API_PREFIX)
app.include_router(reports.router, prefix=settings.API_PREFIX)
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(exchange_rates.router, prefix=settings.API_PREFIX)
app.include_router(projections.router, prefix=settings.API_PREFIX)
app.include_router(admin.router, prefix=settings.API_PREFIX)
app.include_router(audit.router, prefix=settings.API_PREFIX)
app.include_router(notifications.router, prefix=settings.API_PREFIX)
app.include_router(annual_planning.router, prefix=settings.API_PREFIX)
app.include_router(snapshots.router, prefix=settings.API_PREFIX)
app.include_router(approvals.router, prefix=settings.API_PREFIX)
app.include_router(tasks.router, prefix=settings.API_PREFIX)


@app.get("/", tags=["Health"])
def root():
    return {
        "sistema": "Endeudamiento VP Finanzas",
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Health check para monitoreo."""
    from sqlalchemy import text
    from app.database import engine
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = "error"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "environment": settings.ENVIRONMENT,
    }
