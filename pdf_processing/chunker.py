"""
Нарезка структурированного документа (document.json) на смысловые чанки.

Чанк — это один раздел нормы (заголовок 2-го уровня и его содержимое),
обогащённый контекстом: название документа, краткое описание,
родительский раздел. Большие чанки дробятся по заголовкам уровня 3,
а при их отсутствии — по границам абзацев.

Главная функция: build_chunks(document) -> list[dict]
"""

import re

from pdf_processing.drawing import extract_stupen

# Типы блоков-мусора, которые не идут в чанки.
SKIP_BLOCK_TYPES = {"document_index", "header", "footer"}

# Фразы-маркеры нетехнического контента (логотипы, штампы). Модель не всегда
# пишет каноническую метку дословно (например «Logo... bez technického obsahu»),
# поэтому матчим по подстроке без учёта регистра, а не точным равенством.
NON_TECHNICAL_SUBSTRINGS = (
    "není technický obsah",  # каноническая метка из промпта
    "bez technického",  # частая перефразировка модели
)

# Слово 'logo' проверяем отдельно — как целое слово (\b), а не подстроку:
# подстрока ловила бы инфлектированные 'katalogové', 'dialogový' и т.п.
_LOGO_WORD = re.compile(r"\blogo\b")

# Порог: чанки длиннее этого числа символов — кандидаты на дробление.
MAX_CHUNK_CHARS = 2500

# Жёсткий предел для частей без заголовка-границы: если текст между заголовками
# ур.3 разросся больше этого, режем по абзацу принудительно — иначе раздел со
# скудными подзаголовками упёрся бы в лимит эмбеддинга (~8000 токенов). С запасом
# под колебания «символов на токен».
HARD_SPLIT_CHARS = 6000


def is_block_useful(block: dict) -> bool:
    """
    Решает, годится ли блок для попадания в чанк.
    Отсекает мусор: оглавление, колонтитулы, логотипы, пустые блоки.
    """
    block_type = block["type"]

    if block_type in SKIP_BLOCK_TYPES:
        return False

    if block_type in ("figure", "table"):
        description = block.get("description")
        if not description:
            # Таблица без vision-описания, но с текстом ячеек (markdown из
            # Docling) — полезна: точные значения ищутся по тексту. Так
            # таблицы не выпадают из поиска в режиме «Без LLM».
            if block_type == "table":
                text = block.get("text")
                return bool(text and text.strip())
            return False
        low = description.lower()
        if any(marker in low for marker in NON_TECHNICAL_SUBSTRINGS):
            return False
        if _LOGO_WORD.search(low):
            return False
        return True

    text = block.get("text")
    return bool(text and text.strip())


def build_chunk_text(blocks: list[dict]) -> str:
    """
    Собирает текст чанка из списка блоков.
    Описания figure/table вливаются с пометкой [SCHÉMA: ...] / [TABULKA: ...].
    Принимает только полезные блоки (отфильтрованные через is_block_useful).
    """
    pieces = []
    for block in blocks:
        block_type = block["type"]
        if block_type == "figure":
            pieces.append(f"[SCHÉMA: {block['description']}]")
        elif block_type == "table":
            # Пересказ vision (тема таблицы) + сам текст ячеек (точные
            # значения) — что из этого есть. Старые индексы без text и
            # режим «Без LLM» без description работают одинаково честно.
            description = block.get("description")
            text = (block.get("text") or "").strip()
            if description and text:
                pieces.append(f"[TABULKA: {description}]\n{text}")
            elif description:
                pieces.append(f"[TABULKA: {description}]")
            else:
                pieces.append(f"[TABULKA]\n{text}")
        else:
            pieces.append(block["text"].strip())
    return "\n\n".join(pieces)


def page_of_block(block: dict) -> int:
    """
    Достаёт номер страницы из block_id.
    'p12_b03' -> 12
    """
    # block_id вида 'p12_b03': берём часть до '_', отрезаем 'p', переводим в int
    return int(block["block_id"].split("_")[0][1:])


