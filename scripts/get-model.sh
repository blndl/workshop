#!/usr/bin/env bash
# Fetch the YOLOv8n person-detection model into models/ (git-ignored: 12.8 MB).
# Source: the copy in IA_VISON/ (the vision branch, merged into main), else the
# Hugging Face mirror it came from (salim4n/yolov8n-detect-onnx).
# Licence: Ultralytics YOLO is AGPL-3.0; check before any redistribution.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=models/yolov8n.onnx
URL=${MODEL_URL:-https://huggingface.co/salim4n/yolov8n-detect-onnx/resolve/main/yolov8n-onnx-web/yolov8n.onnx}
mkdir -p models
if [[ -s $OUT && "${FORCE:-}" != 1 ]]; then echo "$OUT already there"; exit 0; fi
# The vision work (IA_VISON/, merged into main) ships the same model: use it if it's there.
if [[ -s IA_VISON/public/models/yolov8n.onnx ]]; then
  cp IA_VISON/public/models/yolov8n.onnx "$OUT"
  echo "copied $OUT from IA_VISON/public/models/"
elif git cat-file -e origin/main:IA_VISON/public/models/yolov8n.onnx 2>/dev/null; then
  git show origin/main:IA_VISON/public/models/yolov8n.onnx > "$OUT"
  echo "copied $OUT from main (IA_VISON/public/models/)"
else
  curl -fL --retry 3 -o "$OUT" "$URL"
  echo "downloaded $OUT"
fi
ls -l "$OUT"
