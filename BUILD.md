# Building the distribution (block E)

How to build the runnable application for the end user. The current goal is
a **test build on Windows** to run through the "clean install" scenario.

> The `.exe` can only be built on Windows. On macOS PyInstaller produces a
> macOS binary, not an `.exe`. So the pilot build is done on a Windows PC.

## What the code already provides

- **User data is separated from the binary.** `backend/core/paths.py` puts
  `app.db` and `data/` into a system directory: on Windows —
  `%APPDATA%\Search_standarts\`. Updating the app does not touch the data.
  On a clean machine everything is created from scratch → a new registration
  (by design).
- **FastAPI serves the frontend itself** (`backend/app.py`), no separate Vite
  server needed.
- **The launcher** `run_app.py` — starts the server and opens the browser.
  The build's entry point.
- **Docling models ship inside the distribution** (option 2):
  `download_models.py` downloads them into `docling_models/`, `build.spec`
  packs them into the build, the parser reads them from there. Nothing is
  downloaded on the user's machine.
- **The spec** `build.spec` — one-folder, with the heavy dependencies pulled in.

## Before building: version and variant

Check TWO constants in `backend/version.py`:

- `APP_VERSION` — bump it and duplicate in `installer.iss` (`MyAppVersion`).
- `PUBLIC_BUILD` — build variant: `True` = public (fail-open: an unreachable
  license server never blocks the app), `False` = pilot (offline for more
  than 1 day blocks the UI until the server is reachable).

## Build steps on Windows

From the project root, with the Python venv activated:

```bat
REM 1. Project dependencies (once)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller

REM 2. Download docling models into docling_models\ (once, ~640 MB, internet needed)
python download_models.py

REM 3. Build the frontend (Node.js required)
cd frontend
npm install
npm run build
cd ..

REM 4. Build the application
pyinstaller build.spec --noconfirm
```

Result: `dist\Search_standarts\` — a folder with `Search_standarts.exe`
inside. Run it by double-clicking `Search_standarts.exe` (a console window
with logs opens + the browser at `http://127.0.0.1:8000`).

## Clean-install check

1. Run `Search_standarts.exe`.
2. The registration page must open (empty DB) → register.
3. In "Nastavení" paste your OpenAI key.
4. In "Knihovna" point to a folder with PDFs → "Skenovat" → process 1–2
   documents.
5. Ask a question → check the answer and the clickable source.

The data ends up in `%APPDATA%\Search_standarts\`.

## If the build fails or the .exe does not start

The most common problem — PyInstaller missed dynamic imports of
`docling`/`torch`.

- **`ModuleNotFoundError: X` at startup** → add `X` (the package name) to
  `HEAVY_PACKAGES` in `build.spec` and rebuild (step 4).
- **`FileNotFoundError` for a file inside a package** → same trick: put the
  package into `HEAVY_PACKAGES`.
- **Copy the full error text from the console window** — it drives targeted
  spec fixes.

## Known caveats

- **Size.** The `dist\Search_standarts\` folder is large (torch + docling
  models — ~1 GB) — normal for one-folder with ML.
- **Console.** The test build uses `console=True` (logs and errors visible).
  The final build sets `False` (in `build.spec`).
- **Installer.** Wrapping into a single `Setup.exe` (Inno Setup) — the next
  step after a successful test build.
- **`DOWNLOAD_URL` on the license server** — replace the placeholder with
  the GitHub Release link before handing out the pilot (see
  `PROJECT_STATE.md`, block E).
