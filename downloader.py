import os
import re
import hashlib
from pathlib import Path
from typing import Optional, Tuple, Callable
import yt_dlp

try:
    import imageio_ffmpeg
    BUNDLED_FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    BUNDLED_FFMPEG = None

def get_ffmpeg_path() -> Optional[str]:
    """Return path to ffmpeg binary if available."""
    if BUNDLED_FFMPEG and os.path.exists(BUNDLED_FFMPEG):
        return BUNDLED_FFMPEG
    # Check system PATH
    from shutil import which
    sys_ffmpeg = which("ffmpeg")
    return sys_ffmpeg

def is_youtube_url(source: str) -> bool:
    """Check if the source string is a YouTube URL."""
    return bool(re.search(r'(youtube\.com|youtu\.be)', source, re.IGNORECASE))

def extract_youtube_id(url: str) -> Optional[str]:
    """Extract 11-char YouTube video ID."""
    match = re.search(r'(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})', url)
    return match.group(1) if match else None

def get_video_source(
    source: str,
    cache_dir: Path,
    max_height: int = 720,
    cookies_file: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None
) -> Tuple[Path, str, Optional[str]]:
    """
    Resolves input source to a local video file path.
    Returns: (local_video_path, title, youtube_id)
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. Local video file
    local_path = Path(source)
    if local_path.is_file():
        title = local_path.stem
        return local_path.resolve(), title, None

    if not is_youtube_url(source):
        raise FileNotFoundError(f"Input '{source}' is not a valid local file or YouTube URL.")

    # 2. YouTube URL
    yt_id = extract_youtube_id(source)
    file_prefix = yt_id if yt_id else hashlib.md5(source.encode()).hexdigest()[:12]
    
    # Check cache first
    existing = list(cache_dir.glob(f"{file_prefix}_*.mp4"))
    if not existing:
        existing = list(cache_dir.glob(f"{file_prefix}.mp4"))
    
    if existing:
        cached_file = existing[0]
        # Extract title from filename if format was {file_prefix}_{title}.mp4
        title = cached_file.stem.replace(f"{file_prefix}_", "") if f"{file_prefix}_" in cached_file.stem else cached_file.stem
        if progress_callback:
            progress_callback(100.0, f"Using cached video: {cached_file.name}")
        return cached_file.resolve(), title, yt_id

    # Configure yt-dlp
    ffmpeg_exe = get_ffmpeg_path()
    
    # Format selection: prefer mp4 video <= max_height, fallback to <=1080, then bestvideo
    format_str = (
        f"bestvideo[height<={max_height}][ext=mp4]/"
        f"bestvideo[height<={max_height}]/"
        f"bestvideo[height<=1080][ext=mp4]/"
        f"bestvideo[height<=1080]/"
        f"bestvideo/best"
    )

    out_template = str(cache_dir / f"{file_prefix}_%(title).100B.%(ext)s")

    ydl_opts = {
        'format': format_str,
        'outtmpl': out_template,
        'noplaylist': True,
        'quiet': False,
        'no_warnings': False,
    }

    if ffmpeg_exe:
        ydl_opts['ffmpeg_location'] = ffmpeg_exe

    if cookies_file and os.path.exists(cookies_file):
        ydl_opts['cookiefile'] = cookies_file
    elif cookies_from_browser:
        ydl_opts['cookiesfrombrowser'] = (cookies_from_browser,)

    def yt_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            if total > 0 and progress_callback:
                pct = (downloaded / total) * 100
                progress_callback(pct, f"Downloading: {pct:.1f}%")
        elif d['status'] == 'finished' and progress_callback:
            progress_callback(100.0, "Download completed. Processing stream...")

    ydl_opts['progress_hooks'] = [yt_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(source, download=True)
            video_title = info.get('title', file_prefix)
            # Find the actual downloaded file on disk
            downloaded_files = list(cache_dir.glob(f"{file_prefix}_*.*"))
            if downloaded_files:
                target_file = downloaded_files[0]
            else:
                target_file = cache_dir / f"{file_prefix}.mp4"
            
            return target_file.resolve(), video_title, yt_id
    except yt_dlp.utils.DownloadError as e:
        err_msg = str(e)
        if "Private video" in err_msg or "Sign in" in err_msg:
            raise RuntimeError(
                f"Video is restricted or private. Please provide cookies using "
                f"--cookies or --cookies-from-browser. Details: {err_msg}"
            )
        raise RuntimeError(f"yt-dlp failed to download video: {err_msg}")
