"""Search-backed checks for an offer investigation."""

from __future__ import annotations

import re
from itertools import chain

from . import domains
from .models import Finding, Severity, Source

_SCAM = re.compile(r"\b(?:scam|fraud|fake|beware|cheat|complaint)\b", re.IGNORECASE)


def _items(data, *keys):
    for key in keys:
        value = data.get(key, [])
        if isinstance(value, list):
            return value
    return []


def _source(item, engine="google"):
    url = item.get("link") or item.get("website") or item.get("url")
    return [Source(item.get("title", "Search result"), url, engine,
                   item.get("snippet", ""))] if url else []


def _mentions(item, company):
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
    return any(token in text for token in domains.company_tokens(company))


def footprint(ctx):
    company = ctx.offer.company
    data = ctx.tools.web_json(company)
    organic = _items(data, "organic_results")
    kg = data.get("knowledge_graph") or {}
    findings = []
    if kg:
        findings.append(Finding("footprint", Severity.POSITIVE, "Company has a web presence",
                                f'{kg.get("title", company)}: {kg.get("type", "knowledge graph")}',
                                _source(kg)))
    website = kg.get("website", "")
    if website and domains.domain_matches_company(website, company):
        ctx.official_domain = domains.registrable(website)
    if not ctx.official_domain:
        for item in organic:
            domain = domains.registrable(item.get("link", ""))
            if domain and not domains.is_third_party(domain) and domains.domain_matches_company(domain, company):
                ctx.official_domain = domain
                break
    matching = [item for item in organic if _mentions(item, company)]
    for item in organic:
        if domains.registrable(item.get("link", "")) in domains.REGISTRY_MIRRORS and _mentions(item, company):
            findings.append(Finding("footprint", Severity.POSITIVE, "Public company registration record",
                                    "A registry mirror lists the company.", _source(item)))
            break
    if len(matching) < 2:
        findings.append(Finding("footprint", Severity.HIGH, "Almost no web footprint",
                                "Fewer than two web results mention the company."))
    ctx.footprint_size = "large" if kg or len(matching) >= 6 else ("small" if matching else "none")
    for item in organic:
        if (ctx.official_domain and domains.registrable(item.get("link", "")) == ctx.official_domain
                and _SCAM.search(item.get("title", "") + " " + item.get("snippet", ""))):
            findings.append(Finding("footprint", Severity.INFO,
                                    "The company publishes a recruitment fraud advisory",
                                    item.get("snippet", ""), _source(item)))
            ctx.advisory_domains.update(re.findall(r"@([a-z0-9.-]+\.[a-z]{2,})",
                                                    item.get("snippet", "").lower()))
    return findings


def domain_consistency(ctx):
    if not ctx.official_domain:
        return []
    findings = []
    values = [(d, True) for d in ctx.offer.email_domains]
    values += [(domains.registrable(u), False) for u in ctx.offer.urls]
    for domain, email in dict.fromkeys(values):
        if domains.is_free_mail(domain) or domains.is_third_party(domain):
            continue
        if domain in {ctx.official_domain, *ctx.advisory_domains}:
            if email:
                findings.append(Finding("domain_consistency", Severity.POSITIVE,
                                        "Recruiter uses the official domain", domain))
        elif domains.is_lookalike(domain, ctx.official_domain, ctx.offer.company):
            findings.append(Finding("domain_consistency", Severity.CRITICAL,
                                    "Domain imitates the company", domain))
            ctx.suspicious_domains.add(domain)
        elif email:
            findings.append(Finding("domain_consistency", Severity.MEDIUM,
                                    "Recruiter domain is not the company's", domain))
            ctx.suspicious_domains.add(domain)
    return findings


def scam_reports(ctx):
    company = ctx.offer.company
    data = ctx.tools.web_json(f'"{company}" scam OR fraud OR fake job offer')
    hits = [item for item in _items(data, "organic_results") if _mentions(item, company)
            and _SCAM.search(item.get("title", "") + " " + item.get("snippet", ""))]
    if not hits:
        return []
    complaint = [i for i in hits if domains.registrable(i.get("link", "")) in domains.COMPLAINT_SITES]
    sources = list(chain.from_iterable(_source(i) for i in (complaint + [i for i in hits if i not in complaint])[:4]))
    if ctx.footprint_size == "large":
        ctx.impersonation_risk = True
        return [Finding("scam_reports", Severity.MEDIUM,
                        "Scammers commonly impersonate this company", f"{len(hits)} matching reports.", sources)]
    return [Finding("scam_reports", Severity.HIGH if len(hits) >= 2 else Severity.MEDIUM,
                    "Complaints name this company", f"{len(hits)} matching reports.", sources)]


