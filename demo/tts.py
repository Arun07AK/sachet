"""Generate narration clips with edge-tts and record their durations."""
import asyncio
import json
import subprocess
from pathlib import Path

import edge_tts

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
VOICE = "en-IN-PrabhatNeural"


async def main():
    AUDIO.mkdir(exist_ok=True)
    text = json.loads((HERE / "narration.json").read_text())
    durations = {}
    for name, line in text.items():
        out = AUDIO / f"{name}.mp3"
        await edge_tts.Communicate(line, VOICE, rate="+4%").save(str(out))
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True)
        durations[name] = float(probe.stdout.strip())
        print(f"{name}: {durations[name]:.1f}s")
    (AUDIO / "durations.json").write_text(json.dumps(durations, indent=1))
    print("total", round(sum(durations.values()), 1))


asyncio.run(main())
