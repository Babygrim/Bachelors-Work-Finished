"""Time approximation and estimation for video upscaling operations."""

import math


class UpscalingTimeEstimator:
    """Estimate processing time for video upscaling based on hardware and model characteristics.
    
    Benchmarks (fps - frames per second processed):
    - GPU (DirectML): 15-45 fps depending on model/resolution
    - CPU: 1-5 fps
    - 4x upscaling is slower than 2x
    - Anime models (6B blocks) are faster than general models (23B blocks)
    """
    
    # Baseline FPS for different models on GPU (DirectML)
    GPU_FPS_BASELINE = {
        "general_4x": 20,          # RealESRGAN_x4plus
        "general_2x": 35,          # RealESRGAN_x2plus
        "general_anime_4x": 28,    # RealESRGAN_x4plus_anime_6B (lighter model)
        "lightweight_4x": 40,      # realesr-general-x4v3
    }
    
    # CPU is roughly 15-20x slower than GPU
    CPU_FPS_MULTIPLIER = 0.08
    
    def __init__(self):
        self.last_estimate = None
        self.last_actual = None
    
    @staticmethod
    def _get_model_category(model_name: str) -> str:
        """Categorize model for FPS estimation.
        
        Args:
            model_name: Model name from dropdown
            
        Returns:
            Model category string
        """
        lower = model_name.lower()
        
        if "anime" in lower:
            return "general_anime_4x"
        elif "x2" in lower or "2plus" in lower:
            return "general_2x"
        elif "general" in lower or "v3" in lower:
            return "lightweight_4x"
        else:
            return "general_4x"
    
    @staticmethod
    def _get_resolution_factor(input_resolution: tuple, scale: int) -> float:
        """Calculate resolution adjustment factor for FPS estimation.
        
        Higher resolution = slower processing.
        
        Args:
            input_resolution: (width, height) tuple of input video
            scale: Upscaling factor (2, 4, 8)
            
        Returns:
            Adjustment factor (1.0 = baseline, >1.0 = slower)
        """
        w, h = input_resolution
        pixels = w * h
        
        # Baseline: 1920x1080 (2.07M pixels)
        baseline_pixels = 1920 * 1080
        
        # Adjustment: more pixels = slower
        # Roughly linear relationship
        return max(0.3, pixels / baseline_pixels)
    
    def estimate_time(self, 
                     total_frames: int,
                     fps: float,
                     input_resolution: tuple,
                     scale: int,
                     model_name: str,
                     is_gpu: bool = True) -> dict:
        """Estimate total processing time for video upscaling.
        
        Args:
            total_frames: Total number of frames in video
            fps: Frames per second of the video
            input_resolution: (width, height) tuple
            scale: Upscaling factor (2, 4, 8)
            model_name: Model name from dropdown
            is_gpu: True if using GPU, False if CPU
            
        Returns:
            Dictionary with:
            - 'total_seconds': Total estimated time in seconds
            - 'hours': Hours component
            - 'minutes': Minutes component  
            - 'seconds': Seconds component
            - 'formatted': Human-readable string like "2h 15m 30s"
            - 'fps': Estimated frames per second for this configuration
            - 'confidence': Confidence level (1-5, 5 being highest)
        """
        model_category = self._get_model_category(model_name)
        base_fps = self.GPU_FPS_BASELINE.get(model_category, 20)
        
        # Apply adjustments
        resolution_factor = self._get_resolution_factor(input_resolution, scale)
        fps_adjusted = base_fps / resolution_factor
        
        if not is_gpu:
            fps_adjusted *= self.CPU_FPS_MULTIPLIER
        
        # 4x scale is slower than 2x
        if scale == 8:
            fps_adjusted *= 0.4  # ~60% slower
        elif scale == 4:
            fps_adjusted *= 0.6  # ~40% slower
        # 2x is baseline
        
        # Calculate time
        total_seconds = max(1, total_frames / max(fps_adjusted, 0.1))
        
        # Convert to h:m:s
        hours = int(total_seconds // 3600)
        remaining = total_seconds - (hours * 3600)
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        
        # Format as string
        if hours > 0:
            formatted = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            formatted = f"{minutes}m {seconds}s"
        else:
            formatted = f"{seconds}s"
        
        # Confidence depends on input parameters and model knowledge
        confidence = 3
        if model_name in self.GPU_FPS_BASELINE.values() or "anime" in model_name.lower():
            confidence = 4
        if input_resolution in [(1920, 1080), (1280, 720)]:
            confidence = 4
        
        estimate = {
            "total_seconds": total_seconds,
            "hours": hours,
            "minutes": minutes,
            "seconds": seconds,
            "formatted": formatted,
            "fps": round(fps_adjusted, 2),
            "confidence": min(5, confidence),
        }
        
        self.last_estimate = estimate
        return estimate
    
    def record_actual_time(self, actual_seconds: float, estimate_dict: dict = None):
        """Record actual processing time for future calibration.
        
        Args:
            actual_seconds: Actual time taken in seconds
            estimate_dict: Original estimate dict (for comparison)
        """
        self.last_actual = {
            "seconds": actual_seconds,
            "estimate": estimate_dict,
        }
    
    def get_accuracy_ratio(self) -> float:
        """Get ratio of estimated vs actual time (1.0 = perfect).
        
        Returns:
            Ratio, or None if no estimate/actual recorded
        """
        if not self.last_estimate or not self.last_actual:
            return None
        
        estimated = self.last_estimate["total_seconds"]
        actual = self.last_actual["seconds"]
        return estimated / actual if actual > 0 else None
    
    def estimate_total_time(self, progress_percent: int, elapsed_seconds: float) -> float:
        """Estimate total time based on current progress and elapsed time.
        
        Args:
            progress_percent: Current progress (0-100)
            elapsed_seconds: Time elapsed so far in seconds
            
        Returns:
            Estimated total time in seconds
        """
        if progress_percent <= 0 or progress_percent >= 100:
            return max(1, elapsed_seconds)
        
        # Linear estimation: if we're at X%, total time = elapsed / (X/100)
        estimated_total = elapsed_seconds / (progress_percent / 100.0)
        
        return max(elapsed_seconds, estimated_total)


def format_time_estimate(total_seconds: int | float) -> str:
    """Format seconds into human-readable h:m:s string.
    
    Args:
        total_seconds: Total seconds
        
    Returns:
        Formatted string like "1h 30m 45s"
    """
    total_seconds = int(total_seconds)
    hours = total_seconds // 3600
    remaining = total_seconds - (hours * 3600)
    minutes = remaining // 60
    seconds = remaining % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"
