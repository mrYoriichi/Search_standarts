"""
Тест vision-моделей на чертёжных листах (VL).

Что делает: берёт несколько страниц-листов из VL-PDF, рендерит их в PNG,
прогоняет каждую через указанные модели с одним VL-промптом и сохраняет
описания в файлы + печатает токены и цену за страницу.

Цель — глазами сравнить качество описаний mini vs gpt-5.5 и узнать
реальную цену одной страницы, прежде чем гонять весь документ (151 стр.).

Запуск из корня репозитория:
    python -m vl_pipeline.test_vision

Параметры (PDF, страницы, модели) — константы ниже, правь под себя.
"""
import json
import subprocess
import textwrap
from pathlib import Path

from dotenv import load_dotenv

from pdf_processing.image_description import ask_vision

# .env с OPENAI_API_KEY лежит в корне репозитория
load_dotenv()

# ---------- Настройки теста (правь под себя) ----------

# Путь к тестовому VL-PDF
PDF_PATH = Path("/Users/maximmaltsev/projects/VL_pipeline/Sample/VL4_2021_final.pdf")

# Страницы-листы из разных частей документа (чертежи начинаются со стр. 14)
TEST_PAGES: list[int] = [20, 75, 130]

# Модели для сравнения: (id_модели, цена_вход_за_1M, цена_выход_за_1M).
# Цены в USD за 1M токенов. Картинка тарифицируется как input-токены.
# Если id mini-модели другой — поменяй строку.
MODELS: list[tuple[str, float, float]] = [
    ("gpt-5.4-mini", 0.75, 4.50),
    ("gpt-5.5", 5.0, 30.0),
]

# Разрешение рендера страницы (DPI). 200 хватает, чтобы прочитать штамп.
RENDER_DPI = 200

# Куда складывать PNG и текстовые описания
OUTPUT_DIR = Path(__file__).parent / "test_output"


# ---------- VL-промпт ----------

VL_PROMPT = """Jsi expert na stavební a mostní dokumentaci.

Na obrázku je jeden vzorový list (VL) — technický výkres mostního detailu.
Vzorový list obvykle obsahuje: výkres detailu, blok "POZNÁMKY" (číslované
textové poznámky) a razítko vpravo dole (kód listu jako "VL 4 101.07",
datum, název listu a označení řady).

ÚKOL:
Z obrázku vyčti informace a vrať POUZE validní JSON s těmito klíči:
- "kod": kód listu z razítka bez prefixu (např. "101.07"); pokud nelze, ""
- "nazev": název listu z razítka
- "rada": označení řady / skupiny (např. "ŘADA 100 – PROSTOROVÉ USPOŘÁDÁNÍ")
- "popis_vykresu": podrobný technický popis výkresu — co detail znázorňuje,
  VŠECHNY viditelné konstrukční prvky a jejich vzájemné uspořádání, klíčové
  kótované rozměry a hodnoty (min. sklony, tloušťky, vzdálenosti), použité
  materiály a k čemu detail slouží. Popisuj POUZE to, co je na výkrese
  skutečně vidět — nic si nevymýšlej a nedoplňuj neexistující údaje
- "poznamky": přepiš VŠECHNY číslované poznámky z bloku POZNÁMKY přesně jako
  text (zachovej čísla i odkazy na normy a jiné listy)

Vše v češtině. Nepřidávej žádný text mimo JSON.
"""


