"""Batch-convert every RRDBNet upscaling `.pth` in weights/ to FP32 + FP16 ONNX.

Skips precisions that already exist. Skips non-upscaling checkpoints
(GFPGAN / deblur / refocus / etc.) which use different architectures.

Usage:
    py scripts/export_onnx.py
"""

import os
import re
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from models.onnx_realesrganer import _export_both  # noqa: E402

WEIGHTS_DIR = os.path.join(ROOT_DIR, 'weights')

# Filenames that are NOT plain RRDBNet upscalers — skip them.
SKIP_SUBSTRINGS = (
    'gfpgan',          # face restoration (StyleGAN2-based)
    'fatality-deblur', # deblur model (different arch)
    'refocus',         # deblur/focus model
    'model_ckpt',      # SRCNN scratch checkpoint
)


def _scale_from_name(name: str) -> int | None:
    """Detect upscale factor from a filename prefix like '2x-...', '4x-...', '8x-...'."""
    m = re.match(r'^\s*(\d+)x[-_]', name, flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def _num_block_from_name(name: str) -> int:
    """Anime checkpoints use 6 RRDB blocks; everything else uses 23."""
    return 6 if 'anime_6b' in name.lower() else 23


def main() -> int:
    if not os.path.isdir(WEIGHTS_DIR):
        print(f"weights/ not found at {WEIGHTS_DIR}")
        return 1

    # Sweep zero-byte / partial ONNX files left behind by previous failed exports.
    removed = 0
    for fname in os.listdir(WEIGHTS_DIR):
        if not (fname.lower().endswith('.onnx') or fname.lower().endswith('.onnx.tmp')):
            continue
        fpath = os.path.join(WEIGHTS_DIR, fname)
        try:
            if fname.lower().endswith('.tmp') or os.path.getsize(fpath) < 1024 * 1024:
                os.remove(fpath)
                print(f"removed partial/empty: {fname}")
                removed += 1
        except OSError:
            pass
    if removed:
        print(f"cleaned up {removed} stale file(s)\n")

    pth_files = sorted(f for f in os.listdir(WEIGHTS_DIR) if f.lower().endswith('.pth'))
    if not pth_files:
        print("No .pth files found.")
        return 0

    converted = 0
    skipped = 0
    for fname in pth_files:
        lower = fname.lower()
        if any(s in lower for s in SKIP_SUBSTRINGS):
            print(f"skip (non-RRDBNet): {fname}")
            skipped += 1
            continue

        scale = _scale_from_name(fname)
        if scale is None:
            print(f"skip (no Nx prefix): {fname}")
            skipped += 1
            continue

        pth_path = os.path.join(WEIGHTS_DIR, fname)
        base = os.path.splitext(pth_path)[0]
        fp32 = base + '_fp32.onnx'
        fp16 = base + '_fp16.onnx'
        if os.path.exists(fp32) and os.path.exists(fp16):
            print(f"ok  (both onnx present): {fname}")
            continue

        num_block = _num_block_from_name(fname)
        print(f"--> exporting {fname}  (scale={scale}, num_block={num_block})")
        try:
            _export_both(pth_path, scale, num_block=num_block)
            converted += 1
        except Exception as e:  # pragma: no cover
            print(f"    FAILED: {e}")

    print(f"\nDone. Converted: {converted}, skipped: {skipped}, total .pth: {len(pth_files)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
