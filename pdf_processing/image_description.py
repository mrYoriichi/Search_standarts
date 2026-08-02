"""Describing schemes and tables via the vision LLM (OpenAI).

Takes a page screenshot, asks the model to describe the schemes/tables
on it, returns the model's answer. The Czech prompts are functional —
the corpus and the descriptions are Czech.
"""

import base64
import json
import time
import re
from pathlib import Path

from openai import OpenAI


# Default vision model. The app overrides it with the vision_model
# setting; this constant is the default for the CLI and direct calls.
VISION_MODEL = "gpt-5.4-mini"

# Prompt for the vision passport of a drawing page (whole sheet = one
# image). The goal is not "what is visible" but a SEARCH-RICH passport:
# the title block (razítko) yields identifying terms (object type,
# investor, year, stage, new build vs reconstruction) that help both BM25
# and the vector search tell this sheet from others.
DRAWING_PROMPT = """Jsi expert na stavební, mostní a železniční dokumentaci.
Na obrázku je jeden list výkresové dokumentace stavebního projektu (v ČR).

Vytvoř bohatý vyhledávací popis listu: identifikaci z razítka (rozpisky) i to,
co je na výkrese skutečně nakresleno a vyřešeno. Nehádej: co nelze přečíst,
nech prázdné ("").

Vrať POUZE validní JSON s klíči:
- "druh": druh a účel konstrukce (typ objektu) co nejpřesněji, např.
  "trubní propustek", "most pro protihlukovou stěnu (PHS)", "opěrná zeď",
  "silniční most". NEUVÁDĚJ obor (železniční/silniční) — ten se doplní zvlášť
  z investora.
- "objekt": číslo a název stavebního objektu (např. "SO 02 propustek v km 66,375").
- "nazev": název výkresu (přílohy) z razítka — co list zobrazuje, např.
  "Nový stav – půdorys a řezy".
- "stavba": název celé stavby / trati / úseku z razítka.
- "investor": investor nebo objednatel z razítka.
- "rok": rok nebo datum z razítka.
- "lokalita": kde stavba je — staničení (km), trať / silnice, obec nebo
  katastrální území, okres, kraj — pokud to lze vyčíst.
- "typ_akce": jedno slovo — "novostavba", "rekonstrukce", nebo "oprava".
- "popis": 3-6 vět, KONKRÉTNĚ vyjmenuj konstrukční prvky a řešení na výkrese.
  ROZLIŠ NOVÝ a STÁVAJÍCÍ stav: jasně uveď hlavní NOVÝ nosný prvek a jeho
  parametry (např. "nový prefabrikovaný trubní propustek DN 800") a co je
  stávající (např. stávající trouba DN 500). Vyjmenuj koncové a navazující
  prvky (monolitická betonová čela a křídla z betonu C30/37, spádová jímka,
  koncový práh, kamenná dlažba, betonové římsy, ocelové zábradlí, podkladní
  beton) a jaké pohledy/řezy/detaily jsou na listu (půdorys, podélný řez, řezy
  A-A až D-D, detail vtoku/výtoku). Uveď určující parametry (průměr DN, třídy
  betonu, materiál), ale NEobkresluj všechny kóty ani rozměry.

Popisuj jen to, co je skutečně vidět. Vše v češtině.
Nepřidávej žádný text mimo JSON.
"""


def encode_image_to_base64(image_path: str | Path) -> str:
    """Read an image file and encode it as base64 (how OpenAI takes images)."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def ask_vision(
    image_path: str | Path,
    prompt: str,
    model: str = VISION_MODEL,
) -> tuple[str, int, int]:
    """One vision request: image + text prompt.

    Returns (answer_text, prompt_tokens, completion_tokens); token counts
    feed the cost accounting. content can be None (model refusal/filter)
    — "" is returned instead of crashing, callers handle empty answers.
    """
    client = OpenAI()  # finds the key in OPENAI_API_KEY

    base64_image = encode_image_to_base64(image_path)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                    },
                ],
            }
        ],
    )

    return (
        response.choices[0].message.content or "",
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
    )


def get_page_context(document: dict, page_number: int) -> dict:
    """Context of one page for the vision LLM.

    Returns {"blocks": page blocks in order, "prev_page_text": ...,
    "next_page_text": ...} (empty strings at the edges).
    """
    pages_by_number = {p["page_number"]: p for p in document["pages"]}

    current_page = pages_by_number.get(page_number)
    if current_page is None:
        return {"blocks": [], "prev_page_text": "", "next_page_text": ""}

    prev_page = pages_by_number.get(page_number - 1, {})
    next_page = pages_by_number.get(page_number + 1, {})

    return {
        "blocks": current_page["blocks"],
        "prev_page_text": prev_page.get("page_text", ""),
        "next_page_text": next_page.get("page_text", ""),
    }


def build_vision_prompt(page_context: dict) -> str:
    """Build the vision prompt from the page context.

    The prompt is Czech: the model reads a Czech document and the
    descriptions must be Czech too.
    """
    blocks = page_context["blocks"]
    prev_text = page_context["prev_page_text"]
    next_text = page_context["next_page_text"]

    # Page blocks go in as JSON text so the model sees the structure:
    # which block follows which, where text is, where a scheme is.
    blocks_json = json.dumps(blocks, ensure_ascii=False, indent=2)

    prompt = f"""Jsi expert na stavební a technickou dokumentaci.

