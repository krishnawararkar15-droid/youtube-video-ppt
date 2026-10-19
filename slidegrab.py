#!/usr/bin/env python3
"""
SlideGrab CLI: Rebuild clean, high-quality slide decks (PDF & PPTX) from video lectures.
"""
import argparse
import sys
import os
from pathlib import Path
from tqdm import tqdm

from config import SlideGrabConfig
from downloader import get_video_source
from region import detect_slide_region, apply_crop
from detector import process_video_stream
from exporter import export_pdf, export_pptx, export_timestamps_csv, format_timestamp

def parse_args():
    parser = argparse.ArgumentParser(
        description="SlideGrab: Rebuild slide decks (PDF + PPTX) from YouTube & local video lectures."
    )
    parser.add_argument("input", help="YouTube video URL or path to local video file")
    parser.add_argument("-o", "--out", default="./output", help="Directory to save exported files (default: ./output)")
    parser.add_argument("--cache", default="./cache", help="Directory for cached downloaded videos (default: ./cache)")
    
    # Timing & Detection
    parser.add_argument("--interval", type=float, default=1.0, help="Sampling interval in seconds (default: 1.0)")
    parser.add_argument("--stable", type=float, default=2.0, help="Seconds a slide must remain stable (default: 2.0)")
    parser.add_argument("--threshold", type=float, default=0.92, help="SSIM similarity threshold (default: 0.92)")
    parser.add_argument("--phash-thresh", type=int, default=6, help="Perceptual hash threshold (default: 6)")
    
    # Crop
    parser.add_argument("--no-crop", action="store_true", help="Disable automatic slide crop detection")
    parser.add_argument("--crop", help="Manual crop bounds: x,y,w,h (e.g. 50,20,1180,680)")
    
    # Filtering & Modes
    parser.add_argument("--quick-test", type=float, default=None, help="Process only the first N minutes of video")
    parser.add_argument("--no-face-filter", action="store_true", help="Disable skipping zoomed teacher face shots")
    parser.add_argument("--live-writing", action="store_true", help="Enable live writing mode for tablet/smartboard lectures")
    parser.add_argument("--keep-revisits", action="store_true", help="Keep duplicate slides if teacher revisits them")
    parser.add_argument("--no-resume", action="store_true", help="Do not resume from previous checkpoint; restart fresh")
    parser.add_argument("--no-review", action="store_true", default=True, help="Auto-export directly without pausing")
    
    # Auth & Cookies
    parser.add_argument("--cookies", help="Path to cookies.txt file for restricted/private videos")
    parser.add_argument("--cookies-from-browser", help="Browser to extract cookies from (e.g. chrome, edge, firefox)")

    return parser.parse_args()

