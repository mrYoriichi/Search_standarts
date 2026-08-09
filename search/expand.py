"""LLM query expansion.

Short queries and Czech typed without diacritics hurt retrieval: the
vector drifts into noise and BM25 misses word forms. One cheap mini call
rewrites the question into an expressive search query: diacritics,
terminology, synonyms.

Multilingual corpus (2026-08-02): BM25 only matches a document's own
language, so the query carries key terms in EVERY corpus language
(detected by search/lang_detect from the document texts). The original
question is kept for answer generation.
"""

from openai import OpenAI

EXPAND_MODEL = "gpt-5.6-luna"

# Language code → name used in the prompt. Unknown codes are skipped.
LANGUAGE_NAMES = {"cs": "Czech", "en": "English", "de": "German", "ru": "Russian"}

PROMPT_TEMPLATE = """You are a search-query rewriter for a library of construction-engineering documents: norms (ČSN, TP, VL, MVL, Eurocode) and bridge project documentation (technical reports, structural calculations, drawings).

The library contains documents in: {languages}.

The user's question may be short, abbreviated or missing diacritics. Rewrite it into ONE search line that:
- restores proper diacritics and expands shorthand,
- contains the key technical terms of the question in EACH library language listed above (translate the terms; keep standard codes like "ČSN 73 6201" as-is),
- adds professional synonyms and closely related terms where they help,
- preserves the ORIGINAL intent of the question; do not invent new topics.

Return ONLY the search line, without quotes and without explanations."""


def build_expand_prompt(languages: set[str] | None) -> str:
    """Expansion system prompt for the given corpus languages.

    None/empty or all-unknown codes → Czech (historical behaviour: the
    pilot corpus is Czech).
    """
    codes = sorted(languages or set())
    names = [LANGUAGE_NAMES[c] for c in codes if c in LANGUAGE_NAMES]
    if not names:
        names = [LANGUAGE_NAMES["cs"]]
    return PROMPT_TEMPLATE.format(languages=", ".join(names))


def expand_query(question: str, languages: set[str] | None = None) -> str:
    """Rewrite the user's question into a search query carrying terms in
    every corpus language (languages; None → Czech).

    Returns one line. On any error or empty response falls back to the
    original question — expansion must never break the search.
    """
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model=EXPAND_MODEL,
            messages=[
                {"role": "system", "content": build_expand_prompt(languages)},
                {"role": "user", "content": question},
            ],
        )
        expanded = (response.choices[0].message.content or "").strip()
        return expanded or question
    except Exception:
        return question
