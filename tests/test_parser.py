"""Тесты make_document_id — идентичность документа (решение №15 в PROJECT_STATE)."""

from pdf_processing.parser import make_document_id


def test_diacritics_and_spaces():
    assert make_document_id("ČSN EN 1991-2.pdf") == "csn_en_1991_2"


def test_simple_name():
    assert make_document_id("MVL 649.pdf") == "mvl_649"


def test_uppercase():
    assert make_document_id("TP_107.PDF") == "tp_107"


def test_parentheses_and_dots():
    assert make_document_id("příloha č.5 (výkres).pdf") == "priloha_c_5_vykres"


def test_cyrillic_becomes_empty():
    # Фиксируем ТЕКУЩЕЕ поведение: кириллица выбрасывается целиком -> пустой id.
    # Это реальная дыра: два русских имени файла дадут одинаковый пустой slug
    # и затрут друг друга. Чинить отдельным шагом (транслитерация) -
    # тогда этот тест сознательно поменяем.
    assert make_document_id("Чертёж моста.pdf") == ""
