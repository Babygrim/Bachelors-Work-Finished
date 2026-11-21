import math
import os
import queue
import threading

import cv2
import numpy as np
import onnxruntime as ort
import torch

from core.models.checkpoints import load_torch_model
from core.models.onnx_io import INPUT_NAME, OUTPUT_NAME, wrap_with_image_io
from core.models.weights import is_compact_model, max_rrdb_output_pixels
from core.progress import report_progress

# Tiles in flight between the producer, the GPU and the post-processing thread.
_NUM_SLOTS = 3
_POST_THREADS = 1
# Set once a DirectML session was created successfully in this process.
_dml_worked = False


class _TileSlot:
    """Input/output buffers (and their IOBinding) owned by one in-flight tile."""

    __slots__ = ("inp", "out", "binding", "meta", "session")


def _as_bgr_uint8(img):
    img = np.asarray(img)
    if img.dtype != np.uint8:
        raise ValueError(f"Expected a uint8 image, got {img.dtype}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    if img.ndim != 3 or img.shape[2] != 3 or img.shape[0] == 0 or img.shape[1] == 0:
        raise ValueError(f"Unsupported image shape: {img.shape}")
    return img


def _export_to_onnx(pth_path, onnx_path, scale, num_block=23, fp16=False):
    """Export a RRDBNet or SRVGGNetCompact .pth checkpoint to ONNX (run once per model)."""
    model = load_torch_model(pth_path, scale, num_block)

    dtype = torch.float16 if fp16 else torch.float32
    if fp16:
        model = model.half()
    dummy = torch.randn(1, 3, 64, 64, dtype=dtype)
    with torch.no_grad():
        torch.onnx.export(
            model,
            dummy,
            onnx_path,
            input_names=['input'],
            output_names=['output'],
            dynamic_axes={
                'input':  {2: 'height', 3: 'width'},
                'output': {2: 'out_height', 3: 'out_width'},
            },
            opset_version=11,
            do_constant_folding=True,
        )
        label = 'fp16' if fp16 else 'fp32'
        print(f"ONNX export ({label}): {os.path.basename(pth_path)} -> {os.path.basename(onnx_path)}")


def _export_both(pth_path, scale, num_block=23):
    """Export a RRDBNet checkpoint to FP32 + FP16 ONNX files (skips precisions already present)."""
    base = os.path.splitext(pth_path)[0]
    for fp16 in (False, True):
        suffix = '_fp16' if fp16 else '_fp32'
        out_path = base + suffix + '.onnx'
        if os.path.exists(out_path):
            continue
        _export_to_onnx(pth_path, out_path, scale, num_block=num_block, fp16=fp16)


class OnnxRealESRGANer:
    """RealESRGAN inference via ONNX Runtime + DirectML execution provider.

    Optimizations:
    - Fixed tile shape (edge tiles padded) so DirectML never re-plans the graph
    - Image pre/post-processing (uint8 BGR <-> normalised RGB, clip, quantise) is folded into
      the ONNX graph (core/models/onnx_io.py), so the CPU only copies uint8 pixels
    - Three-stage tile pipeline (prepare / infer / copy-out on separate threads)
      with per-tile IOBinding buffers, so the GPU is not stalled by CPU work
    - A failed inference rebuilds the session once and retries the tile

    On first use both FP32 and FP16 ONNX files are exported from the .pth
    checkpoint and cached next to it. FP16 is used automatically when available
    (~1.5-2x faster on AMD GPUs); FP32 is the fallback.

    Args:
        scale (int): Upscaling factor.
        pth_path (str): Absolute path to the .pth weight file.
        tile (int): Tile size used during inference.
        tile_pad (int): Overlap padding between tiles.
        num_block (int): Number of RRDB blocks (23 standard, 6 anime).
        num_threads (int): Number of threads for ONNX Runtime parallelization.
        frame_size (tuple[int, int] | None): (width, height) of the frames to upscale. When
            given, the whole frame is processed as a single tile (tile/tile_pad are ignored).
    """

    def __init__(self, scale, pth_path, tile=768, tile_pad=0, num_block=23, num_threads=2,
                 frame_size=None):
        self.scale = scale
        self.tile_size = tile
        self.tile_pad = tile_pad
        self.num_threads = max(1, int(num_threads))

        base = os.path.splitext(pth_path)[0]
        fp_path = base + '.onnx'

        # Export any missing precision (fp32 and/or fp16) from the .pth checkpoint
        if not os.path.exists(fp_path):
            print(f"ONNX models missing for {os.path.basename(pth_path)} — exporting (one-time)...")
            _export_both(pth_path, scale, num_block=num_block)

        self._onnx_path = fp_path

        # Keep the output-sized tensors of RRDBNet models under the DirectML limit (see weights.py).
        stem = os.path.basename(base)
        compact = is_compact_model(stem)
        max_output = max_rrdb_output_pixels(stem)
        if not compact and frame_size is not None:
            if frame_size[0] * frame_size[1] * scale * scale > max_output:
                frame_size = None
        if not compact and frame_size is None:
            max_io = math.isqrt(max_output) // scale
            if tile + 2 * tile_pad > max_io:
                tile = max(8, max_io - 2 * tile_pad)
                self.tile_size = tile

        # Fixed input size: DirectML re-plans the graph on every shape change and
        # runs ~3x slower with dynamic shapes. All tiles are padded to this size.
        if frame_size is not None:
            # Whole-frame mode (real-time video): one tile covers the frame, no overlap needed.
            # Rounded up to a multiple of 4 so models with pixel-unshuffle accept the shape.
            frame_w, frame_h = frame_size
            self.tile_pad = 0
            self.tile_w = self.io_w = -(-int(frame_w) // 4) * 4
            self.tile_h = self.io_h = -(-int(frame_h) // 4) * 4
        else:
            self.tile_w = self.tile_h = tile
            self.io_w = self.io_h = tile + 2 * tile_pad

        self._session_lock = threading.Lock()
        self._pool_lock = threading.Lock()
        self._slot_pool = []
        self._create_session()

        print(f"ORT provider: {self.device} | precision: {self.precision} | threads: {self.num_threads}")

    def _create_session(self):
        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_opts.enable_cpu_mem_arena = False
        sess_opts.inter_op_num_threads = max(2, self.num_threads)
        sess_opts.intra_op_num_threads = max(2, self.num_threads)
        sess_opts.add_free_dimension_override_by_name('height', self.io_h)
        sess_opts.add_free_dimension_override_by_name('width', self.io_w)

        # uint8 BGR NHWC in/out: normalisation, channel order and quantisation run on the GPU.
        model_bytes = wrap_with_image_io(self._onnx_path)
        providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
        session = ort.InferenceSession(model_bytes, sess_options=sess_opts, providers=providers)

        global _dml_worked
        if session.get_providers()[0] == 'DmlExecutionProvider':
            _dml_worked = True
        elif _dml_worked and 'DmlExecutionProvider' in ort.get_available_providers():
            # After a DirectML runtime error (e.g. 887A0001) the process keeps no usable DML device
            # and ORT silently falls back to the CPU, which is ~100x slower; fail loudly instead.
            raise RuntimeError(
                "DirectML is no longer available in this process after an earlier GPU error. "
                "Restart the application to restore GPU upscaling."
            )

        # Warmup: compile DirectML shaders so the first real tile isn't slow.
        warmup = np.zeros((1, self.io_h, self.io_w, 3), dtype=np.uint8)
        session.run([OUTPUT_NAME], {INPUT_NAME: warmup})

        self.precision = 'fp16' if 'fp16' in os.path.basename(self._onnx_path).lower() else 'fp32'
        self.device = session.get_providers()[0]
        self.session = session

    def _recover_session(self, failed_session):
        """Rebuild the session after a runtime failure (e.g. a DirectML device reset)."""
        with self._session_lock:
            if self.session is failed_session:
                self._create_session()

    def _new_slot(self):
        slot = _TileSlot()
        slot.inp = np.zeros((1, self.io_h, self.io_w, 3), dtype=np.uint8)
        slot.out = np.zeros(
            (1, self.io_h * self.scale, self.io_w * self.scale, 3), dtype=np.uint8
        )
        self._bind_slot(slot)
        return slot

    def _bind_slot(self, slot):
        slot.session = self.session
        try:
            binding = self.session.io_binding()
            binding.bind_cpu_input(INPUT_NAME, slot.inp)
            binding.bind_cpu_output(OUTPUT_NAME, slot.out)
            slot.binding = binding
        except Exception:
            slot.binding = None

    def _acquire_slots(self, count):
        # Slots are pooled: allocating the (large) output buffers every frame costs page faults
        # that are measurable at real-time frame rates.
        with self._pool_lock:
            slots = [self._slot_pool.pop() for _ in range(min(count, len(self._slot_pool)))]
        slots.extend(self._new_slot() for _ in range(count - len(slots)))
        for slot in slots:
            if slot.session is not self.session:
                self._bind_slot(slot)
        return slots

    def _release_slots(self, slots):
        with self._pool_lock:
            self._slot_pool.extend(slots)
            del self._slot_pool[_NUM_SLOTS:]

    def _infer(self, slot):
        session = self.session
        if slot.binding is not None:
            session.run_with_iobinding(slot.binding)
            return slot.out[0]
        return session.run([OUTPUT_NAME], {INPUT_NAME: slot.inp})[0][0]

    def _infer_with_retry(self, slots, slot):
        failed_session = self.session
        try:
            return self._infer(slot)
        except Exception as error:
            print(f"ORT inference failed ({error}); rebuilding session and retrying the tile once")
            self._recover_session(failed_session)
            for each in slots:
                self._bind_slot(each)
            return self._infer(slot)

    def _fill_input(self, dst, img_bgr, meta):
        x0p, y0p, x1p, y1p = meta[4:]
        region = img_bgr[y0p:y1p, x0p:x1p]
        pad_h = self.io_h - region.shape[0]
        pad_w = self.io_w - region.shape[1]
        if pad_h or pad_w:
            region = cv2.copyMakeBorder(region, 0, pad_h, 0, pad_w, cv2.BORDER_REPLICATE)
        dst[0] = region

    def _write_output(self, result, tile_out, meta):
        x0, y0, x1, y1, x0p, y0p = meta[:6]
        scale = self.scale
        vx0 = (x0 - x0p) * scale
        vy0 = (y0 - y0p) * scale
        vx1 = vx0 + (x1 - x0) * scale
        vy1 = vy0 + (y1 - y0) * scale
        result[y0 * scale:y1 * scale, x0 * scale:x1 * scale] = tile_out[vy0:vy1, vx0:vx1]

    def _tile_metas(self, W, H):
        tile_w, tile_h, pad = self.tile_w, self.tile_h, self.tile_pad
        metas = []
        for ty in range(math.ceil(H / tile_h)):
            for tx in range(math.ceil(W / tile_w)):
                x0, y0 = tx * tile_w, ty * tile_h
                x1, y1 = min(x0 + tile_w, W), min(y0 + tile_h, H)
                metas.append((
                    x0, y0, x1, y1,
                    max(x0 - pad, 0), max(y0 - pad, 0),
                    min(x1 + pad, W), min(y1 + pad, H),
                ))
        return metas

    def enhance(self, img_bgr, progress_queue=None, outscale=None):
        """Upscale a BGR uint8 image using tiled ONNX inference.

        Every tile is padded to the session's fixed input size and the padding is
        cropped from the output, so DirectML always sees the same tensor shape.

        Args:
            img_bgr: HWC uint8 numpy array in BGR colour order.
            progress_queue: optional multiprocessing.Queue for progress updates (0–100).
            outscale: optional final scale (if differs from model scale, result is resized).

        Returns:
            HWC uint8 numpy array in BGR colour order.
        """
        img_bgr = _as_bgr_uint8(img_bgr)
        h_in, w_in = img_bgr.shape[:2]
        scale = self.scale
        result = np.empty((h_in * scale, w_in * scale, 3), dtype=np.uint8)

        metas = self._tile_metas(w_in, h_in)
        total = len(metas)

        # Three-stage pipeline so the GPU never waits for CPU work:
        #   producer thread: slice/pad tiles into free slots
        #   this thread:     run inference (ORT releases the GIL)
        #   post thread:     copy finished tiles into `result`
        # Each slot owns its input/output buffers, so no buffer is shared between stages.
        slots = self._acquire_slots(min(_NUM_SLOTS, total))
        free, ready, finished = queue.Queue(), queue.Queue(), queue.Queue()
        for slot in slots:
            free.put(slot)

        abort = threading.Event()
        errors = []
        progress_lock = threading.Lock()
        done = [0]

        def fail(error):
            errors.append(error)
            abort.set()

        def take(q):
            # None means "stop": either the end-of-work sentinel or an abort elsewhere.
            while not abort.is_set():
                try:
                    return q.get(timeout=0.1)
                except queue.Empty:
                    pass
            return None

        def produce():
            try:
                for meta in metas:
                    slot = take(free)
                    if slot is None:
                        return
                    self._fill_input(slot.inp, img_bgr, meta)
                    slot.meta = meta
                    ready.put(slot)
                ready.put(None)
            except Exception as error:
                fail(error)

        def post():
            try:
                while True:
                    item = take(finished)
                    if item is None:
                        return
                    slot, tile_out = item
                    self._write_output(result, tile_out, slot.meta)
                    free.put(slot)
                    with progress_lock:
                        done[0] += 1
                        report_progress(progress_queue, "upscale", done[0], total)
            except Exception as error:
                fail(error)

        producer = threading.Thread(target=produce, daemon=True)
        posters = [threading.Thread(target=post, daemon=True) for _ in range(_POST_THREADS)]
        producer.start()
        for poster in posters:
            poster.start()

        try:
            while True:
                slot = take(ready)
                if slot is None:
                    break
                finished.put((slot, self._infer_with_retry(slots, slot)))
        except Exception as error:
            fail(error)
        finally:
            for _ in posters:
                finished.put(None)
            for poster in posters:
                poster.join()
            abort.set()
            producer.join()

        if errors:
            raise errors[0]
        if done[0] != total:
            raise RuntimeError(f"Upscaling incomplete: {done[0]}/{total} tiles processed")
        self._release_slots(slots)

        if outscale is not None and float(outscale) != float(self.scale):
            target_w = int(round(w_in * float(outscale)))
            target_h = int(round(h_in * float(outscale)))
            result = cv2.resize(result, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)

        return result
