"""
Этап 6, часть 2: генерация ответа по найденным чанкам.

На входе: вопрос + список топ-чанков (от hybrid_search через сценарий).
На выходе: краткий ответ на выбранном языке (дефолт — английский, см.
build_system_prompt) + источники (документ, раздел, страницы) только для
тех чанков, на которые модель реально опиралась.

Модуль не лезет в файловую систему — чанки приходят аргументом.
"""

import json
from openai import OpenAI


# Модель для генерации ответа. Та же, что используется в vision-описаниях.
ANSWER_MODEL = "gpt-5.4-mini"


'''
SYSTEM_PROMPT = """Ты помощник по строительным нормам. Отвечаешь строго по предоставленным фрагментам документов.

Правила:
1. Используй ТОЛЬКО информацию из фрагментов. Не добавляй знания извне.
2. Если в фрагментах нет ответа — честно скажи "В найденных фрагментах ответа на этот вопрос нет" и оставь used_chunk_ids пустым.
3. Сначала определи язык вопроса и заполни поле question_language (например: "ru", "cs", "en"). Затем отвечай ровно на этом языке. Чешский может быть написан без диакритики ("celo propustku" = "čelo propustku") — это всё равно чешский.
4. Сохраняй технические обозначения в оригинале: номера норм (ČSN 73 6201), номера разделов (7.12.6), названия разделов на чешском.
5. В used_chunk_ids перечисли ТОЛЬКО те фрагменты, на которые реально опирался. Если использовал 2 из 5 — верни 2.
6. Будь краток и конкретен."""

# Схема структурированного ответа для OpenAI Structured Outputs.
# API гарантирует, что вернёт ровно эту форму JSON — никаких ошибок парсинга.
# used_chunk_ids — только те chunk_id, на которые модель реально опиралась.
'''


RESPONSE_SCHEMA = {
    "name": "rag_answer",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "used_chunk_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "related_chunk_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["answer", "used_chunk_ids", "related_chunk_ids"],
        "additionalProperties": False,
    },
}


# Языки ответа: код из UI → имя языка в промпте. Дефолт — английский
# (решение №12 снято 2026-08-02: чешский — полноценный выбор, не дефолт).
ANSWER_LANGUAGES = {"cs": "Czech", "en": "English", "de": "German"}

# Системный промпт по-английски (нейтрализует языковой bias модели);
# {language} подставляет build_system_prompt.
SYSTEM_PROMPT_TEMPLATE = """You are an assistant for construction standards. The source documents are Czech construction norms (ČSN, MVL); their content is in Czech.

Answer strictly based on the provided fragments.

Rules:
1. Use ONLY information from the fragments. Do not add outside knowledge.
2. ALWAYS answer in {language}, regardless of the language of the question. The question may be in any language (Russian, English, Czech without diacritics) — your answer must always be in {language}.
3. If the fragments do not contain the answer, say so honestly in {language} and return an empty used_chunk_ids.
4. Preserve technical designations in their original form: standard codes (ČSN 73 6201), section numbers (7.12.6), section names in Czech.
5. Cite the source INLINE in the answer text: after each fact or claim, note in parentheses which section and page it comes from, using the fragment's "Раздел" and "Страницы" metadata — e.g. "(7.3 Založení propustků, s. 24)". If several facts come from the same fragment, you may cite it once. Cite only fragments you actually used.
6. In used_chunk_ids list ONLY the fragments you directly based the answer on. If you used 2 of 5, return 2.
7. In related_chunk_ids list other fragments that are relevant and useful to the question but that you did NOT directly use for the answer (e.g. related sections, drawings, or details worth checking). Do NOT include fragments that are off-topic. Do not repeat ids already in used_chunk_ids. If there are none, return an empty list.
8. Be brief and concrete."""


def build_system_prompt(answer_language: str = "en") -> str:
    """Системный промпт с требуемым языком ответа.

    Неизвестный код языка тихо падает на английский — мусор в запросе не
    должен ронять генерацию (эндпоинт и так валидирует Literal, второй рубеж).
    """
    language = ANSWER_LANGUAGES.get(answer_language, ANSWER_LANGUAGES["en"])
    return SYSTEM_PROMPT_TEMPLATE.format(language=language)


def format_chunk_for_prompt(chunk: dict) -> str:
    """
    Форматирует один чанк для подачи в LLM.

    chunk_id явно подписан, чтобы модель не путала его с номером раздела.
    Метаданные сверху коротким блоком — модели проще понять структуру.
    """
    pages = ", ".join(str(p) for p in chunk.get("pages", []))

    return (
        f"[chunk_id={chunk['chunk_id']}]\n"
        f"Документ: {chunk.get('document_title', '')}\n"
        f"Раздел: {chunk.get('section_title', '')}\n"
        f"Страницы: {pages}\n"
        f"\n"
        f"{chunk.get('text', '')}"
    )


