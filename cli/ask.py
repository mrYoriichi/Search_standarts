"""
CLI-сценарий: вопрос к библиотеке из терминала.

Подгружает чанки и эмбеддинги всех документов из data/cli_output/, ищет
гибридным поиском, генерирует ответ через LLM со ссылками на источник.

Запускать после того, как для каждого нужного документа прошёл полный
пайплайн (pipeline/: parse → describe → chunk → embed):
    python -m cli.ask
"""

from dotenv import load_dotenv

load_dotenv()

from backend.core.paths import CLI_OUTPUT_DIR
from indexing.bm25_index import build_bm25_index
from search.answer import generate_answer
from search.hybrid import hybrid_search
from search.library import filter_library, load_library


# Сколько чанков подаём в LLM (договорились на 5)
TOP_K = 5
DATA_ROOT = CLI_OUTPUT_DIR


def select_scope(doc_ids: list[str]) -> set[str]:
    """
    Спрашивает у пользователя, в каких документах искать.

    Пустой ввод — все документы. Иначе принимает номера через запятую
    ("1, 2") или прямо id документа ("mvl649, tp_107"). Незнакомые токены
    игнорируются с предупреждением. Если ничего валидного не выбрано —
    возвращает все документы.
    """
    raw = input(
        'Где искать? (Enter — везде; номера через запятую, напр. "1, 2"; или id): '
    ).strip()
    if not raw:
        return set(doc_ids)

    selected: set[str] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        # Цифра — номер из списка
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(doc_ids):
                selected.add(doc_ids[idx])
                continue
        # Иначе — пытаемся как document_id
        if token in doc_ids:
            selected.add(token)
            continue
        print(f"  [!] Не распознан токен {token!r} — пропущен")

    if not selected:
        print("  Ничего не выбрано — ищу везде.")
        return set(doc_ids)
    return selected


def main():
    chunks, embeddings_index = load_library(DATA_ROOT)

    # Сколько документов и чанков подгрузили — пользователю полезно видеть
    doc_ids = sorted({c["document_id"] for c in chunks})
    print(f"Библиотека: документов {len(doc_ids)}, чанков {len(chunks)}.")
    for i, doc_id in enumerate(doc_ids, start=1):
        print(f"  [{i}] {doc_id}")

    # Выбор области поиска
    allowed_ids = select_scope(doc_ids)
    if allowed_ids != set(doc_ids):
        chunks, embeddings_index = filter_library(chunks, embeddings_index, allowed_ids)
        print(f"Ищу в {len(allowed_ids)} документах, чанков: {len(chunks)}.")

    # BM25-индекс строим из (возможно отфильтрованного) пула на лету
    bm25 = build_bm25_index(chunks)

    # Вопрос с клавиатуры — удобнее, чем менять константу и перезапускать
    question = input("Вопрос: ").strip()
    if not question:
        print("Пустой вопрос.")
        return

    # Гибридный поиск — топ-5 chunk_id'ов с RRF-score
    found = hybrid_search(bm25, embeddings_index, question, top_k=TOP_K)

    print(f"\nНайдено чанков: {len(found)}")
    for chunk_id, score in found:
        print(f"  {chunk_id}  (rrf={score:.4f})")

    # Подтягиваем полные чанки по id, сохраняя порядок поиска
    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    top_chunks = [chunks_by_id[chunk_id] for chunk_id, _ in found]

    # Генерация ответа (запрос к OpenAI)
    print("\nГенерирую ответ...")
    result = generate_answer(question, top_chunks)

    # Печать результата
    print("\n=== Ответ ===")
    print(result["answer"])

    print("\n=== Источники ===")
    if not result["sources"]:
        print("  (нет — модель не нашла ответа в фрагментах)")
    else:
        for src in result["sources"]:
            pages = ", ".join(str(p) for p in src["pages"])
            print(f"  - {src['document']} / {src['section']} / стр. {pages}")


if __name__ == "__main__":
    main()
