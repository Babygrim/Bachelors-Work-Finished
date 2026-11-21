"""Shared constants for upscaling and video processing."""

AMD_VIDEO_SR_MODEL = "AMD VideoSR (AMF)"
AMF_PREVIEW_BUFFER_SECONDS = 0.3
# Frames kept in flight in the AMF pipeline. Shallower depths idle the GPU between round trips
# and stall outright on 120+ fps sources; 6 sustains 60 fps 1080p output.
AMF_PIPELINE_DEPTH = 6
