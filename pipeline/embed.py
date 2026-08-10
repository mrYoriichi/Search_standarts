"""Pipeline stage 4: build the vector index over the chunks.

Takes chunks.json (from the chunk stage), builds the embeddings index
via OpenAI and saves embeddings.json.

The BM25 index is NOT saved — it builds from chunks.json instantly.
Embeddings are an OpenAI call (money/time), so they are worth persisting.

Run AFTER the chunk stage:
    python -m pipeline.parse <pdf>
    python -m pipeline.describe <pdf>
    python -m pipeline.chunk <pdf>
    python -m pipeline.embed <pdf>
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from backend.core.paths import CLI_OUTPUT_DIR
from indexing.embeddings_index import build_embeddings_index, EMBEDDING_MODEL
from common.jsonio import save_json_atomic

# Лёгкий модуль вместо parser: embed работает в основном процессе,
# импорт parser затащил бы docling/torch в родителя.
from pdf_processing.document_id import make_document_id
from common.pricing import embedding_cost


def load_chunks(json_path: Path) -> list[dict]:
    """Read chunks.json into a list of chunks."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def save_index(index: dict, json_path: Path) -> None:
    """Save the vector index to a JSON file."""
    save_json_atomic(json_path, index)


def process(pdf_name: str, doc_dir: Path | None = None) -> None:
    """Build the vector index for chunks.json and save embeddings.json.

    pdf_name — the same name passed to parse (e.g. MVL649).
    doc_dir — document folder; defaults to data/cli_output/<id>, the
    project archive passes its own (projects_data/<slug>).
    """
    doc_dir = doc_dir or (CLI_OUTPUT_DIR / make_document_id(pdf_name))
    chunks_path = doc_dir / "chunks.json"
    index_path = doc_dir / "embeddings.json"
    document_path = doc_dir / "document.json"

    chunks = load_chunks(chunks_path)

    # The "$ per page" metric needs the document's total page count.
    with open(document_path, encoding="utf-8") as f:
        document = json.load(f)
    total_pages = len(document["pages"])

    print(f"Chunks loaded: {len(chunks)}")
    print(f"Model: {EMBEDDING_MODEL}")
    print("Building the vector index (OpenAI call)...")

    index, tokens = build_embeddings_index(chunks)
    save_index(index, index_path)

    print("\nDone!")
    print(f"  Vectors saved: {len(index['items'])}")
    print(f"  File: {index_path}")

    usd = embedding_cost(tokens)
    print("\n=== Embeddings cost ===")
    print(f"  Pages in document: {total_pages}")
    print(f"  Chunks:            {len(chunks)}")
    print(f"  Tokens:            {tokens}")
    print(f"  TOTAL embeddings:  ${usd:.4f}")
    if total_pages:
        print(f"  $ per page:        ${usd / total_pages:.4f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:   python -m pipeline.embed <pdf_name>")
        print("Example: python -m pipeline.embed MVL649")
        sys.exit(1)
    process(sys.argv[1])
