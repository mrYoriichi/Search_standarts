# MAI Assistant - technical overview

A local-first desktop RAG application. It turns folders of construction PDFs
into a searchable database and answers questions about them with a citation
down to the page.

User-facing description: [README.md](README.md).

## The problem

Search across a database of PDF documentation - standards, technical reports,
structural calculations, drawing sets - with a pointer to the source of every
answer.

These PDFs are not plain text: inside them are scans, construction schemes
and tables. Hence four requirements:

- find an **exact designation** - a standard code, a sheet number, a term;
- find by **meaning**, when the question is worded nothing like the document;
- search **drawings**, not only prose;
- keep everything **confidential** - no handing documents and finished
  projects to a third party, no uploading them to somebody else's server.

The requirements come from the daily work of the author and colleagues.

## The solution

A RAG pipeline that runs entirely on the user's machine - that is what
provides the confidentiality.

Retrieval is hybrid: embeddings for meaning, BM25 for exact terms and codes,
merged by reciprocal rank fusion. The language model never does the
searching. It has exactly two jobs: describe drawings and schemes while
indexing, and phrase the final answer out of the fragments retrieval found.

## What makes this RAG different

**Indexes live next to the documents, not inside the app.** Artifacts go into
a hidden `.search_index/` subfolder of the user's own folder. That single
choice turns a company network drive into a shared library: the first machine
to index it pays, every other machine attaches the same folder and adopts the
finished index for free. An `index.lock` file (15-minute TTL, 5-minute
heartbeat) keeps two people from indexing the same folder at once.

**Drawings are first-class documents.** A per-page router decides how each
page is processed, so a single PDF can be part prose and part drawing sheets.
Sheets are read by OCR and described by a vision model - what is drawn, which
object, which design stage - and that description is what makes them findable.

