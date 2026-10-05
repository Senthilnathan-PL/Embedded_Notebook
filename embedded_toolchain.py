"""
Project-local MCU / toolchain management for Embedded Notebook (no Qt imports).

Everything managed here lives under <root>/.embedded/ :

    .embedded/
        arduino-cli/        the arduino-cli executable
        config/             arduino-cli.yaml + environment.json
        data/packages/      installed cores (directories.data)
        data/libraries/     installed libraries (directories.user)
        downloads/          downloaded archives (directories.downloads)
        build/              sketches and compile output
        cache/              build cache
        logs/

Components: EnvironmentManager (paths), BoardRegistry / PlatformManager
(platform + board definitions and status), ArduinoCLIManager (locate, download,
run the local arduino-cli).
"""
import json
import os
import platform as _platform
import queue
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
from urllib.parse import urlparse
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
ARDUINO_CLI_VERSION = "1.1.1"
ESP32_URL = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
ESP8266_URL = "https://arduino.esp8266.com/stable/package_esp8266com_index.json"


# --------------------------------------------------------------------------
# Environment / paths
# --------------------------------------------------------------------------
class EnvironmentManager:
    """Single source of truth for every path Embedded Notebook manages."""

    DIRNAME = ".embedded"

    def __init__(self, app_root=None):
        # Default: the directory of the application source, NOT os.getcwd().
        # `app_root` is the hook for a future project-root override.
        self.APP_ROOT = Path(app_root).resolve() if app_root else Path(__file__).resolve().parent
        self.EMBEDDED_ROOT = self.APP_ROOT / self.DIRNAME
        self.CLI_DIR = self.EMBEDDED_ROOT / "arduino-cli"
        self.ARDUINO_CLI_PATH = self.CLI_DIR / self.exe_name()
        self.CONFIG_DIR = self.EMBEDDED_ROOT / "config"
        self.ARDUINO_CONFIG = self.CONFIG_DIR / "arduino-cli.yaml"
        self.ENV_JSON = self.CONFIG_DIR / "environment.json"
        self.ARDUINO_DATA = self.EMBEDDED_ROOT / "data" / "packages"
        self.ARDUINO_LIBRARIES = self.EMBEDDED_ROOT / "data" / "libraries"
        self.DOWNLOAD_DIR = self.EMBEDDED_ROOT / "downloads"
        self.ARDUINO_BUILD = self.EMBEDDED_ROOT / "build"
        self.ARDUINO_CACHE = self.EMBEDDED_ROOT / "cache"
        self.LOG_DIR = self.EMBEDDED_ROOT / "logs"

    @staticmethod
    def exe_name():
        return "arduino-cli.exe" if sys.platform == "win32" else "arduino-cli"

    def directories(self):
        return [self.CLI_DIR, self.CONFIG_DIR, self.ARDUINO_DATA, self.ARDUINO_LIBRARIES,
                self.DOWNLOAD_DIR, self.ARDUINO_BUILD, self.ARDUINO_CACHE, self.LOG_DIR]

    def ensure_dirs(self):
        for d in self.directories():
            d.mkdir(parents=True, exist_ok=True)

    def exists(self):
        return self.EMBEDDED_ROOT.is_dir()

    def is_initialized(self):
        return self.ENV_JSON.is_file() and self.ARDUINO_CLI_PATH.is_file()

    def write_cli_config(self, additional_urls=()):
        """arduino-cli.yaml pinning every directory inside the environment."""
        def q(p):
            return json.dumps(str(p))       # JSON string == valid YAML double-quoted string
        lines = [
            "directories:",
            f"  data: {q(self.ARDUINO_DATA)}",
            f"  downloads: {q(self.DOWNLOAD_DIR)}",
            f"  user: {q(self.ARDUINO_LIBRARIES.parent)}",
            "board_manager:",
            "  additional_urls:",
        ]
        lines += [f"    - {q(u)}" for u in additional_urls] or ["    []"]
        lines += ["build_cache:", f"  path: {q(self.ARDUINO_CACHE)}",
                  "updater:", "  enable_notification: false",
                  "metrics:", "  enabled: false", ""]
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.ARDUINO_CONFIG.write_text("\n".join(lines), encoding="utf-8")

    def load_state(self):
        try:
            data = json.loads(self.ENV_JSON.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_state(self, state):
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        state = dict(state, schema_version=SCHEMA_VERSION)
        tmp = self.ENV_JSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, self.ENV_JSON)      # atomic: an interrupted write can't corrupt it

    def relpath(self, p):
        """Path relative to APP_ROOT when possible (used for display / json, portable)."""
        try:
            return Path(p).resolve().relative_to(self.APP_ROOT).as_posix()
        except ValueError:
            return str(p)


