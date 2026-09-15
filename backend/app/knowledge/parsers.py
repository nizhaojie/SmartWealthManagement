import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document

SUPPORTED_EXTENSIONS = (".txt", ".md", ".docx")

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_DOCX_HEADING = re.compile(r"^Heading (\d)$")


@dataclass
class Section:
    heading_path: list[str] = field(default_factory=list)
    text: str = ""


def extension_of(filename: str) -> str:
    return Path(filename).suffix.lower()


def is_supported(filename: str) -> bool:
    return extension_of(filename) in SUPPORTED_EXTENSIONS


def parse_document(filename: str, content: bytes) -> list[Section]:
    ext = extension_of(filename)
    if ext == ".txt":
        return _parse_txt(content)
    if ext == ".md":
        return _parse_markdown(content)
    if ext == ".docx":
        return _parse_docx(content)
    raise ValueError(f"unsupported extension: {ext}")


def _parse_txt(content: bytes) -> list[Section]:
    text = content.decode("utf-8").strip()
    return [Section(heading_path=[], text=text)] if text else []


def _parse_markdown(content: bytes) -> list[Section]:
    lines = content.decode("utf-8").splitlines()
    return _sections_from_lines(
        (
            (len(match.group(1)), match.group(2).strip())
            if (match := _MD_HEADING.match(line))
            else (None, line)
        )
        for line in lines
    )


def _parse_docx(content: bytes) -> list[Section]:
    document = Document(io.BytesIO(content))

    def rows():
        for paragraph in document.paragraphs:
            match = _DOCX_HEADING.match(paragraph.style.name if paragraph.style else "")
            if match:
                yield int(match.group(1)), paragraph.text.strip()
            else:
                yield None, paragraph.text

    return _sections_from_lines(rows())


def _sections_from_lines(rows) -> list[Section]:
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            sections.append(Section(heading_path=[title for _, title in stack], text=text))
        buffer.clear()

    for level, text in rows:
        if level is None:
            if text.strip():
                buffer.append(text)
            continue
        flush()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
    flush()
    return sections
