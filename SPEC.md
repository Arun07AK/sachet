# Sachet build spec (internal, for the code generator)

Sachet is an AI agent for Indian students and job seekers. You paste a job or internship offer
(email, offer letter text, SMS, WhatsApp message). The agent extracts entities, plans an
investigation, runs live SerpApi searches, re-plans based on what it finds, and returns an
explainable verdict: "likely_genuine", "caution" or "likely_scam", with a 0-100 risk score,
findings with severity, and cited sources. Every cited URL must have appeared in a SerpApi
result during that investigation (no invented links).

Already written (read them first, keep their APIs): `src/sachet/models.py`, `src/sachet/domains.py`,
`src/sachet/extract.py`. Python 3.10+, no em dashes anywhere in code comments, docs or UI text
(use commas, colons or plain hyphens instead).

SerpApi access goes through the `serpapi-search-tools` package (installed in .venv, read its
source in .venv/lib/python3.13/site-packages/serpapi_search_tools if needed). Factories:
`web_search`, `news_search`, `maps_search` accept `provider="function"`, `client=<obj with
.search(params)->dict>`, `response_format="json"`, `mode="full"` or `"compact"`, `result_limit=int`.
With a custom client they call `client.search(params)` where params includes `engine`, `q` etc,
and return a JSON string. web_search takes `(query, engine)`; restrict with
`allowed_engines=["google"]`. news_search takes `(query)`. maps_search takes
`(query, location=None, zoom=14, nearby=False)`. Google Jobs is not in the package, so call the
gateway directly with `{"engine": "google_jobs", "q": ..., "location": "India"}`.

## Modules to write

### src/sachet/gateway.py
`class SerpGateway` implementing `.search(params: dict) -> dict`:
- ctor: `api_key=None` (falls back to env SERPAPI_API_KEY or SERPAPI_KEY), `budget=10` (max
  live, non-cached calls), `cache_dir=".sachet-cache"` (None disables), `replay_dir=None`
  (if set: offline mode, only read fixtures, raise `MissingFixture` if absent),
  `record_dir=None` (if set: also write every live response there), `on_call=None` callback
  `(SearchCall) -> None`, `defaults={"gl": "in", "hl": "en"}` merged when absent (not for
  engines that reject them: keep for google, google_news, google_jobs, google_maps only as hl).
- cache key: engine + sha1 of json.dumps(params minus api_key/output, sort_keys=True), file name
  `f"{engine}-{sha[:16]}.json"` containing `{"params": ..., "response": ...}`. Same format
  for cache, replay and record dirs so recordings can be replayed.
- live call: `serpapi.Client(api_key=...).search(params)`, convert to plain dict. Strip
  `search_metadata` fields that contain the api key or json/html endpoints before saving.
- raise `BudgetExceeded` when a live call would exceed the budget. Raise `NoApiKey` with a clear
  message when live mode has no key.
- records `self.calls: list[SearchCall]` (engine, query = q or k or first text param, cached
  flag, number of result items, ms, ok, error) and `self.seen_urls: set[str]` of every `link`,
  `website`, `apply_options[].link`, `source.link`-like URL found anywhere in responses (walk
  recursively for keys named link, website, url).
- `remaining` property.

### src/sachet/tools.py
`build_tools(gateway) -> Tools` dataclass holding the three serpapi-search-tools function tools
(web restricted to google, JSON, mode full, result_limit 10; news limit 10; maps limit 10) plus
`jobs(query, location="India") -> dict`. Also `tools.web_json(q) -> dict` helpers that json.loads
the tool output. Also `openai_tool_schemas()` returning OpenAI function-calling schemas for
web_search(query), news_search(query), maps_search(query, location?), jobs_search(query,
location?) and `call_tool(name, args) -> str` dispatcher (returns compact JSON text, truncated to
~6000 chars) for the LLM loop.

