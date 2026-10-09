from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
WEIGHTS_DIR = ROOT_DIR / "weights"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SUPPORTED_SCALES = {2, 4, 8}
MODEL_FILES = {
    "standard": "{scale}x-REAL-General_fp32.onnx",
    "photo": "{scale}x-REAL-fine-tuned-faces_fp32.onnx",
    "anime": "{scale}x-Official-General_fp32.onnx",
    "art": "{scale}x-REAL-Smooth_fp32.onnx",
}
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
