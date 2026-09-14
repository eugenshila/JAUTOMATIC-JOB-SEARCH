"""Small text utilities: HTML stripping, token matching."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterable

_BLOCK_TAGS = {
    "p", "div", "li", "ul", "ol", "tr", "table", "section", "article",
    "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
    "br", "dd", "dt", "dl",
}
_SKIP_TAGS = {"script", "style", "noscript"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "li":
            self.parts.append("\n• ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Convert HTML to readable plain text (no external dependencies)."""
    if not html:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


# Tokens that are plain words / phrases get word-boundary matching; anything
# with punctuation (c++, c#, node.js, .net) falls back to substring matching.
_PLAIN_TOKEN = re.compile(r"^[A-Za-z0-9_ \-]+$")


def token_present(token: str, text: str) -> bool:
    """Case-insensitive check whether `token` appears in `text`.

    Whole-word matching for plain words, substring matching for tokens with
    punctuation so that "c++" and "c#" behave sensibly.
    """
    token = (token or "").strip()
    if not token or not text:
        return False
    if _PLAIN_TOKEN.match(token):
        pattern = r"\b" + re.escape(token) + r"\b"
        return re.search(pattern, text, re.IGNORECASE) is not None
    return token.lower() in text.lower()


def any_token_present(tokens: Iterable[str], text: str) -> bool:
    return any(token_present(t, text) for t in tokens)


def truncate(text: str, limit: int, ellipsis: str = "…") -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + ellipsis
