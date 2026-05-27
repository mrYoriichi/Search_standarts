"""
Цены OpenAI API и расчёт стоимости вызовов.

Здесь два уровня:
1. Сырые цены за 1 миллион токенов — используются в describe.py / index.py
   для расчёта точной стоимости одного запуска по факту использованных токенов.
2. Производные средние цены ($/страница) — заполняются ПОСЛЕ замера
   на реальных документах. Используются в forecast.py для прогноза
   стоимости обработки документа по числу страниц БЕЗ запуска LLM.

Если меняются цены OpenAI или модели — обнови этот файл.
Источник цен: https://openai.com/pricing
"""

# ---------- 1. Сырые цены за 1 миллион токенов (USD) ----------
# Заполнить актуальными ценами OpenAI перед запуском describe.py / index.py.

# gpt-5.5 (vision)
VISION_INPUT_PRICE_PER_M: float | None = 5.0
VISION_OUTPUT_PRICE_PER_M: float | None = 30

# gpt-5.4-mini (генерация ответа в search/answer.py)
ANSWER_INPUT_PRICE_PER_M: float | None = 0.75
ANSWER_OUTPUT_PRICE_PER_M: float | None = 4.50

# text-embedding-3-large
EMBEDDING_PRICE_PER_M: float | None = 0.13


def vision_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """USD за один vision-вызов по факту использованных токенов."""
    if VISION_INPUT_PRICE_PER_M is None or VISION_OUTPUT_PRICE_PER_M is None:
        raise RuntimeError(
            "В pricing.py не заданы VISION_INPUT_PRICE_PER_M / "
            "VISION_OUTPUT_PRICE_PER_M. Заполни актуальными ценами OpenAI."
        )
    return (
        prompt_tokens * VISION_INPUT_PRICE_PER_M / 1_000_000
        + completion_tokens * VISION_OUTPUT_PRICE_PER_M / 1_000_000
    )


def answer_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """USD за один вызов модели ответа по факту использованных токенов."""
    if ANSWER_INPUT_PRICE_PER_M is None or ANSWER_OUTPUT_PRICE_PER_M is None:
        raise RuntimeError(
            "В pricing.py не заданы ANSWER_INPUT_PRICE_PER_M / "
            "ANSWER_OUTPUT_PRICE_PER_M. Заполни актуальными ценами OpenAI."
        )
    return (
        prompt_tokens * ANSWER_INPUT_PRICE_PER_M / 1_000_000
        + completion_tokens * ANSWER_OUTPUT_PRICE_PER_M / 1_000_000
    )


def embedding_cost(total_tokens: int) -> float:
    """USD за вызов эмбеддингов по факту использованных токенов."""
    if EMBEDDING_PRICE_PER_M is None:
        raise RuntimeError(
            "В pricing.py не задана EMBEDDING_PRICE_PER_M. "
            "Заполни актуальной ценой OpenAI."
        )
    return total_tokens * EMBEDDING_PRICE_PER_M / 1_000_000


# ---------- 2. Производные средние цены — заполняются после замера ----------
# Используются в forecast.py для предсказания стоимости обработки
# нового PDF по числу страниц (без обращения к LLM).
#
# Получены из замера 2026-05-21 на MVL649 (47 стр., 33 с figure/table) и
# TP_107 (71 стр., 23 с figure/table). Модели: gpt-5.5, text-embedding-3-large.
# Цены OpenAI: vision $5/$30 за 1M (in/out), embeddings $0.13 за 1M.
# Весами при усреднении берём количества страниц.

AVG_VISION_COST_PER_IMAGE_PAGE: float | None = 0.040    # $/страница с figure/table
AVG_EMBEDDING_COST_PER_PAGE: float | None = 0.00014     # $/страница
