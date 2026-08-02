"""CLI: ask the library a question from the terminal.

Loads chunks and embeddings of every document in data/cli_output/, runs
the hybrid search and generates an answer with source references.

Run after the full pipeline (pipeline/: parse → describe → chunk → embed)
has finished for the documents you need:
    python -m cli.ask
"""

from dotenv import load_dotenv

load_dotenv()

from backend.core.paths import CLI_OUTPUT_DIR
from indexing.bm25_index import build_bm25_index
from search.answer import generate_answer
from search.hybrid import hybrid_search
from search.library import filter_library, load_library


# How many chunks go to the LLM.
TOP_K = 5
DATA_ROOT = CLI_OUTPUT_DIR


def select_scope(doc_ids: list[str]) -> set[str]:
    """Ask the user which documents to search.

    Empty input = all documents. Accepts comma-separated numbers ("1, 2")
    or document ids ("mvl649, tp_107"). Unknown tokens are skipped with a
    warning; nothing valid selected = all documents.
    """
    raw = input(
        'Where to search? (Enter — everywhere; numbers like "1, 2"; or ids): '
    ).strip()
    if not raw:
        return set(doc_ids)

    selected: set[str] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(doc_ids):
                selected.add(doc_ids[idx])
                continue
        if token in doc_ids:
            selected.add(token)
            continue
        print(f"  [!] Unrecognized token {token!r} — skipped")

    if not selected:
        print("  Nothing selected — searching everywhere.")
        return set(doc_ids)
    return selected


def main():
    chunks, embeddings_index = load_library(DATA_ROOT)

    doc_ids = sorted({c["document_id"] for c in chunks})
    print(f"Library: {len(doc_ids)} documents, {len(chunks)} chunks.")
    for i, doc_id in enumerate(doc_ids, start=1):
        print(f"  [{i}] {doc_id}")

    allowed_ids = select_scope(doc_ids)
    if allowed_ids != set(doc_ids):
        chunks, embeddings_index = filter_library(chunks, embeddings_index, allowed_ids)
        print(f"Searching {len(allowed_ids)} documents, {len(chunks)} chunks.")

    # BM25 is built on the fly from the (possibly filtered) pool.
    bm25 = build_bm25_index(chunks)

    question = input("Question: ").strip()
    if not question:
        print("Empty question.")
        return

    found = hybrid_search(bm25, embeddings_index, question, top_k=TOP_K)

    print(f"\nChunks found: {len(found)}")
    for chunk_id, score in found:
        print(f"  {chunk_id}  (rrf={score:.4f})")

    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    top_chunks = [chunks_by_id[chunk_id] for chunk_id, _ in found]

    print("\nGenerating the answer...")
    result = generate_answer(question, top_chunks)

    print("\n=== Answer ===")
    print(result["answer"])

    print("\n=== Sources ===")
    if not result["sources"]:
        print("  (none — the model found no answer in the fragments)")
    else:
        for src in result["sources"]:
            pages = ", ".join(str(p) for p in src["pages"])
            print(f"  - {src['document']} / {src['section']} / p. {pages}")


if __name__ == "__main__":
    main()
