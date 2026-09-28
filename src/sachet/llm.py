"""Optional OpenAI-compatible chat client. Search citations are checked by the planner."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from urllib.parse import urlparse

import httpx

from .gateway import BudgetExceeded
from .models import Finding, Severity, Source


class LLM:
    def __init__(self, base_url="https://api.openai.com/v1", api_key=None,
                 model="gpt-4o-mini", transport=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = httpx.Client(transport=transport, timeout=60)

    @classmethod
    def from_env(cls):
        base = os.getenv("SACHET_LLM_BASE_URL", "https://api.openai.com/v1")
        key = os.getenv("SACHET_LLM_API_KEY")
        if not key and urlparse(base).hostname not in {"localhost", "127.0.0.1", "::1"}:
            return None
        return cls(base, key, os.getenv("SACHET_LLM_MODEL", "gpt-4o-mini"))

    def _chat(self, messages, tools=None):
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        else:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = self.client.post(f"{self.base_url}/chat/completions", json=payload,
                                    headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]

    @staticmethod
    def _json(message):
        value = json.loads(message.get("content") or "{}")
        return value if isinstance(value, dict) else {}

    def refine(self, offer):
        try:
            message = self._chat([
                {"role": "system", "content": "Extract only company, role, city, address. Reply as strict JSON."},
                {"role": "user", "content": offer.raw_text},
            ])
            fields = self._json(message)
            updates = {key: fields[key].strip() for key in ("company", "role", "city", "address")
                       if not getattr(offer, key) and isinstance(fields.get(key), str)
                       and fields[key].strip()}
            return replace(offer, **updates) if updates else offer
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            return offer

    def investigate(self, ctx):
        limit = min(3, ctx.gateway.remaining)
        messages = [
            {"role": "system", "content": ("You are a careful fraud investigator for Indian job "
             "offers. Use at most the allowed tool calls to close the most important open question. "
             "Reply with JSON: {\"findings\": [{\"severity\": \"high|medium|low|info|positive\", "
             "\"title\": str, \"detail\": str, \"source_urls\": [str]}]. "
             "Use only URLs in search results.")},
            {"role": "user", "content": json.dumps({"offer": ctx.offer.to_dict(),
             "findings": [f.to_dict() for f in ctx.findings], "searches_left": ctx.gateway.remaining,
             "max_tool_calls": limit}, ensure_ascii=False)},
        ]
        used = 0
        try:
            for _ in range(6):
                message = self._chat(messages, ctx.tools.openai_tool_schemas() if used < limit else None)
                calls = message.get("tool_calls") or []
                if not calls:
                    findings = self._json(message).get("findings", [])
                    result = []
                    for item in findings if isinstance(findings, list) else []:
                        if not isinstance(item, dict) or item.get("severity") not in {
                            "high", "medium", "low", "info", "positive"}:
                            continue
                        urls = item.get("source_urls", [])
                        if not isinstance(urls, list):
                            continue
                        sources = [Source(ctx.gateway.url_titles.get(url, url), url)
                                   for url in urls if isinstance(url, str)]
                        result.append(Finding("agent", Severity(item["severity"]),
                                              str(item.get("title", "Finding")),
                                              str(item.get("detail", "")), sources, "llm"))
                    return result
                messages.append(message)
                for call in calls:
                    # Every tool call id must get a reply, even past the limit.
                    if used >= limit:
                        output = json.dumps({"error": "tool call limit reached, answer now"})
                    else:
                        function = call.get("function", {})
                        args = json.loads(function.get("arguments") or "{}")
                        used += 1
                        try:
                            output = ctx.tools.call_tool(function.get("name", ""), args)
                        except BudgetExceeded:
                            used = limit
                            output = json.dumps({"error": "search budget used up, answer now"})
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                     "content": output})
            return []
        except (BudgetExceeded, httpx.HTTPError, ValueError, KeyError, TypeError, IndexError,
                RuntimeError, OSError):
            return []

    def summarize(self, report):
        try:
            message = self._chat([
                {"role": "system", "content": "Write a plain 2 to 3 sentence summary grounded only in "
                 "the supplied findings. Reply as JSON with a summary string."},
                {"role": "user", "content": json.dumps({"score": report.score,
                 "verdict": report.verdict_label,
                 "findings": [f.to_dict() for f in report.findings]}, ensure_ascii=False)},
            ])
            summary = self._json(message).get("summary")
            return summary if isinstance(summary, str) and summary.strip() else report.summary
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            return report.summary
