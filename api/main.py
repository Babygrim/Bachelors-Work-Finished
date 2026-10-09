from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Annotated

import cv2
import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image


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
MODEL_CACHE: dict[tuple[str, int], ort.InferenceSession] = {}
MODEL_LOCK = Lock()

app = FastAPI(title="AI Upscaler API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _get_model(model: str, scale: int) -> ort.InferenceSession:
    cache_key = (model, scale)
    if cache_key in MODEL_CACHE:
        return MODEL_CACHE[cache_key]

    filename = MODEL_FILES[model].format(scale=scale)
    model_path = WEIGHTS_DIR / filename
    if not model_path.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"Model weights are not available: {filename}",
        )

    with MODEL_LOCK:
        if cache_key not in MODEL_CACHE:
            MODEL_CACHE[cache_key] = ort.InferenceSession(
                str(model_path),
                providers=["DmlExecutionProvider", "CPUExecutionProvider"],
            )
    return MODEL_CACHE[cache_key]


def _upscale(image: Image.Image, model: str, scale: int) -> Image.Image:
    session = _get_model(model, scale)
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    image_rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    input_tensor = np.transpose(image_rgb, (2, 0, 1))[None, ...]
    output = session.run([output_name], {input_name: input_tensor})[0][0]
    output_rgb = np.transpose(np.clip(output, 0, 1), (1, 2, 0))
    return Image.fromarray((output_rgb * 255).round().astype(np.uint8), mode="RGB")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ai-upscaler-api"}


@app.post("/api/upscale")
async def upscale_image(
    image: Annotated[UploadFile, File(...)],
    scale: Annotated[int, Form(...)],
    model: Annotated[str, Form()] = "standard",
) -> StreamingResponse:
    if scale not in SUPPORTED_SCALES:
        raise HTTPException(
            status_code=400, detail=f"Scale must be one of: {sorted(SUPPORTED_SCALES)}"
        )
    if model not in MODEL_FILES:
        raise HTTPException(status_code=400, detail="Unsupported model")
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="The uploaded file must be an image")

    try:
        payload = await image.read(MAX_UPLOAD_BYTES + 1)
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The uploaded image is too large")
        source = Image.open(BytesIO(payload))
        processed = _upscale(source, model, scale)
        output = BytesIO()
        processed.save(output, format="PNG")
        output.seek(0)
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=f"Could not process image: {error}") from error

    return StreamingResponse(
        output,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="processed.png"'},
    )
