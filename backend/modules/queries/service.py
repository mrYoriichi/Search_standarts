"""Business logic of "question -> answer".

A thin wrapper over the existing code (`ask.py`, `search/*`, `indexing/*`):
load the library -> filter -> hybrid search -> LLM -> write to the DB.

No HTTP here — `ask` can be called from the router, from tests,
or from a future AI orchestrator agent.
"""

import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session

from search.library import filter_library
from indexing.bm25_index import build_bm25_from_tokens
from common.pricing import model_cost
from search.expand import expand_query
from search.lang_detect import corpus_languages
from search.hybrid import search_by_mode
from search.answer import generate_answer

from backend.core import library_cache
from backend.core.ui_messages import msg
from backend.modules.queries.models import QueryLog
from backend.modules.queries.schemas import AskResponse, Source, UsedChunk
from backend.modules.telemetry.service import track_event


logger = logging.getLogger(__name__)

# Strong search: max page images attached to the answering LLM request.
# Each page costs vision tokens; top 3 covers the typical "what is on this
# sheet" question without inflating cost and answer time.
STRONG_MAX_PAGES = 3


class NoSearchableDocumentsError(Exception):
    """The filter matched no documents.

    Typical cause: the user kept the tab open while the selected documents
    got deleted/renamed — the frontend sent stale document_ids. Without this
    check an empty corpus crashed BM25 (ZeroDivisionError -> HTTP 500).
    """


def collect_page_refs(
    top_chunks: list[dict], limit: int = STRONG_MAX_PAGES
) -> list[tuple[str, int]]:
    """Pages of the top results for strong search: a list of (slug, page).

    Walk the chunks in relevance order, within a chunk — over its pages;
    drop duplicate (slug, page) pairs, at most `limit` in total.
    """
    refs: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for chunk in top_chunks:
        slug = chunk.get("document_id", "")
        for page in chunk.get("pages", []):
            key = (slug, page)
            if key in seen:
                continue
            seen.add(key)
            refs.append(key)
            if len(refs) >= limit:
                return refs
    return refs


def _render_page_b64(pdf_path: Path, page_number: int) -> str | None:
    """PNG of a PDF page as base64 — rendered on the fly, no disk writes.

    Best-effort: any failure (broken PDF, missing page) -> None, strong
    search just continues without this image.
    """
    import base64
    import io

    import pypdfium2 as pdfium

    from pdf_processing.drawing import RENDER_MAX_SIDE_PX
    from pdf_processing.pdfium_lock import PDFIUM_LOCK

    try:
        with PDFIUM_LOCK:
            doc = pdfium.PdfDocument(pdf_path)
            try:
                page = doc[page_number - 1]
                width, height = page.get_size()
                scale = RENDER_MAX_SIDE_PX / max(width, height)
                pil = page.render(scale=scale).to_pil()
            finally:
                doc.close()
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        logger.warning(
            "Strong search: failed to render page %s of %s", page_number, pdf_path
        )
        return None


def _build_page_images(db: Session, top_chunks: list[dict]) -> list[dict]:
    """Page snapshots of the top sources: [{"label": "document, s. N", "b64": ...}].

    The PDF path is resolved across all pools (library + archive, see
    resolve_pdf_by_slug); a document without a PDF on disk or a nonexistent
    page is simply skipped — the answer falls back to text.
    """
    from backend.modules.library.service import resolve_pdf_by_slug

    titles = {c.get("document_id", ""): c.get("document_title", "") for c in top_chunks}
    pdf_paths: dict[str, Path | None] = {}
    images: list[dict] = []
    for slug, page in collect_page_refs(top_chunks):
        if slug not in pdf_paths:
            pdf_paths[slug] = resolve_pdf_by_slug(db, slug)
        pdf_path = pdf_paths[slug]
        if pdf_path is None:
            continue
        b64 = _render_page_b64(pdf_path, page)
        if b64 is None:
            continue
        images.append({"label": f"{titles.get(slug, slug)}, s. {page}", "b64": b64})
    return images


