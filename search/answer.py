"""
Этап 6, часть 2: генерация ответа по найденным чанкам.

На входе: вопрос + список топ-чанков (от hybrid_search через сценарий).
На выходе: краткий ответ на языке вопроса + источники (документ, раздел,
страницы) только для тех чанков, на которые модель реально опиралась.

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
            "question_language": {"type": "string"},
            "answer": {"type": "string"},
            "used_chunk_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["question_language", "answer", "used_chunk_ids"],
        "additionalProperties": False,
    },
}


SYSTEM_PROMPT = """You are an assistant for construction standards. The source documents are Czech construction norms (ČSN, MVL); their content is in Czech.

Answer strictly based on the provided fragments.

Rules:
1. Use ONLY information from the fragments. Do not add outside knowledge.
2. If the fragments do not contain the answer, say so honestly (in the question's language) and return an empty used_chunk_ids.
3. First determine the language of the question and put it in question_language (e.g. "ru", "cs", "en"). Then answer in exactly that language. Czech without diacritics ("celo propustku" = "čelo propustku") is still Czech. If the language is ambiguous, default to Czech — the language of the documents.
4. Preserve technical designations in their original form: standard codes (ČSN 73 6201), section numbers (7.12.6), section names in Czech.
5. In used_chunk_ids list ONLY the fragments you actually used. If you used 2 of 5, return 2.
6. Be brief and concrete."""


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


def generate_answer(question: str, chunks: list[dict]) -> dict:
    """
    Главная функция: вопрос + чанки → ответ + источники.

    Один вызов LLM со structured output: модель возвращает текст ответа
    и список chunk_id, на которые реально опиралась. Источники собираем
    сами из метаданных чанков — модели не доверяем переписывать данные.

    Возвращает:
      {
        "answer": "...",
        "sources": [
          {"document": "...", "section": "...", "pages": [...]},
          ...
        ]
      }
    sources пуст, если модель не нашла ответа в фрагментах.
    """
    client = OpenAI()

    response = client.chat.completions.create(
        model=ANSWER_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(question, chunks)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": RESPONSE_SCHEMA,
        },
    )

    parsed = json.loads(response.choices[0].message.content)

    # Собираем источники по id, которые модель пометила как использованные
    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    sources = []
    for chunk_id in parsed["used_chunk_ids"]:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue  # модель назвала id, которого мы не давали — игнорируем
        sources.append({
            "document": chunk.get("document_title", ""),
            "section": chunk.get("section_title", ""),
            "pages": chunk.get("pages", []),
        })

    return {
        "answer": parsed["answer"],
        "sources": sources,
    }
