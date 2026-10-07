"""
Arduino sketch code generation, dependency resolution, and cell merging.
"""
import re
import textwrap
from scripts.common import _mask

_FUNC_RE = re.compile(r"\bvoid\s+(setup|loop)\s*\(\s*(?:void)?\s*\)\s*\{")
_INCLUDE_RE = re.compile(r"\s*#\s*include\b")


def _match_brace(masked, open_idx):
    depth = 0
    for i in range(open_idx, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def split_cell(code):
    """Split cell code into (include_lines, declarations, setup_body, loop_body)."""
    masked = _mask(code)
    bodies, spans = {}, []
    for m in _FUNC_RE.finditer(masked):
        name = m.group(1)
        if name in bodies:
            continue
        open_idx = m.end() - 1
        close = _match_brace(masked, open_idx)
        if close < 0:
            raise ValueError(f"Unbalanced braces in {name}()")
        bodies[name] = code[open_idx + 1:close]
        spans.append((m.start(), close + 1))
    rest = code
    for s, e in reversed(spans):
        rest = rest[:s] + rest[e:]
    includes, decl = [], []
    for line in rest.splitlines():
        (includes if _INCLUDE_RE.match(line) else decl).append(line)
    return (
        [l.strip() for l in includes],
        "\n".join(decl).strip(),
        bodies.get("setup", ""),
        bodies.get("loop", ""),
    )


def _split_deps(text):
    return [t.strip() for t in re.split(r"[,;]", text or "") if t.strip()]


def resolve_order(cells, target):
    """Dependency-first order of cell indices needed to build `target`."""
    def find(token, owner):
        if token.isdigit():
            n = int(token)
            if 1 <= n <= len(cells):
                return n - 1
            raise ValueError(f'Cell {owner + 1} depends on "{token}", but there is no cell {n}.')
        for i, c in enumerate(cells):
            if c["title"].strip().lower() == token.lower():
                return i
        raise ValueError(f'Cell {owner + 1} depends on "{token}", but no cell has that title.')

    order = []

    def visit(i, path):
        if i in order:
            return
        if i in path:
            chain = " -> ".join(str(p + 1) for p in path + [i])
            raise ValueError(f"Circular dependency between cells: {chain}")
        for tok in _split_deps(cells[i]["deps"]):
            visit(find(tok, i), path + [i])
        order.append(i)

    visit(target, [])
    return order


def _block(text, spaces):
    return textwrap.indent(textwrap.dedent(text).strip("\n"), " " * spaces)


def build_sketch(cells, target):
    """cells: list of {"title","deps","code"}. Returns (sketch_source, order)."""
    order = resolve_order(cells, target)
    includes, decls, setups, loop_body = [], [], [], ""
    for i in order:
        c = cells[i]
        inc, decl, setup, loop = split_cell(c["code"])
        includes += [l for l in inc if l not in includes]
        if decl:
            decls.append(f"// ===== Cell {i + 1}: {c['title']} =====\n{decl}")
        if setup.strip():
            setups.append(f"  // {c['title']}\n  {{\n{_block(setup, 4)}\n  }}")
        if i == target:
            loop_body = loop
    parts = []
    if includes:
        parts.append("\n".join(includes))
    parts += decls
    parts.append("void setup() {\n" + "\n".join(setups) + ("\n" if setups else "") + "}")
    parts.append("void loop() {\n" + (_block(loop_body, 2) + "\n" if loop_body.strip() else "") + "}")
    header = (f"// Generated from cell {target + 1} ({cells[target]['title']}); "
              f"cells used: {', '.join(str(i + 1) for i in order)}\n")
    return header + "\n\n".join(parts) + "\n", order

