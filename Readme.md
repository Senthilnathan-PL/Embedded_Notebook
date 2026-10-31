# Embedded Notebook

**Embedded Notebook** is a modern, modular desktop notebook environment designed for programming microcontrollers using Arduino-style C/C++. Instead of struggling with large, monolithic `.ino` files, you can break firmware into logical cells, declare dependencies between them, compile and upload directly to microcontrollers, and monitor serial output in real time.

---

## Key Highlights

- **Interactive Cell Architecture**: Organize code into discrete setup, utility, and execution cells.
- **Cell Dependencies**: Link cells together (e.g., `1, 2` or `PinConfig, SensorDrivers`) to assemble complete sketches on demand.
- **Isolated MCU Toolchain**: Bundles an embedded `arduino-cli` with core platforms and libraries kept entirely within `.embedded/` — leaving your system clean.
- **Native & Jupyter Formats**: Seamless support for `.icpnb` notebooks and standard Jupyter `.ipynb` documents.
- **Rich Media Documentation**: Markdown cells support live text, syntax blocks, images, videos, and animated GIFs (e.g., wiring diagrams and animated lab previews).
- **Built-in Managers**: Search and install official or third-party board packages (NodeMCU/ESP8266, ESP32, AVR, RP2040, etc.) and libraries directly from the UI.
- **Interactive Examples**: Open board core examples and library examples from `File → Examples`, appending them cleanly as individual cells.

---

## System Requirements

### Hardware
- Any supported development board:
  - **ESP8266**: NodeMCU 0.9, NodeMCU 1.0, Wemos D1 Mini, etc.
  - **ESP32**: ESP32 Dev Module, ESP32-C3, ESP32-S3, etc.
  - **Arduino**: Arduino Uno, Arduino Nano, Mega 2560, etc.
  - **RP2040**: Raspberry Pi Pico, Pico W, etc.
- A **micro-USB / USB-C data cable** (ensure the cable supports data lines, not charging-only).

### Software
- **Python 3.10+** installed and available on your system `PATH`.
- Linux: `bash`, `python3-venv` (if not pre-installed on Debian/Ubuntu: `sudo apt install python3-venv`).
- Windows: Windows 10/11 with PowerShell enabled.

---

## Installation & Setup

Embedded Notebook sets up an isolated virtual environment (`.venv`), installs all dependencies, and creates a ready-to-use application launcher for your OS.

---

### Linux Setup

The Linux installer creates the virtual environment, installs dependencies, and registers **Embedded Notebook** directly into your system's application drawer with its custom icon.

#### 1. Prerequisites
Ensure Python 3 and the venv module are installed:
```bash
sudo apt update && sudo apt install python3 python3-venv
```

#### 2. Run the Installer
In the project directory, run:
```bash
bash Linux/install.sh
```

#### What It Does:
- **`.venv/`**: Creates an isolated virtual environment and installs dependencies from `requirements.txt`.
- **App Drawer Entry**: Generates `~/.local/share/applications/embedded-notebook.desktop` linked to the application icon.

#### 3. How to Launch
- **From Application Drawer**: Open your system app launcher (Super / Windows key), search for **Embedded Notebook**, and click to launch.
- **From Terminal**:
  ```bash
  .venv/bin/python embedded_notebook2.py
  ```

---

### Windows Setup

The Windows installer sets up the virtual environment, installs dependencies, and creates a desktop shortcut linked to the application icon.

#### 1. Run the Installer
In File Explorer, double-click **`Windows\install.bat`** (or execute it from Command Prompt / PowerShell).

