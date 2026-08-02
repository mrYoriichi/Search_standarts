"""Splitting the structured document (document.json) into semantic chunks.

A chunk is one section of a norm (a level-2 heading and its content),
enriched with context: document title, summary, parent section. Large
chunks are split at level-3 headings, or at paragraph boundaries when
there are none.

Main entry: build_chunks(document) -> list[dict]
"""

import re

from pdf_processing.drawing import extract_stupen

# Junk block types that never enter chunks.
SKIP_BLOCK_TYPES = {"document_index", "header", "footer"}

# Marker phrases of non-technical content (logos, stamps). The model does
# not always write the canonical label verbatim ("Logo... bez technického
# obsahu"), so we match case-insensitive substrings, not exact equality.
NON_TECHNICAL_SUBSTRINGS = (
    "není technický obsah",  # the canonical label from the prompt
    "bez technického",  # frequent model paraphrase
)

# 'logo' is matched as a whole word (\b), not a substring: a substring
# would catch inflected 'katalogové', 'dialogový' etc.
_LOGO_WORD = re.compile(r"\blogo\b")

# Chunks longer than this are candidates for splitting.
MAX_CHUNK_CHARS = 2500

# Hard limit for parts without a heading boundary: text between level-3
# headings that grows beyond this is force-split at a paragraph — a
# section with sparse subheadings would otherwise hit the embedding limit
# (~8000 tokens). Sized with margin for chars-per-token variation.
HARD_SPLIT_CHARS = 6000


def is_block_useful(block: dict) -> bool:
    """Does the block belong in a chunk?

    Filters junk: table of contents, headers/footers, logos, empties.
    """
    block_type = block["type"]

    if block_type in SKIP_BLOCK_TYPES:
        return False

    if block_type in ("figure", "table"):
        description = block.get("description")
        if not description:
            # A table without a vision description but with cell text
            # (Docling markdown) is useful: exact values are searchable.
            # This keeps tables in the index in no-LLM mode.
            if block_type == "table":
                text = block.get("text")
                return bool(text and text.strip())
            return False
        low = description.lower()
        if any(marker in low for marker in NON_TECHNICAL_SUBSTRINGS):
            return False
        if _LOGO_WORD.search(low):
            return False
        return True

    text = block.get("text")
    return bool(text and text.strip())


def build_chunk_text(blocks: list[dict]) -> str:
    """Assemble chunk text from blocks.

    Figure/table descriptions are inlined as [SCHÉMA: ...] / [TABULKA: ...].
    Expects blocks already filtered through is_block_useful.
    """
    pieces = []
    for block in blocks:
        block_type = block["type"]
        if block_type == "figure":
            pieces.append(f"[SCHÉMA: {block['description']}]")
        elif block_type == "table":
            # Vision paraphrase (table topic) + the cell text (exact
            # values) — whichever exists. Old indexes without text and
            # no-LLM mode without description both behave honestly.
            description = block.get("description")
            text = (block.get("text") or "").strip()
            if description and text:
                pieces.append(f"[TABULKA: {description}]\n{text}")
            elif description:
                pieces.append(f"[TABULKA: {description}]")
            else:
                pieces.append(f"[TABULKA]\n{text}")
        else:
            pieces.append(block["text"].strip())
    return "\n\n".join(pieces)


def page_of_block(block: dict) -> int:
    """Page number from a block_id: 'p12_b03' -> 12."""
    return int(block["block_id"].split("_")[0][1:])


