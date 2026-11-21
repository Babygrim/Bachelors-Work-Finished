"""Convert Real-ESRGAN `.pth` checkpoints in weights/ to ncnn models (weights/ncnn/).

Needs the `pnnx` pip package (conversion only; inference needs just `ncnn`).
Skips non-upscaling checkpoints and models that were already converted.

Usage:
    python scripts/export_ncnn.py
"""

import glob
import os
import re
import shutil
import sys
import tempfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import torch  # noqa: E402

from core.models.checkpoints import load_torch_model  # noqa: E402

WEIGHTS_DIR = os.path.join(ROOT_DIR, 'weights')
NCNN_DIR = os.path.join(WEIGHTS_DIR, 'ncnn')
SKIP_SUBSTRINGS = ('gfpgan', 'fatality-deblur', 'refocus', 'model_ckpt')


def _convert(pth_path, scale, name):
    import pnnx

    model = load_torch_model(pth_path, scale, num_block=6 if 'anime_6b' in name.lower() else 23)
    with tempfile.TemporaryDirectory() as tmp:
        # pnnx writes the path into a generated .py file; backslashes break it, so use a relative path.
        previous_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            pnnx.export(model, 'model.pt', (torch.rand(1, 3, 64, 64),))
        finally:
            os.chdir(previous_cwd)
        param = glob.glob(os.path.join(tmp, '*.ncnn.param'))
        weights = glob.glob(os.path.join(tmp, '*.ncnn.bin'))
        if not param or not weights:
            raise RuntimeError('pnnx produced no ncnn files')
        os.makedirs(NCNN_DIR, exist_ok=True)
        shutil.copy(param[0], os.path.join(NCNN_DIR, name + '.param'))
        shutil.copy(weights[0], os.path.join(NCNN_DIR, name + '.bin'))


def main() -> int:
    converted = 0
    for fname in sorted(os.listdir(WEIGHTS_DIR)):
        if not fname.lower().endswith('.pth'):
            continue
        name = os.path.splitext(fname)[0]
        match = re.match(r'^(\d+)x[-_]', name, flags=re.IGNORECASE)
        if match is None or any(s in name.lower() for s in SKIP_SUBSTRINGS):
            print(f"skip: {fname}")
            continue
        if os.path.exists(os.path.join(NCNN_DIR, name + '.param')):
            print(f"ok (already converted): {fname}")
            continue
        print(f"--> converting {fname}")
        try:
            _convert(os.path.join(WEIGHTS_DIR, fname), int(match.group(1)), name)
            converted += 1
        except Exception as e:
            print(f"    FAILED: {e}")
    print(f"Done. Converted: {converted}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