def render_page(pdf_path: Path, page: int, out_dir: Path) -> Path:
    """
    Рендерит одну страницу PDF в PNG через pdftoppm (poppler).

    Возвращает путь к готовому PNG. pdftoppm сам добавляет к префиксу
    номер страницы, поэтому строим префикс и потом находим файл.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / f"page_{page:03d}"
    subprocess.run(
        [
            "pdftoppm",
            "-f", str(page),
            "-l", str(page),
            "-png",
            "-r", str(RENDER_DPI),
            str(pdf_path),
            str(prefix),
        ],
        check=True,
    )
    # pdftoppm пишет имя вида page_020-20.png; берём первый подходящий
    matches = sorted(out_dir.glob(f"page_{page:03d}*.png"))
    if not matches:
        raise FileNotFoundError(f"pdftoppm не создал PNG для стр. {page}")
    return matches[0]


def format_readable(data: dict) -> str:
    """
    Превращает разобранный ответ модели в удобный для чтения текст.

    Поля-заголовки + перенос длинных абзацев по ширине, чтобы описание
    и примечания не шли одной длинной строкой.
    """
    width = 90
    lines: list[str] = [
        f"KÓD:   {data.get('kod', '')}",
        f"NÁZEV: {data.get('nazev', '')}",
        f"ŘADA:  {data.get('rada', '')}",
        "",
        "POPIS VÝKRESU:",
        textwrap.fill(data.get("popis_vykresu", ""), width=width),
        "",
        "POZNÁMKY:",
    ]

    poznamky = data.get("poznamky", [])
    if isinstance(poznamky, str):
        poznamky = [poznamky]
    for note in poznamky:
        # subsequent_indent — чтобы перенос длинной поznámky был с отступом
        lines.append(textwrap.fill(str(note), width=width, subsequent_indent="   "))

    return "\n".join(lines)


def pretty_description(raw_answer: str) -> str:
    """
    Приводит ответ модели к читаемому виду.

    Если это валидный JSON-объект — раскладываем по полям с переносом строк
    (format_readable). Если разобрать не вышло — отдаём сырой текст (модель
    что-то вернула криво, но человеку всё равно полезно посмотреть).
    """
    text = raw_answer.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return raw_answer
    if not isinstance(data, dict):
        return raw_answer
    return format_readable(data)


def cost_usd(prompt_tokens: int, completion_tokens: int,
             in_price: float, out_price: float) -> float:
    """USD за один вызов по факту токенов и цен модели."""
    return (
        prompt_tokens * in_price / 1_000_000
        + completion_tokens * out_price / 1_000_000
    )


def main() -> None:
    """Прогоняет тест: рендер страниц → каждая модель → файлы + сводка."""
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF не найден: {PDF_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Рендерим страницы один раз (переиспользуем для всех моделей)
    print("Рендерю страницы в PNG...")
    page_images: dict[int, Path] = {
        page: render_page(PDF_PATH, page, OUTPUT_DIR) for page in TEST_PAGES
    }

    # 2. Каждая модель × каждая страница
    # Сводка цен: {model: [(page, cost), ...]}
    summary: dict[str, list[tuple[int, float]]] = {}

    for model, in_price, out_price in MODELS:
        print(f"\n===== Модель: {model} =====")
        summary[model] = []
        for page in TEST_PAGES:
            image_path = page_images[page]
            answer, p_tokens, c_tokens = ask_vision(image_path, VL_PROMPT, model)
            cost = cost_usd(p_tokens, c_tokens, in_price, out_price)
            summary[model].append((page, cost))

            # Сохраняем описание в файл для спокойного чтения
            safe_model = model.replace("/", "_")
            out_file = OUTPUT_DIR / f"{safe_model}__p{page:03d}.txt"
            out_file.write_text(pretty_description(answer), encoding="utf-8")

            print(
                f"  стр {page}: {p_tokens} in / {c_tokens} out токенов, "
                f"${cost:.4f}  →  {out_file.name}"
            )

    # 3. Итоговая сводка цены за страницу
    print("\n===== Цена за страницу =====")
    for model, in_price, out_price in MODELS:
        costs = [c for _, c in summary[model]]
        avg = sum(costs) / len(costs) if costs else 0.0
        full_doc = avg * 138  # ~138 чертёжных листов (стр. 14-151)
        print(
            f"  {model}: средняя ${avg:.4f}/стр, "
            f"прогноз на ~138 листов ≈ ${full_doc:.2f}"
        )


if __name__ == "__main__":
    main()
