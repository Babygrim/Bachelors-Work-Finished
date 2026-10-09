from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import Lock
from uuid import uuid4

import numpy as np
import onnxruntime as ort
from PIL import Image

from ..core.config import MODEL_FILES, SUPPORTED_SCALES, WEIGHTS_DIR
from ..core.errors import AppError, ErrorCode
from ..core.singleton import SingletonMeta
from ..core.store import InMemoryStore


@dataclass
class Job:
    job_id: str
    kind: str
    status: str = "queued"
    progress: int = 0
    result: bytes | None = None
    error: dict[str, str] | None = None


class ModelService(metaclass=SingletonMeta):
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, int], ort.InferenceSession] = {}
        self.lock = Lock()

    def _session(self, model: str, scale: int) -> ort.InferenceSession:
        key = (model, scale)
        if key in self.sessions:
            return self.sessions[key]
        filename = MODEL_FILES[model].format(scale=scale)
        model_path = WEIGHTS_DIR / filename
        if not model_path.is_file():
            raise AppError(
                ErrorCode.MODEL_UNAVAILABLE,
                "The selected upscaling model is unavailable.",
                f"Model weights are missing: {filename}.",
                503,
            )
        with self.lock:
            if key not in self.sessions:
                self.sessions[key] = ort.InferenceSession(
                    str(model_path),
                    providers=["DmlExecutionProvider", "CPUExecutionProvider"],
                )
        return self.sessions[key]

    def upscale(self, payload: bytes, model: str, scale: int) -> bytes:
        if scale not in SUPPORTED_SCALES:
            raise AppError(
                ErrorCode.UNSUPPORTED_SCALE,
                "This upscaling scale is not supported.",
                f"Choose one of: {sorted(SUPPORTED_SCALES)}.",
                400,
            )
        if model not in MODEL_FILES:
            raise AppError(
                ErrorCode.UNSUPPORTED_MODEL,
                "This upscaling model is not supported.",
                f"Choose one of: {sorted(MODEL_FILES)}.",
                400,
            )
        try:
            image = Image.open(BytesIO(payload)).convert("RGB")
        except (OSError, ValueError) as error:
            raise AppError(
                ErrorCode.UNSUPPORTED_FILE,
                "The uploaded file is not a readable image.",
                str(error),
                415,
            ) from error

        session = self._session(model, scale)
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name
        image_rgb = np.asarray(image, dtype=np.float32) / 255.0
        input_tensor = np.transpose(image_rgb, (2, 0, 1))[None, ...]
        output = session.run([output_name], {input_name: input_tensor})[0][0]
        output_rgb = np.transpose(np.clip(output, 0, 1), (1, 2, 0))
        result = Image.fromarray((output_rgb * 255).round().astype(np.uint8), mode="RGB")
        buffer = BytesIO()
        result.save(buffer, format="PNG")
        return buffer.getvalue()


class JobService(metaclass=SingletonMeta):
    def __init__(self) -> None:
        self.store = InMemoryStore()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="upscale")
        self.lock = Lock()

    def submit_image(self, payload: bytes, model: str, scale: int) -> Job:
        job = Job(str(uuid4()), "image")
        with self.lock:
            self.store.jobs[job.job_id] = job
        self.executor.submit(self._run_image, job, payload, model, scale)
        return job

    def _run_image(self, job: Job, payload: bytes, model: str, scale: int) -> None:
        job.status = "processing"
        job.progress = 10
        try:
            job.result = ModelService().upscale(payload, model, scale)
            job.progress = 100
            job.status = "completed"
        except AppError as error:
            job.error = {"code": str(error.code), "message": error.message, "reason": error.reason}
            job.status = "failed"
        except Exception as error:
            job.error = {
                "code": ErrorCode.PROCESSING_FAILED,
                "message": "The image could not be processed.",
                "reason": str(error),
            }
            job.status = "failed"

    def get(self, job_id: str) -> Job:
        job = self.store.jobs.get(job_id)
        if not isinstance(job, Job):
            raise AppError(
                ErrorCode.JOB_NOT_FOUND,
                "The processing job was not found.",
                "It may have expired or the job ID may be incorrect.",
                404,
            )
        return job
