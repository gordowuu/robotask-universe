#!/usr/bin/env python3
"""
batch_diff.py
─────────────
Run pixel-diff analysis across a dataset of generated robot videos
vs reference originals. Outputs a ranked HTML report + CSV.

Metrics per video:
  - PSNR  (Peak Signal-to-Noise Ratio) — higher = more similar
  - Mean pixel diff (0–255)
  - Max pixel diff
  - % pixels changed above threshold
  - SSIM approximation (structural similarity, 0–1)

Requirements: pip install opencv-python numpy

Usage:
  python batch_diff.py [options]

  # Compare individual files:
  python batch_diff.py --ref original.mp4 --gen generated_1.mp4 generated_2.mp4

  # Compare folders (matched by name prefix):
  python batch_diff.py --ref-dir originals/ --gen-dir generated/ --match-prefix

  # Config JSON mode:
  python batch_diff.py --config pairs.json

pairs.json format:
  [{"ref": "orig_ep1.mp4", "gen": "cosmos_ep1_v1.mp4", "label": "ep1-bright-day"}, ...]

Options:
  --ref FILE            Single reference video
  --gen FILE [FILE...]  One or more generated videos to compare against ref
  --ref-dir DIR         Directory of reference videos
  --gen-dir DIR         Directory of generated videos
  --match-prefix        Match gen to ref by shared filename prefix
  --config JSON         JSON config file with explicit pairs
  --output PATH         Output HTML file (default: batch_diff_report.html)
  --csv PATH            Output CSV file (default: batch_diff_results.csv)
  --threshold INT       Pixel diff threshold for "changed" count (default: 20)
  --sample-frames INT   Frames to sample per video (default: 30)
  --scale INT           Resize to this width before comparison (default: 320)
  --title STRING        Report title
"""

import argparse
import base64
import csv
import json
import math
import os
import sys
from pathlib import Path
from datetime import datetime

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# ─────────────────────────────────────────────────────────────
# Metric computation
# ─────────────────────────────────────────────────────────────

