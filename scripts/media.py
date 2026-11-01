"""
Media handling for Embedded Notebooks:
Image and video attachment encoding/decoding, resource resolution,
and integrated video player components for Markdown cells.
"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import (
    QBuffer, QByteArray, QObject, Qt, QUrl, Signal,
)
from PySide6.QtGui import (
    QDesktopServices, QImage, QMovie, QTextDocument,
)
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from scripts.theme import (
    BORDER, MUTED, SURFACE, TEXT,
)

# ---------------------------------------------------------------------------
# Supported extensions and MIME types
# ---------------------------------------------------------------------------
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".webm", ".mkv", ".avi", ".mov"}

IMAGE_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

VIDEO_MIMES = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
}


def is_image_file(path_or_name: str) -> bool:
    ext = Path(path_or_name).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def is_video_file(path_or_name: str) -> bool:
    ext = Path(path_or_name).suffix.lower()
    return ext in VIDEO_EXTENSIONS


def detect_mime(path_or_name: str) -> str:
    ext = Path(path_or_name).suffix.lower()
    if ext in IMAGE_MIMES:
        return IMAGE_MIMES[ext]
    if ext in VIDEO_MIMES:
        return VIDEO_MIMES[ext]
    mime, _ = mimetypes.guess_type(path_or_name)
    return mime or "application/octet-stream"


# ---------------------------------------------------------------------------
# Attachment encoding, decoding, and caching
# ---------------------------------------------------------------------------
_MEDIA_CACHE_DIR = None


def get_media_cache_dir() -> Path:
    global _MEDIA_CACHE_DIR
    if _MEDIA_CACHE_DIR is None:
        _MEDIA_CACHE_DIR = Path(tempfile.gettempdir()) / "embedded_notebook_media"
        _MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _MEDIA_CACHE_DIR


def encode_file_to_attachment(filepath: str | Path) -> tuple[str, str, str]:
    """Read a local file and return (filename, mime_type, base64_string)."""
    p = Path(filepath)
    filename = p.name
    mime = detect_mime(filename)
    raw = p.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return filename, mime, b64


def get_attachment_bytes(attachments: dict, filename: str) -> tuple[str | None, bytes | None]:
    """Retrieve (mime_type, raw_bytes) for a filename from cell['attachments']."""
    if not isinstance(attachments, dict) or filename not in attachments:
        return None, None
    entry = attachments[filename]
    if isinstance(entry, dict):
        # standard nbformat: {"image/png": "b64..."}
        # prefer image/video mime
        for mime, val in entry.items():
            if isinstance(val, str) and (mime.startswith("image/") or mime.startswith("video/")):
                try:
                    return mime, base64.b64decode(val.encode("ascii"))
                except Exception:
                    pass
        for mime, val in entry.items():
            if isinstance(val, str):
                try:
                    return mime, base64.b64decode(val.encode("ascii"))
                except Exception:
                    pass
    elif isinstance(entry, str):
        try:
            return detect_mime(filename), base64.b64decode(entry.encode("ascii"))
        except Exception:
            pass
    return None, None


def cache_attachment_video(filename: str, raw_bytes: bytes) -> Path:
    """Write decoded video bytes to temporary cache so QMediaPlayer can stream it."""
    cache_dir = get_media_cache_dir()
    h = hashlib.sha256(raw_bytes).hexdigest()[:12]
    safe_name = re.sub(r"[^\w\-.]", "_", filename)
    out_file = cache_dir / f"{h}_{safe_name}"
    if not out_file.exists() or out_file.stat().st_size != len(raw_bytes):
        out_file.write_bytes(raw_bytes)
    return out_file


# ---------------------------------------------------------------------------
# Media extraction from Markdown text
# ---------------------------------------------------------------------------
_VIDEO_TAG_RE = re.compile(r'<video[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
_SOURCE_TAG_RE = re.compile(r'<source[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
_MD_IMG_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
_IMG_TAG_RE = re.compile(r'<img[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)


def extract_video_sources(text: str, attachments: dict | None = None) -> list[dict]:
    """Find all video references from HTML tags, markdown links/images, or attachments."""
    found = []
    seen = set()

    def add_video(src: str, label: str = ""):
        clean_src = src.strip()
        if not clean_src or clean_src in seen:
            return
        is_att = clean_src.startswith("attachment:")
        name = clean_src[len("attachment:"):] if is_att else Path(clean_src).name
        # If it's an attachment, verify or guess if it's a video
        if is_att:
            if not is_video_file(name) and attachments and name in attachments:
                att_val = attachments[name]
                if isinstance(att_val, dict) and not any(k.startswith("video/") for k in att_val):
                    return
        elif not is_video_file(clean_src) and not clean_src.startswith(("http://", "https://")):
            return
        seen.add(clean_src)
        found.append({"src": clean_src, "name": name, "label": label, "is_attachment": is_att})

    # 1. <video src="...">
    for m in _VIDEO_TAG_RE.finditer(text):
        add_video(m.group(1))
    for m in _SOURCE_TAG_RE.finditer(text):
        add_video(m.group(1))

    # 2. Markdown links/images pointing to video files or attachment:*.video
    for m in _MD_IMG_RE.finditer(text):
        if is_video_file(m.group(2)) or m.group(2).startswith("attachment:"):
            add_video(m.group(2), m.group(1))
    for m in _MD_LINK_RE.finditer(text):
        if is_video_file(m.group(2)) or (m.group(2).startswith("attachment:") and is_video_file(m.group(2))):
            add_video(m.group(2), m.group(1))

    # 3. Any video attachments present in cell's extra['attachments']
    if attachments and isinstance(attachments, dict):
        for name, data in attachments.items():
            if is_video_file(name):
                add_video(f"attachment:{name}", name)
            elif isinstance(data, dict) and any(k.startswith("video/") for k in data):
                add_video(f"attachment:{name}", name)

    return found


def extract_gif_sources(text: str, attachments: dict | None = None,
                        notebook_dir: Path | str | None = None,
                        base_dir: Path | str | None = None) -> list[dict]:
    """Find all animated GIF references from markdown images, HTML img tags, or attachments."""
    if notebook_dir is None:
        notebook_dir = base_dir
    found = []
    seen = set()

    def check_and_add(src_str: str):
        src_str = src_str.strip()
        if not src_str or src_str in seen:
            return

        is_att = src_str.startswith("attachment:")
        name = src_str[len("attachment:"):] if is_att else Path(src_str).name

        # Verify whether this resource is a GIF
        is_gif = name.lower().endswith(".gif")
        if not is_gif and attachments and name in attachments:
            att_val = attachments[name]
            if isinstance(att_val, dict) and any(k == "image/gif" for k in att_val):
                is_gif = True

        if not is_gif:
            return

        seen.add(src_str)

        raw_bytes = None
        file_path = None

        if is_att or (attachments and src_str in attachments):
            key = name if is_att else src_str
            _, raw_bytes = get_attachment_bytes(attachments, key)
        else:
            cand = Path(src_str)
            if not cand.is_file() and notebook_dir:
                cand = Path(notebook_dir) / src_str
            if not cand.is_file():
                for fallback in (Path.cwd(), Path.cwd() / "Example Notebooks"):
                    alt = fallback / src_str
                    if alt.is_file():
                        cand = alt
                        break
            if cand.is_file():
                file_path = cand.resolve()

        if raw_bytes or (file_path and file_path.is_file()):
            found.append({
                "src": src_str,
                "name": name,
                "is_attachment": is_att,
                "raw_bytes": raw_bytes,
                "file_path": file_path,
            })

    # 1. Markdown images: ![alt](url)
    for m in _MD_IMG_RE.finditer(text):
        check_and_add(m.group(2))

    # 2. HTML img tags: <img src="url">
    for m in _IMG_TAG_RE.finditer(text):
        check_and_add(m.group(1))

    # 3. Attachments
    if attachments and isinstance(attachments, dict):
        for att_name, att_data in attachments.items():
            if att_name.lower().endswith(".gif") or (isinstance(att_data, dict) and "image/gif" in att_data):
                check_and_add(f"attachment:{att_name}")

    return found


# ---------------------------------------------------------------------------
# Animated GIF Controller
# ---------------------------------------------------------------------------
class GifPlayer(QObject):
    """
    Manages QMovie playback for an animated GIF embedded in a QTextDocument.
    Updates QTextDocument image resources on frame change and triggers viewport redraw.
    """

    def __init__(self, doc: QTextDocument, view: QWidget | None,
                 src: str, file_path: Path | None = None,
                 raw_bytes: bytes | None = None,
                 max_width: int = 800, on_first_frame=None, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.view = view
        self.src = src
        self.file_path = file_path
        self.raw_bytes = raw_bytes
        self.max_width = max_width
        self.on_first_frame = on_first_frame

        self.movie: QMovie | None = None
        self._buffer: QBuffer | None = None
        self._byte_array: QByteArray | None = None

        self._setup()

    def _setup(self):
        if self.file_path and Path(self.file_path).is_file():
            self.movie = QMovie(str(self.file_path))
        elif self.raw_bytes:
            self._byte_array = QByteArray(self.raw_bytes)
            self._buffer = QBuffer(self._byte_array)
            self._buffer.open(QBuffer.ReadOnly)
            self.movie = QMovie(self._buffer, QByteArray(b"GIF"))
        else:
            return

        if not self.movie.isValid():
            self.release()
            return

        self.movie.frameChanged.connect(self._on_frame_changed)

        # Apply initial frame immediately so the document has the image rendered
        if self.movie.jumpToFrame(0):
            img = self.movie.currentImage()
            if not img.isNull():
                self._apply_frame(img)

    def _on_frame_changed(self, frame_num: int):
        if self.movie:
            img = self.movie.currentImage()
            if not img.isNull():
                self._apply_frame(img)
                if self.on_first_frame:
                    cb = self.on_first_frame
                    self.on_first_frame = None
                    try:
                        cb()
                    except Exception:
                        pass

    def _apply_frame(self, img: QImage):
        if not self.doc or img.isNull():
            return
        if self.max_width and img.width() > self.max_width:
            img = img.scaledToWidth(self.max_width, Qt.SmoothTransformation)

        # Update document resources under all key variations:
        self.doc.addResource(QTextDocument.ImageResource, QUrl(self.src), img)
        self.doc.addResource(QTextDocument.ImageResource, self.src, img)

        name = Path(self.src).name
        if name != self.src:
            self.doc.addResource(QTextDocument.ImageResource, QUrl(name), img)
            self.doc.addResource(QTextDocument.ImageResource, name, img)

        if self.src.startswith("attachment:"):
            clean_name = self.src[len("attachment:"):]
            self.doc.addResource(QTextDocument.ImageResource, QUrl(clean_name), img)
            self.doc.addResource(QTextDocument.ImageResource, clean_name, img)

        if self.view and hasattr(self.view, "viewport"):
            vp = self.view.viewport()
            if vp:
                vp.update()

    def start(self):
        if self.movie and self.movie.isValid():
            if self.movie.frameCount() != 1:
                self.movie.start()

    def pause(self):
        if self.movie and self.movie.isValid():
            self.movie.setPaused(True)

    def stop(self):
        if self.movie and self.movie.isValid():
            self.movie.stop()

    def release(self):
        if self.movie is not None:
            try:
                self.movie.frameChanged.disconnect()
            except Exception:
                pass
            self.movie.stop()
            self.movie = None
        if self._buffer is not None:
            try:
                self._buffer.close()
            except Exception:
                pass
            self._buffer = None
        self._byte_array = None
        self.view = None
        self.doc = None


# ---------------------------------------------------------------------------
# Custom QTextDocument for MarkdownCell with dynamic attachment image loading
# ---------------------------------------------------------------------------
class MarkdownDocument(QTextDocument):
    """QTextDocument that resolves attachment: and relative image resources seamlessly."""

    def __init__(self, cell_ref, parent=None):
        super().__init__(parent)
        self._cell_ref = cell_ref
        self._cache = {}

    def clear_cache(self):
        self._cache.clear()

    def loadResource(self, r_type, url):
        if r_type == QTextDocument.ImageResource:
            url_str = url.toString() if hasattr(url, "toString") else str(url)

            # For animated GIFs, allow live frames from addResource to take precedence
            is_gif = url_str.lower().endswith(".gif")
            if not is_gif and url_str in self._cache:
                return self._cache[url_str]

            img = self._resolve_image(url_str)
            if img and not img.isNull():
                max_w = 800
                if img.width() > max_w:
                    img = img.scaledToWidth(max_w, Qt.SmoothTransformation)
                if not is_gif:
                    self._cache[url_str] = img
                return img

        return super().loadResource(r_type, url)

    def _resolve_image(self, url_str: str) -> QImage | None:
        cell = self._cell_ref()
        if cell is None:
            return None

        # 1. attachment: protocol
        if url_str.startswith("attachment:"):
            filename = url_str[len("attachment:"):]
            atts = getattr(cell, "extra", {}).get("attachments", {})
            _, raw = get_attachment_bytes(atts, filename)
            if raw:
                qimg = QImage()
                if qimg.loadFromData(raw):
                    return qimg

        # 2. Direct filename in attachments
        atts = getattr(cell, "extra", {}).get("attachments", {})
        if url_str in atts:
            _, raw = get_attachment_bytes(atts, url_str)
            if raw:
                qimg = QImage()
                if qimg.loadFromData(raw):
                    return qimg

        # 3. Local file path (absolute or relative to notebook directory or CWD)
        cand = Path(url_str)
        if not cand.is_file():
            nb_dir = getattr(cell, "notebook_dir", None)
            if nb_dir:
                cand = Path(nb_dir) / url_str
        if not cand.is_file():
            for fallback in (Path.cwd(), Path.cwd() / "Example Notebooks"):
                alt = fallback / url_str
                if alt.is_file():
                    cand = alt
                    break
        if cand.is_file():
            qimg = QImage()
            if qimg.load(str(cand)):
                return qimg

        return None


# ---------------------------------------------------------------------------
# Embedded Video Player Widget
# ---------------------------------------------------------------------------
def format_time_ms(ms: int) -> str:
    s = max(0, int(ms / 1000))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


class VideoPlayerWidget(QFrame):
    """Integrated media player widget embedded in Markdown cells for video attachments."""
    delete_req = Signal(object)

    def __init__(self, src: str, name: str, is_attachment: bool = True,
                 local_file: Path | None = None, parent=None):
        super().__init__(parent)
        self.src = src
        self.name = name
        self.is_attachment = is_attachment
        self.local_file = local_file
        self.setObjectName("videoCard")
        self.setFrameShape(QFrame.StyledPanel)

        # Lazy imports for QtMultimedia
        self._player = None
        self._audio = None
        self._video_widget = None
        self._init_ui()
        self._setup_player()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # --- Top Header ---
        head = QHBoxLayout()
        head.setSpacing(6)

        icon_lbl = QLabel("🎥")
        icon_lbl.setStyleSheet("font-size: 14px;")
        head.addWidget(icon_lbl)

        self.title_lbl = QLabel(self.name)
        self.title_lbl.setStyleSheet(f"font-weight: bold; color: {TEXT}; font-size: 12px;")
        head.addWidget(self.title_lbl, 1)

        badge = QLabel("Attached" if self.is_attachment else "Local File")
        badge.setStyleSheet(f"background: {SURFACE}; color: {MUTED}; border: 1px solid {BORDER}; "
                            "border-radius: 3px; padding: 2px 6px; font-size: 10px;")
        head.addWidget(badge)

        self.popout_btn = QPushButton("⛶ Pop-out")
        self.popout_btn.setObjectName("quiet")
        self.popout_btn.setToolTip("Open video in separate window")
        self.popout_btn.setFixedHeight(24)
        self.popout_btn.clicked.connect(self._open_popout)
        head.addWidget(self.popout_btn)

        if self.is_attachment:
            self.del_btn = QPushButton("✕")
            self.del_btn.setObjectName("move")
            self.del_btn.setToolTip("Remove video from cell")
            self.del_btn.setFixedSize(24, 24)
            self.del_btn.clicked.connect(lambda: self.delete_req.emit(self))
            head.addWidget(self.del_btn)

        lay.addLayout(head)

        # --- Video Output Container ---
        try:
            from PySide6.QtMultimediaWidgets import QVideoWidget
            self._video_widget = QVideoWidget()
            self._video_widget.setMinimumHeight(180)
            self._video_widget.setMaximumHeight(360)
            self._video_widget.setStyleSheet(f"background: black; border-radius: 4px;")
            lay.addWidget(self._video_widget)
        except Exception:
            self._video_widget = None
            fallback_lbl = QLabel("Video preview initialized (external player available)")
            fallback_lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(fallback_lbl)

        # --- Scrub bar ---
        scrub_row = QHBoxLayout()
        scrub_row.setSpacing(8)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        scrub_row.addWidget(self.slider, 1)

        self.time_lbl = QLabel("00:00 / 00:00")
        self.time_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        scrub_row.addWidget(self.time_lbl)
        lay.addLayout(scrub_row)

        # --- Controls Bar ---
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)

        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setObjectName("primary")
        self.play_btn.setFixedHeight(26)
        self.play_btn.clicked.connect(self.toggle_play)
        ctrl.addWidget(self.play_btn)

        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setFixedHeight(26)
        self.stop_btn.clicked.connect(self.stop)
        ctrl.addWidget(self.stop_btn)

        ctrl.addSpacing(12)

        self.mute_btn = QPushButton("🔊")
        self.mute_btn.setObjectName("quiet")
        self.mute_btn.setFixedSize(28, 26)
        self.mute_btn.clicked.connect(self.toggle_mute)
        ctrl.addWidget(self.mute_btn)

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.setFixedWidth(80)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        ctrl.addWidget(self.vol_slider)

        ctrl.addStretch()

        self.sys_btn = QPushButton("Open External")
        self.sys_btn.setObjectName("quiet")
        self.sys_btn.setFixedHeight(26)
        self.sys_btn.setToolTip("Open file in default operating system video player")
        self.sys_btn.clicked.connect(self._open_system_player)
        ctrl.addWidget(self.sys_btn)

        lay.addLayout(ctrl)
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(
            f"#videoCard {{ background: {SURFACE}; border: 1px solid {BORDER}; "
            f"border-radius: 6px; }}"
        )

    def retheme(self):
        self._apply_style()
        self.title_lbl.setStyleSheet(f"font-weight: bold; color: {TEXT}; font-size: 12px;")
        self.time_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")

    def _setup_player(self):
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            if self._video_widget is not None:
                self._player.setVideoOutput(self._video_widget)

            self._audio.setVolume(self.vol_slider.value() / 100.0)

            self._player.playbackStateChanged.connect(self._on_state_changed)
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)

            # Set source file
            if self.local_file and self.local_file.exists():
                self._player.setSource(QUrl.fromLocalFile(str(self.local_file)))
        except Exception:
            self._player = None
            self._audio = None

    def toggle_play(self):
        if self._player is None:
            self._open_system_player()
            return
        from PySide6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def stop(self):
        if self._player is not None:
            self._player.stop()

    def toggle_mute(self):
        if self._audio is not None:
            muted = not self._audio.isMuted()
            self._audio.setMuted(muted)
            self.mute_btn.setText("🔇" if muted else "🔊")

    def _on_volume_changed(self, val):
        if self._audio is not None:
            self._audio.setVolume(val / 100.0)
            if val == 0:
                self.mute_btn.setText("🔇")
            elif self._audio.isMuted():
                self.mute_btn.setText("🔇")
            else:
                self.mute_btn.setText("🔊")

    def _on_state_changed(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        if state == QMediaPlayer.PlayingState:
            self.play_btn.setText("❚❚ Pause")
        else:
            self.play_btn.setText("▶ Play")

    def _on_position_changed(self, pos):
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        dur = self._player.duration() if self._player else 0
        self.time_lbl.setText(f"{format_time_ms(pos)} / {format_time_ms(dur)}")

    def _on_duration_changed(self, dur):
        self.slider.setRange(0, dur)
        pos = self._player.position() if self._player else 0
        self.time_lbl.setText(f"{format_time_ms(pos)} / {format_time_ms(dur)}")

    def _on_slider_moved(self, pos):
        if self._player is not None:
            self._player.setPosition(pos)

    def _open_popout(self):
        dlg = VideoPopoutDialog(self.name, self.local_file, self)
        dlg.exec()

    def _open_system_player(self):
        if self.local_file and self.local_file.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.local_file)))

    def release(self):
        """Stop and release media resources cleanly."""
        if self._player is not None:
            try:
                self._player.stop()
                self._player.setSource(QUrl())
            except Exception:
                pass
            self._player.deleteLater()
            self._player = None
        if self._audio is not None:
            self._audio.deleteLater()
            self._audio = None


class VideoPopoutDialog(QDialog):
    """Dedicated popout dialog to watch video attachments in a larger resizable window."""

    def __init__(self, title: str, local_file: Path | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Video: {title}")
        self.resize(720, 480)
        lay = QVBoxLayout(self)

        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget

        self.vw = QVideoWidget()
        lay.addWidget(self.vw, 1)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.vw)

        # Controls
        ctrl = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self._toggle_play)
        ctrl.addWidget(self.play_btn)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        ctrl.addWidget(self.slider, 1)

        self.time_lbl = QLabel("00:00 / 00:00")
        ctrl.addWidget(self.time_lbl)
        lay.addLayout(ctrl)

        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)
        self.player.playbackStateChanged.connect(self._on_state)

        if local_file and local_file.exists():
            self.player.setSource(QUrl.fromLocalFile(str(local_file)))
            self.player.play()

    def _toggle_play(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_state(self, st):
        from PySide6.QtMultimedia import QMediaPlayer
        self.play_btn.setText("❚❚ Pause" if st == QMediaPlayer.PlayingState else "▶ Play")

    def _on_pos(self, pos):
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.time_lbl.setText(f"{format_time_ms(pos)} / {format_time_ms(self.player.duration())}")

    def _on_dur(self, dur):
        self.slider.setRange(0, dur)
        self.time_lbl.setText(f"{format_time_ms(self.player.position())} / {format_time_ms(dur)}")

    def closeEvent(self, ev):
        self.player.stop()
        super().closeEvent(ev)

