---
name: video-frames
description: Read and analyse a video frame by frame - pulls timestamped key frames at every scene cut plus even coverage, packs them into contact sheets, transcribes speech with timestamps, then breaks the video down (hook, structure by second, on-screen text, transitions, pace, audio). Use whenever the user shares a video file or a Reels/TikTok/YouTube/Shorts link and asks to watch, read, analyse, break down, copy the style of, or describe it - "посмотри видео", "разбери рилс", "что в этом ролике", "по кадрам", "videoni ko'r", "reelsni tahlil qil", "shunaqa video qil" - or needs a reference reel understood before making a similar one.
---

# Video frames

Claude can't watch video, but it can read images. This skill turns a video into
timestamped frames + contact sheets + a transcript, then you read them and write
the breakdown.

## 1. Extract

```bash
python -I <skill-dir>/scripts/frames.py "<file or URL>" --out <scratch>/vf_<name> [--lang uz|ru|en]
```

- URL (Instagram, TikTok, YouTube) needs `yt-dlp` (`pip install yt-dlp`); else ask for the file.
  Private/login-walled posts fail - ask the user to send the file.
- Speech → `transcript.txt` only when `GROQ_API_KEY` is set (Groq Whisper, free tier). No key → frames only, say so.
- Defaults: up to 36 frames, 480 px wide, sheets 4×3. Tune:
  - fast-cut reels / lots of text: `--max-frames 48 --scene 0.25`
  - long video (> 3 min): `--max-frames 60 --cols 5 --rows 4`
  - tiny on-screen text: `--width 720`
- Put the output in the scratchpad, not the user's project.

## 2. Read

1. `index.json` - duration, size, fps, scene cuts, and which frame/time is in which sheet cell.
2. Every `sheets/sheet_NN.jpg` with the Read tool - each cell is stamped `#n mm:ss`.
3. `frames/f_*.jpg` one by one only where you need detail (small text, UI, a logo, a face).
4. `transcript.txt` if present - line up speech with the frame times.

Don't invent what isn't visible. Between two sampled frames you don't know what happened -
say "between 0:04 and 0:06" instead of guessing; re-run with more frames if it matters.

## 3. Write the breakdown

Answer what the user asked. For a reference reel / "make one like this", use:

- **Format** - length, aspect, fps, how many cuts (cuts per 10 s = pace).
- **Hook (0-3 s)** - what's on screen, text, sound/speech, why it stops the scroll.
- **Structure by time** - table `time | on screen | text overlay | speech/sound`.
- **On-screen text** - verbatim, with times; font/colour/position style.
- **Visual style** - colours, footage vs screen recording vs motion graphics, captions style, transitions.
- **Audio** - speech summary or music feel (you can't hear music - say what the transcript shows, mark music as unknown).
- **CTA / ending**.
- **How to remake it** - concrete shot list for the user's own version.

Cite frame times (`0:12`) for every claim so the user can check.

## Notes

- Needs `ffmpeg`/`ffprobe` on PATH. Standard-library Python only, no pip packages.
- The script never uploads frames anywhere; only audio goes to Groq when a key is set.
