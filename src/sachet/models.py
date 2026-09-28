"""Plain data types shared by the extractor, the checks, the planner and the renderers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    POSITIVE = "positive"


# Points added to the risk score for each finding. Positive evidence lowers the score.
WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 45,
    Severity.HIGH: 22,
    Severity.MEDIUM: 10,
    Severity.LOW: 4,
    Severity.INFO: 0,
    Severity.POSITIVE: -12,
}


@dataclass
class Source:
    title: str
    url: str
    engine: str = ""
    snippet: str = ""


@dataclass
class Finding:
    check: str
    severity: Severity
    title: str
    detail: str
    sources: list[Source] = field(default_factory=list)
    origin: str = "rules"  # "rules" (deterministic) or "llm" (agent follow-up)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class Money:
    text: str
    amount_inr: float
    period: str  # "month", "year", "day", "week", "hour", "once"

    @property
    def monthly_inr(self) -> float | None:
        factor = {"month": 1, "year": 1 / 12, "day": 26, "week": 4.33, "hour": 208}.get(self.period)
        return None if factor is None else self.amount_inr * factor


@dataclass
class Offer:
    """Entities pulled out of the pasted offer text."""

    raw_text: str
    company: str | None = None
    role: str | None = None
    city: str | None = None
    address: str | None = None
    emails: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    pay: list[Money] = field(default_factory=list)
    fees: list[Money] = field(default_factory=list)
    fee_sentences: list[str] = field(default_factory=list)
    messaging_apps: list[str] = field(default_factory=list)

    @property
    def email_domains(self) -> list[str]:
        return sorted({e.rsplit("@", 1)[1].lower() for e in self.emails})

    @property
    def offered_monthly_inr(self) -> float | None:
        values = [m.monthly_inr for m in self.pay if m.monthly_inr]
        return max(values) if values else None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["email_domains"] = self.email_domains
        d["offered_monthly_inr"] = self.offered_monthly_inr
        return d


@dataclass
class SearchCall:
    engine: str
    query: str
    cached: bool
    results: int
    ms: int
    ok: bool = True
    error: str = ""


@dataclass
class Report:
    offer: Offer
    findings: list[Finding]
    score: int
    verdict: str
    verdict_label: str
    official_domain: str | None
    calls: list[SearchCall]
    next_steps: list[str]
    summary: str
    mode: str = "rules"
    budget: int = 0
    dropped_llm_findings: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "verdict_label": self.verdict_label,
            "score": self.score,
            "summary": self.summary,
            "official_domain": self.official_domain,
            "mode": self.mode,
            "budget": self.budget,
            "dropped_llm_findings": self.dropped_llm_findings,
            "searches_used": sum(1 for c in self.calls if not c.cached and c.ok),
            "offer": self.offer.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
            "calls": [asdict(c) for c in self.calls],
            "next_steps": self.next_steps,
        }
