"""Pull structured deal fields out of an article.

With ANTHROPIC_API_KEY set, Claude reads each article and returns the fields as
schema-validated JSON. Without it, a rules-based parser handles the headline
patterns both sites use ("X raises $Y in Z round led by W").
"""
import json
import logging
import os
import re

from .sectors import ROUNDS, SECTORS, classify, normalize_round

log = logging.getLogger(__name__)

USD_INR = float(os.environ.get("USD_INR", "88"))
MODEL = os.environ.get("TRACKER_MODEL", "claude-opus-5-5")

VERB = r"(?:raises|raised|bags|secures|secured|gets|nets|closes|picks up|mops up|receives|lands|scores|garners|attracts|snags)"
AMOUNT_RX = re.compile(
    r"(?P<cur>\$|usd|us\$|rs\.?|inr|₹)\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>million|mn|m\b|billion|bn|b\b|crore|cr\b|lakh|lakhs|k\b)?",
    re.I,
)


def parse_amount(text):
    """Return (amount_text, usd_mn, inr_cr) for the first money figure in text."""
    m = AMOUNT_RX.search(text or "")
    if not m:
        return None, None, None
    cur = m.group("cur").lower()
    num = float(m.group("num").replace(",", ""))
    unit = (m.group("unit") or "").lower()
    if cur in ("$", "usd", "us$"):
        scale = {"million": 1, "mn": 1, "m": 1, "billion": 1000, "bn": 1000, "b": 1000, "k": 0.001}
        usd = num * scale[unit] if unit in scale else num / 1e6
        return m.group(0).strip(), round(usd, 3), round(usd * 1e6 * USD_INR / 1e7, 2)
    # INR: express in crore (1 crore = 10 million rupees)
    scale = {"crore": 1, "cr": 1, "lakh": 0.01, "lakhs": 0.01, "million": 0.1, "mn": 0.1, "m": 0.1,
             "billion": 100, "bn": 100, "b": 100, "k": 1e-4}
    inr_cr = num * scale[unit] if unit in scale else num / 1e7
    return m.group(0).strip(), round(inr_cr * 1e7 / USD_INR / 1e6, 3), round(inr_cr, 2)


def split_investors(text):
    text = re.split(r"\s+(?:to|for|in a bid|as it|amid|with plans)\s+", text, maxsplit=1)[0]
    parts = re.split(r",\s*|\s+and\s+|\s*&\s*|\s+with participation from\s+|\s+alongside\s+", text)
    out = []
    for p in parts:
        p = re.sub(r"^(?:with participation from|participation from|along with|including)\s+", "", p.strip(), flags=re.I)
        p = re.sub(r"^(?:others|existing investors|other investors|clutch of investors)$", "", p.strip(" .,"), flags=re.I)
        if p and (p[0].islower() or len(p.split()) > 6 or re.search(r"\b(is|are|was|has|combines|builds|offers)\b", p)):
            continue  # a clause, not an investor name
        if p and len(p) < 70 and not re.search(r"\b(?:others|other (?:angel )?investors|angels?)$", p, re.I):
            out.append(p)
    return out


CITIES = {
    "bengaluru": "Bengaluru", "bangalore": "Bengaluru", "mumbai": "Mumbai", "new delhi": "New Delhi",
    "delhi": "Delhi", "gurugram": "Gurugram", "gurgaon": "Gurugram", "noida": "Noida", "hyderabad": "Hyderabad",
    "chennai": "Chennai", "pune": "Pune", "kolkata": "Kolkata", "ahmedabad": "Ahmedabad", "jaipur": "Jaipur",
    "kochi": "Kochi", "chandigarh": "Chandigarh", "indore": "Indore", "surat": "Surat", "coimbatore": "Coimbatore",
    "lucknow": "Lucknow", "bhubaneswar": "Bhubaneswar", "thiruvananthapuram": "Thiruvananthapuram", "goa": "Goa",
    "nagpur": "Nagpur", "vadodara": "Vadodara", "mysuru": "Mysuru", "visakhapatnam": "Visakhapatnam",
    "kozhikode": "Kozhikode", "bhopal": "Bhopal", "guwahati": "Guwahati", "patna": "Patna", "ranchi": "Ranchi",
    "dehradun": "Dehradun", "mohali": "Mohali", "thane": "Thane", "navi mumbai": "Navi Mumbai",
}
CITY_RX = re.compile(r"\b(" + "|".join(sorted(CITIES, key=len, reverse=True)) + r")\b", re.I)
FOREIGN_RX = re.compile(r"\b(US|U\.S\.|USA|Singapore|UK|London|Dubai|UAE|San Francisco|New York|Silicon Valley|"
                        r"Delaware|Germany|Berlin|Israel|Indonesia|Japan|Australia|Canada|Saudi)[- ]based\b")
