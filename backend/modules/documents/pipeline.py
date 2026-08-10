"""Processing pipeline for one PDF: parse -> describe -> chunk -> embed.

Called from a ThreadPoolExecutor thread, not from an HTTP request — so
the DB session is opened via SessionLocal() and closed in finally;
FastAPI dependencies do not work here.
"""

import json
import logging
import tempfile
from pathlib import Path

from sqlalchemy import select

from backend.core import cpu_gate, index_lock, library_cache, parse_subprocess, progress
from backend.core.database import SessionLocal
from backend.core.ui_messages import msg
from backend.core.errors import classify_pipeline_error
from backend.modules.documents.models import Document
from backend.modules.telemetry.service import track_event


logger = logging.getLogger(__name__)


def run_pipeline_locked(
    library_path: Path, slug: str, pdf_path: str | None, doc_dir: Path
) -> None:
    """The pipeline under the inter-machine folder lock (core/index_lock).

    Refreshes the lock at the start and marks the document finished at
    the end (the folder's last document releases the lock). EVERY path
    that writes into .search_index — button start, reindex, crash
    resume — must go through this wrapper, or the lock goes stale and
    another machine walks in.
    """
    try:
        index_lock.refresh(library_path)
        run_pipeline(slug, pdf_path, doc_dir)
    finally:
        index_lock.done(library_path)


def run_pipeline(slug: str, pdf_path: str | None, doc_dir: Path) -> None:
    """Run the full pipeline for one document.

    slug — the document id, same as the artifact folder name.
    pdf_path — full path to the PDF in the user's folder.
    doc_dir — artifact folder: `<library folder>/.search_index/{slug}`.
    Both come from the caller — no defaults on purpose: a silent fallback
    to a local pool used to route documents away from the library folder.

    Page screenshots live in a TEMPORARY local folder: only the vision
    step needs them; they are not stored (and never travel to a network
    drive).

    On any error: status='failed' + the cause in Document.error_message.
    On success: status='ready', error_message=None.
    """
    # Lazy imports — deferred so the server start and --reload stay
    # light. The heavy stage (parse: Docling/torch/OCR) runs in a child
    # process (core/parse_subprocess) — this process never loads it.
    from pipeline import chunk as chunk_step
    from pipeline import describe as describe_step
    from pipeline import embed as index_step

    # Imported here (not at the top) to avoid a cycle with settings.
    from backend.modules.settings import service as settings_service

    db = SessionLocal()
    try:
        # The vision model is the cost lever, chosen in the UI. Read at
        # document start so the current choice applies.
        vision_model = settings_service.get_vision_model(db)
        describe_images = settings_service.get_describe_images(db)
        try:
            with tempfile.TemporaryDirectory(prefix=f"ss_pages_{slug}_") as tmp:
                pages_dir = Path(tmp)
                # «čtení PDF» ставим только после входа в шлюз — пока
                # документ ждёт своей очереди на parse, статус не врёт.
                with cpu_gate.parse_gate:
                    progress.set_progress(slug, msg("progress.reading"))
                    # The worker stamps document_id=slug into the
                    # artifacts: they must carry the scoped slug
                    # ({folder_id}__{file}) from the DB, not the id derived
                    # from the file name — otherwise the "Where to search"
                    # filter would match no chunk.
                    parse_subprocess.run_parse(
                        slug,
                        pdf_path,
                        doc_dir,
                        pages_dir=pages_dir,
                        on_text_pages=lambda total: progress.set_progress(
                            slug, msg("progress.reading_text", total=total)
                        ),
                        on_drawing_page=lambda done, total: progress.set_progress(
                            slug,
                            msg("progress.reading_drawing", done=done, total=total),
                        ),
                    )
                progress.set_progress(slug, msg("progress.images"))
                describe_step.process(
                    slug,
                    vision_model=vision_model,
                    doc_dir=doc_dir,
                    pages_dir=pages_dir,
                    pdf_path=pdf_path,
                    describe_images=describe_images,
                    on_progress=lambda done, total: progress.set_progress(
                        slug, msg("progress.images_page", done=done, total=total)
                    ),
                    on_drawing_progress=lambda done, total: progress.set_progress(
                        slug, msg("progress.drawings_page", done=done, total=total)
                    ),
                )
            progress.set_progress(slug, msg("progress.chunking"))
            chunk_step.process(slug, doc_dir=doc_dir)
            progress.set_progress(slug, msg("progress.embedding"))
            index_step.process(slug, doc_dir=doc_dir)
        except Exception as exc:
            logger.exception("Pipeline for %s failed", slug)
            doc = db.scalar(select(Document).where(Document.slug == slug))
            if doc is not None:
                doc.status = "failed"
                doc.error_message = classify_pipeline_error(exc)
                db.commit()
            track_event("pdf_failed", error_type=type(exc).__name__)
            return

        # Take the real document title from descriptions.json (set by
        # the describe step) — at registration only the filename was
        # known. A read error must NOT break post-processing: this code
        # is outside the try above, and an unhandled exception would be
        # silently eaten by the executor, leaving the document stuck in
        # processing.
        descriptions_path = doc_dir / "descriptions.json"
        real_title = None
        try:
            with open(descriptions_path, encoding="utf-8") as f:
                real_title = json.load(f).get("document_title")
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read the title from %s", descriptions_path)

        doc = db.scalar(select(Document).where(Document.slug == slug))
        if doc is not None:
            if real_title:
                doc.title = real_title
            doc.status = "ready"
            doc.error_message = None
            db.commit()

        # New chunks/embeddings landed on disk — drop the library cache
        # so the next question sees the fresh document.
        library_cache.invalidate()

        # The chunk count is a proxy for document size — sending the
        # file name is off-limits (personal data).
        chunks_path = doc_dir / "chunks.json"
        chunks_count: int | None = None
        try:
            with open(chunks_path, encoding="utf-8") as f:
                chunks_count = len(json.load(f))
        except Exception:  # pylint: disable=broad-except
            pass
        track_event("pdf_indexed", chunks_count=chunks_count)
    finally:
        progress.clear_progress(slug)
        db.close()
