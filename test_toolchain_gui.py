# GUI-level checks for the toolchain integration. Same harness style as test_notebook_features.py.
import os, sys, tempfile, pathlib, importlib.util
os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = tempfile.mkdtemp(); os.environ["XDG_CONFIG_HOME"] = tmp; os.environ["HOME"] = tmp
sys.argv = ["x"]
from PySide6.QtWidgets import QApplication, QMessageBox
_spec = importlib.util.spec_from_file_location("en", pathlib.Path(__file__).with_name("embedded_notebook2.py"))
en = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(en)
app = QApplication([]); app.setStyle("Fusion"); en.apply_theme(app, "Light")
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
res = []
def check(n, c): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n)

root = pathlib.Path(tmp) / "proj"
w = en.MainWindow(app_root=root); w.show(); app.processEvents()
check("G1 no uninstalled boards shown", w.board_combo.count() == 0)
view_menu = next(action.menu() for action in w.menuBar().actions() if action.text() == "&View")
theme_menu = next(action.menu() for action in view_menu.actions() if action.text() == "&Theme")
theme_actions = {action.text(): action for action in theme_menu.actions()}
check("G1b Auto theme is available and selected by default",
	  set(theme_actions) == {"Auto", "Light", "Dark"}
	  and theme_actions["Auto"].isChecked()
	  and en.resolve_theme("Auto", en.Qt.ColorScheme.Dark) == "Dark"
	  and en.resolve_theme("Auto", en.Qt.ColorScheme.Light) == "Light"
	  and en.resolve_theme("Auto", en.Qt.ColorScheme.Unknown) == "Light")
theme_actions["Auto"].trigger()
w._on_system_color_scheme_changed(en.Qt.ColorScheme.Dark)
check("G1c Auto follows live system dark scheme", en.CURRENT_THEME == "Dark")
w._on_system_color_scheme_changed(en.Qt.ColorScheme.Light)
check("G1d Auto follows live system light scheme", en.CURRENT_THEME == "Light")
theme_actions["Dark"].trigger()
w._on_system_color_scheme_changed(en.Qt.ColorScheme.Light)
check("G1e manual theme overrides system changes and persists",
	  en.CURRENT_THEME == "Dark"
	  and en.QSettings("EmbeddedNotebook", "EmbeddedNotebook").value("theme") == "Dark")
theme_actions["Auto"].trigger()
tool_menu = next(action.menu() for action in w.menuBar().actions() if action.text() == "&Tools")
tool_actions = [action.text() for action in tool_menu.actions()]
check("G1a Tools menu uses Boards Manager only for cores",
	  any("Boards Manager" in text for text in tool_actions)
	  and not any("Toolchain Manager" in text or "Install Core" in text for text in tool_actions))
check("G2 no local cli -> self.cli None (PATH not used)", w.cli is None)
check("G3 workdir inside .embedded", str(w.workdir).startswith(str(root / ".embedded")))
w.notebook.cells[0].editor.setPlainText("void setup(){}\nvoid loop(){}")
w.compile_cell(w.notebook.cells[0]); app.processEvents()
check("G4 compile with no installed boards offers manager", asked and "No installed boards" in asked[-1] and w.proc is None)
w.platforms.installed_platforms = lambda: {"esp32:esp32": "3.2.0"}
w.refresh_boards()
check("G5 only boards for installed core shown", [w.board_combo.itemText(i) for i in range(w.board_combo.count())] == [
	"ESP32 Dev Module", "ESP32-C3 Dev Module", "ESP32-S3 Dev Module"])
cell = w.notebook.cells[0]
header = cell.layout().itemAt(0).layout()
header_widgets = [header.itemAt(i).widget() for i in range(header.count())
				  if header.itemAt(i).widget() is not None]
icon_tips = [widget.toolTip() for widget in header_widgets if isinstance(widget, en.QToolButton)]
header_text = [widget.text() for widget in header_widgets if hasattr(widget, "text")]
check("G6 cell header has icon-only Verify and Upload before move controls",
	  len(icon_tips) == 2 and "Verify" in icon_tips[0] and "Upload" in icon_tips[1]
	  and not any(text in ("Show code", "Verify", "Upload") for text in header_text)
	  and header_text.index("▲") < header_text.index("▼"))
