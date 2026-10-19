import os
import csv
from pathlib import Path
from typing import List, Optional
import img2pdf
from pptx import Presentation
from pptx.util import Inches

from detector import SlideRecord

def format_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS."""
    secs = int(seconds)
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def export_pdf(image_paths: List[Path], output_pdf_path: Path) -> Path:
    """Creates a lossless PDF from slide images using img2pdf."""
    if not image_paths:
        raise ValueError("No slide images to export to PDF.")
    
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    # Convert string paths
    str_paths = [str(p) for p in image_paths if p.is_file()]
    if not str_paths:
        raise ValueError("None of the specified slide images exist on disk.")

    with open(output_pdf_path, "wb") as f:
        f.write(img2pdf.convert(str_paths))
    
    return output_pdf_path

def export_pptx(
    slides: List[SlideRecord],
    slides_dir: Path,
    output_pptx_path: Path,
    youtube_id: Optional[str] = None
) -> Path:
    """
    Exports slides to PPTX with:
    - 16:9 widescreen dimensions (13.333 x 7.5 inches)
    - Full-bleed image layout
    - Slide notes containing timestamp and clickable YouTube jump link
    """
    if not slides:
        raise ValueError("No slides to export to PPTX.")

    output_pptx_path.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    # 16:9 widescreen layout
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    for record in slides:
        img_path = slides_dir / record.image_filename
        if not img_path.is_file():
            continue

        slide = prs.slides.add_slide(blank_layout)
        # Full-bleed picture
        slide.shapes.add_picture(
            str(img_path),
            Inches(0), Inches(0),
            width=prs.slide_width,
            height=prs.slide_height
        )

        # Slide Notes
        notes_slide = slide.notes_slide
        tf = notes_slide.notes_text_frame
        timecode = format_timestamp(record.timestamp_sec)
        
        note_text = f"Slide {record.index}\nTimestamp: {timecode} ({int(record.timestamp_sec)}s)"
        if youtube_id:
            yt_link = f"https://youtu.be/{youtube_id}?t={int(record.timestamp_sec)}"
            note_text += f"\nJump to Video: {yt_link}"
            
        tf.text = note_text

    prs.save(str(output_pptx_path))
    return output_pptx_path

def export_timestamps_csv(
    slides: List[SlideRecord],
    output_csv_path: Path,
    youtube_id: Optional[str] = None
) -> Path:
    """Exports timestamps.csv mapping slide numbers to video timecodes."""
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Slide_Number", "Timestamp_Seconds", "Timecode", "YouTube_Link", "Image_File"])
        for record in slides:
            sec = int(record.timestamp_sec)
            timecode = format_timestamp(sec)
            yt_link = f"https://youtu.be/{youtube_id}?t={sec}" if youtube_id else ""
            writer.writerow([record.index, sec, timecode, yt_link, record.image_filename])
    return output_csv_path
