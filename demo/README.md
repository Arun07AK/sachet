# Demo video pipeline

1. `sachet serve --port 8000` with `SERPAPI_API_KEY` set (live mode).
2. `python demo/tts.py` writes narration clips (edge-tts) and `audio/durations.json`.
3. `python demo/record.py` drives the local app in a real browser (Playwright) and records it.
4. `python demo/assemble.py` mixes narration, burns captions and writes `demo/out/demo.mp4` (ffmpeg).

Needs `playwright` and `edge-tts` (`pip install playwright edge-tts`) plus system ffmpeg.
