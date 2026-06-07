# PyInstaller-спека для сборки Search_standarts в один установочный пакет.
#
# Режим: one-folder (НЕ one-file) — с тяжёлым docling/torch так надёжнее и быстрее
# стартует. Результат: dist/Search_standarts/ (папка с Search_standarts.exe внутри).
#
# Сборка на Windows (из корня проекта, активированный venv):
#   1) cd frontend && npm install && npm run build && cd ..   # фронт → frontend/dist
#   2) pip install pyinstaller
#   3) pyinstaller build.spec --noconfirm
#
# Если при ЗАПУСКЕ .exe вылетает "ModuleNotFoundError: X" или "FileNotFoundError"
# на файл пакета — добавь имя пакета в HEAVY_PACKAGES ниже и пересобери.

from PyInstaller.utils.hooks import collect_all

# Пакеты, которые PyInstaller сам не дотягивает целиком (данные + динамические
# импорты). collect_all берёт их код, бинарники и data-файлы (модели, конфиги).
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
    # Собранный фронтенд — FastAPI отдаёт его как статику (см. backend/core/paths.py).
    ("frontend/dist", "frontend/dist"),
    # Предзагруженные модели docling — парсер берёт их отсюда, докачки нет
    # (download_models.py → docling_models/, см. backend/core/paths.py).
    ("docling_models", "docling_models"),
]
binaries = []
hiddenimports = []

for pkg in HEAVY_PACKAGES:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception:
        # Пакета может не быть в окружении (напр. другой OCR-бэкенд) — пропускаем.
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
    # console=True для тестовой сборки: видно логи uvicorn и ошибки.
    # В финальной (после успешного теста) поставим False.
    console=True,
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