Na obrázku je jedna strana technické normy. Níže je seznam všech bloků
této strany ve formátu JSON (v pořadí, jak jdou na straně):

{blocks_json}

Pro kontext uvádím text sousedních stran:

--- PŘEDCHOZÍ STRANA ---
{prev_text or "(žádná předchozí strana)"}

--- NÁSLEDUJÍCÍ STRANA ---
{next_text or "(žádná následující strana)"}

ÚKOL:
Popiš každý blok typu "figure" a "table". U schémat a výkresů popiš,
co znázorňují, jaké prvky obsahují a k čemu slouží. U tabulek popiš,
jaká data obsahují. Využij okolní text a popisky pro přesnost.

Pokud je blok jen logo, razítko nebo dekorativní prvek bez technického
významu, jako popis uveď přesně: "NENÍ TECHNICKÝ OBSAH".

ODPOVĚĎ:
Vrať POUZE validní JSON — pole objektů. Každý objekt má dva klíče:
"block_id" a "description". Popis je v češtině.
Nepřidávej žádný text mimo JSON.

Příklad formátu odpovědi:
[
  {{"block_id": "p12_b03", "description": "Schéma znázorňuje..."}},
  {{"block_id": "p12_b07", "description": "Tabulka obsahuje..."}}
]
"""
    return prompt


def parse_vision_response(raw_text: str) -> list[dict]:
    """Parse the model's text answer into a list of dicts.

    The model should return a JSON array [{block_id, description}, ...]
    but sometimes wraps it in markdown (```json ... ```). On failure an
    empty list is returned — one bad page must not crash the program.
    """
    text = raw_text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        print("  [!] Could not parse the model answer as JSON")
        return []

    if not isinstance(result, list):
        print("  [!] The model answer is not a list")
        return []

    return result


# Pauses between vision retries (seconds). Transient OpenAI hiccups live
# for seconds — two instant calls hit the same hiccup; a pause heals it.
RETRY_DELAYS = (2.0, 5.0)


class VisionEmptyResponseError(Exception):
    """Vision returned an empty/broken answer for a page that has blocks.

    HTTP 200 with empty content (model refusal) or non-JSON. Without this
    error the page was marked "described" and its schemes fell out of the
    index forever.
    """


def describe_page_visuals(
    document: dict,
    page_number: int,
    image_path: str | Path,
    model: str = VISION_MODEL,
) -> tuple[dict[str, str], int, int]:
    """Describe every figure/table block on one page via the vision LLM.

    Returns (descriptions, prompt_tokens, completion_tokens);
    descriptions is {block_id: description}. The document is read-only —
    accumulation and saving are the caller's job.
    """
    page_context = get_page_context(document, page_number)
    if not page_context["blocks"]:
        return {}, 0, 0

    prompt = build_vision_prompt(page_context)

    # Retry empty/broken answers with pauses (RETRY_DELAYS): two instant
    # calls used to land in the same OpenAI hiccup window (live case
    # 2026-08-02). The page HAS blocks (checked above), so emptiness
    # after all attempts is a failure, not "nothing to describe": marking
    # such a page as processed silently is forbidden.
    prompt_tokens = completion_tokens = 0
    for attempt in range(len(RETRY_DELAYS) + 1):
        raw_answer, in_tok, out_tok = ask_vision(image_path, prompt, model=model)
        prompt_tokens += in_tok
        completion_tokens += out_tok
        desc_by_id = {
            item["block_id"]: item["description"]
            for item in parse_vision_response(raw_answer)
            if "block_id" in item and "description" in item
        }
        if desc_by_id:
            return desc_by_id, prompt_tokens, completion_tokens
        if attempt < len(RETRY_DELAYS):
            time.sleep(RETRY_DELAYS[attempt])
    raise VisionEmptyResponseError(
        f"Vision nevrátil použitelný popis stránky {page_number}"
    )


def _strip_json_markdown(raw: str) -> str:
    """Strip a ```json ... ``` markdown wrapper around the model answer."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


# Sheet-passport fields and their Czech labels (the label itself is a
# useful search term). "druh"/"objekt" form the lead line, "popis" is a
# separate paragraph; these are the middle. The exact title block is
# duplicated by the chunk's OCR text, but clean vision values search
# better than noisy OCR.
_DRAWING_META_LABELS = (
    ("nazev", "Název výkresu"),
    ("stavba", "Stavba"),
    ("lokalita", "Lokalita"),
    ("investor", "Investor"),
    ("rok", "Rok"),
    ("typ_akce", "Typ akce"),
)


