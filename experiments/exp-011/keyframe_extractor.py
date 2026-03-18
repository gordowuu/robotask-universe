#!/usr/bin/env python3
"""
keyframe_extractor.py
─────────────────────
Extract the most visually "interesting" frames from a robot demo MP4
and generate a self-contained HTML contact sheet.

Interestingness metric:
  - High pixel variance (lots of detail / motion)
  - Large frame-to-frame delta (moments of significant change)
  Combined as: score = alpha * variance + (1-alpha) * motion_delta

Requirements: pip install opencv-python (or opencv-python-headless)
Optional:     pip install numpy  (usually bundled with opencv)

Usage:
  python keyframe_extractor.py video.mp4 [options]

Options:
  --n N             Number of keyframes to extract (default: 20)
  --alpha FLOAT     Weight for variance vs motion (0=motion only, 1=variance only, default: 0.5)
  --output PATH     Output HTML file (default: <video_stem>_keyframes.html)
  --min-gap SEC     Minimum gap between selected frames in seconds (default: 0.5)
  --scale INT       Thumbnail width in pixels (default: 320)
  --title STRING    Title for the HTML page (default: video filename)
  --label STRING    Optional label / context text (model name, task, etc.)
"""

import argparse
import base64
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Graceful import
try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# ─────────────────────────────────────────────────────────────
# Core extraction
# ─────────────────────────────────────────────────────────────

def extract_keyframes(
    video_path: str,
    n: int = 20,
    alpha: float = 0.5,
    min_gap_sec: float = 0.5,
    thumb_width: int = 320,
) -> list[dict]:
    """
    Extract N most interesting keyframes from a video.

    Returns a list of dicts:
        { timestamp_sec, frame_num, score, variance, motion_delta, jpeg_b64 }
    """
    if not HAS_CV2:
        print("ERROR: opencv-python is required. Install with: pip install opencv-python-headless")
        sys.exit(1)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: Cannot open video: {video_path}")
        sys.exit(1)

    fps        = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration   = total_frames / fps
    width      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    min_gap_frames = int(min_gap_sec * fps)

    print(f"  Video: {Path(video_path).name}")
    print(f"  Resolution: {width}×{height}  FPS: {fps:.2f}  Duration: {duration:.2f}s  Frames: {total_frames}")

    # ── Pass 1: score every frame ──
    # Sub-sample to avoid memory issues on long videos
    step = max(1, total_frames // 2000)
    print(f"  Scoring every {step} frames…")

    frames_data = []   # { frame_num, variance, motion_delta }
    prev_gray = None

    frame_num = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_num % step == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            var = float(np.var(gray))

            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                motion = float(np.mean(diff))
            else:
                motion = 0.0

            frames_data.append({
                "frame_num":    frame_num,
                "variance":     var,
                "motion_delta": motion,
            })
            prev_gray = gray

        frame_num += 1

    cap.release()

    if not frames_data:
        print("ERROR: No frames extracted.")
        sys.exit(1)

    # Normalize scores to [0, 1]
    max_var    = max(f["variance"]     for f in frames_data) or 1.0
    max_motion = max(f["motion_delta"] for f in frames_data) or 1.0

    for f in frames_data:
        norm_var    = f["variance"]     / max_var
        norm_motion = f["motion_delta"] / max_motion
        f["score"]  = alpha * norm_var + (1.0 - alpha) * norm_motion

    # ── Pass 2: select top N with minimum gap ──
    sorted_frames = sorted(frames_data, key=lambda x: x["score"], reverse=True)
    selected = []
    used_nums = set()

    for f in sorted_frames:
        if len(selected) >= n:
            break
        # Check minimum gap
        if any(abs(f["frame_num"] - u) < min_gap_frames for u in used_nums):
            continue
        selected.append(f)
        used_nums.add(f["frame_num"])

    # Sort selected by time
    selected.sort(key=lambda x: x["frame_num"])

    # ── Pass 3: extract JPEG thumbnails ──
    print(f"  Extracting {len(selected)} thumbnail frames…")
    cap = cv2.VideoCapture(video_path)
    thumb_height = int(thumb_width * height / width)

    results = []
    for f in selected:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f["frame_num"])
        ret, frame = cap.read()
        if not ret:
            continue
        thumb = cv2.resize(frame, (thumb_width, thumb_height))
        _, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        b64 = base64.b64encode(buf).decode("ascii")

        results.append({
            "frame_num":    f["frame_num"],
            "timestamp_sec": f["frame_num"] / fps,
            "score":        f["score"],
            "variance":     f["variance"],
            "motion_delta": f["motion_delta"],
            "jpeg_b64":     b64,
        })

    cap.release()
    return results, { "fps": fps, "total_frames": total_frames, "duration": duration, "width": width, "height": height }


