#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Resolve project root (parent directory of Linux/, or SCRIPT_DIR if run from root)
if [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
    PROJECT_ROOT="$SCRIPT_DIR"
else
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

VENV="$PROJECT_ROOT/.venv"

if ! command -v python3 >/dev/null 2>&1; then
    printf 'Python 3 is required to set up Embedded Notebook.\n' >&2
    exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
    printf 'Creating the project virtual environment...\n'
    python3 -m venv "$VENV"
fi

printf 'Installing/updating Python requirements...\n'
"$VENV/bin/python" -m pip install -r "$PROJECT_ROOT/requirements.txt"


APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$APPLICATIONS_DIR/embedded-notebook.desktop"
mkdir -p "$APPLICATIONS_DIR"

desktop_quote() {
    local value="$1"
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//%/%%}
    printf '"%s"' "$value"
}

PYTHON_EXEC="$(desktop_quote "$VENV/bin/python")"
if [[ -f "$PROJECT_ROOT/embedded_notebook2.py" ]]; then
    APP_EXEC="$(desktop_quote "$PROJECT_ROOT/embedded_notebook2.py")"
else
    APP_EXEC="$(desktop_quote "$PROJECT_ROOT/scripts/main.py")"
fi

ICON_PATH="$PROJECT_ROOT/embeddednotebook.png"
if [[ ! -f "$ICON_PATH" && -f "$SCRIPT_DIR/embeddednotebook.png" ]]; then
    ICON_PATH="$SCRIPT_DIR/embeddednotebook.png"
fi

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Embedded Notebook
Comment=Arduino-style notebook for programming microcontrollers
Exec=$PYTHON_EXEC $APP_EXEC
Path=$PROJECT_ROOT
Icon=$ICON_PATH
Terminal=false
Categories=Development;Electronics;
StartupNotify=true
EOF

chmod 644 "$DESKTOP_FILE"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DESKTOP_FILE"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

printf 'Desktop application installed: %s\n' "$DESKTOP_FILE"
printf 'Open Embedded Notebook from your application drawer.\n'
