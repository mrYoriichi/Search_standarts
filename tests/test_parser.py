"""Tests for make_document_id — document identity (decision #15 in PROJECT_STATE)."""

from pdf_processing.parser import make_block, make_document_id


def test_diacritics_and_spaces():
    assert make_document_id("ČSN EN 1991-2.pdf") == "csn_en_1991_2"


def test_simple_name():
    assert make_document_id("MVL 649.pdf") == "mvl_649"


def test_uppercase():
    assert make_document_id("TP_107.PDF") == "tp_107"


def test_parentheses_and_dots():
    assert make_document_id("příloha č.5 (výkres).pdf") == "priloha_c_5_vykres"


def test_cyrillic_transliterated():
    # NFD decomposes Cyrillic yo into e + diaeresis before the table
    # applies, so the name yields chertezh, not chertyozh.
    assert make_document_id("Чертёж моста.pdf") == "chertezh_mosta"


def test_cyrillic_names_do_not_collide():
    # Cyrillic used to be dropped entirely — two Russian names produced
    # the same empty slug and overwrote each other.
    a = make_document_id("Чертёж.pdf")
    b = make_document_id("Расчёт.pdf")
    assert a and b and a != b


def test_mixed_cyrillic_latin():
    assert make_document_id("Отчёт TP107.pdf") == "otchet_tp107"


class _FakeTableItem:
    """Minimal stand-in for Docling TableItem: only what make_block reads."""

    label = "table"
    prov: list = []

    def export_to_markdown(self, doc=None) -> str:
        return "| Zatížení | Hodnota |\n| vítr | 1,5 kN/m2 |\n"


def test_make_block_saves_table_markdown():
    # STEP 3 (audit 2026-07-19): exact cell values must end up in
    # document.json — the vision retelling does not preserve numbers.
    block = make_block(_FakeTableItem(), 1, 1, doc=None)
    assert block["type"] == "table"
    assert "1,5 kN/m2" in block["text"]
