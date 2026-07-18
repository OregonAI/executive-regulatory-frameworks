#!/usr/bin/env python3
"""Extract plain text from an HTML snapshot for quote verification.
Usage: python3 src/html_to_text.py _meta/snapshots/foo.html [more.html ...]
Writes foo.txt next to each input."""
import html
import re
import sys
from pathlib import Path


def html_to_text(raw: bytes) -> str:
    m = re.search(rb"charset=([\w-]+)", raw[:2048])
    text = raw.decode(m.group(1).decode() if m else "utf-8", errors="replace")
    text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text))


def main():
    for arg in sys.argv[1:]:
        p = Path(arg)
        out = p.with_suffix(".txt")
        out.write_text(html_to_text(p.read_bytes()), encoding="utf-8")
        print(f"{p} -> {out}")


if __name__ == "__main__":
    main()
