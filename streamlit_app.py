"""
SlideGrab Web UI: Streamlit application for rebuilding slide decks from video lectures.
"""
import streamlit as st
import os
import cv2
import json
import shutil
from pathlib import Path
from PIL import Image

from config import SlideGrabConfig
from downloader import get_video_source, is_youtube_url
from region import detect_slide_region, apply_crop, draw_crop_preview
from detector import process_video_stream, SlideRecord
from exporter import export_pdf, export_pptx, export_timestamps_csv, format_timestamp

st.set_page_config(
    page_title="SlideGrab - Lecture Slide Extractor",
    page_icon="📑",
    layout="wide"
)

# Initialize Session State
if "slides" not in st.session_state:
    st.session_state.slides = []
if "slides_dir" not in st.session_state:
    st.session_state.slides_dir = None
if "yt_id" not in st.session_state:
    st.session_state.yt_id = None
if "video_path" not in st.session_state:
    st.session_state.video_path = None
if "crop_box" not in st.session_state:
    st.session_state.crop_box = None
if "export_ready" not in st.session_state:
    st.session_state.export_ready = False

st.title("📑 SlideGrab: Lecture Slide Rebuilder")
st.markdown("Rebuild clean, complete slide decks (**PDF + PPTX**) from YouTube & local video lectures.")

# Sidebar - Settings
with st.sidebar:
    st.header("⚙️ Settings")
    
    st.subheader("⏱️ Sampling & Timing")
    sample_interval = st.slider("Sample Interval (seconds)", min_value=0.5, max_value=5.0, value=1.0, step=0.5,
                                help="How often frames are checked. 1.0s is ideal for most lectures.")
    stability_sec = st.slider("Stability Duration (seconds)", min_value=1.0, max_value=6.0, value=2.0, step=0.5,
                              help="Seconds a slide must remain still to confirm it's not a transition.")
    
    st.subheader("🎯 Sensitivity & Thresholds")
    ssim_threshold = st.slider("SSIM Threshold (Similarity)", min_value=0.70, max_value=0.98, value=0.92, step=0.01,
                               help="Higher = more sensitive to changes (creates more slides). Lower = merges similar slides.")
    phash_thresh = st.slider("Perceptual Hash Threshold", min_value=2, max_value=16, value=6, step=1,
                             help="Distance for duplicate detection across the entire presentation.")

    st.subheader("🖼️ Slide Region & Crop")
    crop_mode = st.radio("Crop Mode", ["Auto-Detect", "Manual (x,y,w,h)", "Full Frame (No Crop)"])
    manual_crop_val = None
    if crop_mode == "Manual (x,y,w,h)":
        manual_crop_input = st.text_input("Coordinates (x, y, w, h)", "0, 0, 1280, 720")
        try:
            parts = [int(p.strip()) for p in manual_crop_input.split(",")]
            if len(parts) == 4:
                manual_crop_val = tuple(parts)
        except Exception:
            st.error("Invalid crop format. Use: x,y,w,h")

    st.subheader("🛡️ Filters & Modes")
    quick_test = st.checkbox("Quick Test Mode", value=False, help="Process only the first few minutes to test settings.")
    test_minutes = 10.0
    if quick_test:
        test_minutes = st.number_input("Minutes to process", min_value=1.0, max_value=60.0, value=10.0, step=1.0)
    
    live_writing = st.checkbox("Live Writing Mode", value=False,
                               help="Enable for chalkboards/tablets where instructor writes progressively.")
    handle_buildups = st.checkbox("Animation / Bullet Build-up Replacement", value=True,
                                  help="Automatically replaces earlier partial bullet slides with the final full slide.")
    filter_faces = st.checkbox("Filter Large Face Shots", value=True,
                               help="Skip frames where instructor's zoomed-in face takes over the screen.")
    keep_revisits = st.checkbox("Keep Slide Revisits", value=False,
                                help="Keep slides if instructor returns to an earlier slide later in the lecture.")

    st.subheader("🍪 Authentication")
    cookies_browser = st.selectbox("Cookies from Browser", ["None", "chrome", "edge", "firefox", "brave"])
    cookies_browser = None if cookies_browser == "None" else cookies_browser

