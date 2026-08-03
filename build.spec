# PyInstaller spec for packaging Search_standarts into one install bundle.
#
# Mode: one-folder (NOT one-file) — with heavy docling/torch it is more
# reliable and starts faster. Result: dist/Search_standarts/ (a folder with
# Search_standarts.exe inside).
#
# Build on Windows (from the project root, venv activated):
#   1) cd frontend && npm install && npm run build && cd ..   # -> frontend/dist
#   2) pip install pyinstaller
#   3) pyinstaller build.spec --noconfirm
#
# If RUNNING the .exe throws "ModuleNotFoundError: X" or "FileNotFoundError"
# for a package file — add the package name to HEAVY_PACKAGES and rebuild.

from PyInstaller.utils.hooks import collect_all

# Packages PyInstaller cannot pull in completely on its own (data files +
# dynamic imports). collect_all takes their code, binaries and data files
# (models, configs).
HEAVY_PACKAGES = [
    "docling",
    "docling_core",
    "docling_ibm_models",
    "docling_parse",
    "transformers",
    "torch",
    "tiktoken",
    "tiktoken_ext",
    "rank_bm25",
    "uvicorn",
    "rapidocr",
    "rapidocr_onnxruntime",
    "onnxruntime",
]

datas = [
    # The built frontend — FastAPI serves it as statics (see backend/core/paths.py).
    ("frontend/dist", "frontend/dist"),
    # Pre-downloaded docling models — the parser reads them from here, no
    # runtime download (download_models.py -> docling_models/, see
    # backend/core/paths.py).
    ("docling_models", "docling_models"),
]
binaries = []
hiddenimports = []

for pkg in HEAVY_PACKAGES:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception:
        # The package may be absent from the env (e.g. another OCR backend) — skip.
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden


a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Search_standarts",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=False for release: the user gets no black console window.
    # For build debugging temporarily set True (uvicorn logs and errors visible).
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Search_standarts",
)
