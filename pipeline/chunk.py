"""Pipeline stage 3: split the document into semantic chunks.

Takes document.json (structure from parse) and descriptions.json
(vision output from describe), merges the descriptions into the document
in memory and splits it into chunks. Saves chunks.json.

Run AFTER parse and describe:
    python -m pipeline.parse <pdf>
    python -m pipeline.describe <pdf>
    python -m pipeline.chunk <pdf>
"""

import json
import sys
from pathlib import Path

from backend.core.paths import CLI_OUTPUT_DIR
from common.jsonio import save_json_atomic
from pdf_processing.chunker import build_chunks_routed

# Лёгкий модуль вместо parser: chunk работает в основном процессе,
# импорт parser затащил бы docling/torch в родителя.
from pdf_processing.document_id import make_document_id


def load_json(json_path: Path) -> dict:
    """Read a JSON file into a dict."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_chunks(chunks: list[dict], json_path: Path) -> None:
    """Save the chunk list to a JSON file."""
    save_json_atomic(json_path, chunks)


def merge_descriptions(document: dict, descriptions: dict) -> None:
    """Merge descriptions.json into the document (in place).

    document_title/document_summary go to the top level;
    block_descriptions are distributed to blocks by block_id. The chunker
    then works unchanged.
    """
    document["document_title"] = descriptions.get("document_title", "")
    document["document_summary"] = descriptions.get("document_summary", "")

    block_descriptions = descriptions.get("block_descriptions", {})
    drawing_descriptions = descriptions.get("drawing_descriptions", {})
    for page in document["pages"]:
        for block in page["blocks"]:
            description = block_descriptions.get(block["block_id"])
            if description:
                block["description"] = description
        # Vision passport of a drawing page (keyed by page number as string).
        drawing_description = drawing_descriptions.get(str(page["page_number"]))
        if drawing_description:
            page["drawing_description"] = drawing_description


def process(pdf_name: str, doc_dir: Path | None = None) -> None:
    """Split the document into chunks and save chunks.json.

    pdf_name — the same name passed to parse (e.g. MVL649).
    doc_dir — document folder; defaults to data/cli_output/<id>, the
    project archive passes its own (projects_data/<slug>).
    """
    doc_dir = doc_dir or (CLI_OUTPUT_DIR / make_document_id(pdf_name))
    document_path = doc_dir / "document.json"
    descriptions_path = doc_dir / "descriptions.json"
    chunks_path = doc_dir / "chunks.json"

    if not descriptions_path.exists():
        print(f"[!] Missing file {descriptions_path}")
        print("    Run first: python -m pipeline.describe <pdf_name>")
        sys.exit(1)

    document = load_json(document_path)
    descriptions = load_json(descriptions_path)

    merge_descriptions(document, descriptions)

    print(f"Document: {document['document_name']}")
    print("Chunking...")

    chunks = build_chunks_routed(document)
    save_chunks(chunks, chunks_path)

    total_chars = sum(len(c["text"]) for c in chunks)
    avg_chars = total_chars // len(chunks) if chunks else 0

    print("\nDone!")
    print(f"  Chunks created: {len(chunks)}")
    print(f"  Average size:   {avg_chars} chars")
    print(f"  Saved to:       {chunks_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:   python -m pipeline.chunk <pdf_name>")
        print("Example: python -m pipeline.chunk MVL649")
        sys.exit(1)
    process(sys.argv[1])
