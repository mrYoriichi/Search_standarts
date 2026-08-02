"""Pre-download docling models into the project (for bundling).

Run ONCE at build time (see BUILD.md). Downloads the PDF-parsing models
into docling_models/ so PyInstaller ships them inside the .exe and the
user never downloads anything.

    python download_models.py
"""

from pathlib import Path

from docling.utils.model_downloader import download_models

OUTPUT_DIR = Path("docling_models")


def main() -> None:
    print(f"Downloading docling models into {OUTPUT_DIR.resolve()} ...")
    # Default flags (layout + tableformer + rapidocr + code/picture) are
    # exactly what our PDF pipeline uses.
    download_models(output_dir=OUTPUT_DIR, progress=True)
    print("Done. Models are in docling_models/")


if __name__ == "__main__":
    main()
