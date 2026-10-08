import json
from pathlib import Path

import numpy as np
import pytest

from alarm_detector.service import DetectorService
from alarm_detector.yolo import CLASSES, Box, decode, nms
from alarm_protocol.transport import MemoryBus

MODEL = Path(__file__).resolve().parents[3] / "models" / "yolov8n.onnx"


def fake_output(*objects):
    """YOLOv8 output (1, 84, N) with the given (class, conf, cx, cy, w, h) in 640x640 space."""
    out = np.zeros((1, 84, max(len(objects), 1)), np.float32)
    for i, (cls, conf, cx, cy, w, h) in enumerate(objects):
        out[0, :4, i] = (cx, cy, w, h)
        out[0, 4 + CLASSES.index(cls), i] = conf
    return out


def test_decode_scales_boxes_back_to_the_image():
    # 1280x640 image letterboxed into 640x640: scale 0.5, 160 px of padding top and bottom.
    out = fake_output(("person", 0.9, 320, 320, 100, 200), ("chair", 0.95, 100, 100, 10, 10))
    boxes = decode(out, 0.5, 0, 160, 1280, 640)
    assert [b.label for b in boxes] == ["person"]  # chairs don't interest the alarm
    b = boxes[0]
    assert (round(b.x, 3), round(b.y, 3), round(b.w, 3), round(b.h, 3)) == (0.422, 0.188, 0.156, 0.625)


def test_threshold_and_nms():
    out = fake_output(("person", 0.9, 300, 300, 100, 100), ("person", 0.8, 305, 302, 100, 100),
                      ("person", 0.3, 50, 50, 20, 20), ("cat", 0.7, 500, 500, 50, 50))
    boxes = decode(out, 1.0, 0, 0, 640, 640, threshold=0.4)
    assert sorted(b.label for b in boxes) == ["cat", "person"]  # duplicate merged, weak one dropped
    assert nms(np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], float), np.array([0.9, 0.8, 0.7]), 0.45) == [0, 2]


class FakeDetector:
    def __init__(self, person):
        self.person = person

    def detect_jpeg(self, data):
        if data == b"broken":
            raise ValueError("not a decodable image")
        return ([Box("person", 0.91, 0.1, 0.2, 0.3, 0.4)] if self.person else [Box("cat", 0.8, 0, 0, 0.2, 0.2)]), 12.5


def run(tmp_path, detector, events):
    (tmp_path / "day").mkdir(exist_ok=True)
    (tmp_path / "day" / "a.jpg").write_bytes(b"jpeg")
    (tmp_path / "day" / "bad.jpg").write_bytes(b"broken")
    bus = MemoryBus()
    svc = DetectorService(detector, tmp_path, bus.client(), "yolov8n.onnx", log=lambda _m: None, wall=lambda: 1.0)
    pub = bus.client()
    for e in events:
        pub.publish("alarm/events", json.dumps(e))
    svc.tick(0)
    return svc, bus


def test_service_publishes_one_result_per_snapshot(tmp_path):
    svc, bus = run(tmp_path, FakeDetector(True), [
        {"type": "snapshot", "path": "day/a.jpg", "reason": "verify-1"},
        {"type": "state", "state": "armed"},
        {"type": "snapshot", "path": "../../etc/passwd", "reason": "x"},   # outside the folder
        {"type": "snapshot", "path": "day/bad.jpg", "reason": "y"},         # unreadable
    ])
    results = [json.loads(p) for t, p in bus.log if t == "alarm/detections"]
    assert len(results) == 1
    r = results[0]
    assert r["person"] and r["confidence"] == 0.91 and r["reason"] == "verify-1" and r["objects"] == {"person": 1}
    status = [json.loads(p) for t, p in bus.log if t == "alarm/detector/status"][-1]
    assert status["ready"] and status["processed"] == 1 and status["errors"] == 1


def test_no_model_reports_it_and_stays_quiet(tmp_path):
    svc, bus = run(tmp_path, None, [{"type": "snapshot", "path": "day/a.jpg", "reason": "verify-1"}])
    assert not [p for t, p in bus.log if t == "alarm/detections"]
    status = [json.loads(p) for t, p in bus.log if t == "alarm/detector/status"][-1]
    assert status["ready"] is False and status["error"] == "model not loaded"


@pytest.mark.skipif(not MODEL.exists(), reason="no model (scripts/get-model.sh)")
def test_real_model_sees_nobody_in_an_empty_room():
    import cv2

    from alarm_detector.yolo import Detector

    img = np.full((480, 640, 3), 90, np.uint8)
    cv2.rectangle(img, (100, 300), (540, 470), (60, 40, 30), -1)  # a "table"
    boxes, ms = Detector(str(MODEL)).detect_jpeg(cv2.imencode(".jpg", img)[1].tobytes())
    assert not [b for b in boxes if b.label == "person"] and ms < 5000
