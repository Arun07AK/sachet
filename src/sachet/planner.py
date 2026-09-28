"""Adaptive investigation plan for a pasted job offer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import checks, domains, scoring
from .extract import extract
from .gateway import BudgetExceeded, SerpGateway
from .models import Finding, Offer, Report, Severity
from .redflags import text_findings
from .tools import build_tools


@dataclass
class Investigation:
    offer: Offer
    tools: Any
    gateway: SerpGateway
    findings: list[Finding] = field(default_factory=list)
    official_domain: str | None = None
    advisory_domains: set[str] = field(default_factory=set)
    footprint_size: str = "none"
    impersonation_risk: bool = False
    steps: list[dict] = field(default_factory=list)
    on_event: Any = None
    suspicious_domains: set[str] = field(default_factory=set)

    def emit(self, event):
        if self.on_event:
            self.on_event(event)

    def add_findings(self, findings):
        for finding in findings:
            self.findings.append(finding)
            self.emit({"type": "finding", **finding.to_dict()})


class Agent:
    def __init__(self, gateway=None):
        self.gateway = gateway
        self.last_investigation: Investigation | None = None

    def run(self, text_or_offer, budget=8, on_event=None, llm=None) -> Report:
        offer = text_or_offer if isinstance(text_or_offer, Offer) else extract(text_or_offer)
        if llm and hasattr(llm, "refine"):
            refined = llm.refine(offer)
            if isinstance(refined, Offer):
                offer = refined
        gateway = self.gateway or SerpGateway(budget=budget if budget is not None else 8)
        if self.gateway is not None and budget is not None:
            gateway.budget = budget
        old_callback = gateway.on_call

        def searched(call):
            if old_callback:
                old_callback(call)
            if on_event:
                on_event({"type": "search", "engine": call.engine, "query": call.query,
                          "cached": call.cached})

        gateway.on_call = searched
        ctx = Investigation(offer, build_tools(gateway), gateway, on_event=on_event)
        self.last_investigation = ctx
        ctx.emit({"type": "extracted", "offer": offer.to_dict()})
        plan = ["text", "footprint", "domain_consistency", "scam_reports", "contact_trace",
                "office_maps", "job_listing", "news"]
        reasons = {"text": "Check offer wording", "footprint": "Find the company online",
                   "domain_consistency": "Compare recruiter and company domains",
                   "scam_reports": "Look for public complaints", "contact_trace": "Trace contact details",
                   "office_maps": "Check the stated office", "job_listing": "Check public job listings",
                   "news": "Check news reports", "domain_probe": "Investigate a suspicious domain"}
        search_steps = {"footprint", "scam_reports", "contact_trace", "office_maps",
                        "job_listing", "news", "domain_probe"}
        replanned = set()
        done = set()
        index = 0
        while index < len(plan):
            name = plan[index]
            index += 1
            if name in done:
                continue
            done.add(name)
            reason = reasons[name]
            missing = None
            if name in {"footprint", "scam_reports", "news"} and not offer.company:
                missing = "company unknown"
            elif name == "domain_consistency" and not ctx.official_domain:
                missing = "official domain unknown"
            elif name == "contact_trace" and not (offer.phones or any(
                    domains.is_free_mail(d) for d in offer.email_domains)):
                missing = "no phone or free-mail contact"
            elif name == "office_maps" and not (offer.company and (offer.address or offer.city)):
                missing = "company and address or city required"
            elif name == "job_listing" and not (offer.company and offer.role):
                missing = "company and role required"
            elif name == "domain_probe" and not ctx.suspicious_domains:
                missing = "no suspicious domain"
            if not missing and name in search_steps and gateway.replay_dir is None and gateway.remaining <= 0:
                missing = "search budget used up"
            status = "done"
            if missing:
                status = "skipped"
                reason = missing
            else:
                try:
                    if name == "text":
                        found = text_findings(offer)
                    elif name == "domain_probe":
                        found = checks.domain_probe(ctx, min(ctx.suspicious_domains))
                    else:
                        found = getattr(checks, name)(ctx)
                    ctx.add_findings(found)
                except BudgetExceeded:
                    status, reason = "skipped", "search budget used up"
                except (RuntimeError, ValueError, OSError) as exc:
                    status, reason = "failed", str(exc)
            step = {"name": name, "reason": reason, "status": status,
                    "added_by": "replan" if name in replanned else "plan"}
            ctx.steps.append(step)
            ctx.emit({"type": "step", **step, "searches_left": gateway.remaining})
            if name == "text" and not offer.company:
                corp = next((d for d in offer.email_domains if not domains.is_free_mail(d)), None)
                if corp:
                    offer.company = domains.label(corp).replace("-", " ").title()
            if name == "footprint" and ctx.footprint_size == "none" and "contact_trace" in plan[index:]:
                plan.remove("contact_trace")
                plan.insert(index, "contact_trace")
                replanned.add("contact_trace")
            if name == "footprint" and not ctx.official_domain:
                offered_domains = set(offer.email_domains)
                offered_domains.update(domains.registrable(url) for url in offer.urls)
                ctx.suspicious_domains.update(
                    d for d in offered_domains if d and not domains.is_free_mail(d)
                    and not domains.is_third_party(d)
                )
                if ctx.suspicious_domains and "domain_probe" not in plan[index:]:
                    plan.insert(index, "domain_probe")
                    reasons["domain_probe"] = "official site not found, probing recruiter domain"
                    replanned.add("domain_probe")
            if (name == "domain_consistency" and ctx.suspicious_domains
                    and "domain_probe" not in plan[index:] and "domain_probe" not in done):
                plan.insert(index, "domain_probe")
                replanned.add("domain_probe")
            if name == "scam_reports" and ctx.impersonation_risk and "contact_trace" in plan[index:]:
                matched = any(f.check == "domain_consistency" and f.severity == Severity.POSITIVE
                              for f in ctx.findings)
                if not matched:
                    plan.remove("contact_trace")
                    plan.insert(index, "contact_trace")
                    replanned.add("contact_trace")
        dropped = 0
        if llm and hasattr(llm, "investigate"):
            try:
                extra = llm.investigate(ctx) or []
                for finding in extra:
                    if not isinstance(finding, Finding):
                        continue
                    if not finding.sources or any(source.url not in gateway.seen_urls
                                                  for source in finding.sources):
                        dropped += 1
                        continue
                    if finding.severity == Severity.CRITICAL:
                        finding.severity = Severity.HIGH
                    finding.origin = "llm"
                    ctx.add_findings([finding])
            except BudgetExceeded:
                pass
        value = scoring.score(ctx.findings)
        label, human = scoring.verdict(value, ctx.findings)
        if label == "likely_scam" and value < 70 and any(
                f.severity == Severity.CRITICAL for f in ctx.findings):
            value = 70
        report = Report(offer, ctx.findings, value, label, human, ctx.official_domain,
                        gateway.calls, [], "", "llm" if llm else "rules", gateway.budget)
        report.dropped_llm_findings = dropped
        report.next_steps = scoring.next_steps(report)
        report.summary = scoring.summary_text(report)
        if llm and hasattr(llm, "summarize"):
            summary = llm.summarize(report)
            if isinstance(summary, str) and summary.strip():
                report.summary = summary
        ctx.emit({"type": "report", "report": report.to_dict()})
        gateway.on_call = old_callback
        return report
