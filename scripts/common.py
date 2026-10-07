"""
Shared text processing and bracket matching utilities.
"""
import re

_ASTRAL_RE = re.compile(r"[\U00010000-\U0010ffff]")
_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
_BRACKET_OPEN = {value: key for key, value in _BRACKET_PAIRS.items()}


def qt_pos_fn(text):
    """Python str index -> QTextDocument position (Qt counts UTF-16 units, Python code points)."""
    if not _ASTRAL_RE.search(text):
        return lambda i: i
    return lambda i: len(text[:i].encode("utf-16-le")) // 2


def _mask(src):
    """Same-length copy of src with comments and string/char literals blanked."""
    out = list(src)
    n, i = len(src), 0

    def blank(a, b):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif src[i] in "\"'":
            q, j = src[i], i + 1
            while j < n and src[j] != q and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            blank(i, j)
            i = j
        else:
            i += 1
    return "".join(out)


def matching_bracket(src, index):
    """Return the matching bracket index, ignoring comments and string literals."""
    if not 0 <= index < len(src):
        return None
    masked = _mask(src)
    bracket = masked[index]
    if bracket in _BRACKET_PAIRS:
        expected = [_BRACKET_PAIRS[bracket]]
        for pos in range(index + 1, len(masked)):
            char = masked[pos]
            if char in _BRACKET_PAIRS:
                expected.append(_BRACKET_PAIRS[char])
            elif char in _BRACKET_OPEN:
                if char != expected[-1]:
                    continue
                expected.pop()
                if not expected:
                    return pos
    elif bracket in _BRACKET_OPEN:
        expected = [_BRACKET_OPEN[bracket]]
        for pos in range(index - 1, -1, -1):
            char = masked[pos]
            if char in _BRACKET_OPEN:
                expected.append(_BRACKET_OPEN[char])
            elif char in _BRACKET_PAIRS and char == expected[-1]:
                expected.pop()
                if not expected:
                    return pos
    return None

