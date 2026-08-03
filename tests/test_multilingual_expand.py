"""Multilingual corpus: expansion searches in all library languages.

Vectors are multilingual out of the box, but BM25 finds a document only
via words in its own language. So each document's language is detected
heuristically from the chunk text, and expansion emits terms in all
corpus languages (Maxim's decision 2026-08-02: do this before eval).
"""

from search.expand import build_expand_prompt
from search.lang_detect import corpus_languages, detect_language

CS = "Odláždění čela propustku se navrhuje podle přílohy. Šířka říčního koryta."
EN = "The wind load on the noise barrier shall be calculated according to the code."
DE = "Die Windlast auf die Lärmschutzwand ist gemäß der Norm zu berechnen. Größe."
# Russian sample ("wind load on the noise barrier..."), written as \u
# escapes to keep the source free of Cyrillic characters.
RU = (
    "\u0412\u0435\u0442\u0440\u043e\u0432\u0430\u044f \u043d\u0430\u0433"
    "\u0440\u0443\u0437\u043a\u0430 \u043d\u0430 \u0448\u0443\u043c\u043e"
    "\u0437\u0430\u0449\u0438\u0442\u043d\u044b\u0439 \u044d\u043a\u0440"
    "\u0430\u043d \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u044f\u0435"
    "\u0442\u0441\u044f \u043f\u043e \u043d\u043e\u0440\u043c\u0430\u043c "
    "\u043f\u0440\u043e\u0435\u043a\u0442\u0430."
)


# --- Document language detection ----------------------------------------------


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
    # The start of the document decides the language: headings/preamble,
    # not the tail, where a foreign-language quote could have landed.
    chunks = [_chunk("doc", CS * 50)]
    chunks.append({"document_id": "doc", "chunk_id": "doc_c999", "text": EN})
    assert corpus_languages(chunks) == {"cs"}


# --- Expansion prompt ---------------------------------------------------------


def test_prompt_lists_all_corpus_languages():
    prompt = build_expand_prompt({"cs", "en", "ru"})
    assert "Czech" in prompt
    assert "English" in prompt
    assert "Russian" in prompt


def test_prompt_defaults_to_czech():
    # No corpus data (empty library, legacy call) — previous behavior:
    # Czech.
    assert "Czech" in build_expand_prompt(None)
    assert "Czech" in build_expand_prompt(set())


def test_prompt_ignores_unknown_codes():
    prompt = build_expand_prompt({"cs", "xx"})
    assert "Czech" in prompt
    assert "xx" not in prompt