view_actions = {action.text(): action for action in view_menu.actions()}
check("G6a code font controls are in View with shortcuts",
	  all(name in view_actions for name in ("Increase Code Font Size", "Decrease Code Font Size",
	                                         "Reset Code Font Size"))
	  and view_actions["Increase Code Font Size"].shortcut().toString() == "Ctrl+="
	  and view_actions["Decrease Code Font Size"].shortcut().toString() == "Ctrl+-")
normal_cell_height = cell.editor.height()
w.set_code_font_size(15)
check("G6b code font size updates existing cells and their height",
	  cell.editor.font().pointSize() == 15 and cell.editor.height() > normal_cell_height)
new_zoom_cell = w.notebook.add_code(scroll=False)
check("G6b1 new cells use the current editor font size", new_zoom_cell.editor.font().pointSize() == 15)
w.increase_code_font_size(); w.decrease_code_font_size()
check("G6c code font increase/decrease changes size", cell.editor.font().pointSize() == 15)
w.set_code_font_size(7)
low_font = cell.editor.font().pointSize()
w.set_code_font_size(25)
high_font = cell.editor.font().pointSize()
w.reset_code_font_size()
check("G6d code font size has bounds and reset", low_font == 8 and high_font == 24
	  and cell.editor.font().pointSize() == 11)
check("G6e editor shows indentation guides", cell.editor.show_indentation_guides)
bracket_code = "if (items[index]) { call({1}); }"
outer_open = bracket_code.index("{")
nested_open = bracket_code.index("{", outer_open + 1)
check("G6f nested bracket matching", en.matching_bracket(bracket_code, outer_open) == bracket_code.rfind("}")
	  and bracket_code[en.matching_bracket(bracket_code, nested_open)] == "}")
ignored_brackets = 'const char *s = "}"; // }\n'
check("G6g brackets in strings/comments are ignored",
	  en.matching_bracket(ignored_brackets, ignored_brackets.index("}")) is None
	  and en.matching_bracket(ignored_brackets, ignored_brackets.rindex("}")) is None)
current_text = cell.editor.toPlainText()
current_open = current_text.index("{")
cursor = en.QTextCursor(cell.editor.document())
cursor.setPosition(en.qt_pos_fn(current_text)(current_open + 1))
cell.editor.setTextCursor(cursor)
check("G6h matching bracket pair highlights at the caret",
	  len(cell.editor._bracket_highlights) == 2)
w.hide_bottom_panel()
check("G6i X control collapses the terminal splitter",
	  w.main_splitter.sizes()[1] == 0)
w.run_sequence(["version"])
check("G6j Verify/build path restores Output panel",
	  w.main_splitter.sizes()[1] > 0 and w.bottom_tabs.currentIndex() == 0)
w.hide_bottom_panel()
w.show_serial_tab()
check("G6k Serial Monitor action restores its tab and panel",
	  w.main_splitter.sizes()[1] > 0 and w.bottom_tabs.currentIndex() == 1)
d = en.ToolchainManagerDialog(w, w.env, w.cli_mgr, w.platforms, first_run=True)
check("G7 dialog: all 7 boards checked by default", len(d.checks) == 7 and all(c.isChecked() for c in d.checks.values()))
check("G8 dialog: 7 boards -> 3 unique platforms", len(d.selected_platform_ids()) == 3)
d.checks["NodeMCU 0.9"].setChecked(False); d.checks["NodeMCU 1.0"].setChecked(False)
check("G9 deselect esp8266 boards -> 2 platforms", d.selected_platform_ids() == ["arduino:avr", "esp32:esp32"])
check("G10 status lists boards as Not Ready", "Not Ready" in d.status_view.toPlainText())

installed_libraries = {}
w.platforms.search_libraries = lambda query: [{"name": "DemoLib", "latest": {
	"version": "1.2.0", "author": "Example", "sentence": "A demo library.",
	"paragraph": "Description for the demo library.", "website": "https://example.com"},
	"available_versions": ["1.0.0", "1.1.0", "1.2.0"]}]
w.platforms.installed_libraries = lambda: [
	{"name": name, "version": version, "author": "Example",
	 "sentence": "A demo library.", "paragraph": "Description for the demo library.",
	 "website": "https://example.com"} for name, version in installed_libraries.items()]
