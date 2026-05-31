"""
VL: описание чертёжных листов и метаданных документа через LLM.

Чертёжный лист — чистая картинка, поэтому описание чертежа берёт vision
(дешёвая mini: точные термины всё равно даёт OCR). Метаданные документа
(title/summary) извлекаем из текстовой части (стр. 1–13) одним текстовым
вызовом — модель «видит» вводную часть и делает корректное описание.
"""
import json

from openai import OpenAI

from pdf_processing.image_description import ask_vision

# Обе задачи на дешёвой mini (цена gpt-5.4-mini = pricing.answer_cost)
SHEET_MODEL = "gpt-5.4-mini"
META_MODEL = "gpt-5.4-mini"

# Vision-промпт: ТОЛЬКО описание чертежа. Примечания (POZNÁMKY) не
# расшифровываем — их точно даёт OCR (короче выход, дешевле, без порчи).
VL_SHEET_PROMPT = """Jsi expert na stavební a mostní dokumentaci.
Na obrázku je jeden vzorový list (VL) — technický výkres mostního detailu.

ÚKOL:
Z razítka vpravo dole vyčti identifikaci listu a popiš výkres.
Vrať POUZE validní JSON s klíči:
- "kod": kód listu z razítka bez prefixu (např. "101.07"); pokud nelze, ""
- "nazev": název listu z razítka
- "rada": označení řady / skupiny (např. "ŘADA 100 – PROSTOROVÉ USPOŘÁDÁNÍ")
- "popis_vykresu": podrobný technický popis výkresu — co detail znázorňuje,
  viditelné konstrukční prvky a jejich vzájemné uspořádání, klíčové kótované
  rozměry, materiály a k čemu detail slouží. Popisuj POUZE to, co je na
  výkrese skutečně vidět — nic si nevymýšlej.

Blok POZNÁMKY NEPŘEPISUJ — poznámky se získávají zvlášť přes OCR.
Vše v češtině. Nepřidávej žádný text mimo JSON.
"""

META_PROMPT = """Jsi expert na stavební a technickou dokumentaci.
Níže je úvodní text technického dokumentu (vzorové listy).

ÚKOL:
1. Urči celý oficiální název dokumentu.
2. Napiš krátké shrnutí (2-3 věty), o čem dokument je a k čemu slouží.

Vrať POUZE validní JSON s klíči "title" a "summary". Obojí v češtině.
Nepřidávej žádný text mimo JSON.

--- ÚVODNÍ TEXT ---
{text}
"""


def _parse_json_object(raw: str) -> dict:
    """Разбирает JSON-объект из ответа модели, чистя markdown-обёртку."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def describe_sheet(image_path, model: str = SHEET_MODEL) -> tuple[dict, int, int]:
    """
    Описывает один чертёжный лист через vision.

    Возвращает (meta, prompt_tokens, completion_tokens), где meta —
    словарь с ключами kod / nazev / rada / popis_vykresu.

    Если модель вернула пустой результат (битый JSON / пустые поля) —
    один повтор: разовые сбои vision самочинятся, не теряя лист.
    """
    meta: dict = {}
    p_tokens = c_tokens = 0
    for _ in range(2):
        raw, p_tokens, c_tokens = ask_vision(image_path, VL_SHEET_PROMPT, model)
        meta = _parse_json_object(raw)
        # успех — есть хоть код, хоть название, хоть описание
        if meta.get("kod") or meta.get("nazev") or meta.get("popis_vykresu"):
            break
    return meta, p_tokens, c_tokens


def extract_document_metadata(
    front_text: str,
    model: str = META_MODEL,
) -> tuple[dict, int, int]:
    """
    Извлекает title/summary документа из его текстовой (вводной) части.

    Возвращает (meta, prompt_tokens, completion_tokens), где meta —
    словарь с ключами title / summary. Текст обрезаем до 8000 символов
    (вводной части хватает, чтобы понять, о чём документ).
    """
    client = OpenAI()
    prompt = META_PROMPT.format(text=front_text[:8000])
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    data = _parse_json_object(response.choices[0].message.content)
    meta = {"title": data.get("title", ""), "summary": data.get("summary", "")}
    return meta, response.usage.prompt_tokens, response.usage.completion_tokens
