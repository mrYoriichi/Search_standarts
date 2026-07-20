"""№9 аудита: пустой/битый ответ Vision не должен тихо терять содержимое.

Раньше страница с figure/table, для которой модель вернула пустоту или
не-JSON, помечалась «описанной» и больше никогда не повторялась — схемы
навсегда выпадали из индекса без единой ошибки.
"""

import json

import pytest

import describe
from pdf_processing import image_description
from pdf_processing.image_description import (
    VisionEmptyResponseError,
    describe_page_visuals,
)

_DOC = {
    "pages": [
        {
            "page_number": 1,
            "blocks": [{"type": "figure", "block_id": "p1_b0"}],
        }
    ]
}


def test_retry_then_error_on_garbage(monkeypatch, tmp_path):
    png = tmp_path / "p001.png"
    png.write_bytes(b"fake png")
    calls: list[str] = []

    def garbage(image_path, prompt, model):
        calls.append(model)
        return "toto není JSON", 1, 1

    monkeypatch.setattr(image_description, "ask_vision", garbage)
    with pytest.raises(VisionEmptyResponseError):
        describe_page_visuals(_DOC, 1, png, model="gpt-test")
    assert len(calls) == 2  # одна повторная попытка, потом ошибка


def test_second_attempt_succeeds(monkeypatch, tmp_path):
    png = tmp_path / "p001.png"
    png.write_bytes(b"fake png")
    answers = [
        "",  # отказ модели (content None -> "")
        '[{"block_id": "p1_b0", "description": "schéma"}]',
    ]

    def flaky(image_path, prompt, model):
        return answers.pop(0), 1, 1

    monkeypatch.setattr(image_description, "ask_vision", flaky)
    desc, in_tok, out_tok = describe_page_visuals(_DOC, 1, png, model="gpt-test")
    assert desc == {"p1_b0": "schéma"}
    assert (in_tok, out_tok) == (2, 2)  # обе попытки оплачены и учтены


def test_page_without_blocks_is_not_an_error(monkeypatch):
    # Легитимная пустота: блоков нет, vision не зовётся, ошибки нет.
    def must_not_run(*args, **kwargs):
        raise AssertionError("страница без блоков не должна уходить в vision")

    monkeypatch.setattr(image_description, "ask_vision", must_not_run)
    desc, in_tok, out_tok = describe_page_visuals({"pages": []}, 1, "x.png")
    assert desc == {}
    assert (in_tok, out_tok) == (0, 0)


def test_failed_page_not_marked_described(tmp_path, monkeypatch):
    # Интеграция через process(): сбойная страница не попадает в
    # described_pages — повторный запуск попробует её снова.
    doc = {
        "document_name": "Test",
        "document_id": "test",
        "pages": [
            {"page_number": 1, "blocks": [{"type": "figure", "block_id": "p1_b0"}]}
        ],
    }
    (tmp_path / "document.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "p001.png").write_bytes(b"fake png")

    monkeypatch.setattr(
        describe,
        "extract_document_metadata",
        lambda image, model: ({"title": "T", "summary": "S"}, 1, 1),
    )
    monkeypatch.setattr(
        image_description, "ask_vision", lambda image_path, prompt, model: ("", 1, 1)
    )

    with pytest.raises(VisionEmptyResponseError):
        describe.process("test", doc_dir=tmp_path)

    saved = json.loads((tmp_path / "descriptions.json").read_text(encoding="utf-8"))
    assert saved["described_pages"] == []  # страница НЕ помечена — повтор возможен
    assert saved["document_title"] == "T"  # оплаченные метаданные сохранены
