# MAI Assistant — technical overview

User-facing description: [README.md](README.md). This page is about how the
thing is built and why it is built that way.

MAI Assistant is a local-first desktop app that turns a folder of
construction PDFs into a searchable database and answers questions about it
with a citation down to the page. It is written by a bridge engineer learning
software engineering, and piloted daily on real standards and finished bridge
projects.

## The problem

A design office keeps hundreds of PDFs: standards, technical reports,
structural calculations, drawing sets. Full-text search over them fails for
two reasons — the wording of the question rarely matches the wording of the
document, and drawing sheets often carry no text layer at all. Feeding
everything into a chat model is not an alternative either: the whole library
does not fit into a context window, and re-reading it per question is slow
and expensive.

So the retrieval is done by code and the language model is used only for what
it is good at: describing what a drawing shows, and phrasing an answer out of
the fragments that were retrieved.

## Shape of the system

A PyInstaller bundle starts a local FastAPI server on `127.0.0.1` and opens a
React SPA against it. Metadata lives in SQLite (WAL); index artifacts are JSON
files stored next to the user's documents. There is no backend of ours in the
request path — only a small licence and telemetry server, and it is fail-open:
if it is unreachable, the app keeps working.

Because the app runs on the user's machine and talks to the OpenAI API with
the user's own key, there is no per-user inference cost on the author's side,
and no user data on the author's side either.

## Indexing pipeline

```
                    ┌─────────────────────────────────────────────┐
 PDF (document,     │            indexing pipeline                │
  project, drawing) │  parse ──▶ describe ──▶ chunk ──▶ embed      │
 ───────────────────▶  (page     (vision LLM  (by       (OpenAI    │
                    │   router,   for schemes  headings) embed-    │
                    │   Docling,  & drawings)            dings)    │
                    │   OCR)                                       │
                    └──────────────────────────┬──────────────────┘
                                               ▼
                              <folder>/.search_index/{doc}/
                              chunks.json + embeddings.json
```

**Page router** (`pdf_processing/page_router.py`). One pipeline, decided per
page: a page is a drawing if vector geometry dominates (>1000 PATH objects)
or there is no extractable text (<50 characters). Measured on live data:
prose pages reach 575 paths, drawings run 3 200–117 000 — a margin of at
least 7×, frozen by a test.

**Prose pages** go through Docling (a temporary PDF of only the prose pages,
page numbers remapped to the original) and are chunked by level-2 headings;
oversized chunks split by level-3 headings, and as a last resort by
paragraphs at a hard limit of 6 000 characters so nothing is silently
truncated at embedding time. Tables arrive as markdown cell text; a vision
retelling is added on top.

**Drawing pages** get OCR of the whole sheet (RapidOCR — published drawings
often have an empty or broken text layer), plus the text layer, plus a vision
"passport" of the sheet, and become one chunk per page. The division of
labour matters: the vision model supplies semantics only (what kind of sheet,
which object, what is drawn), exact title-block strings come from OCR, and
the design stage is pulled out with a regex — the vision model confuses short
stage codes.

**Money safety** is a design constraint, not an afterthought. Scanning a
folder is free and separate from the paid indexing step; vision descriptions
are checkpointed per page, so a crash or a lost network never re-bills pages
that were already described.

## Answering a question

```
 question ──▶ optional LLM query expansion (synonyms, diacritics)
          ──▶ BM25 + vector search over the selected documents
          ──▶ reciprocal rank fusion ──▶ top chunks
          ──▶ one LLM call with Structured Outputs
          ──▶ answer + sources (document / section / page)
```

The answering model returns only the ids of the chunks it actually used; all
source metadata is assembled from our own data. The model therefore cannot
invent a page number — the worst it can do is cite the wrong fragment, which
the user sees immediately. It is also allowed to answer "not found".

Strong search additionally renders the pages behind the top sources (up to 3,
~2200 px) and passes them as images to the answering model — that is what
makes questions about drawings and table cells work.

## Decisions worth explaining

**Indexes live next to the documents**, in a hidden `.search_index/`
subfolder, not in the app's own storage. That single choice is what turns a
plain company network folder into a shared library: the first machine to
index a folder pays for it, every other machine adopts the finished index for
free when it attaches the same folder. Concurrency is handled by an
`index.lock` file (15-minute TTL with a 5-minute heartbeat), and the folder
passport `meta.json` is created with `O_CREAT|O_EXCL` so two machines racing
on a fresh folder cannot end up with two different folder ids.

**Search is a NumPy matrix scan**, not a vector database. Normalized float32
embeddings sit in RAM as one matrix; a query is one matrix multiply — 11–14 ms
over tens of thousands of chunks. At this scale a vector DB would add an
install, a process and a failure mode without buying anything. BM25 is
rebuilt per query from cached tokens, deliberately: IDF has to reflect the
document filter the user selected.

