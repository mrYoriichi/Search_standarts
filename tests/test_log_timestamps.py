"""TimestampWriter: время в начале каждой строки app.log."""

import io
import re

from backend.core.log_time import TimestampWriter

TS = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} "


def test_each_line_gets_timestamp() -> None:
    buf = io.StringIO()
    writer = TimestampWriter(buf)
    writer.write("first\nsecond\n")
    lines = buf.getvalue().splitlines()
    assert len(lines) == 2
    assert all(re.match(TS + r"(first|second)$", line) for line in lines)


def test_partial_writes_get_one_timestamp_per_line() -> None:
    # print() пишет текст и "\n" двумя вызовами write — время не должно
    # попадать в середину строки.
    buf = io.StringIO()
    writer = TimestampWriter(buf)
    writer.write("čtení PDF: výkres ")
    writer.write("3/12")
    writer.write("\n")
    assert re.fullmatch(TS + r"čtení PDF: výkres 3/12\n", buf.getvalue())


def test_delegates_file_attrs() -> None:
    # uvicorn на старте зовёт sys.stdout.isatty() — обёртка не должна падать.
    writer = TimestampWriter(io.StringIO())
    assert writer.isatty() is False
