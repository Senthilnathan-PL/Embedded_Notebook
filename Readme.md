# Embedded Notebook

**Embedded Notebook** is a notebook-style environment for programming microcontrollers using Arduino-style C/C++ code.

Instead of working with a single large `.ino` file, you can organize your embedded program into multiple notebook cells, build dependencies between cells, compile/upload individual cells, and interact with your board through the serial monitor.

---

## Features

* Notebook-based embedded programming
* Arduino-style C/C++ code cells
* Cell-to-cell dependencies
* Compile and upload individual cells
* Serial monitor
* ESP32 support
* NodeMCU / ESP8266 support
* Arduino Uno and Nano support
* Project-local Arduino CLI
* Project-local MCU cores and libraries
* `.icpnb` notebook format
* `.ipynb` notebook compatibility
* No global Arduino CLI installation required

---

# 1. Project Structure

After extracting the project, you should have something similar to:

```text
Embedded_Notebook/
│
├── Embedded_Notebook.sh          # Linux launcher
├── Embedded_Notebook.bat         # Windows launcher
│
├── embedded_notebook2.py         # Main application
├── embedded_toolchain.py         # MCU/toolchain management
├── requirements.txt              # Python dependencies
│
├── lesson1_blink_to_button.ipynb # Example lesson
│
└── .venv/                        # Created automatically
```

The `.embedded/` directory is also created by Embedded Notebook when the local MCU toolchain is installed.

---

# 2. Requirements

## Hardware

You need a supported Arduino-compatible development board.

Examples include:

* NodeMCU 0.9
* NodeMCU 1.0
* ESP32 Dev Module
* ESP32-C3 Dev Module
* ESP32-S3 Dev Module
* Arduino Uno
* Arduino Nano

You will also need a USB cable suitable for your development board.

> Make sure the USB cable supports **data transfer**. Some USB cables are power-only.

---

# 3. Python Requirements

The application requires Python 3.

The project includes a `requirements.txt` file containing:

```text
PySide6>=6.6,<7
pyserial>=3.5
```

The launcher automatically creates a local Python virtual environment and installs these dependencies.

You normally **do not need to install these packages manually**.

---

# 4. Running Embedded Notebook

Choose the instructions for your operating system.

---

## Linux

### Step 1 — Open a terminal

Navigate to the Embedded Notebook directory.

For example:

```bash
cd ~/Embedded_Notebook
```

### Step 2 — Install the desktop app

Run:

```bash
bash Embedded_Notebook.sh
```

The setup script will:

1. Find the project directory.
2. Create `.venv` if it doesn't exist.
3. Install/update Python dependencies.
4. Add **Embedded Notebook** to your application drawer.

The setup script does not start the GUI. Open **Embedded Notebook** from your application
drawer to run it with the project's virtual environment. You do **not** need to manually
activate the environment or run Python yourself.

### If the script has executable permission

You can also run:

```bash
./Embedded_Notebook.sh
```

If Linux says:

```text
Permission denied
```

make it executable:

```bash
chmod +x Embedded_Notebook.sh
```

Then run the setup script once:

```bash
./Embedded_Notebook.sh
```

After setup, start Embedded Notebook from your application drawer.

---

# 5. Windows

## Step 1 — Open the project folder

Open the folder containing:

```text
Embedded_Notebook.bat
embedded_notebook2.py
requirements.txt
```

## Step 2 — Start Embedded Notebook

Double-click:

```text
Embedded_Notebook.bat
```

Alternatively, open Command Prompt in the project directory and run:

```bat
Embedded_Notebook.bat
```

The launcher automatically:

1. Finds the project directory.
2. Creates `.venv` if required.
3. Installs/updates the Python requirements.
4. Starts Embedded Notebook using the local virtual environment.

You do **not** need to activate `.venv` manually.

---

# 6. First Launch — Installing the MCU Toolchain

Embedded Notebook uses its own **project-local Arduino CLI**.

You do **not** need to install Arduino CLI globally.

The application keeps its embedded toolchain inside:

```text
.embedded/
```

The directory contains the locally managed Arduino CLI, MCU cores, libraries, build files, downloads, cache, and configuration.

---

## Installing the NodeMCU Core

Start Embedded Notebook.

Then open:

```text
Tools → Boards Manager
```

Use Search to find the required board platform, select its version, and install it. On
first launch, Embedded Notebook may first open its setup dialog to install the local
Arduino CLI.

