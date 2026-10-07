#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
    PROJECT_ROOT="$SCRIPT_DIR"
else
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$APPLICATIONS_DIR/embedded-notebook.desktop"
STANDARD_DESKTOP="$HOME/.local/share/applications/embedded-notebook.desktop"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/EmbeddedNotebook"

# Safety sanity check: never delete system roots or user home
if [[ -z "$PROJECT_ROOT" || "$PROJECT_ROOT" == "/" || "$PROJECT_ROOT" == "$HOME" ]]; then
    printf 'Error: Refusing to delete unsafe directory path: %s\n' "$PROJECT_ROOT" >&2
    exit 1
fi

FORCE=false
for arg in "${@:-}"; do
    if [[ "$arg" == "-y" || "$arg" == "--yes" || "$arg" == "-f" || "$arg" == "--force" ]]; then
        FORCE=true
    fi
done

if [[ "$FORCE" = false ]]; then
    printf 'WARNING: This will permanently uninstall Embedded Notebook and remove:\n'
    printf '  - Desktop launcher and application shortcuts\n'
    printf '  - User configuration and saved settings\n'
    printf '  - ALL files and subdirectories in: %s (including .embedded toolchains and .venv)\n\n' "$PROJECT_ROOT"
    read -rp "Are you sure you want to permanently delete everything? [y/N]: " confirm
    case "$confirm" in
        [yY]|[yY][eE][sS]) ;;
        *)
            printf 'Uninstallation aborted.\n'
            exit 0
            ;;
    esac
fi

printf '\nUninstalling Embedded Notebook...\n\n'

# 1. Remove desktop launcher
REMOVED_DESKTOP=false
if [[ -f "$DESKTOP_FILE" ]]; then
    printf 'Removing desktop entry: %s\n' "$DESKTOP_FILE"
    rm -f "$DESKTOP_FILE" || true
    REMOVED_DESKTOP=true
fi

if [[ "$DESKTOP_FILE" != "$STANDARD_DESKTOP" && -f "$STANDARD_DESKTOP" ]]; then
    printf 'Removing desktop entry: %s\n' "$STANDARD_DESKTOP"
    rm -f "$STANDARD_DESKTOP" || true
    REMOVED_DESKTOP=true
fi

if [[ "$REMOVED_DESKTOP" = true ]]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
        update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
    fi
    printf 'Desktop launcher removed.\n'
else
    printf 'No desktop entry found.\n'
fi

# 2. Remove user configuration/settings
if [[ -d "$CONFIG_DIR" ]]; then
    printf 'Removing user settings directory: %s\n' "$CONFIG_DIR"
    rm -rf "$CONFIG_DIR" || true
fi

# 3. Remove all files from project directory
printf 'Removing all files in %s...\n' "$PROJECT_ROOT"
cd /tmp
rm -rf "$PROJECT_ROOT"

printf '\nUninstallation complete! All files from the directory and system shortcuts have been removed.\n'
