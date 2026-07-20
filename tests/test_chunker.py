"""Тесты нарезки на чанки (решение №6 и №19 в PROJECT_STATE)."""

from pdf_processing.chunker import build_chunks


def _heading(bid: str, text: str, level: int, number: str = "") -> dict:
    return {
        "block_id": bid,
        "type": "heading",
        "level": level,
        "text": text,
        "section_number": number,
    }


def _para(bid: str, text: str) -> dict:
    return {"block_id": bid, "type": "paragraph", "text": text}


def _doc(pages: list[dict]) -> dict:
    return {
        "document_id": "test_doc",
        "document_title": "Test",
        "document_summary": "Souhrn",
        "pages": pages,
    }


def test_split_by_level2_headings():
    doc = _doc(
        [
            {
                "page_number": 1,
                "blocks": [
                    _heading("p1_b01", "1 Úvod", 1, "1"),
                    _para("p1_b02", "Text úvodu."),
                    _heading("p1_b03", "1.1 Rozsah", 2, "1.1"),
                    _para("p1_b04", "Text rozsahu."),
                    _heading("p1_b05", "1.2 Definice", 2, "1.2"),
                    _para("p1_b06", "Text definic."),
                ],
            }
        ]
    )
    chunks = build_chunks(doc)
    titles = [c["section_title"] for c in chunks]
    assert titles == ["1 Úvod", "1.1 Rozsah", "1.2 Definice"]
    assert all(c["parent_section"] == "1 Úvod" for c in chunks)
    assert chunks[1]["text"] == "Text rozsahu."


def test_chunk_ids_are_sequential_and_unique():
    doc = _doc(
        [
            {
                "page_number": 1,
                "blocks": [
                    _heading("p1_b01", "1 Úvod", 1, "1"),
                    _para("p1_b02", "A."),
                    _heading("p1_b03", "1.1 Rozsah", 2, "1.1"),
                    _para("p1_b04", "B."),
                ],
            }
        ]
    )
    chunks = build_chunks(doc)
    ids = [c["chunk_id"] for c in chunks]
    assert ids == ["test_doc_c001", "test_doc_c002"]
    assert len(ids) == len(set(ids))


def test_junk_blocks_filtered_out():
    doc = _doc(
        [
            {
                "page_number": 1,
                "blocks": [
                    _heading("p1_b01", "1 Úvod", 1, "1"),
                    {"block_id": "p1_b02", "type": "header", "text": "kolontitul"},
                    {"block_id": "p1_b03", "type": "footer", "text": "strana 1"},
                    {
                        "block_id": "p1_b04",
                        "type": "figure",
                        "description": "Logo firmy",
                    },
                    {"block_id": "p1_b05", "type": "figure", "description": None},
                    _para("p1_b06", "Užitečný text."),
                ],
            }
        ]
    )
    chunks = build_chunks(doc)
    assert len(chunks) == 1
    assert chunks[0]["text"] == "Užitečný text."


def test_figure_and_table_markers():
    doc = _doc(
        [
            {
                "page_number": 1,
                "blocks": [
                    _heading("p1_b01", "2 Schémata", 1, "2"),
                    {
                        "block_id": "p1_b02",
                        "type": "figure",
                        "description": "řez mostem",
                    },
                    {
                        "block_id": "p1_b03",
                        "type": "table",
                        "description": "součinitele",
                    },
                ],
            }
        ]
    )
    chunks = build_chunks(doc)
    assert "[SCHÉMA: řez mostem]" in chunks[0]["text"]
    assert "[TABULKA: součinitele]" in chunks[0]["text"]


