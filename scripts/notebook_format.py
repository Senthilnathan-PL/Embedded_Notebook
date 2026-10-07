"""
Notebook file I/O for .icpnb and .ipynb (Jupyter nbformat 4).
"""
import copy
import json
import re
import uuid
from pathlib import Path

NB_EXT = ".icpnb"
NB_EXTS = (".icpnb", ".ipynb")
NB_KEY = "embedded_notebook"
NB_MINOR = 5
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class NotebookFormatError(ValueError):
    """The file is not a usable Jupyter (nbformat 4) notebook."""


def new_notebook_metadata():
    return {"language_info": {"name": "c++"}}


def ensure_notebook_suffix(path):
    """Save As rule: keep .icpnb/.ipynb if the user typed one, otherwise append .icpnb."""
    path = Path(path)
    return path if path.suffix.lower() in NB_EXTS else path.with_name(path.name + NB_EXT)


def _source_to_str(src, where):
    if isinstance(src, str):
        return src
    if isinstance(src, list) and all(isinstance(x, str) for x in src):
        return "".join(src)
    raise NotebookFormatError(f"{where}: 'source' must be a string or a list of strings.")


def _source_to_lines(text):
    """nbformat stores source as a list of lines, each keeping its trailing newline."""
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def parse_notebook(text):
    """JSON text -> (cells, notebook_metadata, nbformat_minor). Raises NotebookFormatError."""
    try:
        nb = json.loads(text)
    except json.JSONDecodeError as e:
        raise NotebookFormatError(
            f"The file is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno}).") from None
    except RecursionError:
        raise NotebookFormatError("The JSON is nested too deeply to read.") from None
    if not isinstance(nb, dict):
        raise NotebookFormatError("The top level of a notebook must be a JSON object.")
    ver = nb.get("nbformat")
    if not isinstance(ver, int) or isinstance(ver, bool):
        raise NotebookFormatError("Missing \"nbformat\" field - this is not a Jupyter notebook.")
    if ver != 4:
        raise NotebookFormatError(f"Unsupported notebook format version {ver}; only nbformat 4 is supported.")
    minor = nb.get("nbformat_minor", 0)
    minor = minor if isinstance(minor, int) and not isinstance(minor, bool) and minor >= 0 else 0
    meta = nb.get("metadata", {})
    if not isinstance(meta, dict):
        raise NotebookFormatError("Notebook \"metadata\" must be a JSON object.")
    raw_cells = nb.get("cells")
    if not isinstance(raw_cells, list):
        raise NotebookFormatError("Missing \"cells\" list.")

    cells = []
    for n, c in enumerate(raw_cells, 1):
        where = f"Cell {n}"
        if not isinstance(c, dict):
            raise NotebookFormatError(f"{where} is not a JSON object.")
        kind = c.get("cell_type")
        if kind not in ("code", "markdown", "raw"):
            raise NotebookFormatError(f"{where}: unknown cell_type {kind!r}.")
        source = _source_to_str(c.get("source", ""), where)
        cmeta = c.get("metadata", {})
        if not isinstance(cmeta, dict):
            raise NotebookFormatError(f"{where}: \"metadata\" must be a JSON object.")
        cmeta = copy.deepcopy(cmeta)
        title = deps = ""
        extra = {}
        if kind == "code":
            ours = cmeta.pop(NB_KEY, None)
            if isinstance(ours, dict):
                title = ours["title"] if isinstance(ours.get("title"), str) else ""
                deps = ours["deps"] if isinstance(ours.get("deps"), str) else ""
            outputs = c.get("outputs", [])
            if not isinstance(outputs, list):
                raise NotebookFormatError(f"{where}: \"outputs\" must be a list.")
            ec = c.get("execution_count")
            extra["outputs"] = copy.deepcopy(outputs)
            extra["execution_count"] = ec if isinstance(ec, int) and not isinstance(ec, bool) else None
        elif isinstance(c.get("attachments"), dict):
            extra["attachments"] = copy.deepcopy(c["attachments"])
        extra["metadata"] = cmeta
        if isinstance(c.get("id"), str):
            extra["id"] = c["id"]
        cells.append({"type": kind, "source": source, "title": title, "deps": deps, "extra": extra})
    return cells, copy.deepcopy(meta), minor


def serialize_notebook(cells, metadata, minor=NB_MINOR):
    """Inverse of parse_notebook."""
    out, seen = [], set()
    for c in cells:
        ex = c.get("extra") or {}
        cid = ex.get("id")
        if not (isinstance(cid, str) and _ID_RE.match(cid)) or cid in seen:
            cid = uuid.uuid4().hex[:8]
        seen.add(cid)
        cmeta = copy.deepcopy(ex.get("metadata", {}))
        cell = {"cell_type": c["type"], "id": cid, "source": _source_to_lines(c["source"])}
        if c["type"] == "code":
            if c.get("title") or c.get("deps"):
                cmeta[NB_KEY] = {k: c[k] for k in ("title", "deps") if c.get(k)}
            cell["execution_count"] = ex.get("execution_count")
            cell["outputs"] = copy.deepcopy(ex.get("outputs", []))
        elif "attachments" in ex:
            cell["attachments"] = copy.deepcopy(ex["attachments"])
        cell["metadata"] = cmeta
        out.append(cell)
    nb = {"cells": out, "metadata": metadata, "nbformat": 4, "nbformat_minor": max(minor, NB_MINOR)}
    return json.dumps(nb, indent=1, sort_keys=True, ensure_ascii=False) + "\n"

