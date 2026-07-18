"""
Боевой VL-пайплайн: PDF чертёжных листов → chunks.json + embeddings.json.

Офлайн-инструмент владельца (НЕ часть приложения, в .exe не идёт). Выход —
схема-совместим с текстовым пайплайном, чтобы load_library слил VL в общий пул.

Логика:
  - страницы с текстовым слоем (вводная часть) → текстовые чанки;
  - страницы-картинки (чертёжные листы) → render → OCR + vision-описание;
  - один чанк = один лист; chunk_id проставляется финальным проходом (решение #19);
  - метаданные документа (title/summary) — из текстовой части одним вызовом LLM.

Запуск из корня репозитория:
    python -m vl_pipeline.process <путь_к_pdf> [--id doc_id] [--limit N]

--limit N — обработать только первые N чертёжных листов (для дешёвой проверки).
"""

import argparse
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from backend.core.paths import RAW_DATA_DIR
from indexing.embeddings_index import build_embeddings_index
from jsonio import save_json_atomic
from pdf_processing.parser import make_document_id
from pricing import embedding_cost, model_cost
from vl_pipeline.describe import describe_sheet, extract_document_metadata

DATA_ROOT = RAW_DATA_DIR
RENDER_DPI = 200
# Порог: страница с >= стольких непробельных символов считается текстовой.
# Чертёжные листы дают ~0 символов текстового слоя — разрыв огромный.
TEXT_PAGE_MIN_CHARS = 50


def page_count(pdf_path: Path) -> int:
    """Число страниц PDF через pdfinfo (poppler)."""
    out = subprocess.run(
        ["pdfinfo", str(pdf_path)], capture_output=True, text=True, check=True
    ).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":")[1].strip())
    raise RuntimeError("pdfinfo не вернул число страниц")


def page_texts(pdf_path: Path) -> list[str]:
    """Текстовый слой по страницам: один pdftotext, разбивка по form-feed."""
    out = subprocess.run(
        ["pdftotext", str(pdf_path), "-"], capture_output=True, text=True, check=True
    ).stdout
    return out.split("\f")


def render_page(pdf_path: Path, page: int, pages_dir: Path) -> Path:
    """Рендерит одну страницу PDF в PNG (pdftoppm). Возвращает путь к файлу."""
    prefix = pages_dir / f"p{page:03d}"
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-png",
            "-r",
            str(RENDER_DPI),
            str(pdf_path),
            str(prefix),
        ],
        check=True,
    )
    matches = sorted(pages_dir.glob(f"p{page:03d}*.png"))
    if not matches:
        raise FileNotFoundError(f"pdftoppm не создал PNG для стр. {page}")
    return matches[0]


def ocr_image(image_path: Path) -> str:
    """OCR картинки через Tesseract (чешский). Возвращает текст."""
    out = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", "ces"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.strip()


