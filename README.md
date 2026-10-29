# video-frames

Claude Code skill: read a video frame by frame. Timestamped key frames (scene cuts + even coverage),
contact sheets, speech transcript with timestamps (Groq Whisper), then a structured breakdown
(hook, timeline, on-screen text, style, audio, how to remake).

```bash
python scripts/frames.py "<video file or URL>" --out vf_out --lang ru
```

Needs ffmpeg/ffprobe; URLs need `yt-dlp`; transcript needs `GROQ_API_KEY`. Install: copy this folder
to `~/.claude/skills/video-frames`.
