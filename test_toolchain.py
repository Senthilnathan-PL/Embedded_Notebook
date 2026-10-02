import json, os, sys, tempfile, stat
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import embedded_toolchain as et

results = []
def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))

tmp = Path(tempfile.mkdtemp())

# --- EnvironmentManager -----------------------------------------------------------
cwd = os.getcwd(); os.chdir(tmp)
env0 = et.EnvironmentManager()
check("root defaults to source dir, not cwd", env0.APP_ROOT == Path(et.__file__).resolve().parent != tmp.resolve())
os.chdir(cwd)
env = et.EnvironmentManager(tmp / "proj")
check("override root", env.APP_ROOT == (tmp / "proj").resolve())
check("all paths inside .embedded", all(str(d).startswith(str(env.EMBEDDED_ROOT)) for d in env.directories()))
check("cli exe name platform-aware", env.ARDUINO_CLI_PATH.name == ("arduino-cli.exe" if sys.platform == "win32" else "arduino-cli"))
check("missing env detected", not env.exists() and not env.is_initialized())
env.ensure_dirs()
check("ensure_dirs creates layout", all(d.is_dir() for d in env.directories()))
env.write_cli_config(["http://x/y.json"])
cfg = env.ARDUINO_CONFIG.read_text()
check("config pins data/downloads/user/cache", all(str(p) in cfg for p in (env.ARDUINO_DATA, env.DOWNLOAD_DIR, env.ARDUINO_CACHE)) and "y.json" in cfg)
env.save_state({"platforms": {"a:b": "1.0"}})
check("state roundtrip + schema", env.load_state()["schema_version"] == et.SCHEMA_VERSION and env.load_state()["platforms"] == {"a:b": "1.0"})
env.ENV_JSON.write_text("{corrupt")
check("corrupt state tolerated", env.load_state() == {})
check("relpath portable", env.relpath(env.ARDUINO_DATA) == ".embedded/data/packages")

# --- Registry ---------------------------------------------------------------------
reg = et.BoardRegistry()
expected = {"Arduino Uno": "arduino:avr", "Arduino Nano": "arduino:avr",
            "ESP32 Dev Module": "esp32:esp32", "ESP32-C3 Dev Module": "esp32:esp32",
            "ESP32-S3 Dev Module": "esp32:esp32", "NodeMCU 0.9": "esp8266:esp8266",
            "NodeMCU 1.0": "esp8266:esp8266"}
check("all 7 boards present w/ right platform", {n: b.platform_id for n, b in reg.boards.items()} == expected)
check("original FQBNs preserved", reg.board("ESP32 Dev Module").fqbn == "esp32:esp32:esp32" and reg.board("Arduino Uno").fqbn == "arduino:avr:uno")
check("all fqbns valid", all(et.BoardRegistry.valid_fqbn(b.fqbn) for b in reg.boards.values()))
check("invalid fqbn rejected", not et.BoardRegistry.valid_fqbn("esp32:esp32") and not et.BoardRegistry.valid_fqbn(""))
check("unsupported board raises", not any(reg.boards.get(x) for x in ["Nope"]))
try: reg.board("Nope"); check("unsupported board KeyError", False)
except KeyError: check("unsupported board KeyError", True)
plats = reg.platforms_for_boards(["ESP32 Dev Module", "ESP32-C3 Dev Module", "ESP32-S3 Dev Module"])
check("3 esp32 boards -> 1 platform", [p.id for p in plats] == ["esp32:esp32"])
check("7 boards -> 3 platforms", len(reg.platforms_for_boards(list(expected))) == 3)
check("extensible", (reg.add_platform(et.Platform("x:y", "X", "y", None, (et.Board("XB", "x:y:b", "x:y"),))) or reg.platform_for("XB").id) == "x:y")