# --------------------------------------------------------------------------
# Board / platform registry
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Board:
    name: str
    fqbn: str
    platform_id: str            # e.g. "esp32:esp32"

@dataclass(frozen=True)
class Platform:
    id: str                     # core id passed to `arduino-cli core install`
    name: str
    architecture: str
    package_url: str = None     # additional board-manager URL (None = built in)
    boards: tuple = field(default_factory=tuple)


class BoardRegistry:
    """Single source of truth for platforms and boards."""

    def __init__(self, platforms=None):
        self.platforms = {}
        self.boards = {}
        for p in (platforms if platforms is not None else default_platforms()):
            self.add_platform(p)

    def add_platform(self, platform):
        self.platforms[platform.id] = platform
        for b in platform.boards:
            self.boards[b.name] = b

    def platform(self, pid):
        return self.platforms[pid]

    def board(self, name):
        try:
            return self.boards[name]
        except KeyError:
            raise KeyError(f"Unsupported board: {name!r}") from None

    def platform_for(self, board_name):
        return self.platforms[self.board(board_name).platform_id]

    def platforms_for_boards(self, board_names):
        """Unique platforms (registry order) needed by these boards - no duplicates."""
        needed = {self.board(n).platform_id for n in board_names}
        return [p for pid, p in self.platforms.items() if pid in needed]

    def all_urls(self):
        return sorted({p.package_url for p in self.platforms.values() if p.package_url})

    @staticmethod
    def valid_fqbn(fqbn):
        parts = str(fqbn).split(":")
        return len(parts) >= 3 and all(x.strip() for x in parts[:3])


def default_platforms():
    def B(name, fqbn, pid):
        return Board(name, fqbn, pid)
    return [
        Platform("arduino:avr", "Arduino AVR", "avr", None, (
            B("Arduino Uno", "arduino:avr:uno", "arduino:avr"),
            B("Arduino Nano", "arduino:avr:nano", "arduino:avr"))),
        Platform("esp32:esp32", "ESP32", "esp32", ESP32_URL, (
            B("ESP32 Dev Module", "esp32:esp32:esp32", "esp32:esp32"),
            B("ESP32-C3 Dev Module", "esp32:esp32:esp32c3", "esp32:esp32"),
            B("ESP32-S3 Dev Module", "esp32:esp32:esp32s3", "esp32:esp32"))),
        Platform("esp8266:esp8266", "ESP8266", "esp8266", ESP8266_URL, (
            B("NodeMCU 0.9", "esp8266:esp8266:nodemcu", "esp8266:esp8266"),
            B("NodeMCU 1.0", "esp8266:esp8266:nodemcuv2", "esp8266:esp8266"))),
    ]


# --------------------------------------------------------------------------
# Arduino CLI manager
# --------------------------------------------------------------------------
class ToolchainError(Exception):
    pass


