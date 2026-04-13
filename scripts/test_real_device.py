#!/usr/bin/env python3
"""Smoke-test the supernote_tool API against a real .note file.

Usage:
    python scripts/test_real_device.py path/to/sample.note
"""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: test_real_device.py <path/to/sample.note>", file=sys.stderr)
        return 1

    note_path = sys.argv[1]

    # Step 1: import
    try:
        import supernote_tool  # type: ignore[import]
        version = getattr(supernote_tool, "__version__", "unknown")
        print(f"supernote_tool version: {version}")
    except ImportError as exc:
        print(f"ERROR: Could not import supernote_tool: {exc}", file=sys.stderr)
        return 1

    # Step 2: load_notebook
    try:
        notebook = supernote_tool.load_notebook(note_path)
        print(f"Page count: {len(notebook.pages)}")
    except AttributeError:
        print(f"load_notebook API mismatch. supernote_tool dir: {dir(supernote_tool)}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR loading notebook: {exc}", file=sys.stderr)
        return 1

    if not notebook.pages:
        print("No pages found.")
        return 0

    # Step 3: to_image
    page = notebook.pages[0]
    try:
        img = page.to_image(dpi=200)
        print(f"Image size (with dpi kwarg): {img.size}")
    except TypeError:
        print("to_image() does not accept dpi kwarg — retrying without it")
        try:
            img = page.to_image()
            print(f"Image size (without dpi kwarg): {img.size}")
        except (AttributeError, TypeError) as exc:
            print(f"to_image() API mismatch: {exc}", file=sys.stderr)
            print(f"page dir: {dir(page)}", file=sys.stderr)
            return 1
    except AttributeError:
        print(f"page has no to_image(). page dir: {dir(page)}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
