"""Mix narration onto the screen recording, burn captions, write demo/out/demo.mp4."""
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
segs = json.loads((OUT / "segments.json").read_text())["segments"]
text = json.loads((HERE / "narration.json").read_text())
dur = json.loads((HERE / "audio" / "durations.json").read_text())
LEAD = 0.25


def ts(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


# captions: sentence-ish chunks, timed by character share of each clip
srt, n = [], 1
for g in segs:
    t0 = g["start"] + LEAD
    chunks = [c.strip() for c in re.split(r"(?<=[.:?!])\s+", text[g["name"]]) if c.strip()]
    total = sum(len(c) for c in chunks)
    t = t0
    for c in chunks:
        d = dur[g["name"]] * len(c) / total
        srt.append(f"{n}\n{ts(t)} --> {ts(t + d - 0.05)}\n{c}\n")
        n += 1
        t += d
(OUT / "captions.srt").write_text("\n".join(srt))

end = segs[-1]["end"]
inputs = ["-i", str(OUT / "raw.webm")]
filters = []
for i, g in enumerate(segs, start=1):
    inputs += ["-i", str(HERE / "audio" / f"{g['name']}.mp3")]
    ms = int((g["start"] + LEAD) * 1000)
    filters.append(f"[{i}:a]adelay={ms}|{ms},aresample=48000[a{i}]")
mix = "".join(f"[a{i}]" for i in range(1, len(segs) + 1))
filters.append(f"{mix}amix=inputs={len(segs)}:normalize=0,apad[aout]")
style = ("FontName=DejaVu Sans,FontSize=9,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,"
         "BorderStyle=4,Outline=0,Shadow=0,MarginV=6,MarginL=40,MarginR=40")
filters.append(f"[0:v]trim=0:{end:.2f},setpts=PTS-STARTPTS,subtitles={OUT / 'captions.srt'}:force_style='{style}',"
               f"format=yuv420p[vout]")
cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
       "-map", "[vout]", "-map", "[aout]", "-t", f"{end:.2f}", "-r", "25",
       "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", "-b:a", "160k",
       "-movflags", "+faststart", str(OUT / "demo.mp4")]
subprocess.run(cmd, check=True)
print("wrote", OUT / "demo.mp4")