def split_large_chunk(chunk: dict) -> list[dict]:
    """Split a large chunk into sub-chunks that fit the embedding limit.

    Rules:
      - below the threshold -> returned as is;
      - level-3 headings present -> cut at them once past the threshold;
        text between headings past HARD_SPLIT_CHARS is cut at a paragraph;
      - no level-3 headings -> cut at paragraph boundaries (MAX_CHUNK_CHARS).
    """
    blocks = chunk["_blocks"]

    if len(chunk["text"]) <= MAX_CHUNK_CHARS:
        return [chunk]

    has_level3 = any(b["type"] == "heading" and b.get("level") == 3 for b in blocks)

    # Accumulate blocks into parts. Without headings we cut at paragraphs
    # already at MAX_CHUNK_CHARS; with headings a part may grow to
    # HARD_SPLIT_CHARS before a paragraph cut — preserving the binding of
    # sub-chunks to their subheadings.
    parts = []
    current_blocks = []
    current_len = 0

    for block in blocks:
        is_heading = block["type"] == "heading" and block.get("level") == 3
        hard_limit = HARD_SPLIT_CHARS if has_level3 else MAX_CHUNK_CHARS
        should_cut = current_blocks and (
            (is_heading and current_len >= MAX_CHUNK_CHARS) or current_len >= hard_limit
        )

        if should_cut:
            parts.append(current_blocks)
            current_blocks = []
            current_len = 0

        current_blocks.append(block)
        text = block.get("text") or block.get("description") or ""
        current_len += len(text)

    if current_blocks:
        parts.append(current_blocks)

    if len(parts) <= 1:
        return [chunk]

    sub_chunks = []
    for part_blocks in parts:
        part_pages = sorted({page_of_block(b) for b in part_blocks})

        sub_chunks.append(
            {
                "document_id": chunk["document_id"],
                "document_title": chunk["document_title"],
                "document_summary": chunk["document_summary"],
                "parent_section": chunk["parent_section"],
                "section_number": chunk["section_number"],
                "section_title": chunk["section_title"],
                "text": build_chunk_text(part_blocks),
                "pages": part_pages,
                "related_blocks": [b["block_id"] for b in part_blocks],
            }
        )

    return sub_chunks


def build_chunks(document: dict) -> list[dict]:
    """Split the document into chunks by section.

    Logic:
      - a level-1 heading is remembered as the parent section;
      - a level-2 heading closes the current chunk and starts a new one;
      - a level-1 section without level-2 subsections becomes its own chunk;
      - other blocks join the current chunk.
    Large chunks are split afterwards via split_large_chunk.
    """
    document_id = document["document_id"]
    doc_title = document.get("document_title", "")
    doc_summary = document.get("document_summary", "")

    # Does the document have numbered sections at all? If not, the
    # "page = chunk" fallback below collects everything and no preamble
    # chunk is needed.
    has_sections = any(
        block["type"] == "heading" and block.get("level") in (1, 2)
        for page in document["pages"]
        for block in page["blocks"]
    )

    chunks = []
    current = None
    parent_section = ""

    def close_current():
        """Finish the current chunk and append it to chunks."""
        if current is None:
            return
        if not current["blocks"]:
            return
        chunks.append(
            {
                "document_id": document_id,
                "document_title": doc_title,
                "document_summary": doc_summary,
                "parent_section": current["parent_section"],
                "section_number": current["section_number"],
                "section_title": current["section_title"],
                "text": build_chunk_text(current["blocks"]),
                "pages": sorted(current["pages"]),
                "related_blocks": [b["block_id"] for b in current["blocks"]],
                "_blocks": list(current["blocks"]),
            }
        )

    def start_chunk(section_number, section_title, parent):
        """Create a new empty chunk shell."""
        return {
            "section_number": section_number,
            "section_title": section_title,
            "parent_section": parent,
            "blocks": [],
            "pages": set(),
        }

    for page in document["pages"]:
        page_num = page["page_number"]
        for block in page["blocks"]:
            if block["type"] == "heading":
                level = block.get("level")

                if level == 1:
                    close_current()
                    parent_section = block["text"].strip()
                    current = start_chunk(
                        block.get("section_number") or "",
                        block["text"].strip(),
                        parent_section,
                    )
                    continue

                if level == 2:
                    close_current()
                    current = start_chunk(
                        block.get("section_number") or "",
                        block["text"].strip(),
                        parent_section,
                    )
                    continue

                # Level 3 (or unnumbered) is content — joins the chunk.

            if not is_block_useful(block):
                continue
            if current is None:
                if not has_sections:
                    continue
                # Preamble: the title page and preface before the first
                # numbered heading used to fall out of the index silently.
                current = start_chunk("", "", "")

            current["blocks"].append(block)
            current["pages"].add(page_num)

    close_current()

    # Fallback: a document without level-1/2 headings (common in project
    # archives: attachment lists, extracts). Chunking above produced
    # nothing but content exists — "page = chunk" keeps the document from
    # vanishing silently.
    if not chunks:
        for page in document["pages"]:
            useful = [b for b in page["blocks"] if is_block_useful(b)]
            if not useful:
                continue
            first_heading = next(
                (b["text"].strip() for b in useful if b["type"] == "heading"), ""
            )
            chunks.append(
                {
                    "document_id": document_id,
                    "document_title": doc_title,
                    "document_summary": doc_summary,
                    "parent_section": "",
                    "section_number": "",
                    "section_title": first_heading,
                    "text": build_chunk_text(useful),
                    "pages": [page["page_number"]],
                    "related_blocks": [b["block_id"] for b in useful],
                    "_blocks": list(useful),
                }
            )

    # Split the large chunks.
    result = []
    for chunk in chunks:
        result.extend(split_large_chunk(chunk))

    # Unique chunk_id: a running counter within the document. The old
    # scheme (document + section number) produced duplicates in norms
    # with annexes where section numbering restarts. The section number
    # stays in section_number.
    for i, chunk in enumerate(result, start=1):
        chunk["chunk_id"] = f"{document_id}_c{i:03d}"

    # Drop the internal _blocks field.
    for chunk in result:
        chunk.pop("_blocks", None)

    return result


