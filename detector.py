import cv2
import numpy as np
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Callable
from PIL import Image
import imagehash
from skimage.metrics import structural_similarity as ssim

from config import SlideGrabConfig
from region import apply_crop

# Safe Face detector initialization across OpenCV 4.x and 5.x
FACE_CASCADE = None
if hasattr(cv2, 'CascadeClassifier') and hasattr(cv2, 'data') and hasattr(cv2.data, 'haarcascades'):
    try:
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        cascade = cv2.CascadeClassifier(cascade_path)
        if not cascade.empty():
            FACE_CASCADE = cascade
    except Exception:
        FACE_CASCADE = None

@dataclass
class SlideRecord:
    index: int
    timestamp_sec: float
    phash: str
    image_filename: str
    crop_box: Optional[Tuple[int, int, int, int]] = None

def compute_phash(gray_img: np.ndarray) -> imagehash.ImageHash:
    """Computes perceptual hash on a grayscale numpy image."""
    pil_img = Image.fromarray(gray_img)
    return imagehash.phash(pil_img)

def is_junk_frame(
    frame: np.ndarray,
    config: SlideGrabConfig,
    face_cascade: cv2.CascadeClassifier = FACE_CASCADE
) -> bool:
    """
    Determines if a frame is junk (pure black/white, blurred transition, or full-screen face).
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_val = np.mean(gray)
    std_val = np.std(gray)

    # 1. Pure black or pure white frame
    if mean_val < 15 or mean_val > 245 or std_val < 10:
        return True

    # 2. Low edge density (blank frame or out-of-focus blur)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    lap_var = laplacian.var()
    if lap_var < (config.min_edge_density * 1000):
        return True

    # 3. Full-screen face detection (teacher talking to camera instead of slides)
    if config.filter_faces and face_cascade is not None and not face_cascade.empty():
        h, w = gray.shape
        total_area = w * h
        # Quick resize for speed
        scale = 320.0 / w
        small_gray = cv2.resize(gray, (320, int(h * scale)))
        faces = face_cascade.detectMultiScale(small_gray, scaleFactor=1.15, minNeighbors=4, minSize=(40, 40))
        for (fx, fy, fw, fh) in faces:
            # Scale face back to original dimensions
            orig_area = (fw / scale) * (fh / scale)
            if (orig_area / total_area) >= config.face_area_threshold:
                return True

    return False

def is_additive_buildup(prev_small_gray: np.ndarray, curr_small_gray: np.ndarray, threshold: float = 0.88) -> bool:
    """
    Detects if curr frame contains prev frame with additive content (e.g. bullet builds, live writing).
    Both inputs must be grayscale uint8 images of identical dimensions (e.g. 320x180).
    """
    # Compute absolute difference
    abs_diff = cv2.absdiff(prev_small_gray, curr_small_gray)
    changed_pixels = np.count_nonzero(abs_diff > 25)
    total_pixels = prev_small_gray.size
    change_ratio = changed_pixels / total_pixels

    # In a build-up, 0.5% to 40% of the slide changes with new content added
    if not (0.005 <= change_ratio <= 0.40):
        return False

    # Check that previous content is largely preserved in unchanged regions
    unchanged_mask = abs_diff <= 25
    prev_unchanged = prev_small_gray[unchanged_mask]
    curr_unchanged = curr_small_gray[unchanged_mask]
    if len(prev_unchanged) == 0:
        return False

    unchanged_ssim = ssim(prev_unchanged, curr_unchanged)
    return unchanged_ssim >= threshold

def process_video_stream(
    video_path: Path,
    config: SlideGrabConfig,
    crop_box: Optional[Tuple[int, int, int, int]] = None,
    progress_callback: Optional[Callable[[float, int, float, Optional[np.ndarray]], None]] = None,
    stop_event: Optional[Callable[[], bool]] = None
) -> Tuple[List[SlideRecord], Path]:
    """
    Processes video stream and extracts high-quality slides.
    Returns: (list_of_slide_records, slides_output_directory)
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video file: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration = total_frames / fps

    if config.quick_test_minutes:
        max_duration = min(video_duration, config.quick_test_minutes * 60.0)
    else:
        max_duration = video_duration

    # Output directory
    slides_dir = config.output_dir / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = config.output_dir / "checkpoint.json"

    # Frame step for sampling
    frame_step = max(1, int(round(fps * config.sample_interval)))
    stability_frames = max(1, int(round(config.stability_seconds / config.sample_interval)))

    # State tracking
    saved_slides: List[SlideRecord] = []
    saved_hashes: List[imagehash.ImageHash] = []

    # Resume from checkpoint if available and requested
    start_sec = 0.0
    if config.resume and checkpoint_file.is_file():
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                chk = json.load(f)
                start_sec = chk.get("last_processed_sec", 0.0)
                for item in chk.get("slides", []):
                    rec = SlideRecord(
                        index=item["index"],
                        timestamp_sec=item["timestamp_sec"],
                        phash=item["phash"],
                        image_filename=item["image_filename"],
                        crop_box=tuple(item["crop_box"]) if item.get("crop_box") else None
                    )
                    saved_slides.append(rec)
                    saved_hashes.append(imagehash.hex_to_hash(item["phash"]))
        except Exception:
            saved_slides = []
            saved_hashes = []
            start_sec = 0.0

    # Stream loop buffers
    COMPARE_SIZE = (320, 180)
    last_accepted_small_gray: Optional[np.ndarray] = None
    last_accepted_hash: Optional[imagehash.ImageHash] = None

    if saved_slides:
        last_rec = saved_slides[-1]
        last_accepted_hash = saved_hashes[-1]
        last_img_path = slides_dir / last_rec.image_filename
        if last_img_path.is_file():
            img = cv2.imread(str(last_img_path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                last_accepted_small_gray = cv2.resize(img, COMPARE_SIZE)

    # Candidate buffer for stability
    candidate_small_gray: Optional[np.ndarray] = None
    candidate_raw_frame: Optional[np.ndarray] = None
    candidate_timestamp: float = 0.0
    candidate_stable_count: int = 0

    curr_frame_idx = int(start_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, curr_frame_idx)

    last_checkpoint_time = time.time()
    slide_counter = len(saved_slides)

    try:
        while True:
            if stop_event and stop_event():
                break

            curr_sec = curr_frame_idx / fps
            if curr_sec > max_duration:
                break

            # Fast skip: grab without decoding
            ret = cap.grab()
            if not ret:
                break

            # Only decode on sample_interval
            if curr_frame_idx % frame_step == 0:
                ret, raw_frame = cap.retrieve()
                if not ret or raw_frame is None:
                    break

                # Apply slide crop
                cropped_frame = apply_crop(raw_frame, crop_box)

                # Skip obvious junk
                if is_junk_frame(cropped_frame, config):
                    curr_frame_idx += 1
                    continue

                # Prepare small grayscale for rapid comparison
                gray = cv2.cvtColor(cropped_frame, cv2.COLOR_BGR2GRAY)
                small_gray = cv2.resize(gray, COMPARE_SIZE)
                curr_phash = compute_phash(small_gray)

                # 1. Compare with current candidate stability buffer
                if candidate_small_gray is not None:
                    cand_ssim = ssim(candidate_small_gray, small_gray)
                    # If frame matches candidate, it is remaining stable
                    if cand_ssim >= config.ssim_threshold:
                        candidate_stable_count += 1
                        # Always keep the LATEST (most complete) frame of the stable period
                        candidate_raw_frame = cropped_frame
                        candidate_timestamp = curr_sec
                    else:
                        # Frame changed while candidate was being evaluated
                        # If candidate was ALREADY stable for stability_frames, commit it now!
                        if candidate_stable_count >= stability_frames:
                            # Commit candidate
                            slide_counter, accepted = _commit_slide(
                                candidate_raw_frame, candidate_timestamp, candidate_small_gray,
                                curr_phash, saved_slides, saved_hashes, config,
                                slides_dir, slide_counter, crop_box, last_accepted_small_gray
                            )
                            if accepted:
                                last_accepted_small_gray = candidate_small_gray
                                last_accepted_hash = curr_phash
                                if progress_callback:
                                    pct = min(100.0, (curr_sec / max_duration) * 100)
                                    progress_callback(pct, len(saved_slides), curr_sec, candidate_raw_frame)

                        # Reset candidate to current frame
                        candidate_small_gray = small_gray
                        candidate_raw_frame = cropped_frame
                        candidate_timestamp = curr_sec
                        candidate_stable_count = 1
                else:
                    # Initial frame check against last accepted slide
                    is_new = False
                    if last_accepted_small_gray is None:
                        is_new = True
                    else:
                        sim = ssim(last_accepted_small_gray, small_gray)
                        if sim < config.ssim_threshold:
                            is_new = True

                    if is_new:
                        candidate_small_gray = small_gray
                        candidate_raw_frame = cropped_frame
                        candidate_timestamp = curr_sec
                        candidate_stable_count = 1

                # Periodic callback for progress update
                if progress_callback and (curr_frame_idx % (frame_step * 5) == 0):
                    pct = min(100.0, (curr_sec / max_duration) * 100)
                    progress_callback(pct, len(saved_slides), curr_sec, None)

                # Periodic Checkpoint
                if (time.time() - last_checkpoint_time) > config.checkpoint_interval_seconds:
                    _save_checkpoint(checkpoint_file, curr_sec, saved_slides)
                    last_checkpoint_time = time.time()

            curr_frame_idx += 1

        # End of stream: commit any lingering stable candidate
        if candidate_raw_frame is not None and candidate_stable_count >= stability_frames:
            slide_counter, accepted = _commit_slide(
                candidate_raw_frame, candidate_timestamp, candidate_small_gray,
                compute_phash(candidate_small_gray), saved_slides, saved_hashes, config,
                slides_dir, slide_counter, crop_box, last_accepted_small_gray
            )

    finally:
        cap.release()
        _save_checkpoint(checkpoint_file, min(curr_sec, max_duration), saved_slides)

    return saved_slides, slides_dir

def _commit_slide(
    raw_frame: np.ndarray,
    timestamp_sec: float,
    small_gray: np.ndarray,
    curr_phash: imagehash.ImageHash,
    saved_slides: List[SlideRecord],
    saved_hashes: List[imagehash.ImageHash],
    config: SlideGrabConfig,
    slides_dir: Path,
    slide_counter: int,
    crop_box: Optional[Tuple[int, int, int, int]],
    last_accepted_small_gray: Optional[np.ndarray]
) -> Tuple[int, bool]:
    """
    Evaluates candidate against build-up and revisit deduplication rules, then saves to disk.
    """
    # 1. Animation / Build-up handling:
    # If this slide is an additive build-up of the immediately preceding slide, REPLACE it!
    if (config.handle_build_ups or config.live_writing_mode) and saved_slides and last_accepted_small_gray is not None:
        if is_additive_buildup(last_accepted_small_gray, small_gray):
            # Replace previous slide image with updated fuller version
            last_rec = saved_slides[-1]
            out_path = slides_dir / last_rec.image_filename
            cv2.imwrite(str(out_path), raw_frame)
            # Update hash and timestamp
            last_rec.timestamp_sec = timestamp_sec
            last_rec.phash = str(curr_phash)
            saved_hashes[-1] = curr_phash
            return slide_counter, True

    # 2. Check against ALL previously saved slides (Global deduplication)
    if not config.keep_revisits:
        for prev_hash in saved_hashes:
            if (curr_phash - prev_hash) <= config.phash_threshold:
                # Revisit of an earlier slide; do not duplicate
                return slide_counter, False

    # 3. New unique slide accepted
    slide_counter += 1
    filename = f"slide_{slide_counter:03d}.png"
    out_path = slides_dir / filename
    cv2.imwrite(str(out_path), raw_frame)

    record = SlideRecord(
        index=slide_counter,
        timestamp_sec=timestamp_sec,
        phash=str(curr_phash),
        image_filename=filename,
        crop_box=crop_box
    )
    saved_slides.append(record)
    saved_hashes.append(curr_phash)

    return slide_counter, True

def _save_checkpoint(checkpoint_file: Path, curr_sec: float, saved_slides: List[SlideRecord]):
    """Saves resumable checkpoint state to JSON."""
    data = {
        "last_processed_sec": curr_sec,
        "slides": [
            {
                "index": s.index,
                "timestamp_sec": s.timestamp_sec,
                "phash": s.phash,
                "image_filename": s.image_filename,
                "crop_box": list(s.crop_box) if s.crop_box else None
            }
            for s in saved_slides
        ]
    }
    with open(checkpoint_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
