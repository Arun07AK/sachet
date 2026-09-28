"""Generate hand-written SerpApi-shaped replay fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from sachet.gateway import SerpGateway

ROOT = Path(__file__).parent / "fixtures" / "synthetic"


def write(params, response):
    gateway = SerpGateway(cache_dir=None, replay_dir=ROOT)
    clean = gateway._params(params)
    path = ROOT / gateway.filename(clean)
    path.write_text(json.dumps({"params": clean, "response": response}, indent=2), encoding="utf-8")


def main():
    company = "Kavera Analytics Pvt Ltd"
    site = "https://kavera-analytics.in"
    write({"engine": "google", "q": company}, {"knowledge_graph": {
        "title": company, "type": "Company", "website": site}, "organic_results": [
        {"title": f"{company} Careers", "link": f"{site}/careers", "snippet": "Open roles"},
        {"title": f"{company} fraud warning", "link": f"{site}/fraud", "snippet":
         "Beware fake recruiters. Write to hr@kavera-analytics.in"},
        {"title": f"{company} registration", "link": "https://zaubacorp.com/kavera", "snippet": "Record"}] + [
        {"title": f"{company} profile {i}", "link": f"https://example{i}.org/kavera",
         "snippet": "Analytics jobs"} for i in range(3)]})
    write({"engine": "google", "q": f'"{company}" scam OR fraud OR fake job offer'},
          {"organic_results": [{"title": f"Fake {company} offer scam",
                               "link": "https://reddit.com/r/jobs/kavera", "snippet": "Impersonation warning"}]})
    write({"engine": "google_news", "q": f"{company} job scam"}, {"news_results": [
        {"title": f"{company} fake job scam", "link": "https://news.example.org/kavera",
         "snippet": "Recruiter impersonation"}]})
    write({"engine": "google_maps", "q": company, "type": "search", "location": "Pune", "z": 14},
          {"local_results": [{"title": company, "link": "https://maps.google.com/kavera",
                              "rating": 4.5, "reviews": 18}]})
    write({"engine": "google_jobs", "q": f"Analyst {company}", "location": "India"},
          {"jobs_results": [{"title": "Analyst", "company_name": company, "via": "Company site",
                             "detected_extensions": {"salary": "₹25K-₹30K a month"},
                             "apply_options": [{"title": "Apply", "link": f"{site}/apply"}]}]})
    write({"engine": "google", "q": '"kavera-analytics-careers.in"'}, {"organic_results": []})
    write({"engine": "google", "q": '"unknown-zyntrix.in"'}, {"organic_results": []})
    write({"engine": "google", "q": '"98765 43210" OR "9876543210"'}, {"organic_results": [
        {"title": "Fake Kavera Analytics Pvt Ltd recruiter scam",
         "link": "https://reddit.com/r/jobs/phone", "snippet": "This contact is reported"}]})
    scam = "Zyntrix Careers Hub"
    write({"engine": "google", "q": scam}, {"organic_results": []})
    write({"engine": "google", "q": f'"{scam}" scam OR fraud OR fake job offer'},
          {"organic_results": [{"title": f"{scam} scam", "link": "https://reddit.com/r/jobs/zyntrix",
                               "snippet": "Fake jobs"},
                              {"title": f"{scam} fraud", "link": "https://voxya.com/zyntrix",
                               "snippet": "Deposit complaint"}]})
    write({"engine": "google_news", "q": f"{scam} job scam"}, {"news_results": []})


if __name__ == "__main__":
    main()
