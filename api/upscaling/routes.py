from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from ..core.config import MAX_UPLOAD_BYTES
from ..core.errors import AppError, ErrorCode
from ..core.schemas import JobResponse
from .service import JobService

router = APIRouter(prefix="/api", tags=["upscaling"])


def _job_response(job) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        result_url=(f"/api/jobs/{job.job_id}/result" if job.status == "completed" else None),
        error=job.error,
    )


@router.post("/upscale", response_model=JobResponse, status_code=202)
async def upscale_image(
    image: Annotated[UploadFile, File(...)],
    scale: Annotated[int, Form(...)],
    model: Annotated[str, Form()] = "standard",
) -> JobResponse:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise AppError(
            ErrorCode.UNSUPPORTED_FILE,
            "Please upload an image file.",
            "The image endpoint accepts image/* content types only.",
            415,
        )
    payload = await image.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise AppError(
            ErrorCode.FILE_TOO_LARGE,
            "The uploaded file is too large.",
            f"The maximum accepted size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            413,
        )
    return _job_response(JobService().submit_image(payload, model, scale))


@router.post("/upscale/video", response_model=JobResponse, status_code=501)
async def upscale_video(
    video: Annotated[UploadFile, File(...)],
    scale: Annotated[int, Form(...)],
    model: Annotated[str, Form()] = "standard",
) -> JobResponse:
    raise AppError(
        ErrorCode.VIDEO_UPSCALING_NOT_IMPLEMENTED,
        "Video upscaling is not available yet.",
        "The video processing pipeline is reserved for a future implementation.",
        501,
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    return _job_response(JobService().get(job_id))


@router.get("/jobs/{job_id}/result")
def get_result(job_id: str) -> Response:
    job = JobService().get(job_id)
    if job.status != "completed" or job.result is None:
        raise AppError(
            ErrorCode.PROCESSING_FAILED,
            "The processing result is not ready.",
            "Poll the job endpoint until its status is completed.",
            409,
        )
    return Response(job.result, media_type="image/png", headers={"Content-Disposition": 'inline; filename="processed.png"'})
