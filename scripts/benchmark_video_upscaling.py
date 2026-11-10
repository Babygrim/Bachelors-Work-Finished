"""Benchmark CPU-first video upscaling for the project's real-time target.

Examples:
    python scripts/benchmark_video_upscaling.py
    python scripts/benchmark_video_upscaling.py --input sample.mp4 --frames 120
    python scripts/benchmark_video_upscaling.py --model fsrcnn --threads 8
"""

import argparse
import hashlib
import json
import tempfile
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import onnx
from onnx import TensorProto, helper
import onnxruntime as ort

ROOT_DIR = Path(__file__).resolve().parents[1]
WEIGHTS_DIR = ROOT_DIR / "weights" / "realtime"

MODEL_SOURCES = {
    "espcn": (
        "https://raw.githubusercontent.com/fannymonori/TF-ESPCN/master/export/"
        "ESPCN_x2.pb",
        "",
    ),
    "fsrcnn-small": (
        "https://raw.githubusercontent.com/Saafke/FSRCNN_Tensorflow/master/models/"
        "FSRCNN-small_x2.pb",
        "",
    ),
    "fsrcnn": (
        "https://raw.githubusercontent.com/Saafke/FSRCNN_Tensorflow/master/models/"
        "FSRCNN_x2.pb",
        "",
    ),
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Video file; synthetic frames are used by default.")
    parser.add_argument("--model", choices=MODEL_SOURCES, default="fsrcnn-small")
    parser.add_argument(
        "--mode",
        choices=("resize", "ai"),
        default="resize",
        help="Fast classic resize or AI ESPCN/FSRCNN benchmark.",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "cpu", "directml"),
        default="auto",
        help="Backend for classic resize; AI mode uses OpenCV CPU.",
    )
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--source-width", type=int, default=800)
    parser.add_argument("--source-height", type=int, default=600)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--threads", type=int, default=0, help="OpenCV CPU threads; 0 keeps the default.")
    parser.add_argument("--download", action="store_true", help="Download missing model weights.")
    return parser.parse_args()


def ensure_model(model_name, allow_download):
    source, expected_sha256 = MODEL_SOURCES[model_name]
    target = WEIGHTS_DIR / Path(source).name
    if not target.is_file():
        if not allow_download:
            raise FileNotFoundError(
                f"Missing {target}. Re-run with --download to fetch the model."
            )
        WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {target.name}...")
        urllib.request.urlretrieve(source, target)
    if expected_sha256:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise RuntimeError(f"SHA-256 mismatch for {target.name}.")
    return target


def create_upscaler(model_name, model_path):
    if not hasattr(cv2, "dnn_superres"):
        raise RuntimeError(
            "cv2.dnn_superres is unavailable. Install opencv-contrib-python "
            "instead of opencv-python."
        )
    upscaler = cv2.dnn_superres.DnnSuperResImpl_create()
    upscaler.readModel(str(model_path))
    upscaler.setModel(model_name.split("-")[0], 2)
    return upscaler


def create_resize_model(input_width, input_height, output_width, output_height):
    scale = min(output_width / input_width, output_height / input_height)
    content_width = round(input_width * scale)
    content_height = round(input_height * scale)
    pad_left = (output_width - content_width) // 2
    pad_top = (output_height - content_height) // 2
    pad_right = output_width - content_width - pad_left
    pad_bottom = output_height - content_height - pad_top
    input_info = helper.make_tensor_value_info(
        "input", TensorProto.FLOAT, [1, 3, input_height, input_width]
    )
    output_info = helper.make_tensor_value_info(
        "output", TensorProto.FLOAT, [1, 3, output_height, output_width]
    )
    scales = helper.make_tensor(
        "resize_scales",
        TensorProto.FLOAT,
        [4],
        [1.0, 1.0, content_height / input_height, content_width / input_width],
    )
    pads = helper.make_tensor(
        "pads",
        TensorProto.INT64,
        [8],
        [0, 0, pad_top, pad_left, 0, 0, pad_bottom, pad_right],
    )
    pad_value = helper.make_tensor(
        "pad_value",
        TensorProto.FLOAT,
        [],
        [0.0],
    )
    resize_node = helper.make_node(
        "Resize",
        ["input", "", "resize_scales"],
        ["resized"],
        mode="linear",
        coordinate_transformation_mode="half_pixel",
    )
    pad_node = helper.make_node(
        "Pad",
        ["resized", "pads", "pad_value"],
        ["output"],
        mode="constant",
    )
    graph = helper.make_graph(
        [resize_node, pad_node],
        "realtime_resize",
        [input_info],
        [output_info],
        [scales, pads, pad_value],
    )
    model = helper.make_model(
        graph,
        producer_name="bachelors-work-finished",
        opset_imports=[helper.make_operatorsetid("", 13)],
    )
    model.ir_version = 8
    return model


