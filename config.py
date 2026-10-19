import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, List

@dataclass
class SlideGrabConfig:
    """Central configuration for SlideGrab pipeline."""
    # Input / Output
    input_source: str = ""
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    cache_dir: Path = field(default_factory=lambda: Path("./cache"))
    quick_test_minutes: Optional[float] = None  # Process only first N minutes if set
    no_review: bool = False

    # Download settings
    max_height: int = 720
    cookies_file: Optional[str] = None
    cookies_from_browser: Optional[str] = None
    keep_video_cache: bool = True

    # Region / Crop settings
    auto_crop: bool = True
    manual_crop: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h)
    crop_sample_count: int = 30

    # Sampling & Stability
    sample_interval: float = 1.0       # Seconds between sampled frames
    stability_seconds: float = 2.0     # Time a frame must be stable to be accepted
    ssim_threshold: float = 0.92       # Similarity threshold (SSIM >= threshold means same slide)
    phash_threshold: int = 6           # Perceptual hash Hamming distance threshold

    # Deduplication & Quality Filters
    keep_revisits: bool = False        # Keep slides if instructor returns to them later
    filter_faces: bool = True          # Skip frames where a large face dominates
    face_area_threshold: float = 0.08  # Max fraction of frame occupied by a face
    min_edge_density: float = 0.003    # Minimum Laplacian edge density to reject blank/black/white frames

    # Build-up & Live Writing
    handle_build_ups: bool = True      # Replace earlier incomplete versions of bullet/animation slides
    live_writing_mode: bool = False    # Settle period for pen/chalk annotations before capturing

    # Checkpoint
    checkpoint_interval_seconds: int = 120  # Save progress every 2 minutes
    resume: bool = True                     # Resume from checkpoint if found
