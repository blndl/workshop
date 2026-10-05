"""Image sources. Each returns JPEG bytes from latest_jpeg() while open."""

from __future__ import annotations

import itertools
import threading
import time
from pathlib import Path


class OpenCVSource:
    """USB webcam (or the Mac's built-in one) through OpenCV.

    While open, a background thread keeps reading frames so a capture is
    instant and never returns a stale buffered frame.
    """

    def __init__(self, device: int = 0, width: int = 1280, height: int = 720, quality: int = 85):
        self.device, self.width, self.height, self.quality = device, width, height, quality
        self._cap = None
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def open(self) -> None:
        import cv2

        if self._cap is not None:
            return
        cap = cv2.VideoCapture(self.device)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open camera {self.device} (on macOS, allow camera access for your terminal)")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap = cap
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 3
        while self._frame is None and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.5)  # let auto-exposure settle; first frames are often dark

    def _reader(self) -> None:
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._frame = frame
            else:
                time.sleep(0.05)

    def latest_jpeg(self) -> bytes:
        import cv2

        with self._lock:
            frame = None if self._frame is None else self._frame.copy()
        if frame is None:
            raise RuntimeError("no frame from camera")
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return buf.tobytes()

    def close(self) -> None:
        if self._cap is None:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._cap.release()
        self._cap, self._frame, self._thread = None, None, None

    @property
    def is_open(self) -> bool:
        return self._cap is not None


class FolderSource:
    """Cycles through the .jpg files in a folder (test images for the detector)."""

    def __init__(self, folder: Path):
        self.files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))
        if not self.files:
            raise ValueError(f"no .jpg files in {folder}")
        self._cycle = itertools.cycle(self.files)
        self.is_open = False

    def open(self) -> None:
        self.is_open = True

    def latest_jpeg(self) -> bytes:
        return next(self._cycle).read_bytes()

    def close(self) -> None:
        self.is_open = False


class FakeSource:
    """Generated frames with a timestamp, or fixed bytes for tests."""

    def __init__(self, data: bytes | None = None):
        self.data = data
        self.is_open = False
        self.opened = 0

    def open(self) -> None:
        self.is_open = True
        self.opened += 1

    def latest_jpeg(self) -> bytes:
        if not self.is_open:
            raise RuntimeError("camera closed")
        if self.data is not None:
            return self.data
        import cv2
        import numpy as np

        img = np.full((360, 640, 3), 60, np.uint8)
        cv2.putText(img, "FAKE CAMERA", (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        cv2.putText(img, time.strftime("%Y-%m-%d %H:%M:%S"), (40, 230), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 2)
        return cv2.imencode(".jpg", img)[1].tobytes()

    def close(self) -> None:
        self.is_open = False
