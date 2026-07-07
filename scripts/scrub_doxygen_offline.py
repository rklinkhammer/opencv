#!/usr/bin/env python3
"""Scrub outbound HTTP(S) links from generated Doxygen HTML for offline use.

Usage:
    python scripts/scrub_doxygen_offline.py [html_root]

Default html_root:
    docs/generated/doxygen/html
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


HTTP_LINK_RE = re.compile(r'href="https?://[^"]+"')
HTTP_SRC_RE = re.compile(r'src="https?://[^"]+"')
DOCTYPE_HTTP_RE = re.compile(r"<!DOCTYPE[^>]+https?://[^>]+>", re.IGNORECASE)
XMLNS_HTTP_RE = re.compile(r'xmlns="https?://www\.w3\.org/1999/xhtml"')


def scrub_file(path: Path) -> tuple[bool, int]:
    """Remove remote references from one HTML file and report whether it changed.

    The rewrite is idempotent. The returned integer is retained for compatibility
    with callers that aggregate per-file change counts.
    """

    original = path.read_text(encoding="utf-8")
    updated = original

    updated = HTTP_LINK_RE.sub('href="#"', updated)
    updated = HTTP_SRC_RE.sub('src=""', updated)
    # Remove remote doctype URL to avoid external reference declarations.
    updated = DOCTYPE_HTTP_RE.sub("<!DOCTYPE html>", updated)
    # Replace XHTML namespace URI with a neutral namespace string.
    updated = XMLNS_HTTP_RE.sub('xmlns="urn:doxygen:xhtml"', updated)

    if updated == original:
        return False, 0

    path.write_text(updated, encoding="utf-8")
    return True, 1


def main(argv: list[str]) -> int:
    """Scrub an HTML tree selected from command-line arguments and return an exit code."""

    root = Path(argv[1]) if len(argv) > 1 else Path("docs/generated/doxygen/html")
    if not root.exists() or not root.is_dir():
        print(f"Error: HTML directory not found: {root}")
        return 1

    changed_files = 0
    for html_file in root.rglob("*.html"):
        changed, _ = scrub_file(html_file)
        if changed:
            changed_files += 1

    print(f"Offline scrub complete. Files changed: {changed_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
