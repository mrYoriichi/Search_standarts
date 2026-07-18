"""Тесты по-страничной сборки чанков (проза + чертёжные страницы)."""

from pdf_processing.chunker import build_chunks_routed


def _prose_page():
    return {
        "page_number": 1,
        "page_type": "text",
        "blocks": [
            {
                "block_id": "p1_b01",
                "type": "heading",
                "text": "1 Úvod",
                "section_number": "1",
                "level": 1,
            },
            {"block_id": "p1_b02", "type": "text", "text": "Nějaký text."},
        ],
    }


def _drawing_page(page_number=2, text="PRICNY REZ ZABRADLI"):
    return {
        "page_number": page_number,
        "page_type": "drawing",
        "drawing_text": text,
        "blocks": [],
    }


def test_prose_and_drawing_both_become_chunks():
    document = {"document_id": "doc", "pages": [_prose_page(), _drawing_page()]}
    chunks = build_chunks_routed(document)
    assert len(chunks) == 2
    # проза первой, чертёж — отдельным чанком
    assert chunks[0]["section_title"] == "1 Úvod"
    assert chunks[1]["text"] == "PRICNY REZ ZABRADLI"
    assert chunks[1]["pages"] == [2]


def test_sequential_chunk_ids_across_prose_and_drawings():
    document = {
        "document_id": "doc",
        "pages": [_prose_page(), _drawing_page(2), _drawing_page(3, "DETAIL A")],
    }
    ids = [c["chunk_id"] for c in build_chunks_routed(document)]
    assert ids == ["doc_c001", "doc_c002", "doc_c003"]


def test_empty_drawing_text_is_skipped():
    document = {
        "document_id": "doc",
        "pages": [_prose_page(), _drawing_page(2, "   ")],
    }
    chunks = build_chunks_routed(document)
    assert len(chunks) == 1  # пустой чертёж не даёт чанк


def test_no_page_type_behaves_as_prose():
    # обратная совместимость: без page_type всё — проза
    page = _prose_page()
    del page["page_type"]
    document = {"document_id": "doc", "pages": [page]}
    chunks = build_chunks_routed(document)
    assert len(chunks) == 1
    assert chunks[0]["chunk_id"] == "doc_c001"
