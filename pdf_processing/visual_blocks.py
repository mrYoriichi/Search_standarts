"""Light helpers for visual (figure/table) blocks.

Deliberately free of Docling imports: describe/chunk/embed run in the
MAIN process and pipeline.parse needs these for the resume path — none
of them may pull the multi-gigabyte ML stack (that belongs to the parse
worker only).
"""

# Block types that need page screenshots (for the vision LLM).
VISUAL_BLOCK_TYPES = {"figure", "table"}


def collect_pages_to_save(document: dict) -> set[int]:
    """Page numbers to save as PNGs: only pages containing figure/table.

    The textual context of neighbouring pages travels separately (the
    page_text field) when sent to the vision LLM.
    """
    pages = document["pages"]
    pages_to_save: set[int] = set()

    for page in pages:
        has_visual = any(
            block["type"] in VISUAL_BLOCK_TYPES for block in page["blocks"]
        )
        if not has_visual:
            continue
        pages_to_save.add(page["page_number"])

    return pages_to_save