For a NodeMCU board, select the appropriate NodeMCU board:

### NodeMCU 0.9

```text
NodeMCU 0.9
```

or:

### NodeMCU 1.0

```text
NodeMCU 1.0
```

Both use the ESP8266 Arduino core.

Select the ESP8266 platform package and install it. Add other package index URLs from the
**Package URLs** tab; packages from those indexes become available in Search.

The application will download and manage the required Arduino CLI/core inside the project.

## Installing Arduino Libraries

Open **Tools → Library Manager** to search the Arduino Library Registry, review library
details, install a library, or view libraries already installed in this project. Library
files are managed locally under `.embedded/` by the project's Arduino CLI.

After installation, include the library in a code cell using its normal Arduino header,
for example:

```cpp
#include <ArduinoJson.h>
```

The board selector only lists boards whose MCU cores are installed. Use Boards Manager to
install another core before selecting that board.

---

# 7. Which NodeMCU Should I Select?

If you have a common ESP8266 NodeMCU development board, it is usually one of these:

| Board              | Select        |
| ------------------ | ------------- |
| NodeMCU 0.9        | `NodeMCU 0.9` |
| NodeMCU v1.0       | `NodeMCU 1.0` |
| ESP8266 NodeMCU V2 | `NodeMCU 1.0` |

If you are unsure which board you have, check the markings on the PCB or the board/module.

---

# 8. Connecting the NodeMCU

Connect your NodeMCU to the computer using USB.

Then open Embedded Notebook.

The serial port should appear in the application's board/port controls.

On Linux, it may look similar to:

```text
/dev/ttyUSB0
```

or:

```text
/dev/ttyACM0
```

On Windows, it may look like:

```text
COM3
```

```text
COM4
```

or another `COM` number.

---

# 9. Your First Lesson

The project includes an example notebook:

```text
lesson1_blink_to_button.ipynb
```

This lesson demonstrates moving from a simple LED blink program to a button-controlled LED.

The lesson contains several code cells.

The basic progression is:

```text
Cell 1
   ↓
LED blinking

Cell 2
   ↓
Read button

Cell 3
   ↓
Button debouncing

Cell 4
   ↓
Button controls LED
```

---

# 10. Opening Lesson 1

Start Embedded Notebook.

Open:

```text
lesson1_blink_to_button.ipynb
```

You can open it using the application's notebook/file-open functionality.

The notebook can also be supplied when launching the application:

```bash
python embedded_notebook2.py lesson1_blink_to_button.ipynb
```

On Windows:

```bat
.venv\Scripts\python.exe embedded_notebook2.py lesson1_blink_to_button.ipynb
```

The application supports `.ipynb` files as well as its `.icpnb` notebook format.

---

# 11. Understanding Notebook Cells

Each code cell contains normal Arduino-style C/C++ code.

For example:

```cpp
const int LED_PIN = 2;

void setup() {
    pinMode(LED_PIN, OUTPUT);
}

void loop() {
    digitalWrite(LED_PIN, HIGH);
    delay(500);

    digitalWrite(LED_PIN, LOW);
    delay(500);
}
```

A cell can contain:

* Global variables
* `#include` statements
* Functions
* `setup()`
* `loop()`

You can build larger programs by splitting them into multiple cells.

---

# 12. Cell Dependencies

A cell can depend on another cell.

For example:

```text
Cell 1
LED setup
   ↓
Cell 2
Button setup
   ↓
Cell 3
Button debounce function
   ↓
Cell 4
Final button-controlled LED
```

When you upload a cell, Embedded Notebook combines the required cells into a single Arduino sketch.

Conceptually:

```text
Dependencies
     ↓
globals + functions
     ↓
setup()
     ↓
uploaded cell's loop()
     ↓
Arduino sketch
     ↓
Compile
     ↓
Upload
```

This allows you to develop embedded programs incrementally.

---

# 13. Show Code

Use **Show Code** on a cell to see the combined Arduino sketch that Embedded Notebook will build from the selected cell and its dependencies.

This is useful for understanding what is actually being compiled and uploaded to the microcontroller.

---

# 14. Creating Your Own Notebook

You do not have to use the supplied lesson.

You can create your own notebook.

Create a new notebook from Embedded Notebook and add code cells.

For example:

### Cell 1 — LED setup

```cpp
const int LED_PIN = 2;

void setup() {
    pinMode(LED_PIN, OUTPUT);
}
```

### Cell 2 — Blink

