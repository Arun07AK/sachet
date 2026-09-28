"""Offline behavior tests using fictional search responses."""

from __future__ import annotations

from pathlib import Path

import pytest

from sachet import checks, domains, scoring
from sachet.extract import extract
from sachet.gateway import BudgetExceeded, MissingFixture, NoApiKey, SerpGateway
from sachet.models import Finding, Money, Offer, Severity, Source
from sachet.planner import Agent, Investigation
from sachet.redflags import text_findings
from sachet.tools import build_tools

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"
COMPANY = "Kavera Analytics Pvt Ltd"


def gateway():
    return SerpGateway(replay_dir=FIXTURES, cache_dir=None)


def context(offer=None):
    gw = gateway()
    offer = offer or Offer("", company=COMPANY, role="Analyst", city="Pune",
                           address="Office: Pune", emails=["hr@kavera-analytics.in"])
    return Investigation(offer, build_tools(gw), gw)


def test_extraction_money_phone_company():
    offer = extract("Company: Kavera Analytics Pvt Ltd\nRole: Analyst\nSalary ₹30,000 per month. "
                    "Pay registration fee ₹2,000. Call +91 98765 43210")
    assert offer.company == COMPANY
    assert offer.phones == ["+91 98765 43210"]
    assert offer.offered_monthly_inr == 30000
    assert offer.fees[0].amount_inr == 2000


def test_domains():
    assert domains.registrable("https://jobs.example.co.in/a") == "example.co.in"
    assert domains.is_free_mail("gmail.com")
    assert domains.domain_matches_company("kavera-analytics.in", COMPANY)
    assert domains.is_lookalike("kavera-analytics-careers.in", "kavera-analytics.in", COMPANY)
    assert domains.is_third_party("linkedin.com")


def test_redflags():
    offer = extract("Company: Zyntrix Careers Hub\nDirect joining today only. "
                    "Like videos for commission per task on Telegram. Send OTP and pay ₹500 fee. "
                    "Email zyntrix@gmail.com. Work from home ₹2,000 per day. Visit bit.ly/join")
    findings = text_findings(offer)
    titles = {f.title for f in findings}
    assert "Asks you to pay before joining" in titles
    assert "Task scam wording" in titles
    assert "Requests secret payment credentials" in titles
    assert "Recruiter uses free mail while claiming a company" in titles
    assert "Offered pay is unusually high" in titles
    assert "Uses a shortened URL" in titles


def test_gateway_replay_and_urls():
    gw = gateway()
    result = gw.search({"engine": "google", "q": COMPANY})
    assert result["knowledge_graph"]["title"] == COMPANY
    assert "https://kavera-analytics.in/careers" in gw.seen_urls
    assert gw.calls[0].cached and gw.calls[0].results == 6
    assert gw.remaining == 10
    with pytest.raises(MissingFixture):
        gw.search({"engine": "google", "q": "No such fixture"})


def test_gateway_budget_cache_and_redaction(tmp_path, monkeypatch):
    class FakeClient:
        def __init__(self, api_key):
            assert api_key == "secret"

        def search(self, params):
            return {"search_metadata": {"json_endpoint": "https://api.test/?key=secret",
                                        "html_endpoint": "https://api.test/html"},
                    "organic_results": [{"link": "https://example.org/a"}]}

    import serpapi

    monkeypatch.setattr(serpapi, "Client", FakeClient)
    gw = SerpGateway(api_key="secret", budget=1, cache_dir=tmp_path, record_dir=tmp_path / "records")
    query = {"engine": "google", "q": "one"}
    gw.search(query)
    gw.search(query)
    assert gw.calls[1].cached
    assert gw.remaining == 0
    assert "secret" not in next(tmp_path.glob("*.json")).read_text()
    assert list((tmp_path / "records").glob("*.json"))
    with pytest.raises(BudgetExceeded):
        gw.search({"engine": "google", "q": "two"})
    with pytest.raises(NoApiKey):
        SerpGateway(api_key=None, cache_dir=None).search({"engine": "google", "q": "x"})


def test_footprint_and_domain_consistency():
    ctx = context()
    found = checks.footprint(ctx)
    assert ctx.official_domain == "kavera-analytics.in"
    assert ctx.footprint_size == "large"
    assert "kavera-analytics.in" in ctx.advisory_domains
    assert any(f.title == "Public company registration record" for f in found)
    assert any(f.title == "The company publishes a recruitment fraud advisory" for f in found)
    assert checks.domain_consistency(ctx)[0].severity == Severity.POSITIVE
    ctx.offer.emails = ["hr@kavera-analytics-careers.in"]
    assert checks.domain_consistency(ctx)[0].severity == Severity.CRITICAL


