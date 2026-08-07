"""
Entry point of the Search_standarts web app.

Creates the FastAPI application and wires up routers from all modules.
Code structure is by module (see VISION.md, the "modular structure" principle).

Run (from the project root):
    uvicorn backend.app:app --reload

After start:
  - http://localhost:8000/api/health  — liveness check
  - http://localhost:8000/docs        — auto docs (Swagger UI)
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from pathlib import Path

# Load .env as early as possible — before importing services that read env vars.
load_dotenv()

from backend.core import index_lock, index_store
from backend.core.database import Base, SessionLocal, engine, ensure_columns
from backend.core.paths import FRONTEND_DIST
from backend.modules.auth import service as auth_service
from backend.modules.auth.deps import require_auth
from backend.modules.auth.models import AuthSession  # noqa: F401 — for create_all
from backend.modules.auth.router import router as auth_router
from backend.modules.telemetry import service as telemetry_service
from backend.modules.telemetry.models import (  # noqa: F401 — for create_all
    PendingEvent,
    PendingReport,
)
from backend.modules.documents.models import Document
from backend.modules.documents.pipeline import run_pipeline_locked
from backend.modules.documents.router import router as documents_router
from backend.modules.health.router import router as health_router
from backend.modules.projects.models import ProjectDocument
from backend.modules.projects.pipeline import run_project_pipeline
from backend.modules.projects.router import router as projects_router
from backend.modules.library.router import router as library_router
from backend.modules.queries.router import router as queries_router
from backend.modules.settings import service as settings_service
from backend.modules.settings.models import Setting  # noqa: F401 — for create_all
from backend.modules.settings.router import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App start/stop: DB, thread pool, resuming interrupted tasks."""
    # Safety net for a clean machine: creates tables if they don't exist yet.
    Base.metadata.create_all(engine)
    # Backfill columns missing from tables created by a previous version.
    ensure_columns()

    # A pool of 3 threads — at most 3 PDFs processed in parallel.
    # The rest wait in the executor's queue.
    executor = ThreadPoolExecutor(max_workers=3)
    app.state.executor = executor

    # Resume documents left in processing after the last crash.
    # The PDF lives in the user's library folder, path from relative_path.
    db = SessionLocal()
    try:
        # Put the DB's OpenAI key (if set) into the env before any LLM calls.
        settings_service.apply_openai_key_to_env(db)
        # Backend text language — from settings (frontend updates it on switch).
        settings_service.apply_ui_language(db)

        library_paths = [Path(p) for p in settings_service.get_library_paths(db)]
        stuck = db.scalars(
            select(Document).where(Document.status == "processing")
        ).all()
        for doc in stuck:
            folder = index_store.resolve_folder(library_paths, doc.slug)
            if folder is None:
                # Folder disconnected or the network drive not mounted yet.
                # Back to pending: it gets indexed by the "Indexovat" button
                # once the folder shows up.
                doc.status = "pending"
                print(f"[startup] Folder for {doc.slug} unavailable — back to pending")
                continue
            busy = index_lock.acquire(folder)
            if busy is not None:
                # Another machine is already indexing the folder — stay out.
                doc.status = "pending"
                print(f"[startup] {doc.slug}: folder indexed by {busy} — pending")
                continue
            index_lock.register(folder, 1)
            executor.submit(
                run_pipeline_locked,
                folder,
                doc.slug,
                str(folder / doc.relative_path),
                index_store.doc_dir(folder, doc.slug),
            )
            print(f"[startup] Resumed pipeline for {doc.slug}")
        db.commit()

        # Same for the project archive: stuck in processing after a crash.
        projects_paths = [Path(p) for p in settings_service.get_projects_paths(db)]
        from backend.modules.projects import service as projects_service

        stuck_projects = db.scalars(
            select(ProjectDocument).where(ProjectDocument.status == "processing")
        ).all()
        for pdoc in stuck_projects:
            root = projects_service.resolve_project_root(
                projects_paths, pdoc.project, pdoc.relative_path
            )
            if root is None:
                # Archive folder unavailable or not configured — same as the
                # library above: pending, indexed by the button once it's back.
                pdoc.status = "pending"
                print(f"[startup] Archive {pdoc.slug}: folder unavailable — pending")
                continue
            busy = index_lock.acquire(root)
            if busy is not None:
                # Another machine is already indexing the folder — stay out.
                pdoc.status = "pending"
                print(f"[startup] Archive {pdoc.slug}: folder indexed by {busy}")
                continue
            index_lock.register(root, 1)
            # The file may have been replaced while the app was down: the stat
            # must match the version the pipeline is about to read.
            projects_service.refresh_file_stat(pdoc, root)
            executor.submit(
                run_project_pipeline,
                pdoc.slug,
                str(root / pdoc.relative_path),
                str(root),
            )
            print(f"[startup] Resumed archive pipeline for {pdoc.slug}")
        db.commit()
    finally:
        db.close()

    # Background license verify once an hour (see backend/modules/auth/service.py).
    # A separate task so it doesn't block server startup.
    verify_task = asyncio.create_task(auth_service.run_verify_loop())

    # Background telemetry sender (see backend/modules/telemetry/service.py).
    telemetry_task = asyncio.create_task(telemetry_service.run_telemetry_sender())

    # App start event — goes to the local queue, the sender ships it when
    # it first can.
    telemetry_service.track_event("app_started")

    yield

    # Don't wait for running jobs (they can take minutes), cancel the queue.
    # Interrupted ones are picked up on the next start.
    executor.shutdown(wait=False, cancel_futures=True)
    verify_task.cancel()
    telemetry_task.cancel()


app = FastAPI(title="Search_standarts API", lifespan=lifespan)

# DNS rebinding protection: the server listens on 127.0.0.1 only, but a
# malicious page can point its domain's DNS at 127.0.0.1 and send requests
# "from inside" the browser. Such requests carry a foreign Host — reject them.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])


@app.middleware("http")
async def block_cross_site_writes(request: Request, call_next):
    """CSRF protection: a foreign site must not trigger our POST/PUT/DELETE.

    The browser sets the Origin header on all cross-site requests and a page
    cannot forge it. Requests without Origin (curl, our own frontend via GET)
    pass through. The port is not checked: Vite in dev calls from
    localhost:5173.
    """
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in ("localhost", "127.0.0.1"):
            return JSONResponse(
                status_code=403, content={"detail": "Cross-site request blocked"}
            )
    return await call_next(request)


# /api/health and /api/auth/* — no require_auth (login and ping must work).
# Other routers are protected: 401 without a session or with a 'blocked' one.
app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(auth_router, prefix="/api", tags=["auth"])

protected = [Depends(require_auth)]
app.include_router(
    queries_router, prefix="/api", tags=["queries"], dependencies=protected
)
app.include_router(
    documents_router, prefix="/api", tags=["documents"], dependencies=protected
)
app.include_router(
    settings_router, prefix="/api", tags=["settings"], dependencies=protected
)
app.include_router(
    library_router, prefix="/api", tags=["library"], dependencies=protected
)
app.include_router(
    projects_router, prefix="/api", tags=["projects"], dependencies=protected
)

# Serve the built frontend from the root — AFTER all /api routers (mounting on
# "/" catches everything else). html=True -> index.html at "/". In dev without
# a build the folder is absent — the frontend comes from Vite (dev proxy on
# /api), so mount only if it exists.
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
