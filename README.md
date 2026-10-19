# 📑 SlideGrab

> **Rebuild clean, high-resolution slide presentations (PDF + PPTX) directly from video lectures.**  
> 100% Free, Local, and Open Source. No paid APIs. No subscriptions. Designed for 3 to 6+ hour long university and exam preparation lectures.

---

## ⚡ Key Highlights

- **Lossless Exports**: Generates pristine **PDF** (via `img2pdf`) and widescreen **16:9 PPTX** (via `python-pptx`) with full-bleed slide visuals.
- **Smart Build-up Detection**: Replaces progressive bullet builds and progressive handwriting with the final, complete slide.
- **Global Deduplication**: Avoids repeating slides when instructors jump back to earlier pages.
- **Auto Slide-Region Crop**: Automatically trims black letterboxing and browser window borders. Supports manual `(x, y, w, h)` overrides.
- **Video Timecodes & Jump Links**: Generates `timestamps.csv` and embeds clickable `https://youtu.be/...` jump links directly in PPTX slide speaker notes.
- **Memory-Safe & High Speed**: Uses streaming `cap.grab()` frame skipping to scan a 6-hour video in ~10–15 minutes on a standard laptop without exhausting RAM.
- **Two Interfaces**: Intuitive **Streamlit Web UI** (with thumbnail review grid) and a full-featured **CLI** for scripting.

---

## 📦 Installation

### 1. Prerequisites
- **Python 3.10 or higher**
- **FFmpeg** (automatically bundled via `imageio-ffmpeg`, or install system-wide):
  - **Windows**: `winget install Gyan.FFmpeg` or `choco install ffmpeg`
  - **macOS**: `brew install ffmpeg`
  - **Linux (Ubuntu/Debian)**: `sudo apt update && sudo apt install -y ffmpeg`

### 2. Setup
Clone this repository and install dependencies:

```bash
# Clone
git clone <your-repo-link>
cd slidegrab

# Create & activate a virtual environment
python -m venv .venv

# Windows:
.\.venv\Scripts\activate

# macOS / Linux:
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

---

## 🚀 Quick Usage

### Option A: Streamlit Web UI (Recommended for visual review)
Launch the interactive web interface locally:

```bash
streamlit run streamlit_app.py
```

---

## 🌐 Cloud Deployment

### 1. Vercel Deployment
This repository is configured for Vercel with `vercel.json` and a root `app.py` / `api/index.py` entrypoint.
- Connect your GitHub repository (`youtube-video-ppt`) on [Vercel](https://vercel.com).
- Click **Deploy**. Vercel will automatically build and host the SlideGrab web app.

> **Note on Vercel**: Serverless functions on Vercel have a 10-second timeout. For processing 3+ hour video lectures in the cloud without local execution, use **Streamlit Community Cloud** below.

### 2. Streamlit Community Cloud (100% Free, Persistent Compute)
- Go to [share.streamlit.io](https://share.streamlit.io/).
- Click **New App**, select your GitHub repository (`youtube-video-ppt`), set Main file path to `streamlit_app.py`, and click **Deploy**.
- You will get a permanent public URL (e.g. `https://youtube-video-ppt.streamlit.app`) with persistent WebSocket support and full multi-hour video extraction.

1. Paste your YouTube link (or local file path).
2. Click **Preview Crop** to verify slide boundary detection.
3. Click **Start Slide Extraction**.
4. In the **Thumbnail Review Grid**, inspect slides, delete any unwanted frames, and download your **PDF**, **PPTX**, and **timestamps.csv**.

---

### Option B: Command Line (CLI)

#### 1. Quick Test (Process only first 10 minutes)
```bash
python slidegrab.py "https://youtu.be/qp5a0uLS0bs" --quick-test 10 --out ./output_test
```

#### 2. Full Run on YouTube Lecture
```bash
python slidegrab.py "https://youtu.be/qp5a0uLS0bs" --out ./lecture_deck --interval 1.0 --stable 2.0
```

#### 3. Run on a Local Video File
```bash
python slidegrab.py "C:/Lectures/chemistry_part1.mp4" --out ./chem_slides
```

#### 4. Custom Crop (e.g., exclude webcam in bottom-right corner)
```bash
python slidegrab.py "https://youtu.be/qp5a0uLS0bs" --crop 0,0,1000,720
```

#### 5. Authenticated / Restricted Videos
If a video requires YouTube login (age-restricted or private):
```bash
python slidegrab.py "https://youtu.be/..." --cookies-from-browser chrome
# or
python slidegrab.py "https://youtu.be/..." --cookies ./cookies.txt
```

---

## 🎛️ Tuning Guide

| Scenario | What to Change | Why |
|---|---|---|
| **Too many duplicate slides** | Increase `--stable` to `3.0` or `4.0`<br>Decrease `--threshold` to `0.88` or `0.85` | Ensures transitions, hand gestures, and minor camera noise settle before saving. |
| **Slides are being missed** | Decrease `--stable` to `1.5`<br>Increase `--threshold` to `0.94` or `0.95`<br>Decrease `--interval` to `0.5` | Catches fast-paced slide transitions or slides shown only for a few seconds. |
| **Teacher walks in front of smartboard** | Enable `--live-writing`<br>Set `--threshold 0.85` | Treats handwriting and posture shifts as progressive updates rather than new slides. |
| **Webcam box or black bars present** | Use `--crop x,y,w,h` | Crops directly to the presentation canvas, ignoring the speaker's webcam box. |
| **Slides repeat when teacher navigates back** | Leave default (`--keep-revisits` off)<br>Decrease `--phash-thresh` to `4` | Discards repeated slides by checking global perceptual hash history. |

---

## ⚠️ Known Limitations

1. **Physical Obstruction**: If a teacher stands directly in front of the board covering equations or text, the video stream itself does not contain those covered pixels. SlideGrab extracts the clearest settled frame, but cannot digitally invent text hidden behind a physical body.
2. **Video Upload Resolution**: The extracted slide quality is bound to the source stream resolution (720p or 1080p). If a video was uploaded at 360p or 480p, text may have blur.
3. **Continuous Smooth Zoom/Panning**: If an instructor continuously zooms in and pans around a digital canvas without stopping for at least the `--stable` duration, SlideGrab will wait until the motion pauses before capturing.

---

## 📁 Output Structure

```
output/
├── slides/
│   ├── slide_001.png
│   ├── slide_002.png
│   └── ...
├── output.pdf             # Lossless, single-file presentation PDF
├── output.pptx            # 16:9 widescreen presentation with clickable timecode notes
├── timestamps.csv         # Spreadsheet of slide numbers, timecodes, and YouTube links
└── checkpoint.json        # Resumable progress tracking state
```
