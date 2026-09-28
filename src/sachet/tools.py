"""Search tools shared by deterministic checks and optional LLM investigation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from serpapi_search_tools import maps_search, news_search, web_search


@dataclass
class Tools:
    web: Any
    news: Any
    maps: Any
    gateway: Any

    def jobs(self, query: str, location: str = "India") -> dict:
        return self.gateway.search({"engine": "google_jobs", "q": query, "location": location})

    def _decode(self, function, *args, **kwargs) -> dict:
        self.gateway.last_error = None
        try:
            return json.loads(function(*args, **kwargs))
        except RuntimeError as exc:
            # serpapi-search-tools wraps client errors in a generic SerpApiSearchError;
            # surface the gateway's original error (budget, missing key, missing fixture).
            original = getattr(self.gateway, "last_error", None)
            if original is not None:
                raise original from exc
            raise

    def web_json(self, query: str) -> dict:
        return self._decode(self.web, query, "google")

    def news_json(self, query: str) -> dict:
        return self._decode(self.news, query)

    def maps_json(self, query: str, location: str | None = None) -> dict:
        return self._decode(self.maps, query, location=location)

    def openai_tool_schemas(self) -> list[dict]:
        specs = [
            ("web_search", "Search the web", False),
            ("news_search", "Search news", False),
            ("maps_search", "Search places", True),
            ("jobs_search", "Search public job listings", True),
        ]
        return [{"type": "function", "function": {"name": name, "description": desc,
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"}, **({"location": {"type": "string"}} if loc else {})},
                    "required": ["query"]}}} for name, desc, loc in specs]

    def call_tool(self, name: str, args: dict) -> str:
        query = args["query"]
        if name == "web_search":
            result = self.web_json(query)
        elif name == "news_search":
            result = self.news_json(query)
        elif name == "maps_search":
            result = self.maps_json(query, args.get("location"))
        elif name == "jobs_search":
            result = self.jobs(query, args.get("location", "India"))
        else:
            raise ValueError(f"Unknown tool: {name}")
        data = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(data) <= 6000:
            return data
        return json.dumps({"truncated": True, "preview": data[:5900]}, ensure_ascii=False)


def build_tools(gateway) -> Tools:
    common = {"provider": "function", "client": gateway, "response_format": "json",
              "mode": "full", "result_limit": 10}
    return Tools(web_search(**common, allowed_engines=["google"]), news_search(**common),
                 maps_search(**common), gateway)