# Discipline derived from the investor in the title block. Vision
# confuses the discipline (writes "železniční" for a road bridge) while
# reading the investor correctly — so the discipline is derived
# deterministically, like the stage from text. Long names first so they
# match before abbreviations.
_OBOR_BY_INVESTOR = (
    ("správa železnic", "železniční"),
    ("české dráhy", "železniční"),
    ("ředitelství silnic a dálnic", "silniční"),
    ("řsd", "silniční"),
)


def obor_from_investor(investor: str) -> str:
    """Discipline (železniční/silniční) from the investor; unknown → ""."""
    low = investor.lower()
    for needle, obor in _OBOR_BY_INVESTOR:
        if needle in low:
            return obor
    return ""


def _looks_meaningful(value: str) -> bool:
    """True when the string carries information: a word of ≥3 letters or a
    number of ≥2 digits.

    Filters vision junk like `km "` (unreadable fields produce stubs).
    """
    return bool(re.search(r"[^\W\d_]{3,}", value) or re.search(r"\d{2,}", value))


def _assemble_drawing_description(meta: dict) -> str:
    """Assemble the sheet's search passport (see DRAWING_PROMPT).

    Lead line: discipline (from investor) + construction type + object
    (most important terms first), then labeled title-block facts, then
    the concrete element description (popis). Empty/junk fields skipped.
    """
    druh = (meta.get("druh") or "").strip()
    obor = obor_from_investor(meta.get("investor") or "")
    if obor and obor not in druh.lower():
        druh = f"{obor} {druh}".strip()

    objekt = (meta.get("objekt") or "").strip()
    lead = ". ".join(p for p in (druh, objekt) if p)

    facts = [
        f"{label}: {value.strip()}"
        for key, label in _DRAWING_META_LABELS
        if (value := (meta.get(key) or "").strip()) and _looks_meaningful(value)
    ]

    popis = (meta.get("popis") or "").strip()

    parts = [p for p in (lead, "\n".join(facts), popis) if p]
    return "\n\n".join(parts)


def describe_drawing(
    image_path: str | Path, model: str = VISION_MODEL
) -> tuple[str, int, int]:
    """Vision description of a drawing page — a search-rich sheet passport.

    Returns (description_text, prompt_tokens, completion_tokens).
    Broken/empty answers retry with pauses (RETRY_DELAYS).

    The title block yields as many identifying fields as possible (object
    type, investor, year, stage, location…) so the sheet stands out in
    both BM25 and the vector. The title/text layer is NOT included here —
    it arrives separately (OCR).
    """
    meta: dict = {}
    prompt_tokens = completion_tokens = 0
    for attempt in range(len(RETRY_DELAYS) + 1):
        raw, p_tok, c_tok = ask_vision(image_path, DRAWING_PROMPT, model=model)
        prompt_tokens += p_tok
        completion_tokens += c_tok
        try:
            parsed = json.loads(_strip_json_markdown(raw))
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            meta = parsed
        if meta.get("druh") or meta.get("objekt") or meta.get("popis"):
            break
        if attempt < len(RETRY_DELAYS):
            time.sleep(RETRY_DELAYS[attempt])

    return _assemble_drawing_description(meta), prompt_tokens, completion_tokens


def extract_document_metadata(
    image_path: str | Path, model: str = VISION_MODEL
) -> tuple[dict, int, int]:
    """Extract the document title and short summary from its first page.

    Returns (meta, prompt_tokens, completion_tokens); meta has 'title'
    and 'summary'. On parse failure meta holds empty strings but the
    token counts are real (the request did happen).
    """
    prompt = """Jsi expert na stavební a technickou dokumentaci.

Na obrázku je titulní strana technické normy nebo vzorového listu.

ÚKOL:
1. Urči celý oficiální název dokumentu (číslo i název dohromady).
2. Napiš krátké shrnutí (1-2 věty), o čem dokument je a k čemu slouží.

ODPOVĚĎ:
Vrať POUZE validní JSON s dvěma klíči: "title" a "summary".
Obojí v češtině. Nepřidávej žádný text mimo JSON.

Příklad formátu:
{"title": "MVL 649 Železobetonové trubní propustky", "summary": "Dokument stanovuje technické podmínky pro..."}
"""

    raw_answer, prompt_tokens, completion_tokens = ask_vision(
        image_path, prompt, model=model
    )

    # A single object is expected here, not a list — parsed separately.
    text = raw_answer.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("  [!] Could not parse the document metadata")
        return {"title": "", "summary": ""}, prompt_tokens, completion_tokens

    meta = {
        "title": data.get("title", ""),
        "summary": data.get("summary", ""),
    }
    return meta, prompt_tokens, completion_tokens