def build_user_message(question: str, chunks: list[dict]) -> str:
    """
    Собирает user-сообщение: вопрос + все чанки через разделитель.
    """
    formatted = "\n\n---\n\n".join(format_chunk_for_prompt(c) for c in chunks)
    return f"Вопрос: {question}\n\nФрагменты:\n\n{formatted}"


def build_user_content(
    question: str,
    chunks: list[dict],
    page_images: list[dict] | None = None,
) -> str | list[dict]:
    """Содержимое user-сообщения: текст, при сильном поиске — текст + картинки.

    page_images — [{"label": "документ, s. N", "b64": "..."}]: снимки страниц
    топ-источников. Без картинок возвращаем обычную строку (старое поведение,
    дешевле по токенам, чем список из одной текстовой части).
    """
    text = build_user_message(question, chunks)
    if not page_images:
        return text

    labels = "; ".join(f"{i + 1}) {img['label']}" for i, img in enumerate(page_images))
    text += (
        f"\n\nAttached are page snapshots of the top sources, in order: {labels}. "
        f"Use them to read details that the text fragments or OCR may have "
        f"missed or garbled (dimensions, labels in drawings, table values)."
    )
    content: list[dict] = [{"type": "text", "text": text}]
    for img in page_images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img['b64']}"},
            }
        )
    return content


def generate_answer(
    question: str,
    chunks: list[dict],
    model: str = ANSWER_MODEL,
    page_images: list[dict] | None = None,
    answer_language: str = "en",
) -> dict:
    """
    Главная функция: вопрос + чанки → ответ + источники.

    model — id модели для генерации (по умолчанию ANSWER_MODEL). Параметр нужен,
    чтобы сравнивать модели (gpt-5.4-mini ↔ gpt-5.5) из UI.
    page_images — снимки страниц топ-источников (сильный поиск), см.
    build_user_content; None = обычный текстовый режим.
    answer_language — язык ответа ("cs"/"en"/"de", дефолт английский).

    Один вызов LLM со structured output: модель возвращает текст ответа
    и список chunk_id, на которые реально опиралась. Источники собираем
    сами из метаданных чанков — модели не доверяем переписывать данные.

    Возвращает:
      {
        "answer": "...",
        "sources": [
          {"document": "...", "section": "...", "pages": [...]},
          ...
        ],
        "prompt_tokens": int,
        "completion_tokens": int,
      }
    sources пуст, если модель не нашла ответа в фрагментах.
    prompt_tokens/completion_tokens — для расчёта стоимости в QueryLog.
    """
    client = OpenAI()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": build_system_prompt(answer_language)},
            {
                "role": "user",
                "content": build_user_content(question, chunks, page_images),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": RESPONSE_SCHEMA,
        },
    )

    parsed = json.loads(response.choices[0].message.content)

    chunks_by_id = {c["chunk_id"]: c for c in chunks}

    def build_sources(chunk_ids: list[str], skip: set[str]) -> list[dict]:
        """Собирает источники по id чанков, пропуская неизвестные и уже учтённые."""
        result = []
        for chunk_id in chunk_ids:
            if chunk_id in skip:
                continue
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue  # модель назвала id, которого мы не давали — игнорируем
            skip.add(chunk_id)
            result.append(
                {
                    "document": chunk.get("document_title", ""),
                    "slug": chunk.get("document_id", ""),
                    "section": chunk.get("section_title", ""),
                    "pages": chunk.get("pages", []),
                }
            )
        return result

    seen: set[str] = set()
    sources = build_sources(parsed["used_chunk_ids"], seen)
    # related — релевантные, но не использованные напрямую; дубли с used убраны
    related = build_sources(parsed.get("related_chunk_ids", []), seen)

    # Полный текст использованных чанков — для отчётов «Nahlásit» (F7): по жалобе
    # видно, что именно модель читала и почему могла промахнуться.
    used_chunks = [
        {
            "chunk_id": cid,
            "document": chunks_by_id[cid].get("document_title", ""),
            "section": chunks_by_id[cid].get("section_title", ""),
            "pages": chunks_by_id[cid].get("pages", []),
            "text": chunks_by_id[cid].get("text", ""),
        }
        for cid in parsed["used_chunk_ids"]
        if cid in chunks_by_id
    ]

    return {
        "answer": parsed["answer"],
        "sources": sources,
        "related_sources": related,
        "used_chunks": used_chunks,
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
    }
