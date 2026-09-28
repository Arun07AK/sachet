"""Rule-based entity extraction from a pasted offer letter, email, SMS or WhatsApp message.

The optional LLM step (llm.py) can refine these fields, but the agent works without it.
"""

from __future__ import annotations

import re

from .domains import FREE_MAIL, host_of, is_free_mail, label, registrable
from .models import Money, Offer

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(
    r"\b(?:https?://[^\s<>\"')\]]+|www\.[^\s<>\"')\]]+|"
    r"(?<![@\w.\-])[a-z0-9][a-z0-9\-]{1,62}\.(?:com|in|co\.in|org|net|io|ai|jobs|careers|work|xyz|site|online|info)"
    r"(?:/[^\s<>\"')\]]*)?)",
    re.IGNORECASE,
)
PHONE_RE = re.compile(r"(?<![\d+])(?:\+?91[\s\-]?)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)")

_AMOUNT = r"(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)"
_UNIT = r"\s*(k|thousand|lakhs?|lacs?|l|lpa|crores?|cr)?\b"
MONEY_RE = re.compile(
    r"(?:₹|\brs\.?|\binr\b|\brupees\b)\s*" + _AMOUNT + _UNIT
    + r"|" + _AMOUNT + r"\s*(lpa|lakhs? per annum|lacs? per annum)\b"
    + r"|" + _AMOUNT + r"\s*(?:/-|rupees\b|rs\b)",
    re.IGNORECASE,
)

_PERIODS = [
    ("year", r"per annum|p\.?\s?a\b|annual|annually|per year|/\s?year|/\s?yr|\bctc\b|\blpa\b|a year"),
    ("month", r"per month|/\s?month|/\s?mo\b|\bp\.?\s?m\b|monthly|a month|every month|stipend"),
    ("week", r"per week|/\s?week|weekly|a week"),
    ("day", r"per day|/\s?day|daily|a day|each day|every day"),
    ("hour", r"per hour|/\s?hr|/\s?hour|hourly|an hour"),
]

FEE_WORDS = re.compile(
    r"\b(fee|fees|deposit|charges?|refundable|registration|processing|verification amount|"
    r"training cost|kit|onboarding amount|security amount|laptop amount|advance)\b",
    re.IGNORECASE,
)
PAY_DEMAND = re.compile(
    r"\b(you (?:need|have|are required) to|kindly|please|must|required to|need to)\s+"
    r"(?:pay|deposit|transfer|send)\b",
    re.IGNORECASE,
)
PAY_WORDS = re.compile(
    r"\b(salary|stipend|ctc|package|earn|earning|income|remuneration|compensation|pay of|"
    r"paid|payout|commission)\b",
    re.IGNORECASE,
)

CITIES = [
    "Bengaluru", "Bangalore", "Mumbai", "New Delhi", "Delhi", "Noida", "Greater Noida",
    "Gurugram", "Gurgaon", "Hyderabad", "Chennai", "Pune", "Kolkata", "Ahmedabad", "Jaipur",
    "Chandigarh", "Mohali", "Patiala", "Kochi", "Cochin", "Coimbatore", "Indore", "Lucknow",
    "Bhopal", "Nagpur", "Thiruvananthapuram", "Trivandrum", "Visakhapatnam", "Vizag",
    "Bhubaneswar", "Surat", "Vadodara", "Mysuru", "Mysore", "Mangaluru", "Mangalore", "Goa",
    "Ludhiana", "Dehradun", "Kanpur", "Nashik", "Madurai", "Guwahati", "Ranchi", "Patna",
]