def news(ctx):
    data = ctx.tools.news_json(f"{ctx.offer.company} job scam")
    hits = [i for i in _items(data, "news_results") if _mentions(i, ctx.offer.company)
            and _SCAM.search(i.get("title", "") + " " + i.get("snippet", ""))]
    if not hits:
        return []
    positive = any(f.check == "domain_consistency" and f.severity == Severity.POSITIVE
                   for f in ctx.findings)
    severity = Severity.INFO if ctx.footprint_size == "large" and positive else Severity.MEDIUM
    return [Finding("news", severity, "News reports a related job scam",
                    hits[0].get("snippet", ""), list(chain.from_iterable(_source(i, "google_news") for i in hits[:4])))]


def contact_trace(ctx):
    contacts = ctx.offer.phones[:1] + [e for e in ctx.offer.emails if domains.is_free_mail(e.split("@")[-1])][:1]
    findings = []
    for contact in contacts:
        digits = re.sub(r"\D", "", contact)
        if contact.startswith("+91") and len(digits) == 12:
            digits = digits[2:]
        query = (f'"{digits[:5]} {digits[5:]}" OR "{digits}"'
                 if len(digits) == 10 else f'"{contact}"')
        data = ctx.tools.web_json(query)
        for item in _items(data, "organic_results"):
            text = item.get("title", "") + " " + item.get("snippet", "")
            if _SCAM.search(text):
                findings.append(Finding("contact_trace", Severity.HIGH,
                                        "This contact appears in scam reports", contact, _source(item)))
                break
            if (ctx.official_domain and domains.registrable(item.get("link", "")) == ctx.official_domain
                    and _mentions(item, ctx.offer.company)):
                findings.append(Finding("contact_trace", Severity.POSITIVE,
                                        "Contact appears on the company website", contact, _source(item)))
                break
    return findings


def office_maps(ctx):
    data = ctx.tools.maps_json(ctx.offer.company, location=ctx.offer.city or ctx.offer.address)
    matches = [i for i in _items(data, "local_results") if _mentions(i, ctx.offer.company)]
    if matches:
        item = matches[0]
        detail = f'Rating {item.get("rating", "unknown")}, {item.get("reviews", "unknown")} reviews.'
        return [Finding("office_maps", Severity.POSITIVE, "Company has a Maps listing",
                        detail, _source(item, "google_maps"))]
    if ctx.offer.address:
        return [Finding("office_maps", Severity.MEDIUM,
                        "No Google Maps listing matches the stated office", ctx.offer.address)]
    return []


def _salary_max(text):
    numbers = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not numbers:
        return None
    amount = max(float(n) for n in numbers)
    low = text.lower()
    if "lpa" in low or "lakh" in low:
        return amount * 100000 / 12
    if "k" in low:
        amount *= 1000
    if "year" in low or "annum" in low:
        amount /= 12
    elif "week" in low:
        amount *= 4.33
    elif "day" in low:
        amount *= 26
    return amount


def job_listing(ctx):
    data = ctx.tools.jobs(f"{ctx.offer.role} {ctx.offer.company}")
    matches = [i for i in _items(data, "jobs_results") if any(
        token in i.get("company_name", "").lower() for token in domains.company_tokens(ctx.offer.company))]
    if not matches:
        return [Finding("job_listing", Severity.LOW, "Role was not found in public listings",
                        "This is a weak signal; many genuine roles are not indexed.")]
    item = matches[0]
    sources = _source(item, "google_jobs")
    for option in item.get("apply_options", []):
        sources += _source(option, "google_jobs")[:1]
        if sources:
            break
    findings = [Finding("job_listing", Severity.POSITIVE, "Role is publicly listed",
                        f'Listed via {item.get("via", "unknown")}.', sources)]
    salary = _salary_max(item.get("detected_extensions", {}).get("salary", ""))
    if salary and ctx.offer.offered_monthly_inr and ctx.offer.offered_monthly_inr > 3 * salary:
        findings.append(Finding("job_listing", Severity.HIGH,
                                "Offered pay is far above public listings",
                                f"Offer: ₹{ctx.offer.offered_monthly_inr:,.0f}/month; listing max: ₹{salary:,.0f}/month.", sources))
    return findings


def domain_probe(ctx, domain=None):
    domain = domain or next(iter(ctx.suspicious_domains), None)
    if not domain:
        return []
    data = ctx.tools.web_json(f'"{domain}"')
    items = _items(data, "organic_results")
    hits = [i for i in items if _SCAM.search(i.get("title", "") + " " + i.get("snippet", ""))]
    if hits:
        return [Finding("domain_probe", Severity.HIGH, "Domain appears in scam reports",
                        domain, list(chain.from_iterable(_source(i) for i in hits[:4])))]
    if not items:
        return [Finding("domain_probe", Severity.HIGH, "Domain has no independent presence", domain)]
    return []