def create_resize_backend(args):
    if args.backend == "cpu":
        return "cpu", None
    if args.backend == "auto" and "DmlExecutionProvider" not in ort.get_available_providers():
        return "cpu", None
    model = create_resize_model(
        args.source_width,
        args.source_height,
        args.width,
        args.height,
    )
    with tempfile.NamedTemporaryFile(suffix=".onnx", delete=False) as model_file:
        model_path = Path(model_file.name)
    onnx.save(model, model_path)
    try:
        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        session = ort.InferenceSession(str(model_path), providers=providers)
    finally:
        model_path.unlink(missing_ok=True)
    return session.get_providers()[0], session


def synthetic_frame(width, height, index):
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = (index * 3) % 256
    frame[:, :, 1] = np.arange(width, dtype=np.uint16)[None, :] % 256
    frame[:, :, 2] = np.arange(height, dtype=np.uint16)[:, None] % 256
    return frame


def letterbox(frame, width, height):
    source_height, source_width = frame.shape[:2]
    scale = min(width / source_width, height / source_height)
    resized = cv2.resize(
        frame,
        (round(source_width * scale), round(source_height * scale)),
        interpolation=cv2.INTER_LINEAR,
    )
    output = np.zeros((height, width, 3), dtype=np.uint8)
    top = (height - resized.shape[0]) // 2
    left = (width - resized.shape[1]) // 2
    output[top:top + resized.shape[0], left:left + resized.shape[1]] = resized
    return output


def sharpen(frame):
    blurred = cv2.GaussianBlur(frame, (0, 0), 1.0)
    return cv2.addWeighted(frame, 1.15, blurred, -0.15, 0)


def benchmark(args, processor, backend_name):
    capture = cv2.VideoCapture(str(args.input)) if args.input else None
    source_width = args.source_width
    source_height = args.source_height
    if capture and capture.isOpened():
        source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or source_width
        source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or source_height
    elif capture:
        capture.release()
        raise RuntimeError(f"Could not open input video: {args.input}")

    warmup = synthetic_frame(source_width, source_height, 0)
    if args.mode == "ai":
        processor.upsample(warmup)
    elif backend_name != "cpu":
        processor.run(
            None,
            {"input": warmup.transpose(2, 0, 1)[None].astype(np.float32) / 255.0},
        )
    timings = []
    completed = 0
    started = time.perf_counter()
    try:
        while completed < args.frames:
            if capture:
                success, frame = capture.read()
                if not success:
                    break
            else:
                frame = synthetic_frame(source_width, source_height, completed)
            frame_started = time.perf_counter()
            if args.mode == "ai":
                output = processor.upsample(frame)
                if output.shape[1::-1] != (args.width, args.height):
                    output = letterbox(output, args.width, args.height)
            elif backend_name == "cpu":
                output = letterbox(frame, args.width, args.height)
                output = sharpen(output)
            else:
                tensor = frame.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
                output = processor.run(None, {"input": tensor})[0][0]
                output = np.clip(output.transpose(1, 2, 0) * 255.0, 0, 255).astype(np.uint8)
            del output
            timings.append(time.perf_counter() - frame_started)
            completed += 1
    finally:
        if capture:
            capture.release()
    elapsed = time.perf_counter() - started
    if not timings:
        raise RuntimeError("No frames were processed.")
    return {
        "model": args.model,
        "mode": args.mode,
        "backend": backend_name,
        "input": str(args.input) if args.input else "synthetic",
        "source_size": [source_width, source_height],
        "output_size": [args.width, args.height],
        "frames": completed,
        "elapsed_seconds": elapsed,
        "end_to_end_fps": completed / elapsed,
        "mean_frame_ms": float(np.mean(timings) * 1000),
        "p95_frame_ms": float(np.percentile(timings, 95) * 1000),
        "target_30fps_met": completed / elapsed >= 30,
        "target_60fps_met": completed / elapsed >= 60,
    }


def main():
    args = parse_args()
    if min(args.frames, args.width, args.height, args.source_width, args.source_height) <= 0:
        raise ValueError("Frame counts and dimensions must be positive.")
    if args.threads:
        cv2.setNumThreads(args.threads)
    if args.mode == "ai":
        model_path = ensure_model(args.model, args.download)
        backend_name = "opencv-cpu"
        processor = create_upscaler(args.model, model_path)
    else:
        backend_name, processor = create_resize_backend(args)
    result = benchmark(args, processor, backend_name)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Benchmark failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