_CORP_SUFFIX = (
    r"(?:Pvt\.?\s*Ltd\.?|Private\s+Limited|Pvt\.?\s+Limited|Limited|Ltd\.?|LLP|Inc\.?|"
    r"Technologies|Technology|Solutions|Infotech|Softech|Software|Services|Consultancy|"
    r"Consulting|Systems|Labs|Enterprises|Industries)"
)
_NAME_WORD = r"[A-Z][A-Za-z0-9&'\-]*"
COMPANY_PATTERNS = [
    re.compile(r"(?im)^\s*(?:company|organi[sz]ation|employer|company name)\s*[:\-]\s*(.+?)\s*$"),
    re.compile(r"(?:Greetings|Congratulations|Welcome)\s+(?:from|to)\s+(" + _NAME_WORD
               + r"(?:\s+" + _NAME_WORD + r"){0,5})"),
    re.compile(r"\b(" + _NAME_WORD + r"(?:\s+(?:&\s+)?" + _NAME_WORD + r"){0,4}\s+" + _CORP_SUFFIX
               + r"(?:\s+" + _CORP_SUFFIX + r")*)"),
    re.compile(r"(?:on behalf of|hiring for|position at|role at|opening at|opportunity at|"
               r"internship at|job at|work at|join|joining)\s+(" + _NAME_WORD
               + r"(?:\s+" + _NAME_WORD + r"){0,3})"),
]
_COMPANY_STOP = {
    "we", "you", "our", "the", "hr", "team", "dear", "candidate", "us", "this", "your", "a", "an",
    "whatsapp", "telegram", "google", "gmail", "india", "hello", "hi", "congratulations",
    "part", "work", "home", "online", "immediately", "today", "now", "role",
}

ROLE_RE = re.compile(
    r"(?:position|role|post|profile|designation|job title|opening)\s*(?:of|:|\-|as|for)\s*"
    r"(?:an?\s+|the\s+)?([A-Za-z][A-Za-z /&+\-]{2,50}?)(?=\s*(?:[.,;\n(]|with|at|in|on|for|$))",
    re.IGNORECASE,
)
ROLE_TITLE_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z+#.\-]*\s+){0,3}(?:Intern|Internship|Engineer|Developer|Executive|Analyst|"
    r"Associate|Manager|Assistant|Operator|Trainee|Consultant|Specialist|Designer|Tester|Writer|"
    r"Representative|Agent))\b"
)
ADDRESS_RE = re.compile(
    r"(?im)^\s*(?:address|office address|venue|reporting (?:at|venue|address)|office|location)"
    r"\s*[:\-]\s*(.{8,160}?)\s*$"
)
PIN_LINE_RE = re.compile(r"(?m)^(.{10,160}?\b\d{6}\b.*)$")


def _sentences(text: str) -> list[str]:
    clean = re.sub(r"\b(rs|no|dr|mr|ms|mrs|pvt|ltd)\.", r"\1 ", text, flags=re.IGNORECASE)
    parts = re.split(r"(?<!\d)[.!?](?!\d)|\n+", clean)
    return [p.strip() for p in parts if p and p.strip()]


def _to_amount(num: str, unit: str | None) -> float:
    value = float(num.replace(",", ""))
    u = (unit or "").lower()
    if u in {"k", "thousand"}:
        value *= 1_000
    elif u in {"lakh", "lakhs", "lac", "lacs", "l", "lpa"} or u.startswith(("lakh", "lac")):
        value *= 100_000
    elif u in {"crore", "crores", "cr"}:
        value *= 10_000_000
    return value


def _period(context: str, unit: str | None) -> str | None:
    if unit and unit.lower().startswith(("lpa", "lakh per", "lakhs per", "lac per", "lacs per")):
        return "year"
    for name, pattern in _PERIODS:
        if re.search(pattern, context, re.IGNORECASE):
            return name
    return None


