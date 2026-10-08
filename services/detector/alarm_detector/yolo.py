"""YOLOv8n object detection with ONNX Runtime (same pre-processing as the
vision branch's browser detector: 640x640 letterbox, RGB, 0-1, NCHW).

Boxes are returned normalised to the original image (0-1), so the dashboard
can draw them over any size of thumbnail.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

INPUT = 640
# COCO classes, in model order.
CLASSES = (
    "person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant stop_sign "
    "parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe backpack umbrella handbag "
    "tie suitcase frisbee skis snowboard sports_ball kite baseball_bat baseball_glove skateboard surfboard "
    "tennis_racket bottle wine_glass cup fork knife spoon bowl banana apple sandwich orange broccoli carrot "
    "hot_dog pizza donut cake chair couch potted_plant bed dining_table toilet tv laptop mouse remote keyboard "
    "cell_phone microwave oven toaster sink refrigerator book clock vase scissors teddy_bear hair_drier toothbrush"
).split()
# What the alarm cares about: people, and the usual false-alarm culprits.
INTERESTING = {"person", "cat", "dog", "bird"}


@dataclass
class Box:
    label: str
    confidence: float
    x: float  # left, 0-1
    y: float  # top, 0-1
    w: float
    h: float

    def as_dict(self) -> dict:
        return {"label": self.label, "confidence": round(self.confidence, 3),
                "x": round(self.x, 4), "y": round(self.y, 4), "w": round(self.w, 4), "h": round(self.h, 4)}


def letterbox(rgb: np.ndarray) -> tuple[np.ndarray, float, float, float]:
    """Resize keeping proportions, pad to 640x640 with grey. Returns (tensor, scale, pad_x, pad_y)."""
    import cv2

    h, w = rgb.shape[:2]
    scale = min(INPUT / w, INPUT / h)
    nw, nh = round(w * scale), round(h * scale)
    pad_x, pad_y = (INPUT - nw) / 2, (INPUT - nh) / 2
    canvas = np.full((INPUT, INPUT, 3), 114, np.uint8)
    top, left = int(round(pad_y - 0.1)), int(round(pad_x - 0.1))
    canvas[top:top + nh, left:left + nw] = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
    tensor = canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    return tensor, scale, left, top


def nms(boxes: np.ndarray, scores: np.ndarray, iou: float) -> list[int]:
    """Indices kept by non-maximum suppression. boxes: (n, 4) as x1, y1, x2, y2."""
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area = lambda b: (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])  # noqa: E731
        union = area(boxes[i:i + 1]) + area(boxes[order[1:]]) - inter
        order = order[1:][inter / np.maximum(union, 1e-9) <= iou]
    return keep


def decode(output: np.ndarray, scale: float, pad_x: float, pad_y: float, width: int, height: int,
           threshold: float = 0.4, iou: float = 0.45) -> list[Box]:
    """YOLOv8 output (1, 84, N) -> boxes of interesting classes, per-class NMS."""
    pred = output[0]
    if pred.shape[0] != 4 + len(CLASSES):
        pred = pred.T  # some exports are (1, N, 84)
    scores_all = pred[4:]
    cls = scores_all.argmax(axis=0)
    conf = scores_all.max(axis=0)
    wanted = np.isin(cls, [CLASSES.index(c) for c in INTERESTING]) & (conf >= threshold)
    if not wanted.any():
        return []
    cx, cy, bw, bh = pred[0, wanted], pred[1, wanted], pred[2, wanted], pred[3, wanted]
    conf, cls = conf[wanted], cls[wanted]
    # From letterboxed 640x640 back to the original image, then to 0-1.
    x1 = ((cx - bw / 2) - pad_x) / scale
    y1 = ((cy - bh / 2) - pad_y) / scale
    x2 = ((cx + bw / 2) - pad_x) / scale
    y2 = ((cy + bh / 2) - pad_y) / scale
    xyxy = np.stack([x1.clip(0, width), y1.clip(0, height), x2.clip(0, width), y2.clip(0, height)], axis=1)
    out = []
    for c in np.unique(cls):
        idx = np.where(cls == c)[0]
        for k in nms(xyxy[idx], conf[idx], iou):
            i = idx[k]
            bx1, by1, bx2, by2 = xyxy[i]
            out.append(Box(CLASSES[int(c)], float(conf[i]), float(bx1 / width), float(by1 / height),
                           float((bx2 - bx1) / width), float((by2 - by1) / height)))
    return sorted(out, key=lambda b: -b.confidence)


class Detector:
    def __init__(self, model_path: str, threshold: float = 0.4):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        self.threshold = threshold

    def detect_jpeg(self, data: bytes) -> tuple[list[Box], float]:
        """Detect in a JPEG. Returns (boxes, latency in ms)."""
        import cv2

        start = time.perf_counter()
        bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("not a decodable image")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        tensor, scale, px, py = letterbox(rgb)
        output = self.session.run(None, {self.input: tensor})[0]
        boxes = decode(output, scale, px, py, rgb.shape[1], rgb.shape[0], self.threshold)
        return boxes, (time.perf_counter() - start) * 1000
