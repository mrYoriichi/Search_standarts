"""
Описание схем и таблиц через vision LLM (OpenAI).

Берёт скриншот страницы, отправляет в модель с просьбой описать
изображённые на ней схемы/таблицы, возвращает ответ модели.
"""
import base64
from pathlib import Path

from openai import OpenAI


# Модель для распознавания изображений.
# Вынесена в константу — поменять модель = поменять одну строку.
VISION_MODEL = "gpt-5.4-mini"


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


def ask_vision(image_path: str | Path, prompt: str) -> str:
    """
    Отправляет один запрос в vision LLM: картинка + текстовый промпт.
    Возвращает текстовый ответ модели.

    image_path — путь к PNG-скриншоту страницы.
    prompt     — текстовая инструкция для модели.
    """
    # Клиент сам найдёт ключ в переменной окружения OPENAI_API_KEY
    client = OpenAI()

    # Кодируем картинку в base64
    base64_image = encode_image_to_base64(image_path)

    # Формируем запрос. content — это список из двух частей:
    # текстовая инструкция и картинка.
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        },
                    },
                ],
            }
        ],
    )

    # Ответ модели лежит внутри структуры response
    return response.choices[0].message.content


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


import json


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
        lines = lines[1:]          # убрать первую строку
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]     # убрать последнюю строку
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
) -> dict[str, str]:
    """
    Описывает все блоки figure/table на одной странице через vision LLM.

    Возвращает словарь {block_id: description}. Сам документ не меняет —
    накопление описаний и сохранение делает вызывающая сторона.

    document     — словарь документа (только для чтения, нужен для контекста);
    page_number  — номер обрабатываемой страницы;
    image_path   — путь к PNG-скриншоту этой страницы.
    """
    # 1. Собираем контекст страницы
    page_context = get_page_context(document, page_number)
    if not page_context["blocks"]:
        return {}

    # 2. Строим промпт
    prompt = build_vision_prompt(page_context)

    # 3. Отправляем в модель
    raw_answer = ask_vision(image_path, prompt)

    # 4. Разбираем ответ в список {block_id, description}
    descriptions = parse_vision_response(raw_answer)
    if not descriptions:
        return {}

    # 5. Превращаем список описаний в словарь {block_id: description}
    return {
        item["block_id"]: item["description"]
        for item in descriptions
        if "block_id" in item and "description" in item
    }


def extract_document_metadata(image_path: str | Path) -> dict:
    """
    Извлекает название и краткое описание документа по его первой странице.

    Возвращает словарь с двумя ключами:
      - title: полное название документа;
      - summary: краткое описание (1-2 предложения), о чём документ.

    При неудаче возвращает пустые строки — не роняем программу.
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

    raw_answer = ask_vision(image_path, prompt)

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
        return {"title": "", "summary": ""}

    # Берём поля с подстраховкой — если модель что-то не вернула
    return {
        "title": data.get("title", ""),
        "summary": data.get("summary", ""),
    }