def compute_metrics_pair(
    ref_path: str,
    gen_path: str,
    sample_frames: int = 30,
    threshold: int = 20,
    scale_w: int = 320,
) -> dict:
    """Compare two videos frame-by-frame, return aggregated metrics."""

    def open_video(path):
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return None, 0, 0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        return cap, n, fps

    cap_ref, n_ref, fps_ref = open_video(ref_path)
    cap_gen, n_gen, fps_gen = open_video(gen_path)

    if cap_ref is None:
        return {"error": f"Cannot open reference: {ref_path}"}
    if cap_gen is None:
        cap_ref.release()
        return {"error": f"Cannot open generated: {gen_path}"}

    n_frames = min(n_ref, n_gen, sample_frames * 10)
    step = max(1, n_frames // sample_frames)

    # Get resolution
    cap_ref.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ret, f = cap_ref.read()
    if not ret:
        return {"error": "Cannot read first frame of reference"}
    orig_h, orig_w = f.shape[:2]
    scale_h = int(scale_w * orig_h / orig_w)

    # Collect metrics
    psnr_vals, mean_diffs, max_diffs, changed_pcts, ssim_vals = [], [], [], [], []
    diff_frames = []  # up to 3 worst frames (jpeg base64)

    frame_idx = 0
    while True:
        ret_a, frame_a = cap_ref.read()
        ret_b, frame_b = cap_gen.read()
        if not ret_a or not ret_b:
            break
        if frame_idx % step == 0:
            # Resize
            fa = cv2.resize(frame_a, (scale_w, scale_h))
            fb = cv2.resize(frame_b, (scale_w, scale_h))

            # Convert to float
            fa_f = fa.astype(np.float32)
            fb_f = fb.astype(np.float32)
            diff = np.abs(fa_f - fb_f)
            diff_mean = diff.mean(axis=2)

            mean_d = float(diff_mean.mean())
            max_d  = float(diff_mean.max())
            changed_pct = float((diff_mean > threshold).sum() / diff_mean.size * 100)
            mse = float(((fa_f - fb_f) ** 2).mean())
            psnr = 10 * math.log10(255**2 / mse) if mse > 0 else float('inf')

            # SSIM approximation (simplified)
            mu_a = fa_f.mean(); mu_b = fb_f.mean()
            sig_a = fa_f.std(); sig_b = fb_f.std()
            sig_ab = float(((fa_f - mu_a) * (fb_f - mu_b)).mean())
            c1, c2 = (0.01 * 255)**2, (0.03 * 255)**2
            ssim = ((2*mu_a*mu_b + c1) * (2*sig_ab + c2)) / ((mu_a**2 + mu_b**2 + c1) * (sig_a**2 + sig_b**2 + c2))

            psnr_vals.append(psnr)
            mean_diffs.append(mean_d)
            max_diffs.append(max_d)
            changed_pcts.append(changed_pct)
            ssim_vals.append(ssim)

            # Save some diff images (worst frames)
            if len(diff_frames) < 3 and mean_d > (sum(mean_diffs)/max(len(mean_diffs),1)) * 1.2:
                diff_vis = np.clip(diff_mean * 4, 0, 255).astype(np.uint8)
                diff_color = cv2.applyColorMap(diff_vis, cv2.COLORMAP_JET)
                # Side by side: ref | diff | gen
                composite = np.concatenate([fa, diff_color, fb], axis=1)
                _, buf = cv2.imencode('.jpg', composite, [cv2.IMWRITE_JPEG_QUALITY, 75])
                diff_frames.append({
                    'frame': frame_idx,
                    'ts': round(frame_idx / fps_ref, 2),
                    'mean_d': round(mean_d, 2),
                    'b64': base64.b64encode(buf).decode(),
                })

        frame_idx += 1

    cap_ref.release()
    cap_gen.release()

    if not psnr_vals:
        return {"error": "No frames could be compared"}

    return {
        "ref":             ref_path,
        "gen":             gen_path,
        "n_frames_compared": len(psnr_vals),
        "psnr_mean":       round(sum(psnr_vals)/len(psnr_vals), 2),
        "psnr_min":        round(min(psnr_vals), 2),
        "mean_diff":       round(sum(mean_diffs)/len(mean_diffs), 2),
        "max_diff":        round(max(max_diffs), 2),
        "changed_pct":     round(sum(changed_pcts)/len(changed_pcts), 2),
        "ssim":            round(sum(ssim_vals)/len(ssim_vals), 4),
        "scale_w":         scale_w,
        "scale_h":         scale_h,
        "diff_frames":     diff_frames,
    }


def score_quality(metrics: dict) -> float:
    """Aggregate quality score (0–100, higher=more similar to ref)."""
    if "error" in metrics:
        return 0.0
    # Weighted: PSNR (capped at 50dB) + SSIM + (1 - changed%)
    psnr_score = min(metrics["psnr_mean"] / 50, 1.0) * 40
    ssim_score = max(0, metrics["ssim"]) * 40
    change_score = max(0, 1 - metrics["changed_pct"] / 100) * 20
    return round(psnr_score + ssim_score + change_score, 1)


# ─────────────────────────────────────────────────────────────
# HTML Report Generator
# ─────────────────────────────────────────────────────────────

HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #08080f; --surf: #0e0e1c; --surf2: #141422; --border: #1e1e32;
      --text: #e0e0f4; --muted: #545472; --accent: #7c6cfc; --green: #22c55e;
      --amber: #fbbf24; --red: #ef4444;
    }}
    body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; min-height: 100vh; }}
    header {{
      background: rgba(8,8,15,0.97); backdrop-filter: blur(14px);
      border-bottom: 1px solid var(--border); padding: 14px 28px;
      display: flex; align-items: center; gap: 14px; position: sticky; top: 0; z-index: 40;
    }}
    .logo {{ font-size: 18px; font-weight: 800; }}
    .logo span {{ color: var(--accent); }}
    .header-meta {{ font-size: 12px; color: var(--muted); }}
    main {{ padding: 28px; max-width: 1200px; margin: 0 auto; }}

    /* Stats bar */
    .stats-bar {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px,1fr)); gap: 10px; margin-bottom: 24px; }}
    .stat-box {{ background: var(--surf); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
    .stat-lbl {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.07em; }}
    .stat-val {{ font-size: 22px; font-weight: 800; margin-top: 4px; font-variant-numeric: tabular-nums; }}

    /* Leaderboard table */
    .lb-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ text-align: left; padding: 9px 12px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); border-bottom: 1px solid var(--border); cursor: pointer; user-select: none; }}
    th:hover {{ color: var(--text); }}
    td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
    tr:hover td {{ background: var(--surf2); }}
    .rank-cell {{ text-align: center; font-size: 14px; font-weight: 800; }}
    .score-big {{ font-size: 16px; font-weight: 800; font-variant-numeric: tabular-nums; }}
    .bar-cell {{ min-width: 120px; }}
    .bar-track {{ height: 6px; background: #1e1e32; border-radius: 3px; overflow: hidden; }}
    .bar-fill  {{ height: 100%; border-radius: 3px; }}

    /* Diff frame gallery */
    .diff-gallery {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }}
    .diff-thumb {{ cursor: pointer; border-radius: 5px; overflow: hidden; border: 1px solid #262640; }}
    .diff-thumb img {{ width: 200px; height: auto; display: block; }}
    .diff-thumb .ts {{ font-size: 10px; color: var(--muted); padding: 2px 5px; background: var(--surf2); text-align: center; }}

    /* Expandable row */
    .detail-row {{ display: none; }}
    .detail-row.open {{ display: table-row; }}
    .detail-cell {{ background: var(--surf2); padding: 14px 18px; border-bottom: 1px solid var(--border); }}

    /* Lightbox */
    .lb {{ position: fixed; inset: 0; z-index: 100; background: rgba(0,0,0,0.92); backdrop-filter: blur(12px);
           display: flex; align-items: center; justify-content: center; padding: 20px;
           opacity: 0; pointer-events: none; transition: opacity 0.2s; }}
    .lb.open {{ opacity: 1; pointer-events: all; }}
    .lb img {{ max-width: 100%; max-height: 90vh; border-radius: 8px; }}
    .lb-close {{ position: fixed; top: 20px; right: 20px; background: #1a1a2a; border: 1px solid #262640;
                  color: #eee; width: 32px; height: 32px; border-radius: 7px; font-size: 14px; cursor: pointer;
                  display: flex; align-items: center; justify-content: center; z-index: 110; }}
  </style>
</head>
<body>
<header>
  <div>
    <div class="logo">Batch<span>Diff</span></div>
    <div class="header-meta">{title} · {timestamp} · {n_pairs} pairs</div>
  </div>
</header>
<main>
"""

HTML_TAIL = """
<div class="lb" id="lb">
  <button class="lb-close" onclick="document.getElementById('lb').classList.remove('open')">✕</button>
  <img id="lb-img" src="" alt="">
</div>
<script>
  function openLB(src) {{
    document.getElementById('lb-img').src = 'data:image/jpeg;base64,' + src;
    document.getElementById('lb').classList.add('open');
  }}
  document.getElementById('lb').addEventListener('click', e => {{
    if (e.target === document.getElementById('lb')) document.getElementById('lb').classList.remove('open');
  }});
  document.addEventListener('keydown', e => {{
    if (e.key === 'Escape') document.getElementById('lb').classList.remove('open');
  }});
  function toggleDetail(id) {{
    const row = document.getElementById('detail-' + id);
    if (row) row.classList.toggle('open');
  }}
</script>
</main></body></html>"""


def score_color(score: float) -> str:
    pct = score / 100
    if pct < 0.5: return f"rgb(240,{int(pct*2*155+52)},52)"
    return f"rgb({int((1-(pct-0.5)*2)*240)},207,52)"


def generate_html_report(results: list[dict], title: str, ref_label: str) -> str:
    ranked = sorted(results, key=lambda r: r.get("quality_score", 0), reverse=True)
    n = len(ranked)
    errors = sum(1 for r in ranked if "error" in r)
    valid = [r for r in ranked if "error" not in r]

    avg_psnr = sum(r["psnr_mean"] for r in valid) / max(len(valid), 1)
    avg_ssim = sum(r["ssim"] for r in valid) / max(len(valid), 1)
    avg_score = sum(r["quality_score"] for r in valid) / max(len(valid), 1)
    best = ranked[0] if ranked and "error" not in ranked[0] else None

    stats_html = f"""
    <div class="stats-bar">
      <div class="stat-box"><div class="stat-lbl">Videos Compared</div><div class="stat-val" style="color:var(--accent)">{n}</div></div>
      <div class="stat-box"><div class="stat-lbl">Avg PSNR</div><div class="stat-val">{avg_psnr:.1f} dB</div></div>
      <div class="stat-box"><div class="stat-lbl">Avg SSIM</div><div class="stat-val">{avg_ssim:.3f}</div></div>
      <div class="stat-box"><div class="stat-lbl">Avg Quality</div><div class="stat-val" style="color:{score_color(avg_score)}">{avg_score:.1f}</div></div>
      <div class="stat-box"><div class="stat-lbl">Best</div><div class="stat-val" style="font-size:13px;margin-top:4px">{Path(best['gen']).name if best else '—'}</div></div>
      <div class="stat-box"><div class="stat-lbl">Errors</div><div class="stat-val" style="color:{'var(--red)' if errors else 'var(--muted)'}">{errors}</div></div>
    </div>"""

    rows_html = ""
    for i, r in enumerate(ranked):
        rank = i + 1
        medal = "🥇" if rank==1 else "🥈" if rank==2 else "🥉" if rank==3 else str(rank)
        gen_name = Path(r["gen"]).name if "gen" in r else "—"
        ref_name = Path(r.get("ref","")).name

        if "error" in r:
            rows_html += f"""<tr><td class="rank-cell">{rank}</td><td colspan="7" style="color:var(--red)">ERROR: {r['error']}</td></tr>"""
            continue

        score = r["quality_score"]
        sc = score_color(score)
        psnr_bar = min(r["psnr_mean"] / 50 * 100, 100)
        ssim_bar = max(0, r["ssim"]) * 100
        changed_bar = r["changed_pct"]

        diff_gallery_html = ""
        if r.get("diff_frames"):
            diff_gallery_html = f"""
              <br><div class="diff-gallery">
                {''.join(f'<div class="diff-thumb" onclick="openLB(\'{f["b64"]}\')"><img src="data:image/jpeg;base64,{f["b64"]}" alt="diff"><div class="ts">t={f["ts"]}s · Δ{f["mean_d"]}</div></div>' for f in r["diff_frames"])}
              </div>"""

        rows_html += f"""
          <tr onclick="toggleDetail('{i}')">
            <td class="rank-cell">{medal}</td>
            <td><div style="font-size:13px;font-weight:700;color:#fff">{gen_name}</div>
                <div style="font-size:11px;color:var(--muted)">vs {ref_name}</div></td>
            <td class="score-big" style="color:{sc}">{score}</td>
            <td><div class="bar-cell">
              <div style="font-size:11px;color:var(--muted);margin-bottom:2px">{r["psnr_mean"]:.1f} dB</div>
              <div class="bar-track"><div class="bar-fill" style="width:{psnr_bar:.1f}%;background:{sc}"></div></div>
            </div></td>
            <td><div style="font-size:11px;color:var(--muted);margin-bottom:2px">{r["ssim"]:.3f}</div>
                <div class="bar-track"><div class="bar-fill" style="width:{ssim_bar:.1f}%;background:{sc}"></div></div></td>
            <td style="font-size:12px;color:var(--muted)">{r["mean_diff"]:.1f}</td>
            <td style="font-size:12px;color:var(--muted)">{r["changed_pct"]:.1f}%</td>
            <td style="font-size:11px;color:var(--muted)">{r["n_frames_compared"]} frames</td>
          </tr>
          <tr class="detail-row" id="detail-{i}">
            <td class="detail-cell" colspan="8">
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;font-size:12px">
                <div><div style="font-weight:700;color:#fff;margin-bottom:4px">Full Metrics</div>
                  PSNR mean: {r["psnr_mean"]} dB<br>PSNR min: {r["psnr_min"]} dB<br>
                  SSIM: {r["ssim"]}<br>Mean diff: {r["mean_diff"]}<br>
                  Max diff: {r["max_diff"]}<br>Changed pixels: {r["changed_pct"]}%</div>
                <div><div style="font-weight:700;color:#fff;margin-bottom:4px">Files</div>
                  Gen: {r["gen"]}<br>Ref: {r["ref"]}<br>
                  Scale: {r.get("scale_w","?")}×{r.get("scale_h","?")}</div>
                <div><div style="font-weight:700;color:#fff;margin-bottom:4px">Diff Frames (click to expand)</div>
                  {diff_gallery_html}</div>
              </div>
            </td>
          </tr>"""

    table_html = f"""
    <div class="lb-wrap">
      <table>
        <thead><tr>
          <th>#</th><th>Video</th><th>Quality Score</th><th>PSNR</th><th>SSIM</th>
          <th>Mean Diff</th><th>Changed %</th><th>Frames</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>"""

    return (
        HTML_HEAD.format(title=title, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"), n_pairs=n) +
        stats_html + table_html + HTML_TAIL
    )


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def build_pairs(args) -> list[tuple[str, str, str]]:
    """Returns list of (ref_path, gen_path, label)"""
    pairs = []

    if args.config:
        with open(args.config) as f:
            data = json.load(f)
        for item in data:
            pairs.append((item["ref"], item["gen"], item.get("label", Path(item["gen"]).stem)))

    elif args.ref and args.gen:
        for gen in args.gen:
            pairs.append((args.ref, gen, Path(gen).stem))

    elif args.ref_dir and args.gen_dir:
        ref_files = {p.stem: p for p in Path(args.ref_dir).glob("*.mp4")}
        for gen_file in Path(args.gen_dir).glob("*.mp4"):
            if args.match_prefix:
                # Match by shared prefix up to first underscore
                prefix = gen_file.stem.split("_")[0]
                ref = next((v for k, v in ref_files.items() if k.startswith(prefix)), None)
            else:
                ref = ref_files.get(gen_file.stem)
            if ref:
                pairs.append((str(ref), str(gen_file), gen_file.stem))

    return pairs


def main():
    parser = argparse.ArgumentParser(description="Batch pixel-diff analysis for generated vs reference robot videos.")
    parser.add_argument("--ref",          help="Single reference video")
    parser.add_argument("--gen",          nargs="+", help="Generated video(s)")
    parser.add_argument("--ref-dir",      help="Directory of reference videos")
    parser.add_argument("--gen-dir",      help="Directory of generated videos")
    parser.add_argument("--match-prefix", action="store_true")
    parser.add_argument("--config",       help="JSON pairs config file")
    parser.add_argument("--output",       default="batch_diff_report.html")
    parser.add_argument("--csv",          default="batch_diff_results.csv")
    parser.add_argument("--threshold",    type=int, default=20)
    parser.add_argument("--sample-frames", type=int, default=30)
    parser.add_argument("--scale",        type=int, default=320)
    parser.add_argument("--title",        default="Batch Diff Report")
    args = parser.parse_args()

    if not HAS_CV2:
        print("ERROR: opencv-python required. pip install opencv-python-headless")
        sys.exit(1)

    pairs = build_pairs(args)
    if not pairs:
        print("ERROR: No video pairs found. Check --ref/--gen or --config.")
        print("  Example: python batch_diff.py --ref original.mp4 --gen generated_1.mp4 generated_2.mp4")
        sys.exit(1)

    print(f"\n[BatchDiff] {len(pairs)} pairs to compare")
    print(f"  Threshold: {args.threshold}  Sample frames: {args.sample_frames}  Scale: {args.scale}px\n")

    results = []
    for i, (ref, gen, label) in enumerate(pairs):
        print(f"  [{i+1}/{len(pairs)}] {Path(gen).name} vs {Path(ref).name}")
        metrics = compute_metrics_pair(ref, gen, args.sample_frames, args.threshold, args.scale)
        metrics["label"] = label
        if "error" not in metrics:
            metrics["quality_score"] = score_quality(metrics)
            print(f"    PSNR={metrics['psnr_mean']:.1f}dB  SSIM={metrics['ssim']:.3f}  Quality={metrics['quality_score']}")
        else:
            metrics["quality_score"] = 0
            print(f"    ERROR: {metrics['error']}")
        results.append(metrics)

    # Sort by quality score
    results.sort(key=lambda r: r.get("quality_score", 0), reverse=True)

    # Write HTML
    html = generate_html_report(results, args.title, args.ref or "")
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  ✓ HTML report: {args.output}  ({os.path.getsize(args.output)//1024} KB)")

    # Write CSV
    valid = [r for r in results if "error" not in r]
    if valid:
        cols = ["label","ref","gen","quality_score","psnr_mean","psnr_min","ssim","mean_diff","max_diff","changed_pct","n_frames_compared"]
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(valid)
        print(f"  ✓ CSV: {args.csv}  ({len(valid)} rows)")

    print(f"\n  Best: {Path(results[0]['gen']).name} — quality {results[0]['quality_score']}\n")


if __name__ == "__main__":
    main()
