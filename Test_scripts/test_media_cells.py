import base64
import os
import pathlib
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.argv = ["x"]

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QFont, QImage, QTextDocument
from PySide6.QtWidgets import QApplication

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent if pathlib.Path(__file__).resolve().parent.name == "Test_scripts" else pathlib.Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.cells import MarkdownCell, Notebook
from scripts.notebook_format import parse_notebook, serialize_notebook
from scripts.media import (
    VideoPlayerWidget, cache_attachment_video, detect_mime,
    encode_file_to_attachment, extract_video_sources, get_attachment_bytes,
    is_image_file, is_video_file,
)

app = QApplication.instance() or QApplication([])


class TestMarkdownMediaCells(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mono = QFont("Monospace", 10)

        # Create a tiny 16x16 PNG image file
        self.test_img_path = pathlib.Path(self.tmp) / "test_diagram.png"
        img = QImage(16, 16, QImage.Format_RGB32)
        img.fill(QColor(0, 150, 150))
        img.save(str(self.test_img_path), "PNG")

        # Create a mock video file (.mp4)
        self.test_video_path = pathlib.Path(self.tmp) / "test_clip.mp4"
        self.test_video_path.write_bytes(b"\x00\x00\x00 ftypisom\x00\x00\x02\x00mock video data")

    def tearDown(self):
        app.processEvents()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_media_type_detection(self):
        self.assertTrue(is_image_file("diagram.png"))
        self.assertTrue(is_image_file("photo.jpg"))
        self.assertTrue(is_image_file("animation.gif"))
        self.assertFalse(is_image_file("clip.mp4"))

        self.assertTrue(is_video_file("demo.mp4"))
        self.assertTrue(is_video_file("recording.webm"))
        self.assertTrue(is_video_file("test.mkv"))
        self.assertFalse(is_video_file("photo.png"))

        self.assertEqual(detect_mime("test.png"), "image/png")
        self.assertEqual(detect_mime("test.mp4"), "video/mp4")

    def test_attachment_encoding_decoding(self):
        fname, mime, b64 = encode_file_to_attachment(self.test_img_path)
        self.assertEqual(fname, "test_diagram.png")
        self.assertEqual(mime, "image/png")
        self.assertTrue(len(b64) > 0)

        atts = {fname: {mime: b64}}
        ret_mime, raw = get_attachment_bytes(atts, fname)
        self.assertEqual(ret_mime, "image/png")
        self.assertEqual(raw, self.test_img_path.read_bytes())

    def test_markdown_cell_attach_image(self):
        cell = MarkdownCell(self.mono, text="# Diagram", kind="markdown")
        self.assertEqual(cell.extra.get("attachments", {}), {})

        # Attach image file
        cell.attach_file(self.test_img_path)

        # Verify attachment is registered
        atts = cell.extra.get("attachments", {})
        self.assertIn("test_diagram.png", atts)
        self.assertIn("image/png", atts["test_diagram.png"])

        # Verify markdown text references attachment
        text = cell.get_text()
        self.assertIn("![test_diagram.png](attachment:test_diagram.png)", text)

        # Switch to preview mode and check document resource resolution
        if not cell.preview:
            cell.toggle()
        self.assertTrue(cell.preview)
        doc = cell.view.document()
        res = doc.resource(QTextDocument.ImageResource, "attachment:test_diagram.png")
        self.assertIsNotNone(res)
        self.assertFalse(res.isNull())
        self.assertEqual(res.width(), 16)
        self.assertEqual(res.height(), 16)

    def test_markdown_cell_attach_video(self):
        cell = MarkdownCell(self.mono, text="# Demo Video", kind="markdown")

        # Attach video file
        cell.attach_file(self.test_video_path)

        # Verify attachment is registered
        atts = cell.extra.get("attachments", {})
        self.assertIn("test_clip.mp4", atts)
        self.assertIn("video/mp4", atts["test_clip.mp4"])

        # Verify markdown tag
        text = cell.get_text()
        self.assertIn('<video src="attachment:test_clip.mp4" controls></video>', text)

        # Switch to preview mode and check video player creation
        if not cell.preview:
            cell.toggle()
        self.assertTrue(cell.preview)
        self.assertEqual(len(cell.video_players), 1)
        player_widget = cell.video_players[0]
        self.assertEqual(player_widget.name, "test_clip.mp4")
        self.assertTrue(player_widget.is_attachment)
        self.assertIsNotNone(player_widget.local_file)
        self.assertTrue(player_widget.local_file.exists())

        # Cleanup
        cell.release()

    def test_video_player_controls(self):
        cached_file = cache_attachment_video("sample.mp4", b"mock mp4 payload")
        player_w = VideoPlayerWidget(src="attachment:sample.mp4", name="sample.mp4",
                                     is_attachment=True, local_file=cached_file)
        self.assertEqual(player_w.name, "sample.mp4")
        player_w.toggle_play()
        player_w.stop()
        player_w.toggle_mute()
        player_w.retheme()
        player_w.release()

    def test_markdown_cell_paste_image(self):
        cell = MarkdownCell(self.mono, text="", kind="markdown")
        img = QImage(24, 24, QImage.Format_RGB32)
        img.fill(QColor(255, 0, 0))

        cell.attach_image_object(img, name_hint="screenshot")
        atts = cell.extra.get("attachments", {})
        self.assertEqual(len(atts), 1)
        fname = next(iter(atts.keys()))
        self.assertTrue(fname.startswith("screenshot_"))
        self.assertTrue(fname.endswith(".png"))
        self.assertIn(f"attachment:{fname}", cell.get_text())

    def test_notebook_serialization_with_media_attachments(self):
        nb = Notebook(self.mono)
        md_cell = nb.add_markdown(text="# Project Guide\n", kind="markdown")
        md_cell.attach_file(self.test_img_path)
        md_cell.attach_file(self.test_video_path)

        cells = nb.export_cells()
        self.assertEqual(len(cells), 1)
        exported_atts = cells[0]["extra"].get("attachments", {})
        self.assertIn("test_diagram.png", exported_atts)
        self.assertIn("test_clip.mp4", exported_atts)

        # Serialize to JSON (Jupyter nbformat 4)
        serialized_json = serialize_notebook(cells, metadata={})
        self.assertIn("test_diagram.png", serialized_json)
        self.assertIn("test_clip.mp4", serialized_json)
        self.assertIn("image/png", serialized_json)
        self.assertIn("video/mp4", serialized_json)

        # Deserialize and load into new notebook
        parsed_cells, meta, minor = parse_notebook(serialized_json)
        self.assertEqual(len(parsed_cells), 1)
        self.assertIn("attachments", parsed_cells[0]["extra"])

        nb2 = Notebook(self.mono)
        nb2.load_cells(parsed_cells)
        self.assertEqual(len(nb2.cells), 1)
        reloaded_cell = nb2.cells[0]
        self.assertIsInstance(reloaded_cell, MarkdownCell)
        self.assertIn("test_diagram.png", reloaded_cell.extra["attachments"])
        self.assertIn("test_clip.mp4", reloaded_cell.extra["attachments"])

        # Check that video player is created upon load
        if not reloaded_cell.preview:
            reloaded_cell.toggle()
        self.assertEqual(len(reloaded_cell.video_players), 1)
        self.assertEqual(reloaded_cell.video_players[0].name, "test_clip.mp4")

        # Cleanup
        reloaded_cell.release()

    def test_markdown_cell_animated_gif_local_file(self):
        gif_path = PROJECT_ROOT / "Example Notebooks" / "Preview.gif"
        self.assertTrue(gif_path.exists())

        md_text = f"# Animated Demonstration\n\n![Preview]({gif_path})\n"
        cell = MarkdownCell(self.mono, text=md_text, kind="markdown")

        if not cell.preview:
            cell.toggle()
        self.assertTrue(cell.preview)

        # Verify GIF player initialized
        self.assertEqual(len(cell.gif_players), 1)
        gp = cell.gif_players[0]
        self.assertIsNotNone(gp.movie)
        self.assertTrue(gp.movie.isValid())
        self.assertGreater(gp.movie.frameCount(), 1)

        # Verify document resource is populated
        doc = cell.view.document()
        res = doc.resource(QTextDocument.ImageResource, str(gif_path))
        self.assertIsNotNone(res)
        self.assertFalse(res.isNull())
        self.assertGreater(res.width(), 0)
        self.assertGreater(res.height(), 0)

        # Advance frame and verify update
        gp.movie.jumpToNextFrame()
        app.processEvents()
        res2 = doc.resource(QTextDocument.ImageResource, str(gif_path))
        self.assertFalse(res2.isNull())

        # Cleanup
        cell.release()
        self.assertEqual(len(cell.gif_players), 0)

    def test_markdown_cell_attach_animated_gif(self):
        gif_path = PROJECT_ROOT / "Example Notebooks" / "Preview.gif"
        cell = MarkdownCell(self.mono, text="# Embedded Lab\n", kind="markdown")

        # Attach animated GIF
        attached_name = cell.attach_file(gif_path)
        self.assertEqual(attached_name, "Preview.gif")

        # Verify attachments metadata
        atts = cell.extra.get("attachments", {})
        self.assertIn("Preview.gif", atts)
        self.assertIn("image/gif", atts["Preview.gif"])
        self.assertIn("![Preview.gif](attachment:Preview.gif)", cell.get_text())

        # Toggle to preview mode
        if not cell.preview:
            cell.toggle()
        self.assertTrue(cell.preview)

        # Verify GIF player created from attachment
        self.assertEqual(len(cell.gif_players), 1)
        gp = cell.gif_players[0]
        self.assertTrue(gp.movie.isValid())
        self.assertGreater(gp.movie.frameCount(), 1)

        # Verify document resource resolves attachment GIF
        doc = cell.view.document()
        res = doc.resource(QTextDocument.ImageResource, "attachment:Preview.gif")
        self.assertIsNotNone(res)
        self.assertFalse(res.isNull())

        # Toggle back to edit mode -> players cleared
        cell.toggle()
        self.assertFalse(cell.preview)
        self.assertEqual(len(cell.gif_players), 0)

        # Toggle to preview again -> players recreated and active
        cell.toggle()
        self.assertTrue(cell.preview)
        self.assertEqual(len(cell.gif_players), 1)

        # Cleanup
        cell.release()


if __name__ == "__main__":
    unittest.main()
