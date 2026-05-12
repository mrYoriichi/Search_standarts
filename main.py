# Импортируем главный класс Docling для конвертации документов
from docling.document_converter import DocumentConverter

# Путь к нашему тестовому PDF
pdf_path = "data/pdfs/MVL649.pdf"

# Создаём конвертер — это объект, который умеет читать документы
converter = DocumentConverter()

# Просим конвертер обработать наш PDF
# Внутри Docling запустит распознавание структуры, текста, таблиц
result = converter.convert(pdf_path)

# Вытаскиваем результат как markdown-текст и выводим в консоль
print(result.document.export_to_markdown())