def test_scam_reports_news_and_contact():
    ctx = context()
    checks.footprint(ctx)
    assert checks.scam_reports(ctx)[0].severity == Severity.MEDIUM
    assert ctx.impersonation_risk
    ctx.offer.phones = ["+91 98765 43210"]
    assert checks.contact_trace(ctx)[0].severity == Severity.HIGH
    ctx.findings = checks.domain_consistency(ctx)
    assert checks.news(ctx)[0].severity == Severity.INFO
    scam = context(Offer("", company="Zyntrix Careers Hub"))
    checks.footprint(scam)
    assert scam.footprint_size == "none"
    assert checks.scam_reports(scam)[0].severity == Severity.HIGH


def test_maps_jobs_and_probe():
    ctx = context()
    checks.footprint(ctx)
    assert checks.office_maps(ctx)[0].severity == Severity.POSITIVE
    ctx.offer.pay = [Money("₹120,000", 120000, "month")]
    listings = checks.job_listing(ctx)
    assert [f.severity for f in listings] == [Severity.POSITIVE, Severity.HIGH]
    assert listings[0].sources[0].url == "https://kavera-analytics.in/apply"
    assert checks.domain_probe(ctx, "kavera-analytics-careers.in")[0].severity == Severity.HIGH


def test_planner_replan_and_citations():
    offer = Offer("Company: Kavera Analytics Pvt Ltd", company=COMPANY, role="Analyst",
                  city="Pune", emails=["hr@kavera-analytics-careers.in"])
    agent = Agent(gateway())
    events = []
    report = agent.run(offer, on_event=events.append)
    assert any(s["name"] == "domain_probe" and s["added_by"] == "replan"
               for s in agent.last_investigation.steps)
    assert report.verdict == "likely_scam"
    assert all(src.url in agent.gateway.seen_urls for f in report.findings for src in f.sources)
    assert {"extracted", "search", "finding", "step", "report"} <= {e["type"] for e in events}


def test_planner_budget_skips():
    class Client:
        def search(self, params):
            return {"organic_results": []}

    from unittest.mock import patch

    import serpapi

    with patch.object(serpapi, "Client", lambda api_key: Client()):
        gw = SerpGateway(api_key="x", budget=1, cache_dir=None)
        agent = Agent(gw)
        agent.run(Offer("", company=COMPANY, role="Analyst"), budget=1)
    assert any(s["status"] == "skipped" and s["reason"] == "search budget used up"
               for s in agent.last_investigation.steps)


def test_scoring_and_llm_filter():
    high = Finding("x", Severity.HIGH, "High", "Test")
    critical = Finding("x", Severity.CRITICAL, "Critical", "Test")
    assert scoring.score([]) == 20
    assert scoring.verdict(20, []) == ("likely_genuine", "Looks genuine (verify anyway)")
    assert scoring.verdict(42, [high])[0] == "caution"
    assert scoring.verdict(65, [critical])[0] == "likely_scam"

    class LLM:
        def investigate(self, ctx):
            return [Finding("llm", Severity.CRITICAL, "Known", "Test", [Source(
                "Page", "https://kavera-analytics.in/careers")]),
                Finding("llm", Severity.HIGH, "Invented", "Test", [Source(
                    "Page", "https://invented.example/link")])]

        def summarize(self, report):
            return "Reviewed evidence."

    agent = Agent(gateway())
    report = agent.run(Offer("", company=COMPANY), llm=LLM())
    llm_findings = [f for f in report.findings if f.origin == "llm"]
    assert len(llm_findings) == 1
    assert llm_findings[0].severity == Severity.HIGH
    assert report.summary == "Reviewed evidence."


def test_tool_dispatch_and_nested_urls(tmp_path):
    class Client:
        def search(self, params):
            return {"jobs_results": [{"apply_options": [
                {"link": "https://apply.example.org/job"}],
                "source": {"link": "https://source.example.org/job"}}]}

    gw = SerpGateway(api_key="test", cache_dir=tmp_path)
    from unittest.mock import patch

    import serpapi

    with patch.object(serpapi, "Client", lambda api_key: Client()):
        tools = build_tools(gw)
        result = tools.call_tool("jobs_search", {"query": "fictional job"})
    assert "https://apply.example.org/job" in result
    assert "https://source.example.org/job" in gw.seen_urls
    assert {schema["function"]["name"] for schema in tools.openai_tool_schemas()} == {
        "web_search", "news_search", "maps_search", "jobs_search"}
    with pytest.raises(ValueError):
        tools.call_tool("unknown", {"query": "x"})
