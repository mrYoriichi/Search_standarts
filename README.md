# MAI Assistant

[![CI](https://github.com/mrYoriichi/Search_standarts/actions/workflows/ci.yml/badge.svg)](https://github.com/mrYoriichi/Search_standarts/actions/workflows/ci.yml)

Ask questions about construction standards in plain language — get a short
answer with a clickable reference to the exact document, section and page.
No more scrolling through 300-page PDFs.

A local-first desktop app for civil engineers working with Czech and
European construction norms (ČSN, Eurocode, ministry guidelines) and their
own project archives. Built by a bridge engineer as a learning project;
piloted daily by a real engineering office.

![Search page](docs/screenshots/search.png)

## What it does

- **Natural-language search over your PDF library.** Ask in any language;
  the answer cites the source inline and links straight to the page in the
  original PDF.
- **Hybrid retrieval.** BM25 keyword search (exact codes and terms like
  "ČSN 73 6201") combined with OpenAI embeddings (meaning), merged via
  reciprocal rank fusion. Pick hybrid / semantic / keyword per question.
- **Understands drawings, not just text.** A per-page router classifies
  every page: prose goes through [Docling](https://github.com/docling-project/docling)
  layout parsing, drawings go through OCR (RapidOCR) plus a vision-LLM
  "passport" of the sheet (what is drawn, which stage, which object).
- **Project archive.** Attach folders of finished projects (technical
  reports, structural calculations, drawing sets) and search your own
  engineering history alongside the norms.
- **Shared team libraries.** Point the app at a network folder: the first
  colleague indexes a document, everyone else adopts the ready-made index
  for free. A lock file coordinates concurrent indexing between machines.
- **Strong search mode.** For hard questions about drawings and tables the
  app attaches page snapshots of the top sources to the answering LLM, so
  it can read dimensions the OCR missed.
- **Three interface languages** (English, Czech, German) and a separate
  answer-language setting — read a Czech norm, get the answer in English.
- **Local-first.** The index, the database and your documents stay on your
  machine. The only outbound calls are OpenAI API requests made with your
  own API key.

![Library page](docs/screenshots/library.png)
![Project archive](docs/screenshots/archive.png)

## How it works

```
                    ┌─────────────────────────────────────────────┐
 PDF (norm/project) │            indexing pipeline                │
 ───────────────────▶  parse ──▶ describe ──▶ chunk ──▶ embed     │
                    │  (Docling,  (vision LLM  (by       (OpenAI  │
                    │   OCR,       for schemes  headings) embed-  │
                    │   page       & drawings)           dings)   │
                    └──────────────────────────┬──────────────────┘
                                               ▼
                              <folder>/.search_index/{doc}/
                              chunks.json + embeddings.json
                                               │
                    ┌──────────────────────────▼──────────────────┐
 question ──────────▶  BM25 + vector search (NumPy, in-RAM cache) │
                    │  → RRF merge → top chunks → answer LLM      │
                    │  → answer + cited sources (doc/section/page)│
                    └─────────────────────────────────────────────┘
```

Key design decisions:

- **Indexes live next to the documents** in a hidden `.search_index/`
  subfolder — that is what makes a plain network folder a shared library.
  The app never modifies user files; it only writes inside its own
  subfolder.
- **Search is a NumPy matrix scan** over normalized embeddings held in
  RAM (~10 ms for tens of thousands of chunks) — no vector database
  needed at this scale. BM25 is rebuilt per query from cached tokens so
  IDF respects the active document filter.
- **One LLM call per answer** with structured output: the model returns
  the answer text plus the ids of chunks it actually used; source metadata
  is assembled from our own data, never trusted to the model.
- **Money-safety everywhere.** Scanning is free and separate from paid
  indexing; vision progress is checkpointed per page so a crash never
  re-bills; adoption re-checks before every paid run.

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite (WAL) |
| PDF processing | Docling, pypdfium2, RapidOCR (onnxruntime) |
| Search | rank-bm25, OpenAI `text-embedding-3-large`, NumPy |
| LLM | OpenAI API (user's own key), Structured Outputs |
| Frontend | React, TypeScript, Vite, Tailwind, shadcn/ui |
| Packaging | PyInstaller one-folder + Inno Setup (Windows) |
| Quality | pytest (194 tests), ruff, ESLint, GitHub Actions CI |

## Repository layout

```
pipeline/        4 indexing stages: parse → describe → chunk → embed
search/          library loading, hybrid search, query expansion, answering
indexing/        BM25 and embedding index construction
pdf_processing/  page router (prose vs drawing), parser, OCR, vision prompts
backend/         FastAPI app: core (cache, locks, limits) + feature modules
                 (auth, documents, library, projects, queries, settings)
frontend/        React SPA (no router, no state library — deliberately small)
cli/             run the pipeline and ask questions from a terminal
tests/           pytest suite (in-memory SQLite, mocked LLM calls)
```

## Running from source

Requires Python 3.12+, Node.js, and an OpenAI API key.

```bash
# backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# frontend
cd frontend && npm install && npm run build && cd ..

# run (serves the built frontend at http://127.0.0.1:8000)
uvicorn backend.app:app
```

On first launch the app asks you to register and to paste your OpenAI key
(Settings). Then attach a folder with PDFs, hit **Scan** (free), review the
list and hit **Index** (paid: a typical text norm costs cents to index,
vision-heavy drawing sets a bit more — measured ~$0.003–0.004 per drawing
sheet with the default model).

The Windows installer build is documented in [BUILD.md](BUILD.md).

Tests and linters:

```bash
python -m pytest -q
ruff check . && ruff format --check .
cd frontend && npx eslint src --max-warnings 0
```

## Privacy and telemetry, honestly

- Your documents, index and database never leave your machine. Text
  fragments and page images are sent to the **OpenAI API** during indexing
  and answering, billed to **your** key under OpenAI's API terms.
- The app requires a free registration and sends **anonymous usage
  telemetry** to the author's license server: event counts (app started,
  document indexed, question asked), timings, costs and error types —
  **never** question texts, answers or file names. This is what lets a
  solo developer see that the app works in the field.
- The public build is fail-open: if the license server is unreachable,
  the app keeps working. Only an explicit revocation blocks access.
- The public build indexes up to **3000 pages** (library + archive
  combined) — a RAM-driven safety limit measured so the app stays fast on
  an ordinary laptop.

## Status

The app is piloted in a bridge-engineering office (Czech Republic) on
real ČSN/Eurocode norms and finished bridge projects. The public free
Windows build is in preparation. Roadmap highlights: retrieval quality
eval, an MCP server on top of the search API, and an agent that uses the
same REST endpoints as the UI — the API is agent-ready by design.

## License

[PolyForm Noncommercial 1.0.0](LICENSE.md) — you are welcome to read,
learn from and use this software for any noncommercial purpose;
commercial use rights stay with the author.