**Every fragment carries its context.** A fragment is not a bare slice of
text: it is indexed together with the document title and the headings above
it, so it stays findable even when the wording only appears in the heading.
See [What one fragment carries](#what-one-fragment-carries).

**The model cannot invent a citation.** The answering call uses Structured
Outputs and returns only the ids of the fragments it used; every source
line - document, section, page - is assembled from our own data, and the page
number is a link that opens the original PDF at that page.

**Retrieval respects the user's filter.** BM25 is rebuilt per query from
cached tokens, deliberately, so that IDF reflects the subset of documents the
user selected instead of the whole corpus.

**Strong search re-reads the pages.** For hard questions the pages behind the
top sources are rendered (up to 3, ~2200 px) and passed to the answering model
as images - that is what answers "what is drawn on this sheet" and "which
dimension does this table give".

**No vector database.** Normalized float32 embeddings sit in RAM as one NumPy
matrix and a query is a single matrix multiply: 11–14 ms over tens of
thousands of fragments. Nothing to install, nothing to run, nothing to
break - which matters when the product is a desktop installer, not a service.

**Spending is a design constraint.** Scanning a folder is free and separate
from the paid indexing step; vision descriptions are checkpointed per page so
a crash never pays twice; a CLI forecast estimates the cost of a folder
before any money is spent.

**The corpus is multilingual by default.** Question, documents and answer can
each be in a different language; the answer language is a separate setting,
and query expansion uses the languages actually present in the filtered
corpus.

**User files are never modified.** PDFs are read in place; the app writes
only into its own hidden subfolder.

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

### Page router

One pipeline, one decision per page. A page is a **drawing** if vector
geometry dominates (>1000 PATH objects) or there is no extractable text
(<50 characters); otherwise it is **prose**.

Measured on live data: prose pages reach 575 paths, drawings run
3 200–117 000. A margin of at least 7×, frozen by a test.

### Prose pages

- Docling parses only the prose pages - they are collected into a temporary
  PDF, and page numbers are remapped back to the original.
- Chunking follows level-2 headings; oversized chunks split by level-3
  headings, and as a last resort by paragraphs at a hard limit of 6 000
  characters, so nothing is silently truncated at embedding time.
- Text before the first numbered heading (title page, foreword) becomes its
  own fragment instead of falling out of the index.
- Tables arrive as markdown cell text, with a vision retelling on top.

### Drawing pages

- OCR of the whole sheet (RapidOCR) - published drawings often have an empty
  or broken text layer.
- Plus whatever text layer there is.
- Plus a vision "passport" of the sheet.
- The result is one fragment per page.

The division of labour matters: the vision model supplies **semantics only**
(what kind of sheet, which object, what is drawn), exact title-block strings
come from **OCR**, and the design stage is extracted with a **regex** -
vision confuses the short stage codes.

## What one fragment carries

Retrieval quality is decided here, before any search happens. A fragment is
stored - and indexed - with its context around it:

- **Document title**, read by the vision model off the first page. Not the
  file name: `SDS_PK_2025.pdf` is useless to a vector, the real title of the
  document is not.
- **Parent section and section title** - the headings the fragment sits
  under.
- **The text itself**, with descriptions of schemes and tables merged into it
  inline, marked `[SCHÉMA: …]` and `[TABULKA: …]`.
- **Page numbers**, which later become the clickable citation.
- For the project archive, the **project name** is prefixed into the document
  title of every fragment, so a sheet knows which project it belongs to.

The header is not decoration: the text that gets embedded, and the text that
BM25 tokenizes, is `document title + parent section + section title + body` -
identical in both indexes. A section called "Založení propustků" therefore
answers a question about culvert foundations even if those words never appear
in its body.

## Answering a question

```
 question ──▶ optional LLM query expansion (synonyms, diacritics)
          ──▶ BM25 + vector search over the selected documents
          ──▶ reciprocal rank fusion ──▶ top fragments
          ──▶ one LLM call with Structured Outputs
          ──▶ answer + sources (document / section / page)
```

One paid call per answer. The model is allowed to say "not found", and it
filters the fragment ids itself, so an answer never cites material it did not
use. Fragments it judged relevant but did not use come back separately, as
"related".

## Why it is built this way

**`chunk_id` is `{document_id}_c{counter}`**, not the section number.
Standards with annexes repeat section numbers, and the earlier scheme produced
duplicate ids that silently corrupted the index, the rank fusion and the
assembly of sources - the kind of bug that yields plausible wrong answers
instead of a crash.

**Document identity is the file name** (slugged, Cyrillic transliterated).
A rename means a new document, and moving a library is an explicit relink in
the UI rather than content-hash magic. Predictable beats clever when a wrong
guess costs the user money in re-indexing.

**Only the expensive artifact is persisted.** `embeddings.json` is written to
disk because it costs money; the BM25 index is rebuilt locally in
milliseconds and never stored.

**The folder passport is created with `O_CREAT|O_EXCL`.** Two machines
starting on the same fresh network folder would otherwise end up with two
different folder ids, and every document in it would be indexed twice.

**The volume limit is counted in pages, not documents**, and adopted indexes
count towards it. A 300-page standard and a one-sheet drawing load memory very
differently, and a limit that ignored the free adoption of a shared folder
would not limit memory at all.

**No server of ours is in the request path.** The app talks to the OpenAI API
directly with the user's key; the only backend is a small licence and
telemetry service, and it is fail-open - if it is unreachable, the app keeps
working.

## Measured numbers

| What | Measured |
|---|---|
| Vector search | 11–14 ms over 30k fragments |
| Vision description | ~$0.04 per page containing figures or tables |
| Drawing sheet | $0.003–0.004 per sheet |
| Embeddings | $0.00014 per page |
| Normal answer | ~$0.007, ~4 s |
| Strong search | ~$0.036–0.040, 10–20 s |
| Memory | ~140 KB peak per fragment while loading, ~76 KB steady |

The memory figure is where the page cap of the public build comes from:
5000 pages ≈ 7500 fragments ≈ ~1 GB peak and ~570 MB steady. The peak (JSON
parsing) is roughly twice the steady state, so the cap is what keeps the app
inside a normal laptop.

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
frontend/        React SPA (no router, no state library - deliberately small)
cli/             run the pipeline and ask questions from a terminal
tests/           pytest suite (in-memory SQLite, mocked LLM calls)
```

Modules are organised by task rather than by layer, and every endpoint is
plain REST + Pydantic - which makes the API agent-ready without a dedicated
agent layer.

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

## License

[PolyForm Internal Use 1.0.0](LICENSE.md).
