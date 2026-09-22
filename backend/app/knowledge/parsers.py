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
    """逐行扫描 txt：`问题\\t答案` 是一组问答对，一组一个 Section。

    一组问答就是 FAQ 的最小完整语义单元，整篇当一个 Section 再交给滑动窗口会把它
    切碎——一组问答横跨两个块、一个块里塞着上一组的答案尾巴，引用角标指向的位置
    也就不是完整的一组。tab 分隔是强特征，因此这里按内容嗅探、不接收文档类型；
    代价是制表符排版的表格型 txt 会被误判成问答对（见 spec 的 Further Notes）。
    其余行按原样累积成普通 Section，问答节与普通节按文件原始顺序交错。
    """
    sections: list[Section] = []
    buffer: list[str] = []

    def flush_paragraph() -> None:
        text = "\n".join(buffer).strip()
        if text:
            sections.append(Section(heading_path=[], text=text))
        buffer.clear()

    for line in content.decode("utf-8").split("\n"):
        question, separator, answer = line.partition("\t")
        if separator and question.strip():
            flush_paragraph()
            question = question.strip()
            sections.append(
                Section(heading_path=[question], text=f"{question}\n{answer.strip()}")
            )
            continue
        buffer.append(line)
    flush_paragraph()
    return sections


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