```cpp
void loop() {
    digitalWrite(LED_PIN, HIGH);
    delay(500);

    digitalWrite(LED_PIN, LOW);
    delay(500);
}
```

Then configure the dependency relationship if required.

Your notebook can contain as many logical sections/cells as your project needs.

---

# 15. `.ipynb` vs `.icpnb`

Embedded Notebook supports both formats.

## `.ipynb`

This is the standard Jupyter Notebook format.

Example:

```text
my_project.ipynb
```

Use this if you want to work with a conventional Jupyter-compatible notebook file.

---

## `.icpnb`

Embedded Notebook's native notebook extension is:

```text
.icpnb
```

For example:

```text
my_robot.icpnb
```

The notebook content uses the Jupyter Notebook JSON structure, but the `.icpnb` extension identifies it as an Embedded Notebook project.

---

# 16. Recommended Learning Workflow

If you are new to Embedded Notebook, follow this sequence:

```text
1. Start Embedded Notebook
        ↓
2. Open Boards Manager
        ↓
3. Install NodeMCU core
        ↓
4. Connect NodeMCU through USB
        ↓
5. Select the correct board
        ↓
6. Select the serial port
        ↓
7. Open lesson1_blink_to_button.ipynb
        ↓
8. Read the first cell
        ↓
9. Compile / Upload
        ↓
10. Observe the board
        ↓
11. Move through the dependent cells
        ↓
12. Create your own notebook
```

---

# 17. Creating Your Own Embedded Project

Once you understand the first lesson, create a notebook for your own project.

For example:

```text
my_nodemcu_project.icpnb
```

You could organize it like:

```text
Cell 1
Constants and pin definitions

Cell 2
Sensor initialization

Cell 3
Sensor reading functions

Cell 4
Motor control

Cell 5
Communication

Cell 6
Main application
```

Then use cell dependencies to combine the required functionality.

This keeps your embedded code organized without having to maintain one huge Arduino sketch.

---

# 18. Troubleshooting

## Python is not found

If you see something similar to:

```text
python is not recognized
```

on Windows, or:

```text
python: command not found
```

on Linux, install Python 3 and make sure it is available from your terminal.

Then run the launcher again.

---

## `serial` module is missing

If you see:

```text
ModuleNotFoundError: No module named 'serial'
```

make sure you start the application using the supplied launcher.

The launcher installs:

```text
pyserial
```

into the project's virtual environment.

If necessary, manually install it:

### Linux

```bash
.venv/bin/python -m pip install -r requirements.txt
```

### Windows

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## NodeMCU is not detected

Check:

1. The USB cable supports data.
2. The NodeMCU is powered.
3. The correct USB/serial driver is installed.
4. The serial port appears in the operating system.
5. The correct port is selected in Embedded Notebook.
6. The correct NodeMCU board is selected.

---

## Toolchain is not installed

Open:

```text
Tools → Boards Manager
```

and install the required board platform.

For NodeMCU, install the ESP8266 platform through Boards Manager.

---

# 19. Important: Do Not Delete `.embedded` Unless You Intend To Reset the Toolchain

Embedded Notebook stores its local MCU toolchain and related data inside:

```text
.embedded/
```

This can include:

```text
.embedded/
├── arduino-cli/
├── config/
├── data/
├── downloads/
├── build/
├── cache/
└── logs/
```

Deleting this directory may require the MCU cores and other toolchain components to be downloaded again.

---

# 20. Quick Start

If everything is already installed:

### Linux

```bash
bash Embedded_Notebook.sh
```

### Windows

```text
Double-click Embedded_Notebook.bat
```

Then:

```text
Tools
  ↓
Boards Manager
  ↓
Install NodeMCU core
  ↓
Connect NodeMCU
  ↓
Select board + serial port
  ↓
Open lesson1_blink_to_button.ipynb
  ↓
Compile / Upload
```

After completing the lesson, create your own:

```text
.icpnb
```

or:

```text
.ipynb
```

notebook and start building your own embedded project.

---

# 21. Getting Started

If this is your first time using Embedded Notebook, **start with:**

```text
lesson1_blink_to_button.ipynb
```

It introduces the basic idea of using multiple cells, dependencies, Arduino-style code, and uploading the resulting sketch to a microcontroller.

Once you understand the lesson, create your own notebook and experiment with sensors, LEDs, buttons, motors, serial communication, and other embedded hardware.

**Happy making!**
