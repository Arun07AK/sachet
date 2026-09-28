"""Risk scoring and plain-language recommendations."""

from __future__ import annotations

from .models import WEIGHTS, Severity


def score(findings):
    return max(0, min(100, 20 + sum(WEIGHTS[f.severity] for f in findings)))


def verdict(value, findings):
    if any(f.severity == Severity.CRITICAL for f in findings):
        value = max(value, 70)
    if value >= 60:
        return "likely_scam", "Likely scam"
    if value >= 30:
        return "caution", "Proceed with caution"
    return "likely_genuine", "Looks genuine (verify anyway)"


def next_steps(report):
    steps = ["Do not pay any fee to get or keep a job."]
    if report.official_domain:
        steps += [f"Check the role on the official careers page at {report.official_domain}.",
                  f"Reply only to an address at {report.official_domain} after verification."]
    steps += [("If you lost money, call the National Cyber Crime Helpline 1930 or report at "
               "https://cybercrime.gov.in."), "Report fake job posts on the platform where they appear."]
    return steps


def summary_text(report):
    key = [f for f in report.findings if f.severity in {Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM}]
    if key:
        return f"This offer has a {report.score}/100 risk score. Key concerns: " + "; ".join(
            f.title.lower() for f in key[:2]) + ". Verify independently before sharing money or documents."
    return (f"This offer has a {report.score}/100 risk score. No strong warning signs were found. "
            "Verify the role with the company before sharing documents.")
