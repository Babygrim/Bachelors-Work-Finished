import atexit
import math
import os
import weakref

import cv2
import numpy as np

from core.progress import report_progress

_live_models = weakref.WeakSet()


def _release_vulkan():
    # Without an explicit teardown the process spins forever in ncnn's Vulkan destructors at exit.
    import ncnn

    for model in list(_live_models):
        model.net.clear()
    ncnn.destroy_gpu_instance()


atexit.register(_release_vulkan)


class NcnnRealESRGANer:
    """Real-ESRGAN inference via ncnn + Vulkan (works on any Vulkan GPU, no DirectML).

    Drop-in alternative to OnnxRealESRGANer: same `enhance()` contract and `device` attribute.

    Args:
        scale (int): Upscaling factor of the model.
        param_path (str): Path to the ncnn `.param` file (the `.bin` must sit next to it).
        tile (int): Tile size used during inference.
        tile_pad (int): Overlap padding between tiles.
        num_threads (int): CPU threads (used for CPU fallback and pre/post work inside ncnn).
    """

    INPUT_BLOB = "in0"
    OUTPUT_BLOB = "out0"

    def __init__(self, scale, param_path, tile=384, tile_pad=32, num_threads=2):
        import ncnn

        self._ncnn = ncnn
        self.scale = scale
        self.tile_size = tile
        self.tile_pad = tile_pad

        bin_path = os.path.splitext(param_path)[0] + ".bin"
        if not os.path.exists(bin_path):
            raise FileNotFoundError(f"ncnn weights not found: {bin_path}")

        use_vulkan = ncnn.get_gpu_count() > 0
        self.net = ncnn.Net()
        self.net.opt.use_vulkan_compute = use_vulkan
        self.net.opt.use_fp16_packed = use_vulkan
        self.net.opt.use_fp16_storage = use_vulkan
        self.net.opt.use_fp16_arithmetic = use_vulkan
        self.net.opt.num_threads = max(1, int(num_threads))
        self.net.load_param(param_path)
        self.net.load_model(bin_path)
        _live_models.add(self)
        self.device = "NcnnVulkanExecutionProvider" if use_vulkan else "NcnnCPUExecutionProvider"
        print(f"ncnn device: {self.device} | model: {os.path.basename(param_path)}")

        # Warmup: build Vulkan pipelines so the first real tile isn't slow.
        self._run_tile(np.zeros((3, 64, 64), dtype=np.float32))

    def _run_tile(self, tile_chw):
        # The Mat borrows the numpy buffer, so keep `tile_chw` alive until clone() has copied it.
        tile_chw = np.ascontiguousarray(tile_chw, dtype=np.float32)
        extractor = self.net.create_extractor()
        extractor.input(self.INPUT_BLOB, self._ncnn.Mat(tile_chw).clone())
        _, out = extractor.extract(self.OUTPUT_BLOB)
        # np.array(Mat) is a view of ncnn-owned memory; copy before the Mat is released.
        return np.array(out).copy()

    def enhance(self, img_bgr, progress_queue=None, outscale=None):
        """Upscale a BGR uint8 image with tiled ncnn inference.

        Returns:
            HWC uint8 numpy array in BGR colour order.
        """
        h_in, w_in = img_bgr.shape[:2]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img_chw = np.ascontiguousarray(np.transpose(img_rgb, (2, 0, 1)))

        C, H, W = img_chw.shape
        tile, pad, scale = self.tile_size, self.tile_pad, self.scale
        output = np.zeros((C, H * scale, W * scale), dtype=np.float32)

        tiles_x = math.ceil(W / tile)
        tiles_y = math.ceil(H / tile)
        total = tiles_x * tiles_y
        done = 0

        for ty in range(tiles_y):
            for tx in range(tiles_x):
                x0, y0 = tx * tile, ty * tile
                x1, y1 = min(x0 + tile, W), min(y0 + tile, H)
                x0p, y0p = max(x0 - pad, 0), max(y0 - pad, 0)
                x1p, y1p = min(x1 + pad, W), min(y1 + pad, H)

                tile_out = self._run_tile(img_chw[:, y0p:y1p, x0p:x1p])

                vx0 = (x0 - x0p) * scale
                vy0 = (y0 - y0p) * scale
                vx1 = vx0 + (x1 - x0) * scale
                vy1 = vy0 + (y1 - y0) * scale
                output[:, y0 * scale:y1 * scale, x0 * scale:x1 * scale] = tile_out[:, vy0:vy1, vx0:vx1]

                done += 1
                report_progress(progress_queue, "upscale", done, total)

        output_rgb = np.transpose(np.clip(output, 0, 1), (1, 2, 0))
        result = cv2.cvtColor((output_rgb * 255.0).round().astype(np.uint8), cv2.COLOR_RGB2BGR)

        if outscale is not None and float(outscale) != float(self.scale):
            target_w = int(round(w_in * float(outscale)))
            target_h = int(round(h_in * float(outscale)))
            result = cv2.resize(result, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
        return result