# ─────────────────────────────────────────────────────────────
# HTML generator
# ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #080810; --surf: #0e0e1c; --surf2: #151522; --border: #1e1e32;
      --text: #e0e0f4; --muted: #545470; --accent: #7c6cfc;
    }}
    body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; min-height: 100vh; }}
    header {{
      background: rgba(8,8,16,0.97); backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border); padding: 14px 24px;
      display: flex; align-items: center; gap: 14px; position: sticky; top: 0; z-index: 40;
    }}
    .logo {{ font-size: 18px; font-weight: 800; }}
    .logo span {{ color: var(--accent); }}
    .meta {{ font-size: 12px; color: var(--muted); }}
    .badge {{
      font-size: 11px; padding: 3px 9px; border-radius: 20px;
      background: rgba(124,108,252,0.12); border: 1px solid rgba(124,108,252,0.25); color: #c4b5fd;
    }}
    main {{ padding: 24px; max-width: 1400px; margin: 0 auto; }}
    .info-bar {{
      background: var(--surf); border: 1px solid var(--border); border-radius: 10px;
      padding: 14px 18px; margin-bottom: 20px;
      display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 14px;
    }}
    .info-item .label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }}
    .info-item .value {{ font-size: 14px; font-weight: 700; margin-top: 3px; }}
    .contact-sheet {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax({thumb_w}px, 1fr));
      gap: 10px;
    }}
    .kf-card {{
      background: var(--surf); border: 1px solid var(--border);
      border-radius: 8px; overflow: hidden; cursor: pointer;
      transition: all 0.15s;
    }}
    .kf-card:hover {{ border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }}
    .kf-card img {{ width: 100%; height: auto; display: block; }}
    .kf-meta {{ padding: 7px 10px; border-top: 1px solid var(--border); }}
    .kf-ts {{ font-size: 12px; font-weight: 700; color: #fff; font-variant-numeric: tabular-nums; }}
    .kf-score-bar {{ height: 3px; border-radius: 2px; margin-top: 5px; background: var(--border); }}
    .kf-score-fill {{ height: 100%; border-radius: 2px; }}
    .kf-detail {{ font-size: 10px; color: var(--muted); margin-top: 3px; display: flex; justify-content: space-between; }}
    .rank-badge {{
      position: relative; display: inline-block;
      font-size: 10px; font-weight: 700; padding: 1px 6px;
      border-radius: 4px; background: rgba(124,108,252,0.15);
      color: #c4b5fd; border: 1px solid rgba(124,108,252,0.25);
      margin-left: 4px;
    }}
    /* Lightbox */
    .lb {{ position: fixed; inset: 0; z-index: 100; background: rgba(0,0,0,0.92); backdrop-filter: blur(12px);
           display: flex; align-items: center; justify-content: center; padding: 24px;
           opacity: 0; pointer-events: none; transition: opacity 0.2s; }}
    .lb.open {{ opacity: 1; pointer-events: all; }}
    .lb-inner {{ background: var(--surf); border: 1px solid #262640; border-radius: 12px; overflow: hidden; max-width: 900px; width: 100%; }}
    .lb-inner img {{ width: 100%; height: auto; display: block; }}
    .lb-footer {{ padding: 12px 16px; display: flex; align-items: center; justify-content: space-between; border-top: 1px solid var(--border); }}
    .lb-close {{ position: fixed; top: 20px; right: 24px; background: #1a1a28; border: 1px solid #262640; color: var(--text); width: 34px; height: 34px; border-radius: 8px; font-size: 15px; cursor: pointer; display: flex; align-items: center; justify-content: center; z-index: 110; }}
  </style>
</head>
<body>
<header>
  <div>
    <div class="logo">Key<span>Frame</span>Extractor</div>
    <div class="meta">{label_text}</div>
  </div>
  <span class="badge">{n_frames} keyframes extracted</span>
  <span style="margin-left:auto;font-size:11px;color:var(--muted)">Generated {timestamp}</span>
</header>
<main>
  <div class="info-bar">
    <div class="info-item"><div class="label">Source</div><div class="value" style="font-size:12px">{source_file}</div></div>
    <div class="info-item"><div class="label">Duration</div><div class="value">{duration_str}</div></div>
    <div class="info-item"><div class="label">Resolution</div><div class="value">{resolution}</div></div>
    <div class="info-item"><div class="label">FPS</div><div class="value">{fps:.1f}</div></div>
    <div class="info-item"><div class="label">Total Frames</div><div class="value">{total_frames}</div></div>
    <div class="info-item"><div class="label">Keyframes</div><div class="value" style="color:var(--accent)">{n_frames}</div></div>
  </div>
  <div class="contact-sheet">
    {cards_html}
  </div>
</main>

<div class="lb" id="lb">
  <button class="lb-close" onclick="document.getElementById('lb').classList.remove('open')">✕</button>
  <div class="lb-inner">
    <img id="lb-img" src="" alt="">
    <div class="lb-footer">
      <div id="lb-info" style="font-size:13px"></div>
      <button onclick="document.getElementById('lb').classList.remove('open')"
        style="background:#1a1a28;border:1px solid #262640;color:#e0e0f4;padding:6px 14px;border-radius:7px;cursor:pointer;font-size:12px">
        Close
      </button>
    </div>
  </div>
</div>

<script>
  function openLB(src, info) {{
    document.getElementById('lb-img').src = src;
    document.getElementById('lb-info').innerHTML = info;
    document.getElementById('lb').classList.add('open');
  }}
  document.addEventListener('keydown', e => {{
    if (e.key === 'Escape') document.getElementById('lb').classList.remove('open');
  }});
  document.getElementById('lb').addEventListener('click', e => {{
    if (e.target === document.getElementById('lb')) document.getElementById('lb').classList.remove('open');
  }});
</script>
</body>
</html>"""


def score_color(score: float) -> str:
    """score in [0,1] → hex color red→yellow→green"""
    if score < 0.5:
        r = 240; g = int(score * 2 * 200 + 52); b = 52
    else:
        r = int((1 - (score - 0.5) * 2) * 240); g = 207; b = 52
    return f"rgb({r},{g},{b})"


def fmt_ts(sec: float) -> str:
    m = int(sec // 60)
    s = sec % 60
    return f"{m}:{s:05.2f}"


def generate_html(
    frames: list[dict],
    video_meta: dict,
    source_file: str,
    title: str,
    label: str,
    thumb_width: int,
) -> str:
    dur = video_meta["duration"]
    cards = []
    for i, f in enumerate(frames):
        score_pct = f["score"] * 100
        color = score_color(f["score"])
        data_uri = f"data:image/jpeg;base64,{f['jpeg_b64']}"
        ts = fmt_ts(f["timestamp_sec"])
        info_str = (
            f"<strong style='color:#fff'>{ts}</strong> "
            f"<span style='color:#888'>&nbsp;·&nbsp; frame {f['frame_num']} "
            f"&nbsp;·&nbsp; score {f['score']:.3f} "
            f"&nbsp;·&nbsp; var {f['variance']:.0f} "
            f"&nbsp;·&nbsp; Δ {f['motion_delta']:.2f}</span>"
        )
        cards.append(f"""
    <div class="kf-card" onclick="openLB('{data_uri}', '{info_str}')">
      <img src="{data_uri}" alt="Frame at {ts}" loading="lazy">
      <div class="kf-meta">
        <div style="display:flex;align-items:baseline;justify-content:space-between">
          <span class="kf-ts">{ts}</span>
          <span class="rank-badge">#{i+1}</span>
        </div>
        <div class="kf-score-bar">
          <div class="kf-score-fill" style="width:{score_pct:.1f}%;background:{color}"></div>
        </div>
        <div class="kf-detail">
          <span>var {f['variance']:.0f}</span>
          <span>Δ {f['motion_delta']:.2f}</span>
          <span style="color:{color}">s={f['score']:.3f}</span>
        </div>
      </div>
    </div>""")

    duration_str = fmt_ts(dur)
    label_text = label or Path(source_file).name

    return HTML_TEMPLATE.format(
        title=title,
        label_text=label_text,
        n_frames=len(frames),
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        source_file=Path(source_file).name,
        duration_str=duration_str,
        resolution=f"{video_meta['width']}×{video_meta['height']}",
        fps=video_meta["fps"],
        total_frames=video_meta["total_frames"],
        cards_html="\n".join(cards),
        thumb_w=thumb_width,
    )


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract keyframes from a robot demo MP4 and generate an HTML contact sheet."
    )
    parser.add_argument("video",              help="Input MP4 file path")
    parser.add_argument("--n",      type=int, default=20,    help="Number of keyframes (default: 20)")
    parser.add_argument("--alpha",  type=float, default=0.5, help="Variance weight 0-1 (default: 0.5)")
    parser.add_argument("--output",           default=None,  help="Output HTML file")
    parser.add_argument("--min-gap", type=float, default=0.5, help="Min gap between frames in sec (default: 0.5)")
    parser.add_argument("--scale",  type=int, default=320,   help="Thumbnail width px (default: 320)")
    parser.add_argument("--title",            default=None,  help="HTML page title")
    parser.add_argument("--label",            default=None,  help="Context label (model name, task, etc.)")
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"ERROR: File not found: {args.video}")
        sys.exit(1)

    stem   = Path(args.video).stem
    output = args.output or f"{stem}_keyframes.html"
    title  = args.title  or f"{stem} — Keyframes"

    print(f"\n[KeyframeExtractor]")
    frames, meta = extract_keyframes(
        args.video,
        n=args.n,
        alpha=args.alpha,
        min_gap_sec=args.min_gap,
        thumb_width=args.scale,
    )

    print(f"  Generating HTML contact sheet…")
    html = generate_html(frames, meta, args.video, title, args.label or "", args.scale)

    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(output) / 1024
    print(f"  ✓ Saved: {output}  ({size_kb:.0f} KB, {len(frames)} frames)")
    print(f"\n  Open in browser: file://{os.path.abspath(output)}\n")


if __name__ == "__main__":
    main()
