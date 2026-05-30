"""
Нарезка структурированного документа (document.json) на смысловые чанки.

Чанк — это один раздел нормы (заголовок 2-го уровня и его содержимое),
обогащённый контекстом: название документа, краткое описание,
родительский раздел. Большие чанки дробятся по заголовкам уровня 3.

Главная функция: build_chunks(document) -> list[dict]
"""

import re

# Типы блоков-мусора, которые не идут в чанки.
SKIP_BLOCK_TYPES = {"document_index", "header", "footer"}

# Фразы-маркеры нетехнического контента (логотипы, штампы). Модель не всегда
# пишет каноническую метку дословно (например «Logo... bez technického obsahu»),
# поэтому матчим по подстроке без учёта регистра, а не точным равенством.
NON_TECHNICAL_SUBSTRINGS = (
    "není technický obsah",  # каноническая метка из промпта
    "bez technického",       # частая перефразировка модели
)

# Слово 'logo' проверяем отдельно — как целое слово (\b), а не подстроку:
# подстрока ловила бы инфлектированные 'katalogové', 'dialogový' и т.п.
_LOGO_WORD = re.compile(r"\blogo\b")

# Порог: чанки длиннее этого числа символов — кандидаты на дробление.
MAX_CHUNK_CHARS = 2500


def make_chunk_id(document_id: str, section_number: str) -> str:
    """
    Строит chunk_id из id документа и номера раздела.
    'mvl649' + '7.12' -> 'mvl649_7_12'
    """
    section_part = section_number.replace(".", "_")
    return f"{document_id}_{section_part}"


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
            pieces.append(f"[TABULKA: {block['description']}]")
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
    Дробит большой чанк на под-чанки по заголовкам уровня 3.

    Правила:
      - чанк короче порога -> возвращаем как есть;
      - нет заголовков уровня 3 -> возвращаем как есть (не дробим);
      - иначе -> накапливаем блоки, режем у заголовка ур.3,
        когда накопленный текст подошёл к порогу.

    Возвращает список чанков (один или несколько).
    """
    blocks = chunk["_blocks"]

    if len(chunk["text"]) <= MAX_CHUNK_CHARS:
        return [chunk]

    has_level3 = any(
        b["type"] == "heading" and b.get("level") == 3 for b in blocks
    )
    if not has_level3:
        return [chunk]

    # Накапливаем блоки в части
    parts = []
    current_blocks = []
    current_len = 0

    for block in blocks:
        is_level3 = block["type"] == "heading" and block.get("level") == 3

        if is_level3 and current_len >= MAX_CHUNK_CHARS and current_blocks:
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
    for i, part_blocks in enumerate(parts):
        if i == 0:
            sub_id = chunk["chunk_id"]
        else:
            sub_id = f"{chunk['chunk_id']}_p{i + 1}"

        part_pages = sorted({page_of_block(b) for b in part_blocks})

        sub_chunks.append({
            "chunk_id": sub_id,
            "document_id": chunk["document_id"],
            "document_title": chunk["document_title"],
            "document_summary": chunk["document_summary"],
            "parent_section": chunk["parent_section"],
            "section_number": chunk["section_number"],
            "section_title": chunk["section_title"],
            "text": build_chunk_text(part_blocks),
            "pages": part_pages,
            "related_blocks": [b["block_id"] for b in part_blocks],
        })

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

    chunks = []
    current = None
    parent_section = ""

    def close_current():
        """Закрывает текущий чанк: достраивает и кладёт в chunks."""
        if current is None:
            return
        if not current["blocks"]:
            return
        chunks.append({
            "chunk_id": make_chunk_id(document_id, current["section_number"]),
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
        })

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

            if current is None:
                continue
            if not is_block_useful(block):
                continue

            current["blocks"].append(block)
            current["pages"].add(page_num)

    close_current()

    # Дробим большие чанки
    result = []
    for chunk in chunks:
        result.extend(split_large_chunk(chunk))

    # Убираем служебное поле _blocks
    for chunk in result:
        chunk.pop("_blocks", None)

    return result