def install_test_library(name, version, progress=None):
	if progress:
		progress(f"Downloading {name}-{version}.zip")
	installed_libraries[name] = version
w.platforms.install_library = install_test_library
w.platforms.remove_library = lambda name, progress=None: installed_libraries.pop(name, None)
library_dialog = en.LibraryManagerDialog(w, w.platforms)
worker = library_dialog.worker; worker.wait(3000); app.processEvents()
lib_flags = library_dialog.windowFlags()
check("G11a Library Manager is an independent resizable window",
	  library_dialog.isWindow() and not library_dialog.isModal()
	  and bool(lib_flags & en.Qt.WindowMinimizeButtonHint)
	  and bool(lib_flags & en.Qt.WindowMaximizeButtonHint)
	  and library_dialog.content_splitter.count() == 2)
check("G11b library lists use gentle per-pixel scrolling",
	  library_dialog.results.verticalScrollMode() == en.QAbstractItemView.ScrollPerPixel
	  and library_dialog.results.verticalScrollBar().singleStep() == 10
	  and library_dialog.task_panel.output.verticalScrollBar().singleStep() == 10)
library_dialog.search_edit.setText("DemoLib")
library_dialog.search()
worker = library_dialog.worker; worker.wait(3000); app.processEvents()
item = library_dialog.results.item(0)
row = library_dialog.results.itemWidget(item) if item else None
version_combo = row.findChild(en.QComboBox) if row else None
install_button = row.findChild(en.QPushButton) if row else None
row_text = " ".join(label.text() for label in row.findChildren(en.QLabel)) if row else ""
check("G11 library entry shows description and version choices", library_dialog.results.count() == 1
	  and "Description for the demo library." in row_text
	  and "More info" in row_text
	  and version_combo is not None
	  and [version_combo.itemText(i) for i in range(version_combo.count())]
	  == ["1.2.0", "1.1.0", "1.0.0"])
version_combo.setCurrentText("1.1.0")
install_button.click()
worker = library_dialog.worker; worker.wait(3000); app.processEvents()
if library_dialog.worker is not None:
	worker = library_dialog.worker; worker.wait(3000); app.processEvents()
check("G12 library manager installs and refreshes installed list",
	  installed_libraries == {"DemoLib": "1.1.0"}
	  and library_dialog.installed_list.count() == 1
 	  and install_button.text() == "Remove"
 	  and "DemoLib-1.1.0.zip" in library_dialog.task_panel.current_file.text()
	  and "Downloading DemoLib-1.1.0.zip" in library_dialog.task_panel.output.toPlainText()
	  and library_dialog.task_panel.progress.value() == 1)
installed_item = library_dialog.installed_list.item(0)
installed_row = library_dialog.installed_list.itemWidget(installed_item)
installed_button = installed_row.findChild(en.QPushButton)
installed_version = installed_row.findChild(en.QComboBox)
installed_text = " ".join(label.text() for label in installed_row.findChildren(en.QLabel))
check("G13 Installed tab uses library cards with version and Remove",
	  "Description for the demo library." in installed_text
	  and installed_version.currentText() == "1.1.0"
	  and installed_button.text() == "Remove")
installed_button.click()
worker = library_dialog.worker; worker.wait(3000); app.processEvents()
if library_dialog.worker is not None:
	worker = library_dialog.worker; worker.wait(3000); app.processEvents()
check("G14 Remove uninstalls and changes Search action back to Install",
	  not installed_libraries and library_dialog.installed_list.count() == 0
	  and install_button.text() == "Install")
w.library_manager_dialog = library_dialog
w.open_library_manager()
check("G14a Library Manager opens nonmodally from Tools",
	  library_dialog.isVisible() and not library_dialog.isModal())
library_dialog.close()

board_installed = {}
board_package = {"id": "arduino:avr", "latest_version": "1.8.8", "installed_version": "",
                 "maintainer": "Arduino", "website": "https://arduino.cc/",
                 "releases": {
                     "1.8.7": {"name": "Arduino AVR Boards", "version": "1.8.7",
							   "types": ["Arduino"], "boards": [{"name": "Arduino Uno"}]},
                     "1.8.8": {"name": "Arduino AVR Boards", "version": "1.8.8",
							   "types": ["Arduino"],
							   "boards": [{"name": "Arduino Uno"}, {"name": "Arduino Nano"}]}}}
