"""Read and write a whole file, closing it afterwards.

Seventeen sites across ten modules did this by hand and left the handle open —
`json.load(open(path))`, `open(path).read().strip()`, `json.dump(d, open(path, 'w'))`.
CPython's refcounting closes those almost immediately, which is why nothing ever visibly
broke; what it does produce is a `ResourceWarning`, and the test suite runs with
`filterwarnings = ["error"]`, so any test that touched one failed.

These are deliberately tiny. They exist for the closing and for having one spelling of
each operation, not to add behaviour.
"""

import json
import os


def read_text(path, errors: str = 'strict', encoding: str = 'utf-8') -> str:
    """The whole file as text.

    The encoding is pinned rather than taken from the locale: a GPX written on one
    machine and read on another must not depend on either one's `LANG`, and under a
    non-UTF-8 locale `errors='replace'` would silently mangle every non-ASCII waypoint
    name instead of reading it.

    `errors='replace'` is the setting the plotter exports want: Raymarine GPX is not
    reliably utf-8, and one bad byte in one waypoint name should not abort a scan over the
    whole corpus.
    """
    with open(path, errors=errors, encoding=encoding) as f:
        return f.read()


def read_stripped(path, errors: str = 'strict', encoding: str = 'utf-8') -> str:
    """The whole file, whitespace-trimmed. Used for the one-line API token file, where a
    smuggled newline in an `authorization:` header is a 401 that reads like expiry."""
    return read_text(path, errors=errors, encoding=encoding).strip()


def write_text(path, text: str, encoding: str = 'utf-8') -> None:
    with open(path, 'w', encoding=encoding) as f:
        f.write(text)


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_json(path, obj, indent: int | None = None) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=indent)


def read_json_or_none(path):
    """`read_json`, or None when the file is not there.

    The gap scans cache the 2.4 MB journey to a file and re-read it on the next run; a
    missing cache is the ordinary first-run case, not an error.
    """
    if not path or not os.path.isfile(path):
        return None
    return read_json(path)