#### What It Does:
- **`.venv\`**: Creates an isolated virtual environment and installs dependencies from `requirements.txt`.
- **Desktop Shortcut**: Generates an **Embedded Notebook** shortcut on your Desktop (`Embedded Notebook.lnk`) styled with `embeddednotebook.ico`.

#### 2. How to Launch
- **From Desktop**: Double-click the **Embedded Notebook** desktop shortcut.
- **From Batch Launcher**: Double-click `Windows\run.bat` in the project folder.

---

## Step-by-Step Beginner Guide

### Step 1: Install Your Board Core
1. Launch Embedded Notebook.
2. In the menu bar, open **Tools → Boards Manager**.
3. Under the **Search** tab, locate your board package:
   - For NodeMCU / ESP8266: search `esp8266` and click **Install**.
   - For ESP32: search `esp32` and click **Install**.
   - For Arduino Uno / Nano: search `avr` (Arduino AVR Boards) and click **Install**.
   *(For custom cores such as Raspberry Pi Pico, switch to the **Package URLs** tab, paste the board index JSON URL, and search for the package).*
4. When installation finishes, close the dialog.

### Step 2: Connect Hardware & Select Board / Port
1. Plug your microcontroller into your computer via USB.
2. In the top toolbar:
   - Select your board model from the **Board** dropdown (e.g., `NodeMCU 0.9 (ESP-12 Module)`).
   - Select the detected serial port from the **Port** dropdown (e.g., `/dev/ttyUSB0` on Linux or `COM3` on Windows).
   - Click the **Refresh** button if your device was plugged in after opening the app.

### Step 3: Explore Built-in Lessons
1. Open **File → Examples → Notebook Examples → lesson1_blink_to_button**.
2. This lesson demonstrates transitioning from a basic LED blink sketch to an interactive debounced button state machine across multiple cells.

### Step 4: Verify & Upload
1. Click on the code cell you want to run.
2. Click the **Verify** checkmark button (or `Ctrl+R`) to compile the sketch and verify syntax.
3. Click the **Upload** arrow button (or `Ctrl+U`) to compile and flash the sketch to your board.
4. If the Serial Monitor is open, it will automatically pause for flashing and reconnect once upload completes.

### Step 5: Serial Communication
1. Open **Tools → Serial Monitor** (or press `Ctrl+Shift+M`).
2. Select the appropriate baud rate (e.g., `115200` or `9600`) and click **Connect**.
3. View real-time timestamped serial logs and send commands to your board.

---

## How Cell Dependencies Work

When you upload or verify a specific cell, Embedded Notebook inspects its **Dependencies** input line and recursively merges all prerequisites into a standard Arduino sketch:

```text
┌───────────────────────────────────────────────┐
│ Cell 1: Pin Definitions & Variables           │
│ const int LED_PIN = 2;                        │
└───────────────────────┬───────────────────────┘
                        │ (Depends on: 1)
┌───────────────────────▼───────────────────────┐
│ Cell 2: Helper Functions                      │
│ void blinkRate(int ms) { ... }                │
└───────────────────────┬───────────────────────┘
                        │ (Depends on: 1, 2)
┌───────────────────────▼───────────────────────┐
│ Cell 3: Main Execution Loop                   │
│ void setup() { pinMode(LED_PIN, OUTPUT); }    │
│ void loop()  { blinkRate(200); }              │
└───────────────────────────────────────────────┘
```

1. **Include Statements (`#include`)**: Aggregated at the top of the generated sketch without duplicates.
2. **Global Declarations & Functions**: Preserved in dependency order.
3. **Setup Logic (`setup()`)**: All `setup()` blocks from ancestor cells and the active cell run sequentially in dependency order.
4. **Loop Logic (`loop()`)**: The `loop()` from the targeted cell forms the active running loop on the microcontroller.
5. Use **Sketch → Show Generated Code (`Ctrl+Shift+G`)** anytime to view the complete assembled `.ino` file before flashing.

---

## Editor Features & Shortcuts

The built-in C++ editor provides IDE-grade productivity features:

- **Smart Indentation**: Automatically matches indentation depth on Enter; hitting Enter between brackets `{}` or `()` inserts an indented middle line.
- **Bracket & Quote Completion**: Typing `(`, `[`, `{`, `"`, or `'` inserts the matching pair with cursor centered; typing the closing character skips over it cleanly.
- **Contextual Commenting (`Ctrl+/`)**: 
  - On a single line: comments/uncomments starting from the current cursor position.
  - Across multiple lines: comments/uncomments beginning from the first selected character.
- **Live Bracket Matching**: Highlights matching enclosing bracket pairs under the caret.
- **Indentation Guides**: High-contrast visual indent guides assist in reading nested blocks.

| Shortcut | Description |
| :--- | :--- |
| `Ctrl+R` | Verify / compile the currently selected cell |
| `Ctrl+U` | Compile and upload sketch to the selected board |
| `Ctrl+Shift+G` | View the combined generated Arduino sketch |
| `Ctrl+Shift+M` | Toggle the bottom Serial Monitor panel |
| `Ctrl+/` | Toggle comment / uncomment for selection or line |
| `Ctrl+F` / `Ctrl+H` | Search / Replace text across all notebook cells |
| `F3` / `Shift+F3` | Navigate next / previous search match |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | Increase / Decrease / Reset editor font size |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo edits |
| `Ctrl+N` / `Ctrl+O` / `Ctrl+S` | New / Open / Save notebook |
| `Ctrl+Shift+S` | Save As (`.icpnb` or `.ipynb`) |

---

## Adding Libraries & Custom Boards

### Installing Libraries
1. Open **Tools → Library Manager**.
2. Search for the library name (e.g. `ArduinoJson`, `Adafruit SSD1306`, `Servo`).
3. Select your desired version from the dropdown and click **Install**.
4. Include the library in your cell with `#include <LibraryName.h>`.
5. Browse example sketches bundled with the library under **File → Examples → Installed Libraries Examples**.

### Adding Custom Board URLs
1. Open **Tools → Boards Manager → Package URLs**.
2. Enter the board index URL (e.g. Raspberry Pi Pico: `https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json`).
3. Click **Add URL**.
4. Switch to the **Search** tab and install the newly available platform core.

---