board_package2 = {"id": "esp32:esp32", "latest_version": "3.3.12", "installed_version": "",
				  "maintainer": "Espressif Systems", "website": "https://esp32.com",
				  "releases": {"3.3.12": {"name": "esp32", "version": "3.3.12",
											"types": ["Contributed"],
											"boards": [{"name": f"ESP32 Variant {index}"}
												  for index in range(50)]}}}
board_package3 = {"id": "custom:board", "latest_version": "2.0.0", "installed_version": "",
				  "maintainer": "Example", "website": "https://example.com",
				  "releases": {"2.0.0": {"name": "Custom Board Core", "version": "2.0.0",
											"types": ["Contributed"],
											"boards": [{"name": "Custom Board"}]}}}
w.platforms.search_platforms = lambda query="": [board_package, board_package2, board_package3] if not query else [
	package for package in (board_package, board_package2, board_package3)
	if query.lower() in package["releases"][package["latest_version"]]["name"].lower()]
w.platforms.installed_platforms = lambda: dict(board_installed)
def install_test_board(platform_id, version, progress=None):
	if progress:
		progress(f"Downloading {platform_id.replace(':', '-')}-{version}.tar.gz")
	board_installed[platform_id] = version
def remove_test_board(platform_id, progress=None):
	if progress:
		progress(f"Removing {platform_id}")
	board_installed.pop(platform_id, None)
w.platforms.install_platform = install_test_board
w.platforms.remove = remove_test_board
w.platforms.additional_package_urls = lambda: list(custom_package_urls)
custom_package_urls = []
def add_test_package_url(url, progress=None):
	custom_package_urls.append(url)
	if progress:
		progress("Downloading package_index.json")
def remove_test_package_url(url, progress=None):
	custom_package_urls.remove(url)
	if progress:
		progress("Refreshing package indexes")
w.platforms.add_package_url = add_test_package_url
w.platforms.remove_package_url = remove_test_package_url
boards_dialog = en.BoardsManagerDialog(w, w.platforms)
worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
board_flags = boards_dialog.windowFlags()
check("G14b Boards Manager is an independent resizable window",
	  boards_dialog.isWindow() and not boards_dialog.isModal()
	  and bool(board_flags & en.Qt.WindowMinimizeButtonHint)
	  and bool(board_flags & en.Qt.WindowMaximizeButtonHint)
	  and boards_dialog.content_splitter.count() == 2)
check("G14c board and URL lists use gentle per-pixel scrolling",
	  boards_dialog.results.verticalScrollMode() == en.QAbstractItemView.ScrollPerPixel
	  and boards_dialog.installed_list.verticalScrollBar().singleStep() == 10
	  and boards_dialog.package_url_list.verticalScrollBar().singleStep() == 10)
w.boards_manager_dialog = boards_dialog
w.open_boards_manager()
check("G14d Boards Manager opens nonmodally from Tools",
	  boards_dialog.isVisible() and not boards_dialog.isModal())
check("G15 boards manager shows package details and versions",
	  boards_dialog.results.count() == 3
	  and [boards_dialog.type_combo.itemText(i) for i in range(boards_dialog.type_combo.count())]
	  == ["All", "Arduino", "Contributed"]
	  and all(boards_dialog.results.item(i).sizeHint().height() <= 260
		  for i in range(boards_dialog.results.count())))
boards_dialog.type_combo.setCurrentText("Arduino")
check("G16 type filter narrows package cards", boards_dialog.results.count() == 1)
boards_dialog.type_combo.setCurrentText("All")
board_row = boards_dialog.results.itemWidget(boards_dialog.results.item(0))
check("G17 board card lists supported models", "Arduino Nano" in " ".join(
	  label.text() for label in board_row.findChildren(en.QLabel)))
board_version = board_row.findChild(en.QComboBox)
board_action = board_row.findChild(en.QPushButton)
board_version.setCurrentText("1.8.7")
board_action.click()
worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
if boards_dialog.worker is not None:
	worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
check("G18 selected board version installs and action becomes Remove",
	  board_installed == {"arduino:avr": "1.8.7"}
	  and board_action.text() == "Remove"
	  and boards_dialog.installed_list.count() == 1
	  and "arduino-avr-1.8.7.tar.gz" in boards_dialog.task_panel.current_file.text()
	  and "Downloading arduino-avr-1.8.7.tar.gz" in boards_dialog.task_panel.output.toPlainText()
	  and boards_dialog.task_panel.progress.value() == 1)
