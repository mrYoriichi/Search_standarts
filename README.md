# MAI Assistant

[![CI](https://github.com/mrYoriichi/Search_standarts/actions/workflows/ci.yml/badge.svg)](https://github.com/mrYoriichi/Search_standarts/actions/workflows/ci.yml)

**English** | [Čeština](README.cs.md) | [Deutsch](README.de.md)

Ask questions about construction standards in plain language — get a short
answer with a clickable reference to the exact document, section and page.
No more scrolling through 300-page PDFs.

Local-first desktop app for civil engineers working with Czech and European
norms (ČSN, Eurocode) and their own project archives. Built by a bridge
engineer; piloted daily by a real engineering office.

**Your documents never leave your computer.** The index and the database
live on your machine; there is no cloud storage and nobody — including the
author — ever sees your files or questions. The only outbound traffic is
OpenAI API calls made with your own key.

![Search page](docs/screenshots/search.png)

## Features

- **Ask in any language** — the answer cites the source inline and links to
  the exact page in the original PDF.
- **Hybrid search** — BM25 (exact codes like "ČSN 73 6201") + OpenAI
  embeddings (meaning), merged by reciprocal rank fusion.
- **Understands drawings** — a per-page router sends prose through
  [Docling](https://github.com/docling-project/docling) and drawings
  through OCR + a vision-LLM description of the sheet.
- **Project archive** — search your finished projects (reports,
  calculations, drawing sets) alongside the norms.
- **Shared team libraries** — one colleague indexes a network folder,
  everyone else adopts the ready index for free; a lock file coordinates
  machines.
- **Strong search** — attaches page snapshots to the answering LLM for
  hard questions about drawings and tables.
- **3 interface languages** (EN/CS/DE) + separate answer language.
- **Local-first** — index, database and documents stay on your machine.

![Library page](docs/screenshots/library.png)
![Project archive](docs/screenshots/archive.png)

## OpenAI API key

The app runs on your own OpenAI key — you pay OpenAI directly, the app
adds nothing on top.

1. Create an account at [platform.openai.com](https://platform.openai.com).
2. **Billing → Add credits** — prepay a small amount (minimum $5 goes a
   long way).
3. **API keys → Create new secret key** — copy the `sk-…` key.
4. Paste it in the app under **Settings → OpenAI key**. It is stored only
   on your computer.

Measured costs with the default model:

| Action | Cost |
|---|---|
| Index a text norm | ~$0.04 per page with schemes, less for plain text |
| Index a drawing sheet | < $0.01 |
| One question | < $0.01 |
| One strong-search question | ~$0.04 |

## How it works

```
                    ┌─────────────────────────────────────────────┐
 PDF (norm/project) │            indexing pipeline                │
 ───────────────────▶  parse ──▶ describe ──▶ chunk ──▶ embed     │
                    │  (Docling,  (vision LLM  (by       (OpenAI  │
                    │   OCR,       for schemes  headings) embed-  │
                    │   page       & drawings)           dings)   │
                    │   router)                                   │
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

Design decisions worth noting:

- **Indexes live next to the documents** (hidden `.search_index/`
  subfolder) — that is what turns a plain network folder into a shared
  library. User files are never modified.
- **Search is a NumPy matrix scan** over normalized embeddings in RAM
  (~10 ms for tens of thousands of chunks) — no vector DB needed at this
  scale. BM25 is rebuilt per query from cached tokens so IDF respects the
  document filter.
- **One LLM call per answer** with structured output: the model returns
  only the ids of chunks it used; source metadata is assembled from our
  own data.
- **Money-safety** — scanning is free and separate from paid indexing;
  vision progress is checkpointed per page so a crash never re-bills.

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite (WAL) |
| PDF processing | Docling, pypdfium2, RapidOCR (onnxruntime) |
| Search | rank-bm25, OpenAI `text-embedding-3-large`, NumPy |
| LLM | OpenAI API (user's own key), Structured Outputs |
| Frontend | React, TypeScript, Vite, Tailwind, shadcn/ui |
| Packaging | PyInstaller + Inno Setup (Windows) |
| Quality | pytest (194 tests), ruff, ESLint, GitHub Actions CI |

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

## Privacy and telemetry

- Documents, index and database never leave your machine. Text fragments
  and page images go to the **OpenAI API** only, billed to your key.
- Free registration is required; the app sends **anonymous telemetry**
  (event counts, timings, costs, error types — never question texts or
  file names).
- Fail-open: an unreachable license server never blocks the app.
- The public build indexes up to **3000 pages** (RAM-driven safety limit).

## Status

Piloted in a bridge-engineering office (Czech Republic) on real
ČSN/Eurocode norms and finished bridge projects. Public free Windows
build in preparation. Next: retrieval-quality eval, an MCP server on top
of the search API — the REST API is agent-ready by design.

## License

[PolyForm Internal Use 1.0.0](LICENSE.md) — free to use inside your
organization, commercial companies included; selling the software or
offering it to third parties as a product/service stays with the author.