### src/sachet/redflags.py
`text_findings(offer: Offer) -> list[Finding]` with check="text", deterministic:
- fees demanded (offer.fees / fee_sentences): CRITICAL "Asks you to pay before joining".
- task-scam wording (like videos, rate products/hotels, prepaid task, youtube likes, review
  tasks, crypto, telegram task, commission per task): CRITICAL.
- asks for OTP / UPI PIN / card CVV: CRITICAL. Asks for Aadhaar/PAN/bank details before interview: MEDIUM.
- recruiter uses free mail (domains.is_free_mail) while claiming a company: HIGH.
- "no interview", "direct joining", "without interview", "selected based on your profile": HIGH.
- WhatsApp/Telegram as the main channel: MEDIUM.
- urgency (within 24 hours, today only, limited seats, immediately, last chance): MEDIUM.
- unrealistic pay: any pay with period day >= 1500 or week >= 10000 for work-from-home/part
  time/data entry, or monthly >= 100000 for intern/fresher/data entry: HIGH.
- URL shorteners: LOW.
Each finding quotes the matching phrase in detail.

### src/sachet/checks.py
Each check is a function `(ctx) -> list[Finding]` where `ctx` is `Investigation` state
(see planner). Checks and their SerpApi calls:
1. `footprint`: web_search(company). Parse knowledge_graph (title, type, website) and organic
   results. Determine `ctx.official_domain`: knowledge_graph website registrable domain if it
   matches the company (domains.domain_matches_company) else the first organic result whose
   domain matches the company and is not third party. POSITIVE if knowledge graph present.
   POSITIVE (small) if a registry mirror (domains.REGISTRY_MIRRORS) lists the company: "public
   company registration record". HIGH if fewer than 2 organic results mention any company token:
   "almost no web footprint". Store `ctx.footprint_size` ("large" if knowledge graph or >=6 of
   10 organic results mention the company, "small" otherwise, "none").
   Also detect company fraud advisories: organic result on the official domain whose title or
   snippet mentions fraud/fake/beware/scam: INFO finding "The company publishes a recruitment
   fraud advisory", and if the snippet names an official mail domain (regex @([a-z0-9.-]+)),
   store it in ctx.advisory_domains.
2. `domain_consistency` (no search): compare offer email domains and url domains to
   official_domain (and advisory_domains). Lookalike (domains.is_lookalike): CRITICAL
   "Domain imitates the company". Email domain equal to official: POSITIVE. Corporate domain that
   neither matches nor imitates: MEDIUM "Recruiter domain is not the company's".
3. `scam_reports`: web_search(f'"{company}" scam OR fraud OR fake job offer'). Count organic
   results whose title+snippet contain scam words and a company token. Split into complaint
   sites (domains.COMPLAINT_SITES) vs others. If footprint large: MEDIUM "Scammers commonly
   impersonate this company" (this raises the weight of domain checks, set
   ctx.impersonation_risk=True). If small/none and >=2 hits: HIGH "Complaints name this company";
   1 hit: MEDIUM. Sources: up to 4 results.
4. `news`: news_search(f"{company} job scam"). If >=1 news result mentions a company token and
   scam words: MEDIUM (or INFO if footprint large and domain checks already positive).
5. `contact_trace`: for the first phone and the first free-mail address: web_search(f'"{value}"').
   Hits with scam words: HIGH "This contact appears in scam reports". Hits naming the company on
   the official domain: POSITIVE.
6. `office_maps`: if company and (address or city): maps_search(company, location=city or
   address). Listing whose title matches company tokens: POSITIVE with rating and reviews count
   in detail and a Google Maps link if available (use `link` or build from place_id/data_id only
   if a URL string exists in the response; never invent). Address given but no matching listing:
   MEDIUM "No Google Maps listing matches the stated office".