def split_large_chunk(chunk: dict) -> list[dict]:
    """
    Дробит большой чанк на под-чанки, чтобы они влезали в лимит эмбеддинга.

    Правила:
      - чанк короче порога -> возвращаем как есть;
      - есть заголовки ур.3 -> режем у них, дойдя до порога; но если между
        заголовками текст разросся сверх HARD_SPLIT_CHARS — режем по абзацу;
      - заголовков ур.3 нет -> режем по границам абзацев (порог MAX_CHUNK_CHARS).

    Возвращает список чанков (один или несколько).
    """
    blocks = chunk["_blocks"]

    if len(chunk["text"]) <= MAX_CHUNK_CHARS:
        return [chunk]

    has_level3 = any(b["type"] == "heading" and b.get("level") == 3 for b in blocks)

    # Накапливаем блоки в части. Режем у заголовков ур.3; если их нет —
    # по границам абзацев (тем же порогом), иначе гигантский раздел без
    # подзаголовков остался бы одним куском и обрезался при эмбеддинге.
    parts = []
    current_blocks = []
    current_len = 0

    for block in blocks:
        is_heading = block["type"] == "heading" and block.get("level") == 3
        # Без заголовков режем по абзацам уже на MAX_CHUNK_CHARS. При заголовках
        # даём части дорасти до HARD_SPLIT_CHARS, прежде чем резать по абзацу, —
        # бережём привязку под-чанков к подзаголовкам.
        hard_limit = HARD_SPLIT_CHARS if has_level3 else MAX_CHUNK_CHARS
        should_cut = current_blocks and (
            (is_heading and current_len >= MAX_CHUNK_CHARS) or current_len >= hard_limit
        )

        if should_cut:
            parts.append(current_blocks)
            current_blocks = []
            current_len = 0

        current_blocks.append(block)
        text = block.get("text") or block.get("description") or ""
        current_len += len(text)

    if current_blocks:
        parts.append(current_blocks)

    if len(parts) <= 1:
        return [chunk]

    # Собираем под-чанки
    sub_chunks = []
    for part_blocks in parts:
        part_pages = sorted({page_of_block(b) for b in part_blocks})

        sub_chunks.append(
            {
                "document_id": chunk["document_id"],
                "document_title": chunk["document_title"],
                "document_summary": chunk["document_summary"],
                "parent_section": chunk["parent_section"],
                "section_number": chunk["section_number"],
                "section_title": chunk["section_title"],
                "text": build_chunk_text(part_blocks),
                "pages": part_pages,
                "related_blocks": [b["block_id"] for b in part_blocks],
            }
        )

    return sub_chunks


def build_chunks(document: dict) -> list[dict]:
    """
    Нарезает документ на чанки по разделам.

    Логика:
      - заголовок уровня 1 -> запоминается как родительский раздел;
      - заголовок уровня 2 -> закрывает текущий чанк, начинает новый;
      - если у раздела ур.1 нет подразделов ур.2 -> он сам становится чанком;
      - остальные блоки -> идут в текущий чанк.
    Большие чанки в конце дробятся через split_large_chunk.

    Возвращает список чанков (словарей).
    """
    document_id = document["document_id"]
    doc_title = document.get("document_title", "")
    doc_summary = document.get("document_summary", "")

    # Есть ли в документе нумерованные разделы вообще: если нет — весь текст
    # соберёт фоллбек «страница = чанк» ниже, чанк-преамбула не нужен.
    has_sections = any(
        block["type"] == "heading" and block.get("level") in (1, 2)
        for page in document["pages"]
        for block in page["blocks"]
    )

    chunks = []
    current = None
    parent_section = ""

    def close_current():
        """Закрывает текущий чанк: достраивает и кладёт в chunks."""
        if current is None:
            return
        if not current["blocks"]:
            return
        chunks.append(
            {
                "document_id": document_id,
                "document_title": doc_title,
                "document_summary": doc_summary,
                "parent_section": current["parent_section"],
                "section_number": current["section_number"],
                "section_title": current["section_title"],
                "text": build_chunk_text(current["blocks"]),
                "pages": sorted(current["pages"]),
                "related_blocks": [b["block_id"] for b in current["blocks"]],
                "_blocks": list(current["blocks"]),
            }
        )

    def start_chunk(section_number, section_title, parent):
        """Создаёт новый пустой чанк-заготовку."""
        return {
            "section_number": section_number,
            "section_title": section_title,
            "parent_section": parent,
            "blocks": [],
            "pages": set(),
        }

    for page in document["pages"]:
        page_num = page["page_number"]
        for block in page["blocks"]:
            if block["type"] == "heading":
                level = block.get("level")

                if level == 1:
                    close_current()
                    parent_section = block["text"].strip()
                    current = start_chunk(
                        block.get("section_number") or "",
                        block["text"].strip(),
                        parent_section,
                    )
                    continue

                if level == 2:
                    close_current()
                    current = start_chunk(
                        block.get("section_number") or "",
                        block["text"].strip(),
                        parent_section,
                    )
                    continue

                # Уровень 3 (или без уровня) — содержимое, идёт в чанк.

            if not is_block_useful(block):
                continue
            if current is None:
                if not has_sections:
                    continue
                # Преамбула: титул и předmluva до первого нумерованного
                # заголовка — раньше молча выпадали из индекса (№8 аудита).
                current = start_chunk("", "", "")

            current["blocks"].append(block)
            current["pages"].add(page_num)

    close_current()

    # Фоллбек: документ без заголовков ур.1/2 (в архивах проектов — частое
    # дело: seznam příloh, выписки). Нарезка выше дала 0 чанков, но контент
    # есть — берём «страница = чанк», чтобы документ не потерялся молча.
    if not chunks:
        for page in document["pages"]:
            useful = [b for b in page["blocks"] if is_block_useful(b)]
            if not useful:
                continue
            first_heading = next(
                (b["text"].strip() for b in useful if b["type"] == "heading"), ""
            )
            chunks.append(
                {
                    "document_id": document_id,
                    "document_title": doc_title,
                    "document_summary": doc_summary,
                    "parent_section": "",
                    "section_number": "",
                    "section_title": first_heading,
                    "text": build_chunk_text(useful),
                    "pages": [page["page_number"]],
                    "related_blocks": [b["block_id"] for b in useful],
                    "_blocks": list(useful),
                }
            )

    # Дробим большие чанки
    result = []
    for chunk in chunks:
        result.extend(split_large_chunk(chunk))

    # Уникальный chunk_id: сквозной счётчик внутри документа.
    # Старая схема (документ + номер раздела) давала дубликаты в нормах
    # с приложениями, где нумерация разделов начинается заново. Номер
    # раздела остаётся в поле section_number.
    for i, chunk in enumerate(result, start=1):
        chunk["chunk_id"] = f"{document_id}_c{i:03d}"

    # Убираем служебное поле _blocks
    for chunk in result:
        chunk.pop("_blocks", None)

    return result