def ask(
    question: str,
    document_ids: list[str] | None,
    db: Session,
    mode: str = "hybrid",
    answer_model: str = "gpt-5.6-luna",
    expand: bool = True,
    strong: bool = False,
    answer_language: str | None = None,
) -> AskResponse:
    """The main function: question -> answer + sources + QueryLog record id.

    document_ids=None — search the whole library.
    mode — search mode (hybrid / vector / keyword), see search.hybrid.
    answer_model — answer generation model (gpt-5.6-luna / gpt-5.6-sol).
    expand — expand the query via LLM before searching (diacritics/synonyms).
    strong — strong search: attach page snapshots of the top sources to the
    answer (heavy questions about drawings/tables; slower and pricier).
    answer_language — LLM answer language (cs/en/de); None — the user's
    saved setting (see settings.get_answer_language).
    """
    started_at = time.perf_counter()

    # The library lives in memory (see backend/core/library_cache.py) — we hit
    # the disk only on the first question and after library changes. Chunks and
    # tokens come from a single call — guaranteed same cache generation.
    chunks, embeddings_index, tokens_by_id = library_cache.get_library_with_tokens()

    if document_ids:
        chunks, embeddings_index = filter_library(
            chunks, embeddings_index, set(document_ids)
        )
        if not chunks:
            raise NoSearchableDocumentsError(msg("lib.stale_selection"))

    # Expand the query for search (diacritics, terms, synonyms), but generate
    # the answer from the ORIGINAL question — answer what the user asked.
    # Expansion can be turned off (expand=False) — then search as is.
    # Corpus languages are computed from the ALREADY filtered chunks: if the
    # user searches only a Czech folder, English terms are not needed.
    search_query = (
        expand_query(question, corpus_languages(chunks)) if expand else question
    )

    # BM25 is built from the cached tokens of the current chunk set (filter
    # applied) — IDF is computed over this same set, as before.
    tokenized = [tokens_by_id[c["chunk_id"]] for c in chunks]
    chunk_ids = [c["chunk_id"] for c in chunks]
    bm25 = build_bm25_from_tokens(tokenized, chunk_ids)
    found_ids = search_by_mode(bm25, embeddings_index, search_query, mode)

    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    # Orphan vectors (embeddings.json from a different generation than
    # chunks.json) are skipped instead of failing the whole question with
    # a KeyError — audit item #2.
    orphan_ids = [cid for cid in found_ids if cid not in chunks_by_id]
    if orphan_ids:
        logger.warning(
            "Search returned ids without chunks (index out of sync, "
            "reindex needed): %s",
            orphan_ids,
        )
    top_chunks = [chunks_by_id[cid] for cid in found_ids if cid in chunks_by_id]

    # Strong search: render pages of the top sources and pass them as images
    # to the answering LLM — it "sees" the drawing/table, not just text/OCR.
    page_images = _build_page_images(db, top_chunks) if strong else None

    if answer_language is None:
        # The setting lives in the profile; a request may override it
        # explicitly (agent-ready API: an agent need not touch settings).
        from backend.modules.settings import service as settings_service

        answer_language = settings_service.get_answer_language(db)

    # Answer generation time is measured separately — to compare model speed.
    gen_start = time.perf_counter()
    result = generate_answer(
        question,
        top_chunks,
        model=answer_model,
        page_images=page_images,
        answer_language=answer_language,
    )
    answer_ms = int((time.perf_counter() - gen_start) * 1000)

    # Cost counts only the answering LLM call — it dominates.
    # The price comes from the table by model name (pricing.MODEL_PRICES_PER_M).
    cost_usd = model_cost(
        answer_model, result["prompt_tokens"], result["completion_tokens"]
    )
    duration_ms = int((time.perf_counter() - started_at) * 1000)

    log = QueryLog(
        question=question,
        answer=result["answer"],
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # Anonymous technical telemetry: numbers only, no question/answer text.
    track_event(
        "query_asked",
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        scope="filtered" if document_ids else "all",
        mode=mode,
        answer_model=answer_model,
        answer_ms=answer_ms,
        chunks_searched=len(chunks),
        sources_returned=len(result["sources"]),
        strong=strong,
        images_sent=len(page_images or []),
    )

    return AskResponse(
        answer=result["answer"],
        sources=[Source(**s) for s in result["sources"]],
        related_sources=[Source(**s) for s in result["related_sources"]],
        used_chunks=[UsedChunk(**c) for c in result["used_chunks"]],
        query_log_id=log.id,
        search_query=search_query,
        answer_model=answer_model,
        answer_ms=answer_ms,
    )
