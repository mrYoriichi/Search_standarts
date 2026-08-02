"""Answer generation over the retrieved chunks.

Input: the question + top chunks (from hybrid search). Output: a short
answer in the selected language (default English, see
build_system_prompt) + sources (document, section, pages) for only the
chunks the model actually used.

The module never touches the filesystem — chunks arrive as arguments.
"""

import json
from openai import OpenAI


# Answer-generation model (the UI can switch to gpt-5.5 per request).
ANSWER_MODEL = "gpt-5.4-mini"


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


# Answer languages: UI code → language name in the prompt. Default is
# English (user decision 2026-08-02; Czech was the hard rule before).
ANSWER_LANGUAGES = {"cs": "Czech", "en": "English", "de": "German"}

# The system prompt is English (neutralizes the model's language bias);
# {language} is filled in by build_system_prompt. Rule 5 references the
# Russian metadata labels used by format_chunk_for_prompt.
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
    """System prompt with the required answer language.

    Unknown codes silently fall back to English — garbage in the request
    must not break generation (second guard behind the endpoint's
    Literal validation).
    """
    language = ANSWER_LANGUAGES.get(answer_language, ANSWER_LANGUAGES["en"])
    return SYSTEM_PROMPT_TEMPLATE.format(language=language)


def format_chunk_for_prompt(chunk: dict) -> str:
    """Format one chunk for the LLM.

    chunk_id is labeled explicitly so the model does not confuse it with
    a section number. The metadata labels are functional prompt data —
    the system prompt (rule 5) refers to them by name.
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
    """User message: the question + all chunks with separators."""
    formatted = "\n\n---\n\n".join(format_chunk_for_prompt(c) for c in chunks)
    return f"Вопрос: {question}\n\nФрагменты:\n\n{formatted}"


def build_user_content(
    question: str,
    chunks: list[dict],
    page_images: list[dict] | None = None,
) -> str | list[dict]:
    """User-message content: text, or text + images for strong search.

    page_images — [{"label": "document, p. N", "b64": ...}]: snapshots of
    the top sources' pages. Without images a plain string is returned
    (cheaper in tokens than a one-part list).
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
    """Main entry: question + chunks → answer + sources.

    One LLM call with structured output: the model returns the answer
    text and the ids of chunks it actually relied on. Source metadata is
    assembled from our own data — the model is never trusted to copy it.

    Returns {"answer", "sources", "related_sources", "used_chunks",
    "prompt_tokens", "completion_tokens"}; sources is empty when the
    model found no answer. Token counts feed the QueryLog cost.
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
        """Collect sources by chunk id, skipping unknown and already-seen ids."""
        result = []
        for chunk_id in chunk_ids:
            if chunk_id in skip:
                continue
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue  # the model named an id we never gave it — ignore
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
    # related = relevant but not directly used; duplicates of used removed.
    related = build_sources(parsed.get("related_chunk_ids", []), seen)

    # Full text of the used chunks — for "Report" complaints (F7): the
    # report shows exactly what the model read and why it may have missed.
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
