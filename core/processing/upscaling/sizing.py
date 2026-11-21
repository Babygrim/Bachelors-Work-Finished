"""Output sizing calculations for video and image upscaling."""

MODEL_FACTORS = (2, 4, 8)
TARGET_HEIGHTS = (1080, 2160)


def is_target(factor):
    """Check if factor is a target height (1080p or 2160p)."""
    return int(factor) in TARGET_HEIGHTS


def output_plan(source_size, factor):
    """Calculate output dimensions and model factor.
    
    For multipliers (2/4/8): output = source * factor
    For target heights (1080/2160): calculates smallest model factor needed
    to reach that height, maintaining aspect ratio.
    """
    source_width, source_height = source_size
    factor = int(factor)
    if factor not in TARGET_HEIGHTS:
        return factor, (source_width * factor, source_height * factor)
    model_factor = next(
        (value for value in MODEL_FACTORS if source_height * value >= factor),
        MODEL_FACTORS[-1],
    )
    width = round(source_width * factor / source_height)
    return model_factor, (width + width % 2, factor)


def target_label(factor, size):
    """Generate a human-readable label for a target height."""
    name = "1080p Full HD" if int(factor) == 1080 else "2160p 4K"
    return f"{name} ({size[0]} × {size[1]})"
