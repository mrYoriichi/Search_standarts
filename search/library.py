"""Loading and filtering the document pool (chunks.json + embeddings.json).

Shared search plumbing: used by the CLI (cli/ask.py) and by the app's
library cache (backend/core/library_cache.py).
"""

import json
from pathlib import Path

import numpy as np

from backend.core.ui_messages import msg
from indexing.embeddings_index import build_matrix_index


def load_chunks(json_path: Path) -> list[dict]:
    """Read chunks.json into a list of chunks."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def load_index(json_path: Path) -> dict:
    """Read the vector index from disk."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


class EmptyLibraryError(RuntimeError):
    """The root has no ready document — such a root can be silently
    skipped when merging pools (unlike incompatible models)."""


def load_library(data_root: Path) -> tuple[list[dict], dict]:
    """Merge chunks and embeddings of every ready document into one pool.

    Scans the subfolders of data_root, taking chunks.json and
    embeddings.json from each. Folders without the complete pair
    (unfinished pipeline) are skipped.

    Every document must be indexed with ONE embedding model — vectors
    from different models are incomparable; a mismatch raises loudly.

    Returns (chunks, embeddings_index) where the index is the matrix form
    from build_matrix_index: all vectors in one normalized float32 matrix.
    """
    all_chunks: list[dict] = []
    all_items: list[dict] = []
    model: str | None = None

    for doc_dir in sorted(data_root.iterdir()):
        if not doc_dir.is_dir():
            continue
        chunks_path = doc_dir / "chunks.json"
        index_path = doc_dir / "embeddings.json"
        if not chunks_path.exists() or not index_path.exists():
            continue  # pipeline not finished for this document

        try:
            chunks = load_chunks(chunks_path)
            index = load_index(index_path)
            index_model = index["model"]
            index_items = index["items"]
        except (OSError, json.JSONDecodeError, KeyError):
            # One broken index file must not take down the whole search:
            # skip the document, the rest of the library keeps working.
            print(f"[!] Broken index, skipping document: {doc_dir.name}")
            continue

        # Model check; the text reaches the UI via a 400 response.
        if model is None:
            model = index_model
        elif model != index_model:
            raise RuntimeError(
                msg(
                    "lib.mixed_models_doc",
                    doc=doc_dir.name,
                    model_a=index_model,
                    model_b=model,
                )
            )

        all_chunks.extend(chunks)
        all_items.extend(index_items)

    if not all_chunks:
        raise EmptyLibraryError(f"No ready document found in {data_root}.")

    return all_chunks, build_matrix_index(all_items, model)


def filter_library(
    chunks: list[dict],
    embeddings_index: dict,
    allowed_ids: set[str],
) -> tuple[list[dict], dict]:
    """Keep only chunks and embeddings of the selected documents.

    Input/output format is unchanged — BM25 and the hybrid search work on
    the result as usual. The embedding matrix knows nothing about
    document_id (only row order ↔ chunk_ids), so a boolean mask built
    from the selected chunk ids cuts the matrix and the id list alike.
    """
    chunks_f = [c for c in chunks if c["document_id"] in allowed_ids]
    allowed_chunk_ids = {c["chunk_id"] for c in chunks_f}

    chunk_ids = embeddings_index["chunk_ids"]
    mask = np.array([cid in allowed_chunk_ids for cid in chunk_ids], dtype=bool)
    return chunks_f, {
        "model": embeddings_index["model"],
        "chunk_ids": [cid for cid, keep in zip(chunk_ids, mask) if keep],
        "matrix": embeddings_index["matrix"][mask],
    }
