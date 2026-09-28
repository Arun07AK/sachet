"""Budgeted SerpApi access with reproducible offline recordings."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from .models import SearchCall


class BudgetExceeded(RuntimeError):
    """The live search budget is exhausted."""


class MissingFixture(FileNotFoundError):
    """A replay search has no matching recording."""


class NoApiKey(RuntimeError):
    """Live search needs a SerpApi key."""


class SerpGateway:
    def __init__(self, api_key=None, budget=10, cache_dir=".sachet-cache", replay_dir=None,
                 record_dir=None, on_call=None, defaults=None):
        self.api_key = api_key or os.getenv("SERPAPI_API_KEY") or os.getenv("SERPAPI_KEY")
        self.budget = budget
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.replay_dir = Path(replay_dir) if replay_dir is not None else None
        self.record_dir = Path(record_dir) if record_dir is not None else None
        self.on_call = on_call
        self.defaults = {"gl": "in", "hl": "en"} if defaults is None else defaults
        self.calls: list[SearchCall] = []
        self.seen_urls: set[str] = set()
        self._used = 0
        self.last_error: Exception | None = None

    @property
    def remaining(self):
        return max(0, self.budget - self._used)

    def _params(self, params):
        clean = {k: v for k, v in params.items() if k not in {"api_key", "output"}}
        engine = clean.get("engine", "google")
        allowed = {"google", "google_news", "google_jobs", "google_maps"}
        if engine in allowed:
            keys = ("hl",) if engine == "google_maps" else ("gl", "hl")
            for key in keys:
                if key in self.defaults:
                    clean.setdefault(key, self.defaults[key])
        return clean

    @staticmethod
    def filename(params):
        engine = params.get("engine", "google")
        digest = hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()
        return f"{engine}-{digest[:16]}.json"

    def _sanitize(self, value, metadata=False):
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                if key in {"api_key", "json_endpoint", "html_endpoint"}:
                    continue
                if metadata and isinstance(child, str) and (
                    self.api_key and self.api_key in child or "output=json" in child
                    or "output=html" in child
                ):
                    continue
                result[key] = self._sanitize(child, metadata or key == "search_metadata")
            return result
        if isinstance(value, list):
            return [self._sanitize(child, metadata) for child in value]
        return value

    def _record(self, directory, filename, params, response):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_text(json.dumps({"params": params, "response": response},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")

    def _urls(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                if (key.lower() in {"link", "website", "url"} and isinstance(child, str)
                        and urlparse(child).scheme in {"http", "https"}):
                    self.seen_urls.add(child)
                self._urls(child)
        elif isinstance(value, list):
            for child in value:
                self._urls(child)

    def search(self, params: dict) -> dict:
        clean = self._params(params)
        filename = self.filename(clean)
        start = time.monotonic()
        cached = False
        try:
            directory = self.replay_dir or self.cache_dir
            path = directory / filename if directory else None
            if path and path.exists():
                response = json.loads(path.read_text(encoding="utf-8"))["response"]
                cached = True
            elif self.replay_dir is not None:
                raise MissingFixture(f"Missing SerpApi fixture: {filename}")
            else:
                if self.remaining <= 0:
                    raise BudgetExceeded("SerpApi search budget used up")
                if not self.api_key:
                    raise NoApiKey("Set SERPAPI_API_KEY or SERPAPI_KEY for live searches")
                import serpapi

                self._used += 1
                response = self._sanitize(dict(serpapi.Client(api_key=self.api_key).search(clean)))
                if self.cache_dir:
                    self._record(self.cache_dir, filename, clean, response)
                if self.record_dir:
                    self._record(self.record_dir, filename, clean, response)
            self._urls(response)
            results = sum(len(v) for k, v in response.items() if k in {
                "organic_results", "news_results", "local_results", "jobs_results"} and isinstance(v, list))
            call = SearchCall(clean.get("engine", "google"), str(clean.get("q") or clean.get("k")
                              or next((v for k, v in clean.items() if k != "engine" and isinstance(v, str)), "")),
                              cached, results, round((time.monotonic() - start) * 1000))
        except Exception as exc:
            self.last_error = exc
            call = SearchCall(clean.get("engine", "google"), str(clean.get("q", "")), cached,
                              0, round((time.monotonic() - start) * 1000), False, str(exc))
            self.calls.append(call)
            if self.on_call:
                self.on_call(call)
            raise
        self.last_error = None
        self.calls.append(call)
        if self.on_call:
            self.on_call(call)
        return response
