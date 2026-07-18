"""Пайплайн обработки документов архива проектов.

Чертёжный лист ("sheet"): страница = один чанк. Текст чанка = vision-описание
(что изображено, какие виды/разрезы/детали, объект из росписки) + текстовый
слой страницы (штамп, примечания — OCR не нужен, текст в PDF уже есть).

Работает на pypdfium2 (рендер + текстовый слой) — без внешних программ,
чтобы работало и из .exe (в отличие от офлайн vl_pipeline на poppler/tesseract).
"""

import json
import logging
from pathlib import Path

import pypdfium2 as pdfium
from sqlalchemy import select

from backend.core import progress
from backend.core.database import SessionLocal
from backend.core.errors import classify_pipeline_error
from backend.core.paths import PROJECTS_DATA_DIR
from backend.modules.projects.models import ProjectDocument
from PIL import Image

from indexing.embeddings_index import build_embeddings_index
from jsonio import save_json_atomic
from pdf_processing.image_description import ask_vision
from pdf_processing.ocr import ocr_image
from pricing import model_cost


logger = logging.getLogger(__name__)

# Длинная сторона рендера листа. Чертёж A1/A0 в полном разрешении — десятки
# мегапикселей; vision всё равно ужимает, поэтому рендерим сразу разумно.
_RENDER_MAX_SIDE_PX = 2200

SHEET_PROMPT = """Jsi expert na stavební a mostní dokumentaci.
Na obrázku je jeden list výkresové dokumentace stavebního projektu.

ÚKOL:
Z razítka (rozpisky) vyčti identifikaci a popiš, co výkres zobrazuje.
Vrať POUZE validní JSON s klíči:
- "objekt": jaký stavební objekt výkres patří (z razítka — např. "SO 202 most
  přes údolí, dálnice D7" nebo "protihluková stěna"); pokud nelze určit, ""
- "cislo": číslo výkresu z razítka (např. "202.211"); pokud nelze, ""
- "nazev": název výkresu z razítka
- "popis": 3-6 vět — co výkres zobrazuje: jaký konstrukční prvek, jaké pohledy,
  řezy a detaily obsahuje (např. půdorys, podélný řez, řez A-A, detail kotvení),
  jaké tabulky (výkaz výztuže, materiálů). Popisuj POUZE to, co je skutečně
  vidět. NEUVÁDĚJ rozměry ani odkazy na jiné výkresy.

Textové bloky (poznámky, legendy) NEPŘEPISUJ — text se získává zvlášť.
Vše v češtině. Nepřidávej žádný text mimo JSON.
"""