def build_drawing_chunk(page: dict, document: dict) -> dict:
    """Chunk for one drawing page.

    text = the vision passport of the sheet (pure semantics: type,
    object, what is drawn) + the stage extracted from text + the raw
    drawing_text (OCR + text layer: exact title-block lines and terms).
    The passport exists only in standard mode; no-LLM mode keeps just
    drawing_text. Drawings have no sections — the whole page is one
    chunk; object context comes from document_title.
    """
    drawing_text = page.get("drawing_text", "")

    parts = []
    paspport = page.get("drawing_description", "").strip()
    if paspport:
        parts.append(paspport)
    stupen = extract_stupen(drawing_text)
    if stupen:
        parts.append(f"Stupeň dokumentace: {stupen}")
    if drawing_text.strip():
        parts.append(drawing_text.strip())

    return {
        "document_id": document["document_id"],
        "document_title": document.get("document_title", ""),
        "document_summary": document.get("document_summary", ""),
        "parent_section": "",
        "section_number": "",
        "section_title": "",
        "text": "\n\n".join(parts),
        "pages": [page["page_number"]],
        "related_blocks": [],
    }


def build_chunks_routed(document: dict) -> list[dict]:
    """Chunking aware of page types (the per-page router).

    Prose pages (page_type != 'drawing') go through the regular
    build_chunks; drawing pages get one chunk per page from drawing_text.
    Results are merged and chunk_id renumbered with one counter across
    the document. Without page_type behaves exactly like build_chunks
    (all pages prose) — backward compatible.
    """
    pages = document["pages"]
    prose_pages = [p for p in pages if p.get("page_type") != "drawing"]
    drawing_pages = [p for p in pages if p.get("page_type") == "drawing"]

    chunks = build_chunks({**document, "pages": prose_pages})
    for page in drawing_pages:
        has_text = page.get("drawing_text", "").strip()
        has_paspport = page.get("drawing_description", "").strip()
        if has_text or has_paspport:
            chunks.append(build_drawing_chunk(page, document))

    # One chunk_id counter across the merged list (prose + drawings).
    document_id = document["document_id"]
    for i, chunk in enumerate(chunks, start=1):
        chunk["chunk_id"] = f"{document_id}_c{i:03d}"
    return chunks