# --- fake arduino-cli -------------------------------------------------------------
fake = r'''#!/usr/bin/env python3
import sys, json, os
log = os.environ.get("FAKE_LOG")
open(log, "a").write(json.dumps({"argv": sys.argv[1:], "env": {k: v for k, v in os.environ.items() if k.startswith("ARDUINO_")}}) + "\n")
state = os.environ["FAKE_STATE"]
a = sys.argv[1:]
if "--config-file" in a: i = a.index("--config-file"); a = a[:i] + a[i+2:]
inst = json.load(open(state)) if os.path.exists(state) else {}
if a[:1] == ["version"]: print(json.dumps({"VersionString": "1.1.1"}))
elif a[:2] == ["core", "list"]: print(json.dumps({"platforms": [{"id": k, "installed_version": v} for k, v in inst.items()]}))
elif a[:2] == ["core", "search"]: print(json.dumps({"platforms": [{
    "id": "arduino:avr", "latest_version": "1.8.8", "installed_version": inst.get("arduino:avr", ""),
    "maintainer": "Arduino", "website": "https://arduino.cc/",
    "releases": {"1.8.8": {"name": "Arduino AVR Boards", "version": "1.8.8",
                           "boards": [{"name": "Arduino Uno"}], "help": {"online": "https://arduino.cc/"}}}
}, {"id": "custom:board", "latest_version": "2.0.0", "installed_version": "",
    "maintainer": "Example", "website": "https://example.com",
    "releases": {"2.0.0": {"name": "Example Board Core", "version": "2.0.0",
                           "boards": [{"name": "Example Board"}]}}}]}))
elif a[:2] == ["core", "install"]: inst[a[2].split("@", 1)[0]] = a[2].split("@", 1)[-1] if "@" in a[2] else "9.9.9"; json.dump(inst, open(state, "w")); print("Downloading core-package.tar.gz")
elif a[:2] == ["core", "uninstall"]: inst.pop(a[2], None); json.dump(inst, open(state, "w"))
elif a[:2] == ["core", "update-index"]:
    if os.environ.get("FAKE_OFFLINE"): sys.stderr.write("network down\n"); sys.exit(1)
elif a[:2] == ["lib", "search"]:
    print(json.dumps({"libraries": [{"name": "ArduinoJson", "latest": {"version": "7.4.3"}}]}))
elif a[:2] == ["lib", "list"]: print(json.dumps({"installed_libraries": [{"library": {"name": "ArduinoJson", "version": "7.4.3"}}]}))
elif a[:2] == ["lib", "install"]: print("Downloading library-package.zip")
elif a[:2] == ["lib", "uninstall"]: print("Uninstalling library")
'''
env = et.EnvironmentManager(tmp / "proj2"); env.ensure_dirs()
cli = et.ArduinoCLIManager(env)
check("cli not installed initially", not cli.is_installed() and cli.version() is None)
env.ARDUINO_CLI_PATH.write_text(fake); env.ARDUINO_CLI_PATH.chmod(0o755)
os.environ["FAKE_LOG"] = str(tmp / "calls.log"); os.environ["FAKE_STATE"] = str(tmp / "state.json")
check("local cli version", cli.version() == "1.1.1")
check("command uses local exe + config", cli.command(["x"])[0] == str(env.ARDUINO_CLI_PATH) and "--config-file" in cli.command(["x"]))
os.environ["ARDUINO_DIRECTORIES_DATA"] = "/global/Arduino15"
check("global ARDUINO_* env overridden", cli.process_env()["ARDUINO_DIRECTORIES_DATA"] == str(env.ARDUINO_DATA))
del os.environ["ARDUINO_DIRECTORIES_DATA"]

pm = et.PlatformManager(env, cli)
ok, msg = pm.check_ready("ESP32 Dev Module")
check("not-ready explains platform (not 'Unknown FQBN')", not ok and "ESP32" in msg and "not installed" in msg and "FQBN" not in msg)
ok, msg = pm.check_ready("Bogus"); check("unknown board message", not ok and "Unsupported" in msg)
msgs = []
res = pm.install(["esp32:esp32", "esp32:esp32", "arduino:avr"], progress=msgs.append)
calls = [json.loads(l) for l in open(tmp / "calls.log")]
installs = [c["argv"][-1] for c in calls if "install" in c["argv"] and "core" in c["argv"]]
check("no duplicate platform install", sorted(installs) == ["arduino:avr", "esp32:esp32"], installs)
check("install results ok", res == {"esp32:esp32": None, "arduino:avr": None})
check("progress messages", any("Updating package indexes" in m for m in msgs) and any("Finalizing" in m for m in msgs))
check("all calls used --config-file + local dirs", all("--config-file" in c["argv"] and c["env"].get("ARDUINO_DIRECTORIES_DATA") == str(env.ARDUINO_DATA) for c in calls))
check("esp32 url in config, not avr-only", et.ESP32_URL in env.ARDUINO_CONFIG.read_text())
st = env.load_state()
check("environment.json records versions", st["platforms"] == {"esp32:esp32": "9.9.9", "arduino:avr": "9.9.9"} and st["arduino_cli_version"] == "1.1.1")
package_url = "https://example.com/package_index.json"
pm.add_package_url(package_url)
packages = pm.search_platforms("Custom")
check("custom package URL persists in CLI config", package_url in env.ARDUINO_CONFIG.read_text()
    and package_url in pm.additional_package_urls())