## Project Structure Overview

```text
Embedded_Notebook/
├── Linux/               # Linux launcher, desktop installer, and uninstaller
├── Windows/             # Windows batch launcher, shortcut generator, and uninstaller
├── scripts/             # Core Python modules
│   ├── main.py          # Application bootstrap
│   ├── main_window.py   # Primary IDE window, menus, toolbar, compiler & serial pipeline
│   ├── cells.py         # Code, markdown, and notebook container widgets
│   ├── editor.py        # C++ editor, syntax highlighter, guides, auto-close & comments
│   ├── dialogs.py       # Boards Manager, Library Manager, Find/Replace, and Tools
│   ├── media.py         # Video and animated GIF player engine
│   ├── toolchain.py     # Local Arduino CLI, platform and package manager backend
│   ├── sketch_builder.py# Dependency graph resolution and C++ sketch assembly
│   ├── notebook_format.py# .icpnb and .ipynb serialization
│   └── theme.py         # Auto/Light/Dark themes and vector icons
├── Example Notebooks/   # Hands-on lessons, lab exercises, and sample notebooks
├── Test_scripts/        # Complete automated test suite (CLI, GUI, Media)
├── requirements.txt     # Python dependencies (PySide6, pyserial)
└── .embedded/           # Self-contained local toolchain folder (auto-generated)
```

---

## Troubleshooting

### Board Not Detected on USB
- Ensure your cable supports **data transfer** (try another USB port or cable).
- Ensure required USB-UART bridge drivers are installed (CH340, CP2102, FTDI, or CDC ACM).
- On Linux, verify your user account has dialout permissions:
  ```bash
  sudo usermod -aG dialout $USER
  ```
  *(Log out and log back in for changes to take effect).*

### Compilation Errors ("Platform not ready")
- Open **Tools → Boards Manager** and confirm the core for your selected board is installed.
- Ensure the board selected in the toolbar matches your physical board.

### Resetting the Local Toolchain
- All MCU tools, cores, and builds reside in `.embedded/`. To perform a clean reset, delete the `.embedded/` folder; Embedded Notebook will re-prompt to initialize on next launch.

---

## Uninstallation

If you ever wish to completely remove Embedded Notebook, automated uninstallation scripts are provided for both operating systems.

> [!WARNING]
> The uninstallation scripts are designed for a **full and clean removal**. They will prompt for confirmation before proceeding unless run with a force flag (`-y` or `--force`).

### Linux Uninstallation

Run the uninstaller script from your terminal:
```bash
bash Linux/uninstall.sh
```
*(To skip the interactive confirmation prompt, run: `bash Linux/uninstall.sh --yes`)*

#### What `Linux/uninstall.sh` Removes:
1. **Desktop Launcher Entry**:
   - Removes `~/.local/share/applications/embedded-notebook.desktop` (and `$XDG_DATA_HOME` equivalents).
   - Runs `update-desktop-database` to immediately unregister the app from your system application drawer / search menu.
2. **User Preferences & State**:
   - Removes `~/.config/EmbeddedNotebook/` (saved window sizes, themes, and manager caches).
3. **Local Virtual Environment & Toolchains**:
   - Completely removes the isolated `.venv/` virtual environment and `.embedded/` folder (including downloaded Arduino cores, toolchain binaries, and build artifacts).
4. **Project Directory**:
   - Safely removes the project directory, leaving your host system completely clean.

---

### Windows Uninstallation

Run the uninstaller script by double-clicking **`Windows\uninstall.bat`** or executing it from Command Prompt / PowerShell:
```cmd
Windows\uninstall.bat
```
*(To skip the interactive confirmation prompt, pass: `Windows\uninstall.bat /y`)*

#### What `Windows\uninstall.bat` Removes:
1. **Desktop Shortcuts & Cleaners**:
   - Removes `%USERPROFILE%\Desktop\Embedded Notebook.lnk`.
   - Cleans any legacy desktop launcher files or folders (e.g. `Embedded Notebook.bat` or temporary Desktop folders).
2. **User Preferences & Settings**:
   - Removes `%APPDATA%\EmbeddedNotebook` (all user theme preferences, recent board selections, and manager caches).
3. **Local Virtual Environment & Toolchains**:
   - Deletes `.venv\` and the `.embedded\` local toolchain folder.
4. **Project Files**:
   - Safely switches out of the directory and removes all project files in the background.

---

## Testing

Run the automated test suite locally to verify toolchain integrity, GUI actions, and media engines:

```bash
# Toolchain & CLI backend (58 tests)
.venv/bin/python Test_scripts/test_toolchain.py

# Media & GIF cell rendering (9 tests)
QT_QPA_PLATFORM=offscreen .venv/bin/python Test_scripts/test_media_cells.py

# GUI, hotkeys, board manager & examples (81 tests)
QT_QPA_PLATFORM=offscreen .venv/bin/python Test_scripts/test_toolchain_gui.py
```