BODY_DEAL = re.compile(
    r"^(?P<company>[^,]{2,80}?)(?:,\s*(?P<desc>(?:an?|the|India's|India’s)\s[^.]{5,220}?),)?\s+"
    r"(?:has\s+|have\s+|had\s+)?(?:raised|secured|bagged|closed|received|mopped up|garnered|netted|picked up|"
    r"announced (?:that it has raised|a fresh|its|a))\s+(?P<rest>.+)$", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"‘'(])")
USE_RX = re.compile(r"(will use|plans to use|intends to use|to use the (?:fresh )?(?:funds|capital|proceeds)|"
                    r"proceeds will|funds will be|capital will be|plans to deploy|will deploy|"
                    r"(?:the )?(?:fresh )?(?:funds|capital|money|investment) (?:will|would) (?:be used|help|go))", re.I)
PREFIX_RX = re.compile(r"^(?:[\w&-]+-based|homegrown|indian|bengaluru's|mumbai's|delhi's|"
                       r"[\w-]+(?: [\w-]+){0,3}\s(?:startup|platform|brand|company|firm|maker|provider|player|venture))\s+", re.I)


def clean_company(name):
    name = name.strip(" “”\"'")
    for _ in range(2):
        name = PREFIX_RX.sub("", name)
    name = re.sub(r"^(?:startup|platform|brand|company|firm)\s+", "", name, flags=re.I)
    return name.strip(" ,")


def find_deal(title, sentences):
    """Locate the sentence announcing the raise. Returns (company, appositive_desc, rest, from_title)."""
    m = re.match(rf"^(?P<company>.+?)\s+{VERB}\s+(?P<rest>.+)$", title, re.I)
    if m:
        company = clean_company(m.group("company"))
        if ":" not in company and 0 < len(company.split()) <= 6:
            return company, None, m.group("rest"), True
    for sent in sentences[:12]:
        b = BODY_DEAL.match(sent)
        if not b:
            continue
        company = clean_company(b.group("company"))
        if 0 < len(company.split()) <= 6 and (AMOUNT_RX.search(b.group("rest")) or re.search(r"round|funding", b.group("rest"), re.I)):
            return company, b.group("desc"), b.group("rest"), False
    return None


