import re

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+|[^\sA-Za-z0-9]")


def _token_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _TOKEN_PATTERN.finditer(text)]


def chunk_text(text: str, *, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    spans = _token_spans(text)
    if not spans:
        return []

    step = max(1, chunk_size - overlap)
    chunks: list[str] = []
    start = 0
    total = len(spans)
    while start < total:
        end = min(start + chunk_size, total)
        piece = text[spans[start][0] : spans[end - 1][1]].strip()
        if piece:
            chunks.append(piece)
        if end == total:
            break
        start += step
    return chunks
