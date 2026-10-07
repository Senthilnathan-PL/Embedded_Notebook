"""
Background reader thread for serial monitor.
"""
from PySide6.QtCore import QThread, Signal
import serial


class SerialWorker(QThread):
    line = Signal(str)
    error = Signal(str)

    def __init__(self, port, baud):
        super().__init__()
        self.port, self.baud = port, baud
        self._running = True
        self._ser = None

    def run(self):
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=0.1)
        except Exception as e:  # noqa: BLE001
            self.error.emit(f"Could not open {self.port}: {e}")
            return
        buf = b""
        while self._running:
            try:
                data = self._ser.read(256)
            except Exception as e:  # noqa: BLE001
                self.error.emit(f"Serial error: {e}")
                break
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self.line.emit(raw.decode(errors="replace").rstrip("\r"))
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass

    def send(self, text):
        if self._ser and self._ser.is_open:
            self._ser.write(text.encode())

    def stop(self):
        self._running = False
        self.wait(2000)

