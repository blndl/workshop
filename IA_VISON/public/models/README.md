# Camera model

`yolov8n.onnx` is the YOLOv8n (nano) COCO object-detection model used by the browser camera pipeline. It is loaded locally through ONNX Runtime Web; camera frames are not uploaded.

Source mirror: `salim4n/yolov8n-detect-onnx` on Hugging Face, file `yolov8n-onnx-web/yolov8n.onnx`.

The mirror does not declare a model-weight license in its metadata. Ultralytics' YOLO implementation is AGPL-3.0, with a separate Enterprise license available for some use cases. Confirm model and implementation licensing with the project team before redistribution or commercial deployment.