class ArduinoCLIManager:
    def __init__(self, env):
        self.env = env

    # ---- locating / version
    def path(self):
        return self.env.ARDUINO_CLI_PATH

    def is_installed(self):
        return self.path().is_file()

    def base_args(self):
        """Global flags forcing the local config, so a global one is never consulted."""
        return ["--config-file", str(self.env.ARDUINO_CONFIG)]

    def command(self, args):
        return [str(self.path()), *self.base_args(), *args]

    def process_env(self):
        e = dict(os.environ)
        # keep arduino-cli from falling back to global dirs via environment overrides
        for k in list(e):
            if k.startswith("ARDUINO_"):
                del e[k]
        e["ARDUINO_DIRECTORIES_DATA"] = str(self.env.ARDUINO_DATA)
        e["ARDUINO_DIRECTORIES_DOWNLOADS"] = str(self.env.DOWNLOAD_DIR)
        e["ARDUINO_DIRECTORIES_USER"] = str(self.env.ARDUINO_LIBRARIES.parent)
        e["ARDUINO_BUILD_CACHE_PATH"] = str(self.env.ARDUINO_CACHE)
        return e

    def run(self, args, timeout=600):
        if not self.is_installed():
            raise ToolchainError("Local arduino-cli is not installed.")
        try:
            r = subprocess.run(self.command(args), capture_output=True, text=True,
                               timeout=timeout, env=self.process_env())
        except subprocess.TimeoutExpired:
            raise ToolchainError("arduino-cli timed out.") from None
        except OSError as e:
            raise ToolchainError(f"Could not run arduino-cli: {e}") from None
        return r

    def run_streaming(self, args, output=None, timeout=3600):
        if not self.is_installed():
            raise ToolchainError("Local arduino-cli is not installed.")
        try:
            process = subprocess.Popen(self.command(args), stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1,
                                       env=self.process_env())
        except OSError as e:
            raise ToolchainError(f"Could not run arduino-cli: {e}") from None

        lines = queue.Queue()
        done = object()

        def read_output():
            try:
                for line in process.stdout:
                    lines.put(line.rstrip("\r\n"))
            finally:
                lines.put(done)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        captured = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise ToolchainError("arduino-cli timed out.")
            try:
                line = lines.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if line is done:
                break
            captured.append(line)
            if output is not None:
                output(line)

        returncode = process.wait()
        if returncode != 0:
            raise ToolchainError("\n".join(captured[-30:]).strip() or
                                 f"arduino-cli failed (exit code {returncode}).")
        return subprocess.CompletedProcess(self.command(args), returncode,
                                           stdout="\n".join(captured), stderr="")

    def version(self):
        if not self.is_installed():
            return None
        try:
            r = self.run(["version", "--format", "json"], timeout=30)
            data = json.loads(r.stdout)
            return data.get("VersionString") or data.get("version")
        except (ToolchainError, ValueError):
            return None

    # ---- download
    @staticmethod
    def download_url(version=ARDUINO_CLI_VERSION, system=None, machine=None):
        system = system or sys.platform
        machine = (machine or _platform.machine()).lower()
        arch = {"x86_64": "64bit", "amd64": "64bit", "aarch64": "ARM64", "arm64": "ARM64",
                "i386": "32bit", "i686": "32bit", "armv7l": "ARMv7"}.get(machine)
        if arch is None:
            raise ToolchainError(f"Unsupported CPU architecture: {machine}")
        if system == "win32":
            osname, ext = "Windows", "zip"
        elif system.startswith("linux"):
            osname, ext = "Linux", "tar.gz"
        else:
            raise ToolchainError(f"Unsupported operating system: {system}")
        return (f"https://github.com/arduino/arduino-cli/releases/download/v{version}/"
                f"arduino-cli_{version}_{osname}_{arch}.{ext}")

    def install(self, progress=None, cancelled=lambda: False):
        """Download + unpack arduino-cli into the environment. Reuses a valid local copy."""
        say = progress or (lambda m: None)
        self.env.ensure_dirs()
        if self.is_installed() and self.version():
            say(f"Local Arduino CLI {self.version()} found - reusing it.")
            return
        url = self.download_url()
        archive = self.env.DOWNLOAD_DIR / url.rsplit("/", 1)[1]
        part = archive.with_suffix(archive.suffix + ".part")
        say("Downloading Arduino CLI...")
        try:
            with urllib.request.urlopen(url, timeout=30) as resp, open(part, "wb") as out:
                while True:
                    if cancelled():
                        raise ToolchainError("Cancelled by user.")
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(part, archive)
        except ToolchainError:
            part.unlink(missing_ok=True)
            raise
        except OSError as e:
            part.unlink(missing_ok=True)
            raise ToolchainError(f"Could not download Arduino CLI (check your internet "
                                 f"connection and disk space): {e}") from None
        say("Installing Arduino CLI...")
        try:
            self._extract(archive)
        except (OSError, zipfile.BadZipFile, tarfile.TarError) as e:
            archive.unlink(missing_ok=True)      # corrupted download: do not keep it
            raise ToolchainError(f"The downloaded Arduino CLI archive is corrupt or could "
                                 f"not be unpacked: {e}") from None
        if not self.version():
            raise ToolchainError("Arduino CLI was unpacked but does not run on this system.")

    def _extract(self, archive):
        exe = self.env.exe_name()
        self.env.CLI_DIR.mkdir(parents=True, exist_ok=True)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as z:
                data = z.read(exe)
        else:
            with tarfile.open(archive) as t:
                m = t.extractfile(exe)
                if m is None:
                    raise tarfile.TarError(f"{exe} missing from archive")
                data = m.read()
        tmp = self.path().with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.chmod(0o755)
        os.replace(tmp, self.path())


