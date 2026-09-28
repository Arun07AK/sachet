"""Command line interface for investigations and the local web app."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .envfile import load_dotenv
from .gateway import SerpGateway
from .planner import Agent
from .report import to_markdown, to_terminal


def examples_dir():
    root = Path(__file__).resolve().parents[2] / "examples"
    return root if root.is_dir() else Path(__file__).parent / "examples"


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(prog="sachet")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("file", nargs="?", default="-")
    check.add_argument("--budget", type=int, default=8)
    output = check.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true")
    output.add_argument("--markdown", action="store_true")
    check.add_argument("--replay")
    check.add_argument("--record")
    check.add_argument("--no-cache", action="store_true")
    check.add_argument("--llm", action="store_true")
    check.add_argument("--verbose", action="store_true")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--replay")
    commands.add_parser("examples")
    args = parser.parse_args(argv)
    if args.command == "examples":
        for path in sorted(examples_dir().glob("*.txt")):
            print(path.name)
        return 0
    if args.command == "serve":
        import uvicorn

        from .web import create_app

        uvicorn.run(create_app(replay_dir=args.replay), host=args.host, port=args.port)
        return 0
    if args.budget < 0:
        parser.error("budget must be zero or greater")
    if not args.replay and not (os.getenv("SERPAPI_API_KEY") or os.getenv("SERPAPI_KEY")):
        print("Set SERPAPI_API_KEY for live searches. Get a free key at "
              "https://serpapi.com/users/sign_up", file=sys.stderr)
        return 3
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        parser.error(str(exc))
    gateway = SerpGateway(budget=args.budget, replay_dir=args.replay, record_dir=args.record,
                          cache_dir=None if args.no_cache else ".sachet-cache")

    def progress(event):
        if event["type"] == "search":
            suffix = " (cached)" if event["cached"] else ""
            print(f"search {event['engine']}: {event['query']}{suffix}", file=sys.stderr)
        elif event["type"] == "step":
            print(f"step {event['name']}: {event['status']}", file=sys.stderr)
        elif args.verbose and event["type"] == "finding":
            print(f"finding: {event['title']}", file=sys.stderr)

    llm = None
    if args.llm:
        from .llm import LLM

        llm = LLM.from_env()
        if llm is None:
            print("LLM is not configured; using rules only.", file=sys.stderr)
    report = Agent(gateway).run(text, budget=args.budget, on_event=progress, llm=llm)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif args.markdown:
        print(to_markdown(report), end="")
    else:
        print(to_terminal(report, color=sys.stdout.isatty()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