# Main Input Section
input_col1, input_col2 = st.columns([3, 1])
with input_col1:
    video_source = st.text_input(
        "YouTube Video URL or Local File Path",
        placeholder="https://www.youtube.com/watch?v=... or C:/path/to/lecture.mp4"
    )

with input_col2:
    st.write("")
    st.write("")
    analyze_crop_btn = st.button("🔍 Preview Crop")

# Crop Preview Section
if analyze_crop_btn and video_source:
    with st.spinner("Analyzing video for slide region preview..."):
        try:
            cache_p = Path("./cache")
            v_path, v_title, yt_id = get_video_source(
                video_source, cache_p, cookies_from_browser=cookies_browser
            )
            st.session_state.video_path = v_path
            st.session_state.yt_id = yt_id
            
            # Auto or manual crop
            if crop_mode == "Auto-Detect":
                detected_crop = detect_slide_region(v_path, sample_count=20)
            elif crop_mode == "Manual (x,y,w,h)" and manual_crop_val:
                detected_crop = manual_crop_val
            else:
                detected_crop = None
            
            st.session_state.crop_box = detected_crop

            # Grab frame 30s in for preview
            cap = cv2.VideoCapture(str(v_path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps * 30))
            ret, p_frame = cap.read()
            cap.release()

            if ret and p_frame is not None:
                vis_frame = draw_crop_preview(p_frame, detected_crop)
                vis_rgb = cv2.cvtColor(vis_frame, cv2.COLOR_BGR2RGB)
                st.image(vis_rgb, caption=f"Detected Region: {detected_crop or 'Full Frame'}", use_container_width=True)
            st.success("Slide region analyzed successfully!")
        except Exception as e:
            st.error(f"Crop preview failed: {e}")

# Start Processing
start_scan_btn = st.button("🚀 Start Slide Extraction", type="primary")

if start_scan_btn:
    if not video_source:
        st.warning("Please provide a YouTube URL or local file path.")
    else:
        st.session_state.export_ready = False
        config = SlideGrabConfig(
            input_source=video_source,
            output_dir=Path("./output"),
            cache_dir=Path("./cache"),
            quick_test_minutes=test_minutes if quick_test else None,
            sample_interval=sample_interval,
            stability_seconds=stability_sec,
            ssim_threshold=ssim_threshold,
            phash_threshold=phash_thresh,
            auto_crop=(crop_mode == "Auto-Detect"),
            manual_crop=manual_crop_val if crop_mode == "Manual (x,y,w,h)" else None,
            filter_faces=filter_faces,
            handle_build_ups=handle_buildups,
            live_writing_mode=live_writing,
            keep_revisits=keep_revisits,
            cookies_from_browser=cookies_browser
        )

        progress_container = st.container()
        with progress_container:
            st.info("Step 1/2: Preparing video source...")
            progress_bar = st.progress(0.0)
            metric_cols = st.columns(3)
            time_metric = metric_cols[0].empty()
            slides_metric = metric_cols[1].empty()
            speed_metric = metric_cols[2].empty()
            preview_slot = st.empty()

            try:
                def dl_callback(pct, msg):
                    progress_bar.progress(pct / 100.0)
                    time_metric.metric("Download", f"{pct:.1f}%")

                video_path, title, yt_id = get_video_source(
                    config.input_source,
                    config.cache_dir,
                    cookies_from_browser=config.cookies_from_browser,
                    progress_callback=dl_callback
                )
                st.session_state.video_path = video_path
                st.session_state.yt_id = yt_id

                # Resolve crop box
                crop_box = None
                if config.manual_crop:
                    crop_box = config.manual_crop
                elif config.auto_crop:
                    crop_box = detect_slide_region(
                        video_path,
                        sample_count=config.crop_sample_count,
                        max_duration_seconds=config.quick_test_minutes * 60 if config.quick_test_minutes else None
                    )
                st.session_state.crop_box = crop_box

                # Scan video
                st.info("Step 2/2: Extracting unique slides from video...")
                
                def scan_callback(pct, slide_cnt, curr_sec, latest_frame):
                    progress_bar.progress(min(1.0, pct / 100.0))
                    time_metric.metric("Video Time", format_timestamp(curr_sec))
                    slides_metric.metric("Slides Found", str(slide_cnt))
                    speed_metric.metric("Progress", f"{pct:.1f}%")
                    if latest_frame is not None:
                        rgb = cv2.cvtColor(latest_frame, cv2.COLOR_BGR2RGB)
                        preview_slot.image(rgb, caption=f"Latest Slide #{slide_cnt} ({format_timestamp(curr_sec)})", width=400)

                slides, slides_dir = process_video_stream(
                    video_path=video_path,
                    config=config,
                    crop_box=crop_box,
                    progress_callback=scan_callback
                )

                st.session_state.slides = slides
                st.session_state.slides_dir = slides_dir
                st.session_state.export_ready = True
                st.success(f"Extraction Complete! Discovered {len(slides)} unique slides.")

            except Exception as e:
                st.error(f"Error during extraction: {e}")

