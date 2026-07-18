"""
Описание схем и таблиц через vision LLM (OpenAI).

Берёт скриншот страницы, отправляет в модель с просьбой описать
изображённые на ней схемы/таблицы, возвращает ответ модели.
"""

import base64
import json
import re
from pathlib import Path

from openai import OpenAI


# Модель для распознавания изображений (дефолт). В приложении выбор перекрывается
# настройкой vision_model («Knihovna»); эта константа — дефолт для CLI/функций.
VISION_MODEL = "gpt-5.4-mini"

# Промпт для vision-описания чертёжной страницы (целый лист = одна картинка).
# Задача — не «что видно», а НАСЫЩЕННЫЙ поисковый паспорт листа: из росписки
# (razítko) вытаскиваем максимум идентифицирующих терминов (тип объекта,
# инвестор, год, стадия, новостройка/реконструкция), которые помогают и
# полнотекстовому (BM25), и векторному поиску отличить этот лист от чужого.
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
    """
    Читает файл картинки и кодирует его в строку base64.

    OpenAI API принимает картинки не как файлы, а как текст в формате base64
    (это способ представить двоичные данные обычными символами).
    """
    with open(image_path, "rb") as f:
        # f.read() — двоичное содержимое файла
        # base64.b64encode — кодирует его в base64
        # .decode("utf-8") — превращает байты в обычную строку
        return base64.b64encode(f.read()).decode("utf-8")


def ask_vision(
    image_path: str | Path,
    prompt: str,
    model: str = VISION_MODEL,
) -> tuple[str, int, int]:
    """
    Отправляет один запрос в vision LLM: картинка + текстовый промпт.

    Возвращает кортеж (текст_ответа, prompt_tokens, completion_tokens).
    Токены нужны для подсчёта стоимости вызова (см. pricing.py).

    image_path — путь к PNG-скриншоту страницы.
    prompt     — текстовая инструкция для модели.
    model      — id модели; по умолчанию VISION_MODEL. Параметр нужен,
                 чтобы сравнивать модели на одной картинке (VL-тест).
    """
    # Клиент сам найдёт ключ в переменной окружения OPENAI_API_KEY
    client = OpenAI()

    # Кодируем картинку в base64
    base64_image = encode_image_to_base64(image_path)

    # Формируем запрос. content — это список из двух частей:
    # текстовая инструкция и картинка.
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

    # OpenAI возвращает использованные токены в response.usage.
    # prompt_tokens включает токены и текста, и картинки.
    return (
        response.choices[0].message.content,
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
    )


def get_page_context(document: dict, page_number: int) -> dict:
    """
    Собирает контекст одной страницы для отправки в vision LLM.

    Возвращает словарь с тремя ключами:
      - blocks: все блоки страницы (по порядку);
      - prev_page_text: текст предыдущей страницы (или пустая строка);
      - next_page_text: текст следующей страницы (или пустая строка).
    """
    # Превращаем список страниц в словарь {номер: страница} для быстрого доступа
    pages_by_number = {p["page_number"]: p for p in document["pages"]}

    current_page = pages_by_number.get(page_number)
    if current_page is None:
        # Такой страницы нет — возвращаем пустой контекст
        return {"blocks": [], "prev_page_text": "", "next_page_text": ""}

    # Текст соседних страниц. .get(..., {}) — если соседа нет,
    # берём пустой словарь, чтобы следующий .get не упал.
    prev_page = pages_by_number.get(page_number - 1, {})
    next_page = pages_by_number.get(page_number + 1, {})

    return {
        "blocks": current_page["blocks"],
        "prev_page_text": prev_page.get("page_text", ""),
        "next_page_text": next_page.get("page_text", ""),
    }


def build_vision_prompt(page_context: dict) -> str:
    """
    Строит текстовый промпт для vision LLM на основе контекста страницы.

    Промпт на чешском: модель работает с чешским документом,
    описания тоже нужны чешские.
    """
    blocks = page_context["blocks"]
    prev_text = page_context["prev_page_text"]
    next_text = page_context["next_page_text"]

    # Блоки страницы — отдаём модели как JSON-текст, чтобы она видела
    # структуру: какой блок за каким идёт, где текст, где схема.
    blocks_json = json.dumps(blocks, ensure_ascii=False, indent=2)

    # Собираем промпт по частям. f-строки подставляют переменные в текст.
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
    """
    Разбирает текстовый ответ модели в список словарей.

    Модель должна вернуть JSON-массив [{block_id, description}, ...],
    но иногда оборачивает его в markdown (```json ... ```).
    Эта функция чистит обёртку и парсит JSON.

    При неудаче возвращает пустой список (не роняем всю программу
    из-за одной кривой страницы).
    """
    text = raw_text.strip()

    # Убираем markdown-обёртку ```json ... ``` если она есть
    if text.startswith("```"):
        # Разбиваем по строкам, выкидываем первую (```json) и последнюю (```)
        lines = text.split("\n")
        lines = lines[1:]  # убрать первую строку
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # убрать последнюю строку
        text = "\n".join(lines)

    # Пытаемся разобрать JSON
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Модель вернула что-то не похожее на JSON
        print("  [!] Не удалось разобрать ответ модели как JSON")
        return []

    # Подстраховка: ожидаем именно список
    if not isinstance(result, list):
        print("  [!] Ответ модели не является списком")
        return []

    return result


