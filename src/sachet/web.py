"""FastAPI app for streaming local investigations."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .cli import examples_dir
from .gateway import SerpGateway
from .planner import Agent

_STATIC = Path(__file__).parent / "static"


class InvestigationRequest(BaseModel):
    text: str = Field(min_length=1)
    budget: int | None = Field(default=None, ge=0, le=100)
    use_llm: bool = False


def create_app(replay_dir=None, budget=8):
    app = FastAPI(title="Sachet")
    @app.get("/")
    async def index():
        return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/static/{filename}")
    async def static(filename: str):
        if filename not in {"app.js", "style.css"}:
            return Response(status_code=404)
        media = "text/javascript" if filename.endswith(".js") else "text/css"
        return Response((_STATIC / filename).read_text(encoding="utf-8"), media_type=media)

    @app.get("/api/health")
    async def health():
        from .llm import LLM

        return {"ok": True, "live": bool(os.getenv("SERPAPI_API_KEY") or os.getenv("SERPAPI_KEY")),
                "replay": replay_dir is not None, "llm": LLM.from_env() is not None}

    @app.get("/api/examples")
    async def examples():
        return [{"name": path.stem, "text": path.read_text(encoding="utf-8")}
                for path in sorted(examples_dir().glob("*.txt"))]

    @app.post("/api/investigate")
    async def investigate(request: InvestigationRequest):
        events = Queue()
        chosen_budget = budget if request.budget is None else request.budget

        def worker():
            try:
                llm = None
                if request.use_llm:
                    from .llm import LLM

                    llm = LLM.from_env()
                gateway = SerpGateway(budget=chosen_budget, replay_dir=replay_dir,
                                      cache_dir=None if replay_dir else ".sachet-cache")
                Agent(gateway).run(request.text, budget=chosen_budget,
                                   on_event=events.put, llm=llm)
            except (RuntimeError, ValueError, OSError, KeyError) as exc:
                events.put({"type": "error", "message": str(exc)})
            finally:
                events.put(None)

        Thread(target=worker, daemon=True).start()

        async def stream():
            while True:
                try:
                    event = events.get_nowait()
                except Empty:
                    await asyncio.sleep(0.01)
                    continue
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    return app
