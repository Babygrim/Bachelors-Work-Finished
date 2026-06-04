import math
import os

import cv2
import numpy as np
import onnxruntime as ort
import torch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _export_to_onnx(pth_path, onnx_path, scale, num_block=23, fp16=False):
    """Export a RRDBNet .pth checkpoint to ONNX format (run once per model)."""
    from models.rrdbnet_arch import RRDBNet

    model = RRDBNet(
        num_in_ch=3, num_out_ch=3, num_feat=64,
        num_block=num_block, num_grow_ch=32, scale=scale,
    )

    loadnet = torch.load(pth_path, map_location='cpu', weights_only=True)
    if 'params_ema' in loadnet:
        model.load_state_dict(loadnet['params_ema'], strict=True)
    elif 'params' in loadnet:
        model.load_state_dict(loadnet['params'], strict=True)
    else:
        model.load_state_dict(loadnet, strict=True)
    model.eval()

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
    """Export a RRDBNet checkpoint to both FP32 and FP16 ONNX files."""
    base = os.path.splitext(pth_path)[0]
    for fp16 in (False, True):
        suffix = '_fp16' if fp16 else '_fp32'
        _export_to_onnx(pth_path, base + suffix + '.onnx', scale, num_block=num_block, fp16=fp16)


class OnnxRealESRGANer:
    """RealESRGAN inference via ONNX Runtime + DirectML execution provider.

    On first use both FP32 and FP16 ONNX files are exported from the .pth
    checkpoint and cached next to it. FP16 is used automatically when available
    (~1.5-2x faster on AMD GPUs); FP32 is the fallback.

    Args:
        scale (int): Upscaling factor.
        pth_path (str): Absolute path to the .pth weight file.
        tile (int): Tile size used during inference.
        tile_pad (int): Overlap padding between tiles.
        num_block (int): Number of RRDB blocks (23 standard, 6 anime).
    """

    def __init__(self, scale, pth_path, tile=512, tile_pad=30, num_block=23):
        self.scale = scale
        self.tile_size = tile
        self.tile_pad = tile_pad

        base = os.path.splitext(pth_path)[0]
        fp32_path = base + '_fp32.onnx'
        fp16_path = base + '_fp16.onnx'

        # Export both precisions if the base fp32 doesn't exist yet
        if not os.path.exists(fp32_path):
            print("ONNX models not found — exporting fp32 + fp16 (one-time, may take a moment)...")
            _export_both(pth_path, scale, num_block=num_block)

        # Prefer fp16 when available
        if os.path.exists(fp16_path):
            onnx_path = fp16_path
            self.np_dtype = np.float16
        else:
            onnx_path = fp32_path
            self.np_dtype = np.float32

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_opts.enable_cpu_mem_arena = False

        providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
        self.session = ort.InferenceSession(onnx_path, sess_options=sess_opts, providers=providers)
        self.input_name  = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

        label = 'fp16' if self.np_dtype == np.float16 else 'fp32'
        print(f"ORT provider: {self.session.get_providers()[0]} | precision: {label}")

        # Warmup: compile DirectML shaders so the first real tile isn't slow.
        warmup = np.zeros((1, 3, 64, 64), dtype=self.np_dtype)
        self.session.run([self.output_name], {self.input_name: warmup})

    def enhance(self, img_bgr, progress_queue=None):
        """Upscale a BGR uint8 image using tiled ONNX inference.

        Args:
            img_bgr: HWC uint8 numpy array in BGR colour order.
            progress_queue: optional multiprocessing.Queue for progress updates (0–100).

        Returns:
            HWC uint8 numpy array in BGR colour order.
        """
        # BGR uint8 → RGB float CHW in [0, 1]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img_chw = np.ascontiguousarray(np.transpose(img_rgb, (2, 0, 1))).astype(self.np_dtype)

        C, H, W = img_chw.shape
        tile  = self.tile_size
        pad   = self.tile_pad
        scale = self.scale
        out_H, out_W = H * scale, W * scale

        output = np.zeros((C, out_H, out_W), dtype=np.float32)

        # Try IOBinding on the first interior tile (fixed padded size).
        # If DML doesn't support it we fall back to session.run() silently.
        io_pad_h = tile + 2 * pad
        io_pad_w = tile + 2 * pad
        io_out_h = io_pad_h * scale
        io_out_w = io_pad_w * scale

        binding = None
        try:
            binding = self.session.io_binding()
            _buf_in  = np.zeros((1, C, io_pad_h, io_pad_w), dtype=self.np_dtype)
            _buf_out = np.zeros((1, C, io_out_h, io_out_w), dtype=np.float32)
            binding.bind_cpu_input(self.input_name, _buf_in)
            binding.bind_cpu_output(self.output_name, _buf_out)
        except Exception:
            binding = None  # fall back to session.run

        tiles_x = math.ceil(W / tile)
        tiles_y = math.ceil(H / tile)
        total   = tiles_x * tiles_y
        done    = 0

        for ty in range(tiles_y):
            for tx in range(tiles_x):
                x0, y0 = tx * tile, ty * tile
                x1, y1 = min(x0 + tile, W), min(y0 + tile, H)
                x0p, y0p = max(x0 - pad, 0), max(y0 - pad, 0)
                x1p, y1p = min(x1 + pad, W), min(y1 + pad, H)

                ph = y1p - y0p
                pw = x1p - x0p
                is_interior = (ph == io_pad_h and pw == io_pad_w)

                if binding is not None and is_interior:
                    # IOBinding path: write directly into the pre-allocated buffer
                    _buf_in[0] = img_chw[:, y0p:y1p, x0p:x1p]
                    self.session.run_with_iobinding(binding)
                    tile_out = _buf_out[0]
                else:
                    tile_in = np.ascontiguousarray(img_chw[:, y0p:y1p, x0p:x1p])[np.newaxis]
                    tile_out = self.session.run([self.output_name], {self.input_name: tile_in})[0][0]

                ox0, oy0 = x0 * scale, y0 * scale
                ox1, oy1 = x1 * scale, y1 * scale
                vx0 = (x0 - x0p) * scale
                vy0 = (y0 - y0p) * scale
                vx1 = vx0 + (x1 - x0) * scale
                vy1 = vy0 + (y1 - y0) * scale

                output[:, oy0:oy1, ox0:ox1] = tile_out[:, vy0:vy1, vx0:vx1]

                done += 1
                if progress_queue:
                    progress_queue.put((done / total) * 100)

        # RGB float32 CHW [0,1] → BGR uint8 HWC
        output_rgb = np.transpose(np.clip(output, 0, 1), (1, 2, 0))
        return cv2.cvtColor((output_rgb * 255.0).round().astype(np.uint8), cv2.COLOR_RGB2BGR)