7. `job_listing`: gateway.search google_jobs q=f"{role} {company}" location India. Job whose
   company_name matches company tokens: POSITIVE "Role is publicly listed" with `via` and first
   apply link. Parse salary from detected_extensions.salary (e.g. "₹25K–₹30K a month",
   "3–4.5 LPA"); if offer.offered_monthly_inr > 3x the listed monthly max: HIGH "Offered pay is far
   above public listings". No matching listing: LOW (weak signal, say so).
8. `domain_probe` (follow-up only): web_search(f'"{domain}"') for a suspicious corporate domain.
   No results or scam hits: HIGH "Domain has no independent presence" / "Domain appears in scam
   reports".

### src/sachet/planner.py
`Investigation` dataclass: offer, tools, gateway, findings list, official_domain,
advisory_domains, footprint_size, impersonation_risk, steps log (list of dicts with name, reason,
status: "done"|"skipped"|"failed", added_by: "plan"|"replan"), on_event callback.
`class Agent` with `run(text_or_offer, budget=8, on_event=None, llm=None) -> Report`:
- extract (or accept Offer), optionally let `llm.refine(offer)` fill missing fields.
- emit events: {"type": "extracted", "offer": ...}, {"type": "step", "name", "reason", "status"},
  {"type": "finding", ...}, {"type": "search", engine, query, cached}, {"type": "report", ...}.
- initial plan by priority: text rules (free), footprint, domain_consistency, scam_reports,
  contact_trace, office_maps, job_listing, news. Skip steps whose inputs are missing (with a
  reason). Steps that need a search are skipped with reason "search budget used up" once the
  gateway budget is exhausted (catch BudgetExceeded).
- re-planning rules after each step:
  * company unknown but a corporate email domain exists: derive company from domain label, run footprint.
  * after domain_consistency: a lookalike or unmatched corporate domain queues domain_probe for it (priority high).
  * footprint "none": queue contact_trace before others.
  * impersonation_risk and no offer domain matched official: move contact_trace earlier.
- if llm given: after rule steps, `llm.investigate(ctx)` may run extra tool calls within the
  remaining budget and return extra findings; drop any LLM finding whose source URLs are not in
  gateway.seen_urls; LLM findings are capped at HIGH (never CRITICAL) and marked origin="llm".
  `llm.summarize(report)` may replace the summary.
- scoring via scoring.py, next steps via scoring.next_steps.

### src/sachet/scoring.py
`score(findings) -> int` = clamp(20 + sum(WEIGHTS), 0, 100) (neutral start 20).
`verdict(score, findings)`: any CRITICAL -> at least 70. >=60 likely_scam, 30-59 caution, <30
likely_genuine. Labels: "Likely scam", "Proceed with caution", "Looks genuine (verify anyway)".
`next_steps(report)`: always practical, India specific: do not pay any fee; verify on the official
careers page at official_domain if known; reply only to the official domain; if money was lost
call the National Cyber Crime Helpline 1930 or report at https://cybercrime.gov.in; report fake
job posts on the platform. `summary_text(...)`: 2-3 plain sentences built from top findings.

### Tests (pytest, fully offline)
Write synthetic SerpApi-shaped fixtures in `tests/fixtures/synthetic/` using the gateway file
format (a helper `tests/make_fixtures.py` that builds them from compact Python dicts is fine, but
commit the generated JSON). Add `tests/fixtures/synthetic/README.md` stating these are
hand-written fixtures in SerpApi response shape for offline tests, not real search results.
Use company names that are clearly fictional for the scam fixture ("Zyntrix Careers Hub") and a
fictional genuine company ("Kavera Analytics Pvt Ltd", domain kavera-analytics.in) so tests do not
make claims about real firms. Cover: extraction (money, phones, company patterns), redflags,
domains helpers, gateway (cache hit, budget exceeded, replay missing fixture, seen_urls, key
redaction), every check, planner replanning (lookalike -> domain_probe queued; budget exhaustion
-> skipped steps), scoring thresholds, and LLM citation filtering with a fake llm object.
All tests must pass with `pytest -q` and make no network calls.
