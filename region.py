import cv2
import numpy as np
from typing import Optional, Tuple, List
from pathlib import Path

def detect_slide_region(
    video_path: Path,
    sample_count: int = 30,
    max_duration_seconds: Optional[float] = None
) -> Tuple[int, int, int, int]:
    """
    Analyzes video frames across time to auto-detect the primary slide area,
    removing persistent black/dark letterboxes, pillars, or border chrome.
    Returns: (x, y, w, h)
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    if max_duration_seconds and max_duration_seconds < duration:
        total_frames = int(max_duration_seconds * fps)

    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    default_crop = (0, 0, frame_w, frame_h)

    if total_frames <= 0 or sample_count <= 0:
        cap.release()
        return default_crop

    step = max(1, total_frames // sample_count)
    sampled_frames = []

    for i in range(sample_count):
        target_f = min(i * step, total_frames - 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_f)
        ret, frame = cap.read()
        if ret and frame is not None:
            sampled_frames.append(frame)

    cap.release()

    if len(sampled_frames) < 3:
        return default_crop

    # 1. Detect border letterboxing by analyzing average row/column intensity and variance
    # Convert frames to grayscale
    gray_frames = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in sampled_frames]
    
    # Calculate temporal mean and standard deviation
    stack = np.stack(gray_frames, axis=0) # Shape: (N, H, W)
    mean_img = np.mean(stack, axis=0).astype(np.uint8)
    std_img = np.std(stack, axis=0)

    # Detect horizontal black bars (letterboxing top/bottom)
    row_means = np.mean(mean_img, axis=1) # Shape: (H,)
    row_stds = np.mean(std_img, axis=1)

    top_y = 0
    bottom_y = frame_h

    # Top border threshold (near pitch black and zero variance)
    for y in range(0, frame_h // 3):
        if row_means[y] < 12 and row_stds[y] < 8:
            top_y = y + 1
        else:
            break

    # Bottom border threshold
    for y in range(frame_h - 1, 2 * frame_h // 3, -1):
        if row_means[y] < 12 and row_stds[y] < 8:
            bottom_y = y
        else:
            break

    # Detect vertical black bars (pillarboxing left/right)
    col_means = np.mean(mean_img, axis=0) # Shape: (W,)
    col_stds = np.mean(std_img, axis=0)

    left_x = 0
    right_x = frame_w

    for x in range(0, frame_w // 3):
        if col_means[x] < 12 and col_stds[x] < 8:
            left_x = x + 1
        else:
            break

    for x in range(frame_w - 1, 2 * frame_w // 3, -1):
        if col_means[x] < 12 and col_stds[x] < 8:
            right_x = x
        else:
            break

    w = max(10, right_x - left_x)
    h = max(10, bottom_y - top_y)

    # Only apply crop if at least 2% of frame was trimmed as black bars
    area_ratio = (w * h) / (frame_w * frame_h)
    if area_ratio < 0.98 and area_ratio > 0.30:
        return (left_x, top_y, w, h)

    # 2. Contour-based slide bounding box check (for windowed browser/app slides)
    edges = cv2.Canny(mean_img, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    best_rect = default_crop
    max_area = 0
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        aspect = cw / float(ch) if ch > 0 else 0
        # Looking for presentation aspect ratios (16:9 ~ 1.77, 4:3 ~ 1.33)
        if 1.2 <= aspect <= 1.9 and area > (0.40 * frame_w * frame_h):
            if area > max_area:
                max_area = area
                best_rect = (x, y, cw, ch)

    if max_area > (0.50 * frame_w * frame_h):
        return best_rect

    return default_crop

def apply_crop(frame: np.ndarray, crop_box: Optional[Tuple[int, int, int, int]]) -> np.ndarray:
    """Crop frame to (x, y, w, h) bounds."""
    if not crop_box:
        return frame
    x, y, w, h = crop_box
    fh, fw = frame.shape[:2]
    # Guard bounds
    x = max(0, min(x, fw - 1))
    y = max(0, min(y, fh - 1))
    w = max(1, min(w, fw - x))
    h = max(1, min(h, fh - y))
    return frame[y:y+h, x:x+w]

def draw_crop_preview(frame: np.ndarray, crop_box: Optional[Tuple[int, int, int, int]]) -> np.ndarray:
    """Draws a visual green border highlighting the detected crop box."""
    preview = frame.copy()
    if not crop_box:
        return preview
    x, y, w, h = crop_box
    cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 255, 0), 3)
    label = f"Slide Crop: {w}x{h} at ({x},{y})"
    cv2.putText(preview, label, (x + 10, max(30, y + 35)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    return preview
