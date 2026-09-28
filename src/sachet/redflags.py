"""Deterministic warning signs in offer text."""

from __future__ import annotations

import re

from .domains import SHORTENERS, host_of, is_free_mail, registrable
from .models import Finding, Offer, Severity

_RULES = [
    ((r"(?:like videos|youtube likes?|rate (?:products?|hotels?)|prepaid tasks?|review tasks?|"
      r"crypto investment|invest in crypto|usdt|telegram tasks?|commission per task|task commission)"), Severity.CRITICAL,
     "Task scam wording", re.IGNORECASE),
    (r"\b(?:OTP|UPI\s*PIN|CVV)\b", Severity.CRITICAL, "Requests secret payment credentials",
     re.IGNORECASE),
    (r"\b(?:[Aa]adhaar|PAN card|PAN\b|[Bb]ank details|[Bb]ank account)", Severity.MEDIUM,
     "Requests sensitive identity or bank details", 0),
    (r"(?:no interview|direct joining|without interview|selected based on your profile)",
     Severity.HIGH, "Promises selection without an interview", re.IGNORECASE),
    ((r"(?:within \d+ hours|today only|limited seats|last chance|offer expires today|"
      r"urgent(?:ly)? (?:confirm|pay|reply))"),
     Severity.MEDIUM, "Pressures you to act quickly", re.IGNORECASE),
]


def text_findings(offer: Offer) -> list[Finding]:
    findings = []

    def add(severity, title, phrase):
        findings.append(Finding("text", severity, title, f'Matched: "{phrase}"'))

    if offer.fees or offer.fee_sentences:
        add(Severity.CRITICAL, "Asks you to pay before joining",
            offer.fee_sentences[0] if offer.fee_sentences else offer.fees[0].text)
    for pattern, severity, title, flags in _RULES:
        match = re.search(pattern, offer.raw_text, flags)
        if match:
            add(severity, title, match.group(0))
    free = next((e for e in offer.emails if is_free_mail(e.split("@")[-1])), None)
    if free and offer.company:
        add(Severity.HIGH, "Recruiter uses free mail while claiming a company", free)
    if offer.messaging_apps:
        add(Severity.MEDIUM, "Uses messaging apps as the main channel",
            ", ".join(offer.messaging_apps))
    role_text = " ".join(filter(None, [offer.role, offer.raw_text])).lower()
    for pay in offer.pay:
        unrealistic = ((pay.period == "day" and pay.amount_inr >= 1500 or
                        pay.period == "week" and pay.amount_inr >= 10000) and
                       re.search(r"work.from.home|part.time|data entry", role_text)
                       or pay.monthly_inr is not None and pay.monthly_inr >= 100000 and
                       re.search(r"intern|fresher|data entry", role_text))
        if unrealistic:
            add(Severity.HIGH, "Offered pay is unusually high", pay.text)
            break
    for url in [*offer.urls, *re.findall(r"\b(?:bit\.ly|tinyurl\.com|cutt\.ly|rb\.gy|t\.ly|shorturl\.at|is\.gd)/\S+", offer.raw_text, re.IGNORECASE)]:
        if registrable(host_of(url)) in SHORTENERS:
            add(Severity.LOW, "Uses a shortened URL", url)
            break
    return findings