def describe_page_visuals(
    document: dict,
    page_number: int,
    image_path: str | Path,
    model: str = VISION_MODEL,
) -> tuple[dict[str, str], int, int]:
    """
    Описывает все блоки figure/table на одной странице через vision LLM.

    Возвращает кортеж (descriptions, prompt_tokens, completion_tokens).
    descriptions — словарь {block_id: description}. Документ не меняет —
    накопление и сохранение делает вызывающая сторона.

    document     — словарь документа (только для чтения, нужен для контекста);
    page_number  — номер обрабатываемой страницы;
    image_path   — путь к PNG-скриншоту этой страницы.
    """
    # 1. Собираем контекст страницы
    page_context = get_page_context(document, page_number)
    if not page_context["blocks"]:
        return {}, 0, 0

    # 2. Строим промпт
    prompt = build_vision_prompt(page_context)

    # 3. Отправляем в модель — получаем ответ и счётчики токенов
    raw_answer, prompt_tokens, completion_tokens = ask_vision(
        image_path, prompt, model=model
    )

    # 4. Разбираем ответ в список {block_id, description}
    descriptions = parse_vision_response(raw_answer)
    if not descriptions:
        return {}, prompt_tokens, completion_tokens

    # 5. Превращаем список описаний в словарь {block_id: description}
    desc_by_id = {
        item["block_id"]: item["description"]
        for item in descriptions
        if "block_id" in item and "description" in item
    }
    return desc_by_id, prompt_tokens, completion_tokens


def _strip_json_markdown(raw: str) -> str:
    """Убирает markdown-обёртку ```json ... ``` вокруг ответа модели."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


# Поля паспорта листа и их чешские подписи (подпись сама — полезный термин).
# "druh"/"objekt" — ведущая строка, "popis" — отдельным абзацем; здесь середина.
# Точный штамп дублируется из OCR-текста чанка, но чистые значения из vision
# лучше ложатся в поиск, чем шумный OCR.
_DRAWING_META_LABELS = (
    ("nazev", "Název výkresu"),
    ("stavba", "Stavba"),
    ("lokalita", "Lokalita"),
    ("investor", "Investor"),
    ("rok", "Rok"),
    ("typ_akce", "Typ akce"),
)


# Обор конструкции по инвестору из росписки. Vision путает обор (пишет
# «železniční» у silničního mostu), хотя инвестора читает верно — выводим
# обор детерминированно из инвестора, как ступень из текста. Длинное имя
# впереди, чтобы оно сработало раньше аббревиатуры.
_OBOR_BY_INVESTOR = (
    ("správa železnic", "železniční"),
    ("české dráhy", "železniční"),
    ("ředitelství silnic a dálnic", "silniční"),
    ("řsd", "silniční"),
)


def obor_from_investor(investor: str) -> str:
    """Обор (železniční/silniční) по инвестору из росписки. Неизвестный → ""."""
    low = investor.lower()
    for needle, obor in _OBOR_BY_INVESTOR:
        if needle in low:
            return obor
    return ""


def _looks_meaningful(value: str) -> bool:
    """True, если строка несёт инфу: есть слово из ≥3 букв или число из ≥2 цифр.

    Отсекает мусор vision вроде `km "` (у нечитаемого поля модель выдаёт огрызок).
    """
    return bool(re.search(r"[^\W\d_]{3,}", value) or re.search(r"\d{2,}", value))


def _assemble_drawing_description(meta: dict) -> str:
    """Собирает поисковый паспорт листа (см. DRAWING_PROMPT).

    Ведущая строка — обор (из инвестора) + тип конструкции + объект (самые
    важные термины впереди), затем факты из росписки с подписями, в конце —
    конкретное описание элементов (popis). Пустые/мусорные поля пропускаем.
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
    """Vision-описание чертёжной страницы — насыщенный поисковый паспорт листа.

    Возвращает (текст_описания, prompt_tokens, completion_tokens). Токены —
    для подсчёта стоимости вызывающим (как в остальных функциях модуля).
    Битый/пустой ответ повторяем один раз — разовые сбои vision самочинятся.

    Из росписки тянем максимум идентифицирующих полей (тип объекта, инвестор,
    год, стадия, локация…) — чтобы лист хорошо отличался и в BM25, и в векторе.
    Название/текстовый слой сюда НЕ кладём: они добираются отдельно (OCR).
    """
    meta: dict = {}
    prompt_tokens = completion_tokens = 0
    for _ in range(2):
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

    return _assemble_drawing_description(meta), prompt_tokens, completion_tokens


def extract_document_metadata(
    image_path: str | Path, model: str = VISION_MODEL
) -> tuple[dict, int, int]:
    """
    Извлекает название и краткое описание документа по его первой странице.

    Возвращает кортеж (meta, prompt_tokens, completion_tokens).
    meta — словарь с ключами 'title' и 'summary'.

    При неудаче разбора возвращает пустые строки в meta, но токены — реальные
    (запрос всё равно был сделан).
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

    # Разбираем ответ. Здесь ожидаем не список, а один объект,
    # поэтому parse_vision_response не подходит — парсим отдельно.
    text = raw_answer.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("  [!] Не удалось разобрать метаданные документа")
        return {"title": "", "summary": ""}, prompt_tokens, completion_tokens

    # Берём поля с подстраховкой — если модель что-то не вернула
    meta = {
        "title": data.get("title", ""),
        "summary": data.get("summary", ""),
    }
    return meta, prompt_tokens, completion_tokens
