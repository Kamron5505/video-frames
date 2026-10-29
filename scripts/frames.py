#!/usr/bin/env python3
"""Turn a video into frames Claude can read: timestamped key frames, contact sheets, transcript.

    python frames.py <video file | URL> [--out DIR] [--max-frames 36] [--scene 0.3] [--width 480]
                     [--cols 4] [--rows 3] [--no-audio] [--lang uz]

Output DIR (default ./frames_<name>):
    sheets/sheet_01.jpg ...   grids of frames, each cell stamped with its time - read these first
    frames/f_007_00m12.4s.jpg single frames for close looks (on-screen text, UI, details)
    transcript.txt            speech with timestamps (Groq Whisper, needs GROQ_API_KEY) - optional
    index.json                video meta + every frame: time, why it was picked, file, sheet/cell
Needs ffmpeg/ffprobe on PATH; URLs need yt-dlp (`pip install yt-dlp`). Standard library only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def need(tool: str) -> None:
    if not shutil.which(tool):
        sys.exit(f"{tool} not found on PATH - install ffmpeg first")


def download(url: str, dest: Path) -> Path:
    ytdlp = [shutil.which("yt-dlp")] if shutil.which("yt-dlp") else [sys.executable, "-m", "yt_dlp"]
    probe = run([*ytdlp, "--version"], check=False)
    if probe.returncode != 0:
        sys.exit("URL given but yt-dlp is missing: pip install yt-dlp (or pass a local file)")
    dest.mkdir(parents=True, exist_ok=True)
    tmpl = str(dest / "source.%(ext)s")
    res = run([*ytdlp, "-f", "mp4/bv*+ba/b", "--merge-output-format", "mp4", "--no-playlist", "-o", tmpl, url],
              check=False)
    files = sorted(dest.glob("source.*"))
    if res.returncode != 0 or not files:
        sys.exit("download failed:\n" + (res.stderr or res.stdout)[-1500:])
    return files[0]


def probe(path: Path) -> dict:
    res = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    data = json.loads(res.stdout)
    v = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if not v:
        sys.exit("no video stream in " + str(path))
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    return {
        # video stream first: the container can run longer than the picture (audio tail)
        "duration": float(v.get("duration") or data["format"].get("duration") or 0),
        "width": int(v["width"]), "height": int(v["height"]), "fps": round(fps, 2),
        "has_audio": any(s.get("codec_type") == "audio" for s in data["streams"]),
    }


def scene_times(path: Path, threshold: float) -> list[float]:
    res = run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", f"select='gt(scene,{threshold})',showinfo",
               "-an", "-f", "null", "-"], check=False)
    return [float(t) for t in re.findall(r"pts_time:([0-9.]+)", res.stderr)]


def pick(duration: float, scenes: list[float], max_frames: int) -> list[tuple[float, str]]:
    """Scene cuts first, then even coverage; nothing closer than min_gap, capped at max_frames."""
    min_gap = max(0.4, duration / (max_frames * 3))
    chosen: list[tuple[float, str]] = []

    def add(t: float, why: str) -> None:
        t = min(max(t, 0.0), max(duration - 0.05, 0.0))
        if all(abs(t - c) >= min_gap for c, _ in chosen):
            chosen.append((t, why))

    add(0.0, "start")
    even = max(4, max_frames // 2)
    for i in range(even):
        add((i + 0.5) * duration / even, "even")
    for t in scenes:
        if len(chosen) >= max_frames:
            break
        add(t + 0.05, "scene cut")
    add(duration - 0.1, "end")
    chosen.sort()
    if len(chosen) > max_frames:  # thin evenly, keep first/last
        step = (len(chosen) - 1) / (max_frames - 1)
        chosen = [chosen[round(i * step)] for i in range(max_frames)]
    return chosen


def stamp(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):02d}m{s:04.1f}s"


def font_arg() -> str:
    for f in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if Path(f).exists():
            return "fontfile='" + f.replace(":", r"\:") + "':"
    return ""


def grab(path: Path, t: float, out: Path, width: int, label: str) -> bool:
    """Save one labelled frame at t; near the end step back until a frame decodes. False = none found."""
    text = label.replace(":", r"\:")
    draw = (f",drawtext={font_arg()}text='{text}':x=8:y=8:fontsize={max(16, width // 18)}:"
            "fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=6")
    for at in (t, t - 0.5, t - 1.5):
        if at < 0:
            continue
        base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.3f}", "-i", str(path),
                "-frames:v", "1", "-q:v", "3"]
        for vf in (f"scale={width}:-2{draw}", f"scale={width}:-2"):  # 2nd: ffmpeg without drawtext
            if run([*base, "-vf", vf, str(out)], check=False).returncode == 0 and out.exists():
                return True
    return False


def sheets(frames: list[Path], out_dir: Path, cols: int, rows: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    per = cols * rows
    made = []
    with tempfile.TemporaryDirectory() as tmp:
        for n in range(math.ceil(len(frames) / per)):
            chunk = frames[n * per:(n + 1) * per]
            for i, f in enumerate(chunk):
                shutil.copy(f, Path(tmp) / f"c_{n:02d}_{i:03d}.jpg")
            sheet = out_dir / f"sheet_{n + 1:02d}.jpg"
            r = math.ceil(len(chunk) / cols)
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", "1", "-start_number", "0",
                 "-i", str(Path(tmp) / f"c_{n:02d}_%03d.jpg"), "-frames:v", "1",
                 "-vf", f"tile={cols}x{r}:padding=6:margin=6:color=white", "-q:v", "3", str(sheet)])
            made.append(sheet)
    return made


def transcribe(path: Path, out: Path, lang: str | None) -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return "skipped: no GROQ_API_KEY"
    audio = out.with_suffix(".m4a")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "48k", str(audio)])
    boundary = uuid.uuid4().hex
    fields = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json"}
    if lang:
        fields["language"] = lang
    body = b"".join(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
                    for k, v in fields.items())
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.m4a\"\r\n"
             "Content-Type: audio/mp4\r\n\r\n").encode() + audio.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request("https://api.groq.com/openai/v1/audio/transcriptions", body, {
        "Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "video-frames/1.0"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=180))
    except Exception as exc:  # noqa: BLE001 - frames are still useful without speech
        return f"failed: {str(exc)[:200]}"
    finally:
        audio.unlink(missing_ok=True)
    lines = [f"[{stamp(s['start'])} - {stamp(s['end'])}] {s['text'].strip()}" for s in data.get("segments") or []]
    out.write_text("\n".join(lines) or data.get("text", ""), encoding="utf-8")
    return f"ok, {len(lines)} segments, language={data.get('language')}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="video file or URL (Instagram, YouTube, TikTok ... via yt-dlp)")
    ap.add_argument("--out", help="output dir (default ./frames_<name>)")
    ap.add_argument("--max-frames", type=int, default=36)
    ap.add_argument("--scene", type=float, default=0.3, help="scene-cut sensitivity 0..1 (lower = more cuts)")
    ap.add_argument("--width", type=int, default=480, help="frame width in px")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=3)
    ap.add_argument("--no-audio", action="store_true", help="skip the transcript")
    ap.add_argument("--lang", help="speech language hint for Whisper, e.g. uz, ru, en")
    a = ap.parse_args()
    need("ffmpeg"), need("ffprobe")

    is_url = re.match(r"^https?://", a.source) is not None
    name = re.sub(r"[^\w-]+", "_", Path(a.source.split("?")[0].rstrip("/")).stem or "video")[:40]
    out = Path(a.out or f"frames_{name}").resolve()
    out.mkdir(parents=True, exist_ok=True)
    video = download(a.source, out) if is_url else Path(a.source).resolve()
    if not video.exists():
        sys.exit(f"no such file: {video}")

    meta = probe(video)
    if meta["duration"] <= 0:
        sys.exit("could not read the video duration")
    cuts = scene_times(video, a.scene)
    picks = pick(meta["duration"], cuts, max(4, a.max_frames))

    fdir = out / "frames"
    if fdir.exists():
        shutil.rmtree(fdir)
    fdir.mkdir()
    width = min(a.width, meta["width"])
    files, kept = [], []
    for t, why in picks:
        i = len(files) + 1
        f = fdir / f"f_{i:03d}_{stamp(t)}.jpg"
        if grab(video, t, f, width, f"#{i} {stamp(t)}"):
            files.append(f)
            kept.append((t, why))
    picks = kept
    if not files:
        sys.exit("ffmpeg could not decode any frame from " + str(video))
    if (out / "sheets").exists():
        shutil.rmtree(out / "sheets")
    sheet_files = sheets(files, out / "sheets", a.cols, a.rows)

    speech = "skipped (--no-audio)" if a.no_audio else (
        transcribe(video, out / "transcript.txt", a.lang) if meta["has_audio"] else "no audio track")

    per = a.cols * a.rows
    index = {
        "source": a.source, "video": str(video), **meta, "scene_cuts": [round(t, 2) for t in cuts],
        "transcript": speech, "sheets": [str(s) for s in sheet_files],
        "frames": [{"n": i, "time": round(t, 2), "stamp": stamp(t), "why": why, "file": str(f),
                    "sheet": (i - 1) // per + 1, "cell": (i - 1) % per + 1}
                   for i, ((t, why), f) in enumerate(zip(picks, files), 1)],
    }
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"video   {meta['duration']:.1f}s {meta['width']}x{meta['height']} {meta['fps']}fps, "
          f"{len(cuts)} scene cuts")
    print(f"frames  {len(files)} -> {fdir}")
    print("sheets  " + ", ".join(str(s) for s in sheet_files))
    print(f"speech  {speech}")
    print(f"index   {out / 'index.json'}")


if __name__ == "__main__":
    main()