def _parse_json_object(raw: str) -> dict:
    """Разбирает JSON-объект из ответа модели, чистя markdown-обёртку."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def render_page_png(doc: pdfium.PdfDocument, page_index: int, out_path: Path) -> Path:
    """Рендерит страницу PDF в PNG с ограничением длинной стороны."""
    page = doc[page_index]
    width, height = page.get_size()
    scale = _RENDER_MAX_SIDE_PX / max(width, height)
    bitmap = page.render(scale=scale)
    image = bitmap.to_pil()
    image.save(out_path)
    return out_path


def describe_sheet(image_path: Path, model: str) -> tuple[dict, float]:
    """Vision-описание листа. Возвращает (meta, стоимость вызова $).

    meta — словарь objekt/cislo/nazev/popis. Пустой ответ (битый JSON)
    повторяем один раз — разовые сбои vision самочинятся.
    """
    meta: dict = {}
    cost = 0.0
    for _ in range(2):
        raw, p_tokens, c_tokens = ask_vision(image_path, SHEET_PROMPT, model)
        cost += model_cost(model, p_tokens, c_tokens)
        meta = _parse_json_object(raw)
        if meta.get("nazev") or meta.get("popis"):
            break
    return meta, cost


def build_sheet_chunk(
    page_number: int,
    meta: dict,
    layer_text: str,
    ocr_text: str,
    parent_section: str,
) -> dict:
    """Чанк одного листа. Без chunk_id — проставляется финальным проходом (#19).

    text = vision-описание + текстовый слой + OCR; объект из росписки — в
    description, название листа — в section_title (уйдёт в «шапку» при
    индексации). OCR добирает текст, впечатанный в чертёж (метки, примечания,
    ссылки на нормы), которого нет в текстовом слое.
    """
    popis = meta.get("popis", "")
    objekt = meta.get("objekt", "")
    description = f"{objekt}. {popis}".strip(". ") if objekt else popis
    text_parts = [p for p in (description, layer_text, ocr_text) if p and p.strip()]
    return {
        "parent_section": parent_section,
        "section_number": meta.get("cislo", ""),
        "section_title": meta.get("nazev", ""),
        "pages": [page_number],
        "description": description,
        "ocr_text": ocr_text,
        "text": "\n\n".join(text_parts),
        "related_blocks": [],
    }


def process_sheet_document(
    slug: str,
    pdf_path: Path,
    project: str,
    relative_path: str,
    vision_model: str,
    describe_images: bool = True,
) -> tuple[list[dict], float]:
    """Обрабатывает чертёжный документ: каждая страница = чанк-лист.

    Пишет pages/*.png и chunks.json в PROJECTS_DATA_DIR/{slug}/.
    Возвращает (чанки, стоимость LLM $). Эмбеддинги строит вызывающий.
    describe_images=False → режим «Без LLM»: vision пропускаем, чанк листа =
    текстовый слой + OCR (бесплатно).
    """
    doc_dir = PROJECTS_DATA_DIR / slug
    pages_dir = doc_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    # Раздел проекта = подпапки между проектом и файлом (может быть пусто).
    parent_section = str(Path(relative_path).parent.relative_to(project))
    if parent_section == ".":
        parent_section = ""

    chunks: list[dict] = []
    total_cost = 0.0
    doc = pdfium.PdfDocument(pdf_path)
    try:
        total_pages = len(doc)
        for i in range(total_pages):
            page_number = i + 1
            suffix = "vision" if describe_images else "OCR"
            progress.set_progress(slug, f"list {page_number}/{total_pages} ({suffix})…")
            image_path = render_page_png(
                doc, i, pages_dir / f"page_{page_number:03d}.png"
            )
            layer_text = doc[i].get_textpage().get_text_range().strip()
            ocr_text = ocr_image(Image.open(image_path))
            if describe_images:
                meta, cost = describe_sheet(image_path, vision_model)
            else:
                meta, cost = {}, 0.0
            total_cost += cost
            chunks.append(
                build_sheet_chunk(
                    page_number, meta, layer_text, ocr_text, parent_section
                )
            )
    finally:
        doc.close()

    # Метаданные документа: название из имени файла (там номер и суть листа),
    # summary из росписки первого листа — объект + название (контекст объекта
    # попадает в «шапку» каждого чанка при индексации).
    first_meta_description = chunks[0]["description"] if chunks else ""
    doc_title = f"{project} — {Path(relative_path).stem}"
    for i, chunk in enumerate(chunks):
        chunk["document_id"] = slug
        chunk["document_title"] = doc_title
        chunk["document_summary"] = first_meta_description
        chunk["chunk_id"] = f"{slug}_c{i:03d}"

    chunks_path = doc_dir / "chunks.json"
    save_json_atomic(chunks_path, chunks)
    return chunks, total_cost


def _prefix_project_context(doc_dir: Path, project: str) -> None:
    """Добавляет проект в document_title всех чанков (перед эмбеддингом).

    document_title входит в «шапку» чанка при индексации — так чанк
    «zatížení větrem» из статики ищется в контексте своего проекта/объекта.
    """
    chunks_path = doc_dir / "chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    for chunk in chunks:
        title = chunk.get("document_title", "")
        if not title.startswith(project):
            chunk["document_title"] = f"{project} — {title}" if title else project
    save_json_atomic(chunks_path, chunks)


def process_text_document(
    slug: str,
    pdf_path: Path,
    project: str,
    vision_model: str,
    describe_images: bool = True,
) -> None:
    """Текстовый документ архива (TZ, статика): существующий пайплайн норм.

    Docling → vision-описания картинок (модели/эпюры в статике — тоже сюда)
    → нарезка по заголовкам → проект в шапку → эмбеддинги.
    Всё пишется в PROJECTS_DATA_DIR/{slug}/, id чанков — от нашего slug.
    describe_images=False → режим «Без LLM»: vision пропускается.
    """
    # Lazy import — Docling тяжёлый, грузим только при реальной обработке
    # (та же причина, что в documents/pipeline.py).
    import main as parser_step
    import describe as describe_step
    import chunk as chunk_step
    import index as index_step

    doc_dir = PROJECTS_DATA_DIR / slug
    progress.set_progress(slug, "čtení PDF…")
    parser_step.process(slug, pdf_path=str(pdf_path), doc_dir=doc_dir, document_id=slug)
    progress.set_progress(slug, "popis obrázků…")
    describe_step.process(
        slug,
        vision_model=vision_model,
        doc_dir=doc_dir,
        pdf_path=str(pdf_path),
        describe_images=describe_images,
        on_progress=lambda done, total: progress.set_progress(
            slug, f"popis obrázků: strana {done}/{total}"
        ),
    )
    progress.set_progress(slug, "řezání na části…")
    chunk_step.process(slug, doc_dir=doc_dir)
    _prefix_project_context(doc_dir, project)
    progress.set_progress(slug, "indexace…")
    index_step.process(slug, doc_dir=doc_dir)


def run_project_pipeline(slug: str, pdf_path: str) -> None:
    """Полная обработка одного документа архива (вызов из ThreadPoolExecutor).

    Статусы: processing → ready | error (+ текст ошибки в error).
    Сессию БД открываем сами — FastAPI-зависимости в фоновом потоке не работают.
    """
    from backend.modules.settings import service as settings_service

    db = SessionLocal()
    try:
        doc = db.scalar(select(ProjectDocument).where(ProjectDocument.slug == slug))
        if doc is None:
            logger.error("run_project_pipeline: slug %s не найден в БД", slug)
            return
        doc.status = "processing"
        db.commit()

        vision_model = settings_service.get_vision_model(db)
        describe_images = settings_service.get_describe_images(db)
        try:
            if doc.doc_type == "sheet":
                chunks, _ = process_sheet_document(
                    slug=slug,
                    pdf_path=Path(pdf_path),
                    project=doc.project,
                    relative_path=doc.relative_path,
                    vision_model=vision_model,
                    describe_images=describe_images,
                )
                index, _ = build_embeddings_index(chunks)
                index_path = PROJECTS_DATA_DIR / slug / "embeddings.json"
                save_json_atomic(index_path, index)
            else:
                process_text_document(
                    slug=slug,
                    pdf_path=Path(pdf_path),
                    project=doc.project,
                    vision_model=vision_model,
                    describe_images=describe_images,
                )
        except Exception as exc:
            logger.exception("Пайплайн архива для %s упал", slug)
            doc.status = "error"
            doc.error = classify_pipeline_error(exc)
            db.commit()
            return

        doc.status = "ready"
        doc.error = None
        db.commit()

        # Новые чанки/эмбеддинги на диске — сбрасываем кеш, чтобы следующий
        # вопрос увидел свежий документ (пул архива влит в общий кеш поиска).
        from backend.core import library_cache

        library_cache.invalidate()
    finally:
        progress.clear_progress(slug)
        db.close()