def test_table_text_survives_without_description():
    # Режим «Без LLM»: у таблицы нет vision-описания, но есть текст ячеек
    # (markdown из Docling) — таблица НЕ должна выпадать из поиска.
    doc = _doc(
        [
            {
                "page_number": 1,
                "blocks": [
                    _heading("p1_b01", "3 Zatížení", 1, "3"),
                    {
                        "block_id": "p1_b02",
                        "type": "table",
                        "description": None,
                        "text": "| Zatížení | Hodnota |\n| vítr | 1,5 kN/m2 |",
                    },
                ],
            }
        ]
    )
    chunks = build_chunks(doc)
    assert len(chunks) == 1
    assert "1,5 kN/m2" in chunks[0]["text"]
    assert "[TABULKA]" in chunks[0]["text"]


def test_table_description_and_text_combined():
    # Режим «Стандарт»: пересказ vision + точные значения ячеек — оба в чанке
    # (vision описывает тему, но точные числа знает только сам текст таблицы).
    doc = _doc(
        [
            {
                "page_number": 1,
                "blocks": [
                    _heading("p1_b01", "4 Součinitele", 1, "4"),
                    {
                        "block_id": "p1_b02",
                        "type": "table",
                        "description": "součinitele zatížení",
                        "text": "| γ | 1,35 |",
                    },
                ],
            }
        ]
    )
    chunks = build_chunks(doc)
    assert "[TABULKA: součinitele zatížení]" in chunks[0]["text"]
    assert "1,35" in chunks[0]["text"]


def test_fallback_page_per_chunk_when_no_headings():
    # Документ без заголовков ур.1/2 (seznam příloh) не должен потеряться:
    # каждая страница с контентом становится чанком, пустая — пропускается.
    doc = _doc(
        [
            {"page_number": 1, "blocks": [_para("p1_b01", "Obsah přílohy 1.")]},
            {"page_number": 2, "blocks": []},
            {"page_number": 3, "blocks": [_para("p3_b01", "Obsah přílohy 3.")]},
        ]
    )
    chunks = build_chunks(doc)
    assert len(chunks) == 2
    assert chunks[0]["pages"] == [1]
    assert chunks[1]["pages"] == [3]


def test_preamble_before_first_numbered_heading_is_kept():
    # №8 из аудита: титул и předmluva до первого нумерованного заголовка
    # молча выпадали из индекса, если дальше нумерованные разделы есть.
    doc = _doc(
        [
            {
                "page_number": 1,
                "blocks": [
                    _para("p1_b01", "ČSN EN 1992-2. Navrhování betonových mostů."),
                    _heading("p1_b02", "Předmluva", None),
                    _para("p1_b03", "Tato norma nahrazuje vydání z roku 2007."),
                ],
            },
            {
                "page_number": 2,
                "blocks": [
                    _heading("p2_b01", "1 Předmět normy", 1, "1"),
                    _para("p2_b02", "Norma platí pro navrhování mostů."),
                ],
            },
        ]
    )
    chunks = build_chunks(doc)
    all_text = "\n".join(c["text"] for c in chunks)
    assert "nahrazuje vydání" in all_text  # предисловие не потеряно
    assert "betonových mostů" in all_text  # титульный текст не потерян
    # Преамбула — отдельный первый чанк без номера раздела.
    preamble = chunks[0]
    assert preamble["section_number"] == ""
    assert preamble["pages"] == [1]


def test_giant_section_split_by_paragraphs():
    # Раздел без подзаголовков ур.3 длиннее MAX_CHUNK_CHARS (2500)
    # режется по границам абзацев, а не остаётся одним гигантом.
    long_para = "x" * 1500
    doc = _doc(
        [
            {
                "page_number": 1,
                "blocks": [
                    _heading("p1_b01", "3 Dlouhá kapitola", 1, "3"),
                    _para("p1_b02", long_para),
                    _para("p1_b03", long_para),
                    _para("p1_b04", long_para),
                ],
            }
        ]
    )
    chunks = build_chunks(doc)
    assert len(chunks) == 2
    assert all(c["section_title"] == "3 Dlouhá kapitola" for c in chunks)
    assert all(len(c["text"]) < 4000 for c in chunks)