def first_line(text: str, limit: int = 80) -> str:
    """Первая непустая строка текста (для section_title текстовых чанков)."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:limit]
    return ""


def build_text_chunk(page: int, text: str) -> dict:
    """Чанк текстовой страницы (вводная часть). Без chunk_id — ставим позже."""
    return {
        "parent_section": "",
        "section_number": "",
        "section_title": first_line(text),
        "pages": [page],
        "description": "",
        "ocr_text": "",
        "text": text.strip(),
        "related_blocks": [],
    }


def build_sheet_chunk(page: int, meta: dict, ocr_text: str) -> dict:
    """
    Чанк чертёжного листа. Без chunk_id — ставим позже.

    text = описание + OCR (только содержание); название/серия живут в
    section_title/parent_section — build_searchable_text добавит их к эмбеддингу.
    """
    popis = meta.get("popis_vykresu", "")
    return {
        "parent_section": meta.get("rada", ""),
        "section_number": meta.get("kod", ""),
        "section_title": meta.get("nazev", ""),
        "pages": [page],
        "description": popis,
        "ocr_text": ocr_text,
        "text": f"{popis}\n\n{ocr_text}".strip(),
        "related_blocks": [],
    }


def process(
    pdf_path: Path, doc_id: str | None = None, limit: int | None = None
) -> None:
    """Полный прогон: PDF → chunks.json + embeddings.json в data/raw_data/{doc_id}/."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF не найден: {pdf_path}")

    doc_id = doc_id or make_document_id(pdf_path.stem)
    doc_dir = DATA_ROOT / doc_id
    pages_dir = doc_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    total = page_count(pdf_path)
    texts = page_texts(pdf_path)

    # 1. Классификация страниц
    text_pages: list[tuple[int, str]] = []
    sheet_pages: list[int] = []
    for page in range(1, total + 1):
        text = texts[page - 1] if page - 1 < len(texts) else ""
        if len(text.strip()) >= TEXT_PAGE_MIN_CHARS:
            text_pages.append((page, text))
        else:
            sheet_pages.append(page)

    if limit is not None:
        sheet_pages = sheet_pages[:limit]

    print(f"Страниц всего: {total}")
    print(
        f"  текстовых: {len(text_pages)}, чертёжных листов: {len(sheet_pages)}"
        + (f" (ограничено --limit {limit})" if limit is not None else "")
    )

    # 2. Метаданные документа из вводной части (один текстовый вызов)
    front_text = "\n".join(t for _, t in text_pages)
    meta, m_in, m_out = extract_document_metadata(front_text)
    doc_title = meta["title"]
    doc_summary = meta["summary"]
    llm_cost = model_cost("gpt-5.4-mini", m_in, m_out)
    print(f"Документ: {doc_title or '(без названия)'}")

    # 3. Собираем чанки: сначала текстовые, потом листы (в порядке страниц)
    chunks: list[dict] = [build_text_chunk(p, t) for p, t in text_pages]

    for n, page in enumerate(sheet_pages, 1):
        image_path = render_page(pdf_path, page, pages_dir)
        ocr_text = ocr_image(image_path)
        sheet_meta, s_in, s_out = describe_sheet(image_path)
        llm_cost += model_cost("gpt-5.4-mini", s_in, s_out)
        chunks.append(build_sheet_chunk(page, sheet_meta, ocr_text))
        print(
            f"  лист {n}/{len(sheet_pages)} (стр. {page}): "
            f"{sheet_meta.get('kod', '?')} — OCR {len(ocr_text)} симв"
        )

    # 4. Общие поля + chunk_id финальным проходом (решение #19)
    for i, chunk in enumerate(chunks):
        chunk["document_id"] = doc_id
        chunk["document_title"] = doc_title
        chunk["document_summary"] = doc_summary
        chunk["chunk_id"] = f"{doc_id}_c{i:03d}"

    chunks_path = doc_dir / "chunks.json"
    save_json_atomic(chunks_path, chunks)
    print(f"\nЧанков: {len(chunks)} → {chunks_path}")

    # 5. Эмбеддинги
    print("Строю векторный индекс (OpenAI)...")
    index, tokens = build_embeddings_index(chunks)
    index_path = doc_dir / "embeddings.json"
    save_json_atomic(index_path, index)
    emb_cost = embedding_cost(tokens)
    print(f"Векторов: {len(index['items'])} → {index_path}")

    # 6. Стоимость
    print("\n=== Стоимость ===")
    print(f"  LLM (vision + метаданные): ${llm_cost:.4f}")
    print(f"  Embeddings:                ${emb_cost:.4f}")
    print(f"  ИТОГО:                     ${llm_cost + emb_cost:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="VL-пайплайн (офлайн-инструмент)")
    parser.add_argument("pdf", type=Path, help="путь к VL-PDF")
    parser.add_argument("--id", dest="doc_id", default=None, help="id документа (slug)")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="обработать только первые N листов (для проверки)",
    )
    args = parser.parse_args()
    process(args.pdf, args.doc_id, args.limit)


if __name__ == "__main__":
    main()