# Review & Export Section
if st.session_state.get("slides") and st.session_state.get("slides_dir"):
    slides_dir = Path(st.session_state.slides_dir)
    slides = st.session_state.slides

    st.markdown("---")
    st.header(f"🖼️ Slide Review & Export ({len(slides)} Slides)")
    st.write("Review the extracted slides below. You can delete duplicates or unwanted slides before exporting.")

    # Thumbnail Review Grid
    cols_per_row = 4
    to_delete = []

    for i in range(0, len(slides), cols_per_row):
        row_cols = st.columns(cols_per_row)
        for j in range(cols_per_row):
            idx = i + j
            if idx < len(slides):
                rec = slides[idx]
                img_path = slides_dir / rec.image_filename
                with row_cols[j]:
                    if img_path.is_file():
                        img = Image.open(img_path)
                        st.image(img, use_container_width=True)
                    time_str = format_timestamp(rec.timestamp_sec)
                    del_check = st.checkbox(f"Delete #{rec.index} ({time_str})", key=f"del_{rec.index}")
                    if del_check:
                        to_delete.append(rec)

    if to_delete:
        if st.button("🗑️ Delete Selected Slides", type="secondary"):
            st.session_state.slides = [s for s in slides if s not in to_delete]
            st.experimental_rerun()

    # Export Buttons
    st.markdown("### 📥 Generate & Download Artifacts")
    export_col1, export_col2, export_col3 = st.columns(3)

    out_dir = Path("./output")
    pdf_path = out_dir / "output.pdf"
    pptx_path = out_dir / "output.pptx"
    csv_path = out_dir / "timestamps.csv"

    # Always generate fresh exports when requested
    slide_images = [slides_dir / s.image_filename for s in st.session_state.slides]
    try:
        export_pdf(slide_images, pdf_path)
        export_pptx(st.session_state.slides, slides_dir, pptx_path, youtube_id=st.session_state.yt_id)
        export_timestamps_csv(st.session_state.slides, csv_path, youtube_id=st.session_state.yt_id)

        with export_col1:
            if pdf_path.is_file():
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        label="📄 Download PDF",
                        data=f,
                        file_name="lecture_slides.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

        with export_col2:
            if pptx_path.is_file():
                with open(pptx_path, "rb") as f:
                    st.download_button(
                        label="📊 Download PPTX (16:9)",
                        data=f,
                        file_name="lecture_slides.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        use_container_width=True
                    )

        with export_col3:
            if csv_path.is_file():
                with open(csv_path, "rb") as f:
                    st.download_button(
                        label="🕒 Download Timestamps CSV",
                        data=f,
                        file_name="timestamps.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
    except Exception as e:
        st.error(f"Export error: {e}")