def heuristic_extract(art):
    """Rules-based extraction from the headline plus the article's opening paragraphs."""
    title = art.get("title") or ""
    body = art.get("body") or ""
    desc_meta = art.get("description") or ""
    opening = body[:4000]
    sentences = [s.strip() for s in SENT_SPLIT.split(f"{desc_meta} {opening}".strip()) if len(s.strip()) > 20]
    found = find_deal(title, sentences)
    if not found:
        return None
    company, appositive, rest, from_title = found
    key = company.split()[0].lower()
    deal_sentence = next((s for s in sentences if key in s.lower() and AMOUNT_RX.search(s)), "")
    if appositive is None:  # pick up "X, a ... platform, has raised" from the body
        for s in sentences[:12]:
            b = BODY_DEAL.match(s)
            if b and b.group("desc") and key in b.group("company").lower():
                appositive, deal_sentence = b.group("desc"), s
                break

    amount_text, usd, inr = parse_amount(rest)
    if not amount_text:
        amount_text, usd, inr = parse_amount(deal_sentence or opening[:1500])

    round_name = normalize_round(rest)
    if round_name == "Undisclosed":
        round_name = normalize_round(" ".join([deal_sentence] + [s for s in sentences[:8] if re.search(r"\bround\b", s, re.I)][:2]))

    leads, others = [], []
    lm = re.search(r"led by\s+(.+?)(?:[.;]|$)", rest, re.I) or re.search(r"led by\s+(.+?)(?:[.;]|$)", deal_sentence, re.I) \
        or re.search(r"led by\s+(.+?)[.;]", opening[:3000], re.I)
    if lm:
        parts = re.split(r",?\s+(?:with participation from|alongside)\s+", lm.group(1), maxsplit=1, flags=re.I)
        leads = split_investors(parts[0])
        others = split_investors(parts[1]) if len(parts) > 1 else []
    if not others:
        pm = re.search(r"(?:participation from|also participated|saw participation of|alongside|"
                       r"other investors (?:include|including)|existing investors)\s+(.+?)[.;]", opening[:3000], re.I)
        if pm:
            others = [i for i in split_investors(pm.group(1)) if i not in leads]
    if not leads:
        fm = re.search(r"(?:from|by)\s+((?:[A-Z][\w&.'-]*\s?){1,5}(?:Capital|Ventures|Partners|VC|Fund|Investments|Angels|Network|Advisors|Holdings)\b"
                       r"(?:(?:,\s*|\s+and\s+)(?:[A-Z][\w&.'-]*\s?){1,5}(?:Capital|Ventures|Partners|VC|Fund|Investments|Angels|Network|Advisors|Holdings)\b)*)",
                       deal_sentence or rest)
        if fm:
            leads = split_investors(fm.group(1))

    # company brief: the appositive plus the first descriptive sentence that isn't about the raise
    brief_parts = []
    if appositive:
        brief_parts.append(f"{company} is {appositive.strip()}.")
    for s in sentences[:15]:
        low = s.lower()
        if (key in low or low.startswith(("founded", "the startup", "the company", "the platform", "it "))) \
                and not AMOUNT_RX.search(s) and not re.search(r"\b(raised|funding|round|investors?|investment|led by|capital|funds|proceeds)\b", low):
            brief_parts.append(s)
            break
    if not brief_parts and deal_sentence:
        brief_parts.append(deal_sentence)
    brief = " ".join(brief_parts)[:420]

    head_text = f"{title} {appositive or ''} {desc_meta}"
    sector = classify(f"{head_text} {head_text} {brief}")
    if sector == "Other":
        sector = classify(opening[:2000])
    sub_sector = ""
    if appositive:
        sub_sector = re.sub(r"^(?:an?|the|India's|India’s)\s+", "", appositive.strip(), flags=re.I)
        sub_sector = re.split(r"\s+(?:that|which|who|founded|offering|helping|enabling)\s+", sub_sector)[0][:60]

    early = f"{title} {desc_meta} {opening[:2000]}"
    cm = re.search(r"\b(" + CITY_RX.pattern[3:-3] + r")[- ](?:based|headquartered)", early, re.I) \
        or re.search(r"(?:headquartered|based) (?:in|out of) (" + CITY_RX.pattern[3:-3] + r")\b", early, re.I) \
        or CITY_RX.search(early)
    city = CITIES[cm.group(1).lower()] if cm else ""
    indian = bool(city) or bool(re.search(r"\bIndia|Indian\b", early)) or not FOREIGN_RX.search(early[:800])
    if FOREIGN_RX.search(f"{title} {early[:400]}") and not city:
        indian = False

    use = next((s for s in sentences[:25] if USE_RX.search(s)), "")
    if use:
        use = re.sub(r"^.*?\b(?:to|for)\s+", "", use[USE_RX.search(use).end():], count=1).strip(" .")[:200]

    return {
        "is_funding_round": True,
        "is_indian_company": indian,
        "company": company,
        "company_brief": brief,
        "sector": sector,
        "sub_sector": sub_sector,
        "round": round_name,
        "amount_text": amount_text or "Undisclosed",
        "amount_usd_mn": usd,
        "amount_inr_cr": inr,
        "lead_investors": leads,
        "investors": others,
        "city": city,
        "use_of_funds": use,
        "extraction": "rules",
    }


