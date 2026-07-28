"""Тесты make_document_id — идентичность документа (решение №15 в PROJECT_STATE)."""

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
    # ё → е даёт NFD ещё до таблицы, поэтому «чертёж» → chertezh, не chertyozh.
    assert make_document_id("Чертёж моста.pdf") == "chertezh_mosta"


def test_cyrillic_names_do_not_collide():
    # Раньше кириллица выбрасывалась целиком — два русских имени давали
    # одинаковый пустой slug и затирали друг друга.
    a = make_document_id("Чертёж.pdf")
    b = make_document_id("Расчёт.pdf")
    assert a and b and a != b


def test_mixed_cyrillic_latin():
    assert make_document_id("Отчёт TP107.pdf") == "otchet_tp107"


class _FakeTableItem:
    """Минимальный двойник Docling TableItem: только то, что читает make_block."""

    label = "table"
    prov: list = []

    def export_to_markdown(self, doc=None) -> str:
        return "| Zatížení | Hodnota |\n| vítr | 1,5 kN/m2 |\n"


def test_make_block_saves_table_markdown():
    # ШАГ 3 (аудит 2026-07-19): точные значения ячеек должны попадать в
    # document.json — vision-пересказ чисел не сохраняет.
    block = make_block(_FakeTableItem(), 1, 1, doc=None)
    assert block["type"] == "table"
    assert "1,5 kN/m2" in block["text"]
