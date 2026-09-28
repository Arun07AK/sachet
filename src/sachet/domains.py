"""Domain helpers: registrable domains, free mail providers, job boards and lookalike checks."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Two-level public suffixes we meet often in Indian and global hiring mail.
_MULTI_SUFFIXES = {
    "co.in", "net.in", "org.in", "firm.in", "gen.in", "ind.in", "ac.in", "edu.in", "gov.in",
    "nic.in", "res.in", "co.uk", "org.uk", "ac.uk", "com.au", "net.au", "co.jp", "com.sg",
    "com.my", "co.za", "com.br", "com.cn",
}

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.in", "yahoo.co.in", "outlook.com",
    "hotmail.com", "live.com", "msn.com", "rediffmail.com", "protonmail.com", "proton.me",
    "icloud.com", "aol.com", "zoho.com", "zohomail.in", "yandex.com", "mail.com", "gmx.com",
}

# Sites that talk about companies without being the company.
THIRD_PARTY = {
    "linkedin.com", "naukri.com", "glassdoor.com", "glassdoor.co.in", "ambitionbox.com",
    "indeed.com", "in.indeed.com", "wikipedia.org", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "youtube.com", "justdial.com", "zaubacorp.com", "tofler.in",
    "thecompanycheck.com", "falconebiz.com", "crunchbase.com", "quora.com", "reddit.com",
    "internshala.com", "foundit.in", "shine.com", "apna.co", "timesjobs.com", "wellfound.com",
    "consumercomplaints.in", "voxya.com", "mouthshut.com", "trustpilot.com", "google.com",
    "zoominfo.com", "bloomberg.com", "economictimes.indiatimes.com", "indiatimes.com",
    "moneycontrol.com", "medium.com", "blogspot.com", "wordpress.com", "github.com",
}

# Company registry mirrors: a hit here means an MCA registration record is public.
REGISTRY_MIRRORS = {"zaubacorp.com", "tofler.in", "thecompanycheck.com", "falconebiz.com"}

COMPLAINT_SITES = {
    "reddit.com", "quora.com", "consumercomplaints.in", "voxya.com", "mouthshut.com",
    "trustpilot.com", "complaintboard.in", "scamadviser.com", "tellows.in", "tellows.com",
}

SHORTENERS = {"bit.ly", "tinyurl.com", "cutt.ly", "rb.gy", "t.ly", "shorturl.at", "is.gd"}

_CORP_WORDS = {
    "pvt", "private", "ltd", "limited", "llp", "inc", "technologies", "technology", "tech",
    "solutions", "services", "infotech", "softech", "software", "consultancy", "consulting",
    "global", "india", "the", "and", "of", "co", "company", "corp", "corporation", "group",
    "systems", "labs", "hr", "careers", "career", "jobs", "job", "recruitment", "hiring",
}


def host_of(url_or_host: str) -> str:
    text = url_or_host.strip().lower()
    if "://" not in text:
        text = "http://" + text
    host = urlparse(text).hostname or ""
    return host.removeprefix("www.")


def registrable(url_or_host: str) -> str:
    """Return the registrable domain, e.g. careers.tcs.com -> tcs.com, x.co.in -> x.co.in."""
    host = host_of(url_or_host)
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    if ".".join(parts[-2:]) in _MULTI_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def label(domain: str) -> str:
    """Main label of a registrable domain: 'amazon' for amazon.jobs, 'foo' for foo.co.in."""
    reg = registrable(domain)
    return reg.split(".")[0] if reg else ""


def is_free_mail(domain: str) -> bool:
    return registrable(domain) in FREE_MAIL or domain.lower() in FREE_MAIL


def is_third_party(domain: str) -> bool:
    reg = registrable(domain)
    host = host_of(domain)
    return reg in THIRD_PARTY or host in THIRD_PARTY


def company_tokens(company: str) -> list[str]:
    """Distinctive lowercase tokens of a company name, corporate filler removed."""
    words = re.findall(r"[a-z0-9]+", company.lower())
    toks = [w for w in words if w not in _CORP_WORDS and len(w) >= 2]
    return toks or words


def company_slug(company: str) -> str:
    return "".join(company_tokens(company))


def domain_matches_company(domain: str, company: str) -> bool:
    """True when the domain's main label is built from the company's distinctive tokens."""
    lab = label(domain).replace("-", "")
    toks = company_tokens(company)
    if not lab or not toks:
        return False
    slug = "".join(toks)
    if lab == slug or lab == toks[0]:
        return True
    initials = "".join(t[0] for t in toks)
    if len(toks) >= 2 and lab == initials:
        return True
    return len(toks[0]) >= 4 and lab.startswith(toks[0]) and len(lab) - len(toks[0]) <= 3


def is_lookalike(domain: str, official: str, company: str | None = None) -> bool:
    """A domain that borrows the brand but is not the official registrable domain."""
    reg, off = registrable(domain), registrable(official)
    if not reg or not off or reg == off:
        return False
    brand = label(off)
    lab = label(reg)
    if len(brand) >= 3 and brand in lab.replace("-", ""):
        return True
    if company:
        toks = company_tokens(company)
        if toks and len(toks[0]) >= 4 and toks[0] in lab.replace("-", ""):
            return True
    return False
