"""Processing pipeline for project archive documents.

All documents (technical reports, statics, drawings) go through the shared
per-page standards pipeline (main->describe->chunk->index): the router itself
decides what is prose (Docling) and what is a drawing (OCR + vision passport).
Archive specifics are only chunk ids derived from the `{project}__{file}`
slug and the project in the chunk "header". Artifacts are written into the
project folder itself (<root>/.search_index/{slug}/, like the library) so
the paid index travels with the folder: copy it to another computer or
share it over the network and everyone searches at no extra cost.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import select

from backend.core import cpu_gate, index_lock, index_store, parse_subprocess, progress
from backend.core.database import SessionLocal
from backend.core.ui_messages import msg
from backend.core.errors import classify_pipeline_error
from backend.modules.projects.models import ProjectDocument

from common.jsonio import save_json_atomic


logger = logging.getLogger(__name__)


def _prefix_project_context(doc_dir: Path, project: str) -> None:
    """Prefix the project into document_title of all chunks (before embedding).

    document_title is part of the chunk "header" at indexing time — so a
    "zatížení větrem" chunk from statics is searchable in the context of its
    project/structure.
    """
    chunks_path = doc_dir / "chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    for chunk in chunks:
        title = chunk.get("document_title", "")
        if not title.startswith(project):
            chunk["document_title"] = f"{project} — {title}" if title else project
    save_json_atomic(chunks_path, chunks)


def process_text_document(
    slug: str,
    pdf_path: Path,
    project: str,
    vision_model: str,
    doc_dir: Path,
    describe_images: bool = True,
) -> None:
    """Text archive document (report, statics): the existing standards pipeline.

    Docling -> vision descriptions of images (models/diagrams in statics too)
    -> chunking by headings -> project into the header -> embeddings.
    Everything is written to doc_dir (<root>/.search_index/{slug}/), chunk
    ids come from our slug. describe_images=False -> "No LLM" mode: vision
    is skipped.
    """
    # Lazy imports — deferred so the server start stays light. The heavy
    # stage (parse: Docling/torch/OCR) runs in a child process
    # (core/parse_subprocess) — this process never loads it.
    from pipeline import chunk as chunk_step
    from pipeline import describe as describe_step
    from pipeline import embed as index_step

    # «čtení PDF» — только после входа в шлюз (см. core/cpu_gate.py).
    with cpu_gate.parse_gate:
        progress.set_progress(slug, msg("progress.reading"))
        # pages_dir не задан — parse кладёт скриншоты в doc_dir/pages
        # (поведение архива не меняем).
        parse_subprocess.run_parse(
            slug,
            str(pdf_path),
            doc_dir,
            on_text_pages=lambda total: progress.set_progress(
                slug, msg("progress.reading_text", total=total)
            ),
            on_drawing_page=lambda done, total: progress.set_progress(
                slug, msg("progress.reading_drawing", done=done, total=total)
            ),
        )
    progress.set_progress(slug, msg("progress.images"))
    describe_step.process(
        slug,
        vision_model=vision_model,
        doc_dir=doc_dir,
        pdf_path=str(pdf_path),
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
    _prefix_project_context(doc_dir, project)
    progress.set_progress(slug, msg("progress.embedding"))
    index_step.process(slug, doc_dir=doc_dir)


def run_project_pipeline(slug: str, pdf_path: str, root: str) -> None:
    """Full processing of one archive document (called from ThreadPoolExecutor).

    root — the project folder; artifacts go to <root>/.search_index/{slug}/.
    Runs under the inter-machine folder lock (core/index_lock): the caller
    takes the lock and registers the document, here it is refreshed at the
    start and released by the folder's last finished document — exactly
    like the library's run_pipeline_locked.
    Statuses: processing -> ready | error (+ error text in `error`).
    We open the DB session ourselves — FastAPI dependencies do not work
    in a background thread.
    """
    try:
        index_lock.refresh(Path(root))
        _run_project_pipeline(slug, pdf_path, root)
    finally:
        index_lock.done(Path(root))


def _run_project_pipeline(slug: str, pdf_path: str, root: str) -> None:
    """The pipeline body (see run_project_pipeline for the lock contract)."""
    from backend.modules.settings import service as settings_service

    db = SessionLocal()
    try:
        doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
        if doc is None:
            logger.error("run_project_pipeline: slug %s not found in the DB", slug)
            return
        doc.status = "processing"
        db.commit()

        vision_model = settings_service.get_vision_model(db)
        describe_images = settings_service.get_describe_images(db)
        try:
            # The folder passport records the embedding model — without it
            # other machines could not adopt the indexes we are about to
            # write. Also fails early and clearly on a read-only folder.
            from indexing.embeddings_index import EMBEDDING_MODEL

            index_store.ensure_meta(Path(root), EMBEDDING_MODEL)
            process_text_document(
                slug=slug,
                pdf_path=Path(pdf_path),
                project=doc.project,
                vision_model=vision_model,
                doc_dir=index_store.doc_dir(Path(root), slug),
                describe_images=describe_images,
            )
        except Exception as exc:
            logger.exception("Archive pipeline for %s failed", slug)
            doc.status = "error"
            doc.error = classify_pipeline_error(exc)
            db.commit()
            return

        doc.status = "ready"
        doc.error = None
        db.commit()

        # New chunks/embeddings on disk — invalidate the cache so the next
        # question sees the fresh document (the archive pool is merged into
        # the shared search cache).
        from backend.core import library_cache

        library_cache.invalidate()
    finally:
        progress.clear_progress(slug)
        db.close()