**Only the expensive artifact is persisted.** `embeddings.json` is written to
disk because it costs money; the BM25 index is rebuilt locally in
milliseconds and never stored.

**`chunk_id` is `{document_id}_c{counter}`**, not the section number.
Standards with annexes repeat section numbers, and the earlier scheme
produced duplicate ids that silently corrupted the index, the rank fusion and
the assembly of sources — the kind of bug that produces plausible wrong
answers rather than a crash.

**User files are never modified.** The app reads PDFs in place and writes
only into its own hidden subfolder.

**Document identity is the file name** (slugged, with Cyrillic
transliterated). A rename means a new document, and moving a library is an
explicit relink in the UI rather than content-hash magic — predictable beats
clever when the wrong guess costs the user money in re-indexing.

**The volume limit is counted in pages, not documents** (3000 in the public
build), and it counts adopted indexes too. A 300-page standard and a one-sheet
drawing load memory very differently, and a limit that ignored free adoption
of a shared folder would not limit memory at all.

## Measured numbers

| What | Measured |
|---|---|
| Vector search | 11–14 ms over 30k chunks |
| BM25 rebuild per query | 1.2 s at 30k chunks (cache is a known fix) |
| Vision description | ~$0.04 per page containing figures or tables |
| Drawing sheet | $0.003–0.004 per sheet |
| Embeddings | $0.00014 per page |
| Normal answer | ~$0.007, ~4 s |
| Strong search | ~$0.036–0.040, 10–20 s |
| Memory | ~140 KB peak per chunk → 3000 pages ≈ 4500 chunks ≈ 630 MB peak |

The memory figure is where the 3000-page cap comes from: the peak (JSON
parsing) is roughly twice the steady state, and it has to stay safe on an
8 GB laptop.

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite (WAL) |
| PDF processing | Docling, pypdfium2, RapidOCR (onnxruntime) |
| Search | rank-bm25, OpenAI `text-embedding-3-large`, NumPy |
| LLM | OpenAI API (user's own key), Structured Outputs |
| Frontend | React, TypeScript, Vite, Tailwind, shadcn/ui |
| Packaging | PyInstaller + Inno Setup (Windows) |
| Quality | pytest (206 tests), ruff, ESLint, GitHub Actions CI |

## Repository layout

```
pipeline/        4 indexing stages: parse → describe → chunk → embed
search/          library loading, hybrid search, query expansion, answering
indexing/        BM25 and embedding index construction
pdf_processing/  page router (prose vs drawing), parser, OCR, vision prompts
backend/         FastAPI app: core (cache, locks, limits) + feature modules
frontend/        React SPA (no router, no state library — deliberately small)
cli/             run the pipeline and ask questions from a terminal
tests/           pytest suite (in-memory SQLite, mocked LLM calls)
```

Modules are organised by task rather than by layer, and every endpoint is a
plain REST + Pydantic call — which makes the API agent-ready without a
dedicated agent layer.

## Running from source

Requires Python 3.12+, Node.js and an OpenAI API key.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cd frontend && npm install && npm run build && cd ..
uvicorn backend.app:app        # → http://127.0.0.1:8000
```

First launch: register → paste your OpenAI key (Settings) → attach a PDF
folder → **Scan** (free) → **Index** (paid). Windows installer build:
[BUILD.md](BUILD.md).

```bash
python -m pytest -q                              # tests
ruff check . && ruff format --check .            # lint
cd frontend && npx eslint src --max-warnings 0   # frontend lint
```

The pipeline also runs headless, which is how it was developed and measured:

```bash
python -m pipeline.parse <pdf>     # PDF → document.json + page screenshots
python -m pipeline.describe <pdf>  # vision LLM → descriptions.json
python -m pipeline.chunk <pdf>     # → chunks.json
python -m pipeline.embed <pdf>     # → embeddings.json
python -m cli.ask                  # question → hybrid search → answer
python -m cli.forecast <path>      # cost forecast without spending anything
```

## Known trade-offs and what is next

- **Retrieval quality is not measured yet.** A small eval (15–20 questions
  with known correct sections) comes before any tuning of chunk boundaries,
  fusion weights or models — tuning without it is guessing.
- **Query expansion is non-deterministic**: reasoning models ignore
  `temperature`. Mitigated in the UI — the rewritten query is shown and can
  be switched off.
- **The library cache reloads fully on any change** (~23 s at 30k chunks).
  Per-document memoization keyed by mtime is the fix; it matters at the design
  ceiling, not at pilot volume.
- **Answers are not streamed.** Structured Outputs returns the JSON as a
  whole, so streaming means splitting text and sources into two messages.
- **An MCP server on top of the search API** is the natural next step — the
  REST layer was built agent-ready from the start.

## License

[PolyForm Internal Use 1.0.0](LICENSE.md).