check("board search includes custom packages", any(p.get("id") == "custom:board" for p in packages))
check("board search returns package metadata", pm.search_platforms("Arduino")[0] == {
    "id": "arduino:avr", "latest_version": "1.8.8", "installed_version": "9.9.9",
    "maintainer": "Arduino", "website": "https://arduino.cc/",
    "releases": {"1.8.8": {"name": "Arduino AVR Boards", "version": "1.8.8",
                           "boards": [{"name": "Arduino Uno"}], "help": {"online": "https://arduino.cc/"}}}
})
board_output = []
pm.install_platform("custom:board", "2.0.0", board_output.append)
check("custom board install uses selected version", any(json.loads(l)["argv"][-2:] == ["install", "custom:board@2.0.0"]
                                                   for l in open(tmp / "calls.log")))
check("board install streams CLI output", "Downloading core-package.tar.gz" in board_output)
pm.remove_package_url(package_url)
check("package URL removal updates saved state and config", package_url not in pm.additional_package_urls()
    and package_url not in env.ARDUINO_CONFIG.read_text())
check("state has no absolute paths", str(tmp) not in json.dumps(st))
check("is_initialized after install", env.is_initialized())
check("ready after install", pm.check_ready("ESP32-S3 Dev Module")[0] and pm.check_ready("Arduino Uno")[0])
check("esp8266 boards not ready", not pm.check_ready("NodeMCU 1.0")[0])
check("library search parses local CLI JSON", pm.search_libraries("ArduinoJson") == [
    {"name": "ArduinoJson", "latest": {"version": "7.4.3"}}])
check("installed library list parses local CLI JSON", pm.installed_libraries() == [
    {"name": "ArduinoJson", "version": "7.4.3"}])
library_output = []
pm.install_library("ArduinoJson", "7.4.3", library_output.append)
check("library install uses selected version", any(json.loads(l)["argv"][-2:] == ["install", "ArduinoJson@7.4.3"]
                                              for l in open(tmp / "calls.log")))
check("library install streams CLI output", "Downloading library-package.zip" in library_output)
pm.remove_library("ArduinoJson")
check("library removal uses local CLI", any(json.loads(l)["argv"][-2:] == ["uninstall", "ArduinoJson"]
                                              for l in open(tmp / "calls.log")))
bs = pm.board_status()
check("board_status", bs["Arduino Nano"] and not bs["NodeMCU 0.9"])
n = len(open(tmp / "calls.log").readlines())
pm.install(["esp32:esp32"])
new = [json.loads(l)["argv"] for l in list(open(tmp / "calls.log"))[n:]]
check("reinstall skips already-installed", not any(a[-2:-1] == ["install"] and "core" in a for a in new))
pm.remove("esp32:esp32")
check("remove works + state updated", "esp32:esp32" not in pm.installed_platforms() and "esp32:esp32" not in env.load_state()["platforms"])

os.environ["FAKE_OFFLINE"] = "1"
try: pm.install(["esp8266:esp8266"]); check("offline raises ToolchainError", False)
except et.ToolchainError as e: check("offline raises ToolchainError", "internet" in str(e))
del os.environ["FAKE_OFFLINE"]

res = pm.install(["esp8266:esp8266"], cancelled=lambda: True)
check("cancel honoured", res == {"esp8266:esp8266": "Cancelled by user."} and "esp8266:esp8266" not in pm.installed_platforms())

args = pm.compile_args("NodeMCU 1.0", "/s", port="/dev/ttyUSB0")
check("compile args: fqbn, local build path, upload", "esp8266:esp8266:nodemcuv2" in args and str(env.ARDUINO_BUILD) in " ".join(args) and "--upload" in args)
check("sketch dir inside build dir", str(pm.sketch_dir()).startswith(str(env.ARDUINO_BUILD)))

# download URL / archive handling
check("url linux", et.ArduinoCLIManager.download_url(system="linux", machine="x86_64").endswith("Linux_64bit.tar.gz"))
check("url windows", et.ArduinoCLIManager.download_url(system="win32", machine="AMD64").endswith("Windows_64bit.zip"))
try: et.ArduinoCLIManager.download_url(system="darwin", machine="x86_64"); check("unsupported OS", False)
except et.ToolchainError: check("unsupported OS", True)

import tarfile, io
env3 = et.EnvironmentManager(tmp / "proj3"); env3.ensure_dirs(); cli3 = et.ArduinoCLIManager(env3)
arc = env3.DOWNLOAD_DIR / "a.tar.gz"
with tarfile.open(arc, "w:gz") as t:
    data = fake.encode(); ti = tarfile.TarInfo(env3.exe_name()); ti.size = len(data); t.addfile(ti, io.BytesIO(data))
cli3._extract(arc)
check("extract installs executable", cli3.is_installed() and os.access(cli3.path(), os.X_OK))
bad = env3.DOWNLOAD_DIR / "bad.tar.gz"; bad.write_bytes(b"garbage")
try: cli3._extract(bad); check("corrupt archive rejected", False)
except Exception as e: check("corrupt archive rejected", isinstance(e, (tarfile.TarError, OSError)))

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