def main():
    args = parse_args()
    
    config = SlideGrabConfig(
        input_source=args.input,
        output_dir=Path(args.out),
        cache_dir=Path(args.cache),
        quick_test_minutes=args.quick_test,
        no_review=args.no_review,
        sample_interval=args.interval,
        stability_seconds=args.stable,
        ssim_threshold=args.threshold,
        phash_threshold=args.phash_thresh,
        auto_crop=not args.no_crop,
        filter_faces=not args.no_face_filter,
        live_writing_mode=args.live_writing,
        keep_revisits=args.keep_revisits,
        resume=not args.no_resume,
        cookies_file=args.cookies,
        cookies_from_browser=args.cookies_from_browser
    )

    if args.crop:
        try:
            parts = [int(p.strip()) for p in args.crop.split(",")]
            if len(parts) == 4:
                config.manual_crop = tuple(parts)
            else:
                print("Warning: --crop must be 4 comma-separated integers (x,y,w,h). Ignoring manual crop.")
        except ValueError:
            print("Warning: Invalid integers in --crop. Ignoring manual crop.")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.cache_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(" SlideGrab: Rebuilding Slide Deck from Video")
    print("=" * 60)
    print(f" Input:      {config.input_source}")
    print(f" Output Dir: {config.output_dir.resolve()}")
    if config.quick_test_minutes:
        print(f" Mode:       Quick Test (First {config.quick_test_minutes} minutes)")
    print(f" Settings:   Interval={config.sample_interval}s, Stability={config.stability_seconds}s, SSIM Threshold={config.ssim_threshold}")
    print("-" * 60)

    # 1. Video acquisition
    print("[1/4] Resolving and fetching video source...")
    def dl_progress(pct, msg):
        sys.stdout.write(f"\r  {msg} [{pct:.1f}%]   ")
        sys.stdout.flush()

    try:
        video_path, video_title, yt_id = get_video_source(
            source=config.input_source,
            cache_dir=config.cache_dir,
            max_height=config.max_height,
            cookies_file=config.cookies_file,
            cookies_from_browser=config.cookies_from_browser,
            progress_callback=dl_progress
        )
        print(f"\n  Ready: '{video_title}' -> {video_path.name}")
    except Exception as e:
        print(f"\nError acquiring video: {e}")
        sys.exit(1)

    # 2. Slide Region Detection
    print("\n[2/4] Analyzing video for slide region / crop...")
    crop_box = None
    if config.manual_crop:
        crop_box = config.manual_crop
        print(f"  Using manual crop: {crop_box}")
    elif config.auto_crop:
        try:
            detected = detect_slide_region(
                video_path,
                sample_count=config.crop_sample_count,
                max_duration_seconds=config.quick_test_minutes * 60 if config.quick_test_minutes else None
            )
            crop_box = detected
            print(f"  Auto-detected slide region: (x={crop_box[0]}, y={crop_box[1]}, w={crop_box[2]}, h={crop_box[3]})")
        except Exception as e:
            print(f"  Warning: Region detection failed ({e}). Defaulting to full frame.")
            crop_box = None
    else:
        print("  Auto-crop disabled; using full frame.")

    # 3. Slide detection and frame sampling
    print("\n[3/4] Scanning video stream and extracting unique slides...")
    pbar = tqdm(total=100, desc="  Scanning", unit="%")
    last_pct = 0.0

    def scan_progress(pct, slide_count, curr_sec, latest_frame):
        nonlocal last_pct
        delta = pct - last_pct
        if delta > 0:
            pbar.update(delta)
            last_pct = pct
        pbar.set_postfix({
            "Time": format_timestamp(curr_sec),
            "Slides": slide_count
        })

    try:
        slides, slides_dir = process_video_stream(
            video_path=video_path,
            config=config,
            crop_box=crop_box,
            progress_callback=scan_progress
        )
    finally:
        pbar.close()

    print(f"\n  Extraction complete! Found {len(slides)} unique slides.")

    if not slides:
        print("  No slides detected! Consider lowering --threshold (e.g. 0.85) or adjusting --stable.")
        sys.exit(0)

    # 4. Export artifacts
    print("\n[4/4] Exporting slide deck artifacts...")
    
    # 4a. PDF Export
    pdf_path = config.output_dir / "output.pdf"
    slide_images = [slides_dir / s.image_filename for s in slides]
    try:
        export_pdf(slide_images, pdf_path)
        print(f"  PDF created:  {pdf_path.resolve()} ({pdf_path.stat().st_size / (1024*1024):.2f} MB)")
    except Exception as e:
        print(f"  PDF export error: {e}")

    # 4b. PPTX Export
    pptx_path = config.output_dir / "output.pptx"
    try:
        export_pptx(slides, slides_dir, pptx_path, youtube_id=yt_id)
        print(f"  PPTX created: {pptx_path.resolve()} ({pptx_path.stat().st_size / (1024*1024):.2f} MB)")
    except Exception as e:
        print(f"  PPTX export error: {e}")

    # 4c. Timestamps CSV
    csv_path = config.output_dir / "timestamps.csv"
    try:
        export_timestamps_csv(slides, csv_path, youtube_id=yt_id)
        print(f"  CSV created:  {csv_path.resolve()}")
    except Exception as e:
        print(f"  CSV export error: {e}")

    print("\n" + "=" * 60)
    print(f" Success! Slide deck with {len(slides)} slides generated in:")
    print(f" {config.output_dir.resolve()}")
    print("=" * 60)

if __name__ == "__main__":
    main()
