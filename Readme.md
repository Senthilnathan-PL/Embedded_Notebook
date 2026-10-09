# Embedded Notebook

**Embedded Notebook** is a desktop notebook environment for programming microcontrollers using Arduino-style C/C++. Organize embedded code into modular cells, link cell dependencies, compile and upload directly to boards, and inspect outputs in the built-in serial monitor.

---

## Highlights

- **Cell-Based C/C++ Development**: Break firmware into setup, helper functions, and loop logic across cells.
- **Cell Dependencies**: Declare dependencies (e.g. `1, 2` or `Blink, Sensors`) to merge and build target sketches incrementally.
- **Self-Contained MCU Toolchain**: Bundles its own isolated `arduino-cli`, MCU cores, libraries, and build cache inside `.embedded/` — zero global toolchain clutter.
- **Dual Notebook Format**: Full support for `.icpnb` and standard Jupyter `.ipynb` formats.
- **Rich Media & Markdown**: Embedded Markdown cells support text notes, diagrams, videos, and animated GIFs.
- **Integrated Board & Library Managers**: Install board platforms (NodeMCU/ESP8266, ESP32, AVR, RP2040) and Arduino libraries directly from the UI.
- **Hardware Examples Menu**: Browse board core examples and installed library examples directly from `File → Examples`, opening sketches into notebook cells.

---

## Project Structure

```text
Embedded_Notebook/
├── Linux/               # Linux desktop launcher (install.sh), uninstaller, and icon
├── Windows/             # Windows launcher (install.bat), uninstaller, and icon
├── scripts/             # Modular application package
│   ├── main.py          # Entry point
│   ├── main_window.py   # Main IDE window, menus, toolbar, compilation & serial runner
│   ├── cells.py         # Code, markdown, and notebook widgets
│   ├── editor.py        # C++ editor, syntax highlighter, auto-indent & auto-close
│   ├── dialogs.py       # Boards Manager, Library Manager, Find/Replace, and Tools
│   ├── media.py         # Video and animated GIF player engine
│   ├── toolchain.py     # Local Arduino CLI, platform and package manager backend
│   ├── sketch_builder.py# Dependency resolution and C++ sketch assembly
│   ├── notebook_format.py# .icpnb and .ipynb serialization
│   └── theme.py         # Auto/Light/Dark themes and vector icons
├── Example Notebooks/   # Hands-on lessons and hardware demo notebooks
├── Test_scripts/        # Automated test suites (CLI, GUI, Media)
├── requirements.txt     # Python dependencies (PySide6, pyserial)
└── .embedded/           # Auto-created local toolchain directory
```

---

## Quick Start

### 1. Installation & Launch

The launcher automatically sets up a local virtual environment (`.venv`) and installs all dependencies:

- **Linux**:
  ```bash
  bash Linux/install.sh
  ```
  Adds **Embedded Notebook** to your application launcher. Open it from your applications menu or run `.venv/bin/python embedded_notebook2.py`.

- **Windows**:
  Double-click `Windows\install.bat` (or run it from CMD/PowerShell).

### 2. First-Time Board Setup

1. Open **Tools → Boards Manager**.
2. Search for your board platform (e.g., `esp8266` for NodeMCU or `esp32` for ESP32) and click **Install**.
   *(Need custom boards like Raspberry Pi Pico? Add the index URL under the **Package URLs** tab).*
3. Connect your board via USB (ensure the cable supports data transfer).
4. Select your board model and serial port from the top toolbar dropdowns.

### 3. Open a Lesson or Example

- Navigate to `File → Examples → Notebook Examples → lesson1_blink_to_button` to start learning.
- Or explore core examples from `File → Examples → Board Examples` and `Installed Libraries Examples`. Clicking an example appends it cleanly as a cell in your active notebook.

---

## Notebook Workflow

```text
Cell 1 (Pin definitions & setup)
       ↓
Cell 2 (Helper functions & debouncing)   [Depends on: 1]
       ↓
Cell 3 (Main execution loop)            [Depends on: 1, 2]
```

- **Verify / Compile (`Ctrl+R`)**: Builds the selected cell together with all required upstream dependencies into a single sketch.
- **Upload (`Ctrl+U`)**: Flashes the compiled binary to the connected board. Automatically disconnects the serial monitor during upload and reconnects once done.
- **Show Generated Code (`Ctrl+Shift+G`)**: Inspects the final assembled `.ino` sketch before uploading.
- **Serial Monitor (`Ctrl+Shift+M`)**: Opens the bottom monitor panel to send and view serial data at configurable baud rates.

---

## Key Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Ctrl+R` | Verify / compile selected cell |
| `Ctrl+U` | Upload sketch to board |
| `Ctrl+Shift+G` | View combined generated sketch |
| `Ctrl+Shift+M` | Toggle Serial Monitor |
| `Ctrl+/` | Comment / uncomment lines from cursor or selection |
| `Ctrl+F` / `Ctrl+H` | Find / Replace across notebook |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0`| Increase / Decrease / Reset editor font size |
| `Ctrl+N` / `Ctrl+O` / `Ctrl+S`| New / Open / Save notebook |

---

## Uninstallation

- **Linux**: `bash Linux/uninstall.sh`
- **Windows**: Run `Windows\uninstall.bat`

Removes the desktop shortcut, user configuration, `.venv`, and the local `.embedded` toolchain cache.

---

## Testing

Run the automated test suites using the project virtual environment:

```bash
# Toolchain & CLI backend (58 tests)
.venv/bin/python Test_scripts/test_toolchain.py

# Media & GIF cell rendering (9 tests)
QT_QPA_PLATFORM=offscreen .venv/bin/python Test_scripts/test_media_cells.py

# GUI, hotkeys, board manager & examples (81 tests)
QT_QPA_PLATFORM=offscreen .venv/bin/python Test_scripts/test_toolchain_gui.py
```