def build_drawing_chunk(page: dict, document: dict) -> dict:
    """Чанк одной чертёжной страницы.

    text = vision-паспорт листа (чистая семантика: тип, объект, что нарисовано)
    + ступень из текста + сырой drawing_text (OCR + текстовый слой: точные
    строки штампа и термины с чертежа). Паспорт есть только в стандартном
    режиме; в «Без LLM» остаётся один drawing_text. У чертежа нет разделов —
    страница целиком = чанк, контекст объекта даёт document_title.
    """
    drawing_text = page.get("drawing_text", "")

    parts = []
    paspport = page.get("drawing_description", "").strip()
    if paspport:
        parts.append(paspport)
    stupen = extract_stupen(drawing_text)
    if stupen:
        parts.append(f"Stupeň dokumentace: {stupen}")
    if drawing_text.strip():
        parts.append(drawing_text.strip())

    return {
        "document_id": document["document_id"],
        "document_title": document.get("document_title", ""),
        "document_summary": document.get("document_summary", ""),
        "parent_section": "",
        "section_number": "",
        "section_title": "",
        "text": "\n\n".join(parts),
        "pages": [page["page_number"]],
        "related_blocks": [],
    }


def build_chunks_routed(document: dict) -> list[dict]:
    """Нарезка с учётом типа страниц (по-страничный роутер).

    Прозаические страницы (page_type != 'drawing') режет обычный build_chunks;
    чертёжные (page_type == 'drawing') — по одному чанку на страницу из
    drawing_text. Результаты сливает и заново нумерует chunk_id сквозным
    счётчиком по всему документу. Без page_type ведёт себя как build_chunks
    (все страницы — проза) — обратная совместимость.
    """
    pages = document["pages"]
    prose_pages = [p for p in pages if p.get("page_type") != "drawing"]
    drawing_pages = [p for p in pages if p.get("page_type") == "drawing"]

    chunks = build_chunks({**document, "pages": prose_pages})
    for page in drawing_pages:
        has_text = page.get("drawing_text", "").strip()
        has_paspport = page.get("drawing_description", "").strip()
        if has_text or has_paspport:
            chunks.append(build_drawing_chunk(page, document))

    # Сквозной chunk_id по всему объединённому списку (проза + чертежи).
    document_id = document["document_id"]
    for i, chunk in enumerate(chunks, start=1):
        chunk["chunk_id"] = f"{document_id}_c{i:03d}"
    return chunks