# --------------------------------------------------------------------------
# Platform manager
# --------------------------------------------------------------------------
class PlatformManager:
    def __init__(self, env, cli, registry=None):
        self.env, self.cli = env, cli
        self.registry = registry or BoardRegistry()

    # ---- status
    def installed_platforms(self):
        """{platform_id: version} as reported by the local arduino-cli."""
        if not self.cli.is_installed():
            return {}
        try:
            r = self.cli.run(["core", "list", "--format", "json"], timeout=60)
            data = json.loads(r.stdout or "{}")
        except (ToolchainError, ValueError):
            return {}
        items = data.get("platforms", data) if isinstance(data, dict) else data
        out = {}
        for p in items or []:
            pid = p.get("id")
            if pid:
                out[pid] = p.get("installed_version") or p.get("installed") or p.get("version", "")
        return out

    def is_platform_installed(self, pid, installed=None):
        installed = self.installed_platforms() if installed is None else installed
        return pid in installed

    def board_status(self, installed=None):
        installed = self.installed_platforms() if installed is None else installed
        return {n: b.platform_id in installed for n, b in self.registry.boards.items()}

    def additional_package_urls(self):
        urls = self.env.load_state().get("additional_package_urls", [])
        if not isinstance(urls, list):
            return []
        return list(dict.fromkeys(url for url in urls if isinstance(url, str)))

    def _write_platform_config(self):
        urls = sorted(set(self.registry.all_urls() + self.additional_package_urls()))
        self.env.write_cli_config(urls)

    def _update_package_indexes(self, progress=None):
        if progress is not None:
            progress("Updating board package indexes...")
        self.cli.run_streaming(["core", "update-index"], progress, timeout=300)

    def add_package_url(self, url, progress=None):
        url = str(url).strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ToolchainError("Enter a valid http:// or https:// package index URL.")
        urls = self.additional_package_urls()
        if url not in urls:
            urls.append(url)
            state = self.env.load_state()
            state["additional_package_urls"] = urls
            self.env.save_state(state)
        self._write_platform_config()
        self._update_package_indexes(progress)

    def remove_package_url(self, url, progress=None):
        urls = [item for item in self.additional_package_urls() if item != url]
        state = self.env.load_state()
        state["additional_package_urls"] = urls
        self.env.save_state(state)
        self._write_platform_config()
        self._update_package_indexes(progress)

    def search_platforms(self, query=""):
        terms = str(query).split()
        self._write_platform_config()
        r = self.cli.run(["core", "search", "--json", "-a", *terms], timeout=180)
        if r.returncode != 0:
            raise ToolchainError((r.stderr or r.stdout).strip() or "Board search failed.")
        try:
            data = json.loads(r.stdout or "{}")
        except ValueError:
            raise ToolchainError("Arduino CLI returned invalid board search data.") from None
        platforms = data.get("platforms", []) if isinstance(data, dict) else []
        return [platform for platform in platforms if isinstance(platform, dict)]

    def install_platform(self, platform_id, version, progress=None):
        self._write_platform_config()
        self.cli.run_streaming(["core", "install", f"{platform_id}@{version}"],
                               progress, timeout=3600)
        self._record_state()

    def check_ready(self, board_name):
        """Return (ok, message). Explains a missing CLI/platform instead of 'Unknown FQBN'."""
        try:
            board = self.registry.board(board_name)
        except KeyError as e:
            return False, str(e.args[0])
        if not BoardRegistry.valid_fqbn(board.fqbn):
            return False, f"Board {board_name!r} has an invalid FQBN: {board.fqbn!r}"
        if not self.cli.is_installed():
            return False, "The local Arduino CLI is not installed. Open Boards Manager to install it."
        plat = self.registry.platform(board.platform_id)
        if not self.is_platform_installed(plat.id):
            return False, (f"{board_name} needs the {plat.name} platform ({plat.id}), which is "
                           f"not installed. Open Boards Manager to install it.")
        return True, ""

    # ---- install / remove
    def install(self, platform_ids, progress=None, cancelled=lambda: False):
        """Install each platform once (deduplicated). Returns {platform_id: error-or-None}."""
        say = progress or (lambda m: None)
        ids = list(dict.fromkeys(platform_ids))              # dedupe, keep order
        self.env.ensure_dirs()
        self.cli.install(say, cancelled)
        urls = sorted({self.registry.platform(i).package_url for i in ids
                       if self.registry.platform(i).package_url})
        self.env.write_cli_config(urls)
        say("Updating package indexes...")
        r = self.cli.run(["core", "update-index"], timeout=300)
        if r.returncode != 0:
            raise ToolchainError("Could not update package indexes (no internet connection?):\n"
                                 + (r.stderr or r.stdout).strip())
        installed = self.installed_platforms()
        results = {}
        for pid in ids:
            if cancelled():
                results[pid] = "Cancelled by user."
                continue
            plat = self.registry.platform(pid)
            if pid in installed:
                say(f"{plat.name} already installed ({installed[pid]}).")
                results[pid] = None
                continue
            say(f"Installing {plat.name}...")
            r = self.cli.run(["core", "install", pid], timeout=3600)
            results[pid] = None if r.returncode == 0 else (r.stderr or r.stdout).strip()
        say("Finalizing environment...")
        self._record_state()
        return results

    def remove(self, pid, progress=None):
        self.cli.run_streaming(["core", "uninstall", pid], progress, timeout=600)
        self._record_state()

    def update(self, progress=None):
        say = progress or (lambda m: None)
        say("Updating package indexes...")
        self.cli.run(["core", "update-index"], timeout=300)
        say("Upgrading platforms...")
        r = self.cli.run(["core", "upgrade"], timeout=3600)
        if r.returncode != 0:
            raise ToolchainError((r.stderr or r.stdout).strip())
        self._record_state()

    def _record_state(self):
        state = self.env.load_state()
        state["arduino_cli_version"] = self.cli.version()
        state["platforms"] = self.installed_platforms()
        state["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        state.setdefault("created", state["updated"])
        self.env.save_state(state)

    # ---- library (local only)
    def search_libraries(self, query):
        terms = str(query).split()
        if not terms:
            return []
        r = self.cli.run(["lib", "search", "--json", "--omit-releases-details", *terms],
                         timeout=180)
        if r.returncode != 0:
            raise ToolchainError((r.stderr or r.stdout).strip() or "Library search failed.")
        try:
            data = json.loads(r.stdout or "{}")
        except ValueError:
            raise ToolchainError("Arduino CLI returned invalid library search data.") from None
        libraries = data.get("libraries", []) if isinstance(data, dict) else []
        return libraries if isinstance(libraries, list) else []

    def installed_libraries(self):
        r = self.cli.run(["lib", "list", "--json"], timeout=120)
        if r.returncode != 0:
            raise ToolchainError((r.stderr or r.stdout).strip() or "Could not list installed libraries.")
        try:
            data = json.loads(r.stdout or "{}")
        except ValueError:
            raise ToolchainError("Arduino CLI returned invalid installed-library data.") from None
        libraries = data.get("installed_libraries", []) if isinstance(data, dict) else []
        if not isinstance(libraries, list):
            return []
        return [item["library"] if isinstance(item, dict) and isinstance(item.get("library"), dict)
                else item for item in libraries if isinstance(item, dict)]

    def install_library(self, name, version=None, progress=None):
        library = f"{name}@{version}" if version else name
        self.cli.run_streaming(["lib", "install", library], progress, timeout=600)

    def remove_library(self, name, progress=None):
        self.cli.run_streaming(["lib", "uninstall", name], progress, timeout=600)

    # ---- compile helpers
    def compile_args(self, board_name, sketch_dir, port=None):
        b = self.registry.board(board_name)
        args = ["compile", "--fqbn", b.fqbn,
                "--build-path", str(self.env.ARDUINO_BUILD / "out")]
        if port:
            args += ["--upload", "-p", port]
        return [*args, str(sketch_dir)]

    def sketch_dir(self):
        return self.env.ARDUINO_BUILD / "sketches" / "notebook_cell"