SCHEMA = {
    "type": "object",
    "properties": {
        "is_funding_round": {"type": "boolean", "description": "True only if this article announces a specific startup/company raising a private funding round (equity, debt or grant). False for roundups, IPOs, M&A, fund launches, results."},
        "is_indian_company": {"type": "boolean", "description": "True if the company raising is Indian or India-headquartered / India-founded with primary operations in India."},
        "company": {"type": "string"},
        "company_brief": {"type": "string", "description": "1-2 sentences: what the company does, who it serves, founding year/founders if stated."},
        "sector": {"type": "string", "enum": list(SECTORS)},
        "sub_sector": {"type": "string", "description": "A short niche label, e.g. 'B2B lending', 'GenAI dev tools'."},
        "round": {"type": "string", "enum": ROUNDS},
        "amount_text": {"type": "string", "description": "Amount as written in the article, e.g. '$15 million' or 'Rs 70 crore'. 'Undisclosed' if not stated."},
        "amount_usd_mn": {"type": ["number", "null"], "description": f"Amount in USD millions (convert INR at {USD_INR} INR/USD). null if undisclosed."},
        "amount_inr_cr": {"type": ["number", "null"], "description": "Amount in INR crore. null if undisclosed."},
        "lead_investors": {"type": "array", "items": {"type": "string"}},
        "investors": {"type": "array", "items": {"type": "string"}, "description": "Other participating investors, excluding the leads."},
        "city": {"type": "string", "description": "Company HQ city if stated, else empty."},
        "use_of_funds": {"type": "string", "description": "One short phrase, else empty."},
    },
    "required": ["is_funding_round", "is_indian_company", "company", "company_brief", "sector", "sub_sector",
                 "round", "amount_text", "amount_usd_mn", "amount_inr_cr", "lead_investors", "investors",
                 "city", "use_of_funds"],
    "additionalProperties": False,
}

PROMPT = """You are building an Indian startup funding tracker. Read this news article and extract the deal.
Use only facts stated in the article; leave strings empty (or null amounts) when not stated.
If the article covers several deals or is a roundup, set is_funding_round to false.

URL: {url}
Published: {published}
Headline: {title}
Summary: {description}

Article:
{body}"""


class LLMExtractor:
    def __init__(self):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.use_fallbacks = True
        self.calls = 0

    def _create(self, **kwargs):
        if self.use_fallbacks:
            try:
                return self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            except self.anthropic.BadRequestError as e:
                log.warning("fallbacks not accepted (%s); continuing without", e)
                self.use_fallbacks = False
        return self.client.messages.create(**kwargs)

    def generate_json(self, prompt, schema, effort="low", max_tokens=4000):
        self.calls += 1
        resp = self._create(
            model=MODEL,
            max_tokens=max_tokens,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("model declined")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)

    def extract(self, art):
        prompt = PROMPT.format(body=art["body"][:8000] or art.get("description", ""), **{
            k: art.get(k) or "" for k in ("url", "published", "title", "description")})
        data = self.generate_json(prompt, SCHEMA)
        data["extraction"] = "ai"
        return data


def make_extractor():
    """Return a callable art -> dict|None, preferring Claude when a key is configured."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        llm = LLMExtractor()

        def run(art):
            try:
                return llm.extract(art)
            except Exception as e:  # keep the crawl going; fall back to rules for this article
                log.warning("AI extraction failed for %s: %s", art["url"], e)
                return heuristic_extract(art)
        run.llm = llm
        return run
    log.info("ANTHROPIC_API_KEY not set: using rules-based extraction")
    heuristic_extract.llm = None
    return heuristic_extract
