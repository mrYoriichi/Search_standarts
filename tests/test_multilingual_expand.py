"""Многоязычный корпус: расширение ищет на всех языках библиотеки.

Вектор многоязычен «из коробки», но BM25 находит документ только словами
его языка. Поэтому язык каждого документа определяется эвристикой по
тексту чанков, а расширение выдаёт термины на всех языках корпуса
(решение Максима 2026-08-02: делаем до eval).
"""

from search.expand import build_expand_prompt
from search.lang_detect import corpus_languages, detect_language

CS = "Odláždění čela propustku se navrhuje podle přílohy. Šířka říčního koryta."
EN = "The wind load on the noise barrier shall be calculated according to the code."
DE = "Die Windlast auf die Lärmschutzwand ist gemäß der Norm zu berechnen. Größe."
RU = "Ветровая нагрузка на шумозащитный экран определяется по нормам проекта."


# --- Определение языка документа ---------------------------------------------


def test_detect_czech_by_diacritics():
    assert detect_language(CS) == "cs"


def test_detect_english_plain_latin():
    assert detect_language(EN) == "en"


def test_detect_german_by_umlauts():
    assert detect_language(DE) == "de"


def test_detect_russian_by_cyrillic():
    assert detect_language(RU) == "ru"


def test_detect_empty_defaults_to_english():
    assert detect_language("") == "en"


def _chunk(doc: str, text: str) -> dict:
    return {"document_id": doc, "chunk_id": f"{doc}_c001", "text": text}


def test_corpus_languages_collects_per_document():
    chunks = [
        _chunk("norma_cs", CS),
        _chunk("report_en", EN),
        _chunk("bericht_de", DE),
    ]
    assert corpus_languages(chunks) == {"cs", "en", "de"}


def test_corpus_languages_samples_first_chunks_only():
    # Язык решает начало документа: заголовки/преамбула, а не хвост,
    # куда могла попасть иноязычная цитата.
    chunks = [_chunk("doc", CS * 50)]
    chunks.append({"document_id": "doc", "chunk_id": "doc_c999", "text": EN})
    assert corpus_languages(chunks) == {"cs"}


# --- Промпт расширения --------------------------------------------------------


def test_prompt_lists_all_corpus_languages():
    prompt = build_expand_prompt({"cs", "en", "ru"})
    assert "Czech" in prompt
    assert "English" in prompt
    assert "Russian" in prompt


def test_prompt_defaults_to_czech():
    # Нет данных о корпусе (пустая библиотека, старый вызов) — прежнее
    # поведение: чешский.
    assert "Czech" in build_expand_prompt(None)
    assert "Czech" in build_expand_prompt(set())


def test_prompt_ignores_unknown_codes():
    prompt = build_expand_prompt({"cs", "xx"})
    assert "Czech" in prompt
    assert "xx" not in prompt