installed_board_row = boards_dialog.installed_list.itemWidget(boards_dialog.installed_list.item(0))
installed_board_action = installed_board_row.findChild(en.QPushButton)
check("G19 Installed boards use the same detail card",
	  installed_board_row.findChild(en.QComboBox).currentText() == "1.8.7"
	  and "Arduino Uno" in " ".join(label.text() for label in
	      installed_board_row.findChildren(en.QLabel)))
installed_board_action.click()
worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
if boards_dialog.worker is not None:
	worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
check("G20 board removal refreshes Installed and Search",
	  not board_installed and boards_dialog.installed_list.count() == 0
	  and board_action.text() == "Install")
custom_controls = next(item for item in boards_dialog.search_controls if item[0] == "custom:board")
custom_controls[2].click()
worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
if boards_dialog.worker is not None:
	worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
check("G20a custom core install updates Installed and Search action",
	  board_installed == {"custom:board": "2.0.0"}
	  and boards_dialog.installed_list.count() == 1
	  and next(item for item in boards_dialog.search_controls if item[0] == "custom:board")[2].text() == "Remove")
boards_dialog.search_edit.setText("Custom Board Core")
boards_dialog.search()
worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
check("G20b searching an installed custom core shows Remove",
	  boards_dialog.results.count() == 1
	  and boards_dialog.search_controls[0][2].text() == "Remove")
boards_dialog.search_controls[0][2].click()
worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
if boards_dialog.worker is not None:
	worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
check("G20c custom core Remove refreshes Installed",
	  not board_installed and boards_dialog.installed_list.count() == 0)

board_installed.update({f"custom:scroll{index}": "1.0" for index in range(5)})
boards_dialog.refresh_installed()
worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
boards_dialog.tabs.setCurrentIndex(1); app.processEvents()
check("G20d Installed tab scrolls through long core lists",
	  boards_dialog.installed_list.count() == 5
	  and boards_dialog.installed_list.verticalScrollBar().maximum() > 0)
custom_package_urls[:] = [f"https://example.com/index-{index}.json" for index in range(20)]
boards_dialog._populate_package_urls(custom_package_urls)
boards_dialog.tabs.setCurrentIndex(2); app.processEvents()
check("G20e Package URLs tab scrolls through long URL lists",
	  boards_dialog.package_url_list.count() == 20
	  and boards_dialog.package_url_list.verticalScrollBar().maximum() > 0)
custom_package_urls.clear()
boards_dialog.package_url_edit.setText("https://example.com/custom_package_index.json")
boards_dialog.add_package_url()
worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
if boards_dialog.worker is not None:
	worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
check("G21 Package URLs tab adds indexes and shows progress",
	  custom_package_urls == ["https://example.com/custom_package_index.json"]
	  and boards_dialog.package_url_list.count() == 1
	  and "package_index.json" in boards_dialog.task_panel.current_file.text()
	  and "Downloading package_index.json" in boards_dialog.task_panel.output.toPlainText())
url_row = boards_dialog.package_url_list.itemWidget(boards_dialog.package_url_list.item(0))
url_row.findChild(en.QPushButton).click()
worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
if boards_dialog.worker is not None:
	worker = boards_dialog.worker; worker.wait(3000); app.processEvents()
check("G22 Package URLs tab removes index links",
	  not custom_package_urls and boards_dialog.package_url_list.count() == 0)
w.boards_manager_dialog = boards_dialog
w.library_manager_dialog = library_dialog
w._on_system_color_scheme_changed(en.Qt.ColorScheme.Dark)
board_title = boards_dialog.results.itemWidget(boards_dialog.results.item(0)).findChildren(en.QLabel)[0]
library_title = library_dialog.results.itemWidget(library_dialog.results.item(0)).findChildren(en.QLabel)[0]
check("G23 Auto rethemes open manager cards",
	  en.CURRENT_THEME == "Dark"
	  and "#A9BCBC" in board_title.text()
	  and "#A9BCBC" in library_title.text())
w._on_system_color_scheme_changed(en.Qt.ColorScheme.Light)
boards_dialog.close()
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
