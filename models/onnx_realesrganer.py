import math
import os

import cv2
import numpy as np
import onnxruntime as ort
import torch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _export_to_onnx(pth_path, onnx_path, scale, num_block=23):
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

    dummy = torch.randn(1, 3, 64, 64)
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
    print(f"ONNX export: {os.path.basename(pth_path)} -> {os.path.basename(onnx_path)}")


class OnnxRealESRGANer:
    """RealESRGAN inference via ONNX Runtime + DirectML execution provider.

    The ONNX model is exported from the .pth checkpoint on first use and cached
    next to it as a .onnx file. Subsequent runs load the cached file directly.
    CPU-side tiling keeps VRAM usage proportional to tile size, not image size.

    Args:
        scale (int): Upscaling factor.
        pth_path (str): Absolute path to the .pth weight file.
        tile (int): Tile size used during inference.
        tile_pad (int): Overlap padding between tiles.
        num_block (int): Number of RRDB blocks in the model (23 for standard, 6 for anime).
    """

    def __init__(self, scale, pth_path, tile=512, tile_pad=30, num_block=23):
        self.scale = scale
        self.tile_size = tile
        self.tile_pad = tile_pad

        onnx_path = os.path.splitext(pth_path)[0] + '.onnx'
        if not os.path.exists(onnx_path):
            print("ONNX model not found — exporting (one-time, may take a moment)...")
            _export_to_onnx(pth_path, onnx_path, scale, num_block=num_block)

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_opts.enable_cpu_mem_arena = False

        providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
        self.session = ort.InferenceSession(onnx_path, sess_options=sess_opts, providers=providers)
        self.input_name  = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

        active_provider = self.session.get_providers()[0]
        print(f"ORT provider: {active_provider}")

        # Warmup: compile DirectML shaders on the first call so it doesn't
        # happen mid-processing and skew the progress bar timing.
        warmup = np.zeros((1, 3, 64, 64), dtype=np.float32)
        self.session.run([self.output_name], {self.input_name: warmup})

    def enhance(self, img_bgr, progress_queue=None):
        """Upscale a BGR uint8 image using tiled ONNX inference.

        Args:
            img_bgr: HWC uint8 numpy array in BGR colour order.
            progress_queue: optional multiprocessing.Queue for progress updates (0–100).

        Returns:
            HWC uint8 numpy array in BGR colour order.
        """
        # BGR uint8 → RGB float32 CHW in [0, 1]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img_chw = np.ascontiguousarray(np.transpose(img_rgb, (2, 0, 1)))

        C, H, W = img_chw.shape
        tile  = self.tile_size
        pad   = self.tile_pad
        scale = self.scale
        out_H, out_W = H * scale, W * scale

        output = np.zeros((C, out_H, out_W), dtype=np.float32)

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