def extract_money(text: str) -> tuple[list[Money], list[Money], list[str]]:
    """Split money mentions into pay offered and fees demanded."""
    pay: list[Money] = []
    fees: list[Money] = []
    fee_sentences: list[str] = []
    for sentence in _sentences(text):
        for m in MONEY_RE.finditer(sentence):
            if m.group(1):
                num, unit = m.group(1), m.group(2)
            elif m.group(3):
                num, unit = m.group(3), m.group(4)
            else:
                num, unit = m.group(5), None
            amount = _to_amount(num, unit)
            if amount < 50:
                continue
            after = sentence[m.end(): m.end() + 40]
            before = sentence[max(0, m.start() - 40): m.start()]
            period = _period(after, unit) or _period(before, unit)
            is_fee = bool(FEE_WORDS.search(sentence) or PAY_DEMAND.search(sentence))
            is_pay = bool(PAY_WORDS.search(sentence))
            if is_fee and not (is_pay and not PAY_DEMAND.search(sentence) and period):
                fees.append(Money(m.group(0).strip(), amount, "once"))
                if sentence not in fee_sentences:
                    fee_sentences.append(sentence)
            elif is_pay or period:
                if period is None and re.search(r"stipend|salary", sentence, re.IGNORECASE):
                    period = "month"
                pay.append(Money(m.group(0).strip(), amount, period or "once"))
    return pay, fees, fee_sentences


def _clean_company(name: str) -> str | None:
    name = re.sub(r"\s+", " ", name).strip(" .,:;-'\"")
    words = name.split()
    while words and words[0].lower() in _COMPANY_STOP:
        words = words[1:]
    while words and words[-1].lower() in {"for", "as", "in", "the", "and", "team", "hr", "is"}:
        words = words[:-1]
    if not words:
        return None
    name = " ".join(words)
    if name.lower() in _COMPANY_STOP or len(name) < 2:
        return None
    return name


def extract_company(text: str, emails: list[str]) -> str | None:
    for pattern in COMPANY_PATTERNS:
        for m in pattern.finditer(text):
            name = _clean_company(m.group(1))
            if name:
                return name
    for email in emails:
        domain = email.rsplit("@", 1)[1].lower()
        if not is_free_mail(domain):
            lab = label(domain)
            if lab:
                return lab.replace("-", " ").title()
    return None


def extract_role(text: str) -> str | None:
    m = ROLE_RE.search(text)
    if m:
        role = m.group(1).strip(" .,-")
        first = role.split()[0].lower() if role.split() else ""
        if (2 < len(role) <= 50 and role.lower() not in {"the", "a", "our", "this"}
                and first not in {"in", "at", "on", "with", "from", "to", "is", "has"}):
            return role
    m = ROLE_TITLE_RE.search(text)
    return m.group(1).strip() if m else None


def extract_city(text: str) -> str | None:
    for city in CITIES:
        if re.search(r"\b" + re.escape(city) + r"\b", text, re.IGNORECASE):
            return city
    return None


def extract_address(text: str) -> str | None:
    m = ADDRESS_RE.search(text)
    if m:
        return m.group(1).strip()
    m = PIN_LINE_RE.search(text)
    return m.group(1).strip() if m else None


def _norm_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return "+91 " + digits[:5] + " " + digits[5:] if len(digits) == 10 else raw.strip()


def extract(text: str) -> Offer:
    emails = sorted({e.strip(".").lower() for e in EMAIL_RE.findall(text)})
    email_hosts = {e.rsplit("@", 1)[1] for e in emails}
    urls: list[str] = []
    for u in URL_RE.findall(text):
        u = u.rstrip(".,;:")
        host = host_of(u)
        if not host or host in email_hosts and "/" not in u.split("//")[-1]:
            continue
        if registrable(host) in FREE_MAIL:
            continue
        if u not in urls:
            urls.append(u)
    phones: list[str] = []
    for p in PHONE_RE.findall(text):
        n = _norm_phone(p)
        if n not in phones:
            phones.append(n)
    pay, fees, fee_sentences = extract_money(text)
    apps = []
    low = text.lower()
    if "whatsapp" in low or "wa.me" in low:
        apps.append("WhatsApp")
    if "telegram" in low or "t.me/" in low:
        apps.append("Telegram")
    return Offer(
        raw_text=text,
        company=extract_company(text, emails),
        role=extract_role(text),
        city=extract_city(text),
        address=extract_address(text),
        emails=emails,
        urls=urls,
        phones=phones,
        pay=pay,
        fees=fees,
        fee_sentences=fee_sentences,
        messaging_apps=apps,
    )
