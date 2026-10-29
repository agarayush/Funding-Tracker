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
        if p and len(p) < 70 and not re.search(r"\b(?:others|other (?:angel )?investors|angels?)$", p, re.I):
            out.append(p)
    return out


def heuristic_extract(art):
    title = art["title"]
    body = art.get("body", "")
    text = f"{title}. {art.get('description', '')} {body[:3000]}"
    m = re.match(rf"^(?P<company>.+?)\s+{VERB}\s+(?P<rest>.+)$", title, re.I)
    if not m:
        return None
    company = re.sub(r"^(?:[\w-]+-based|homegrown|bengaluru's|mumbai's|delhi's)\s+", "", m.group("company"), flags=re.I)
    # "Fintech startup Cent" -> "Cent"
    company = re.sub(r"^.*\b(?:startup|platform|brand|company|firm|maker|provider)\s+(?=\S)", "", company, flags=re.I)
    amount_text, usd, inr = parse_amount(m.group("rest"))
    if not amount_text:
        amount_text, usd, inr = parse_amount(text)
    if ":" in company or len(company.split()) > 6:  # feature stories, not deal announcements
        return None
    round_name = normalize_round(m.group("rest"))
    if round_name == "Undisclosed":
        round_name = normalize_round(" ".join(re.findall(r"[^.]*\b(?:round|funding)\b[^.]*", body[:1500])[:2]))
    leads = []
    lm = re.search(r"led by\s+(.+?)(?:[.;]|$)", m.group("rest"), re.I) or re.search(r"led by\s+(.+?)[.;]", text, re.I)
    others = []
    if lm:
        parts = re.split(r",?\s+(?:with participation from|alongside)\s+", lm.group(1), maxsplit=1, flags=re.I)
        lead_text, part_text = parts[0], parts[1] if len(parts) > 1 else ""
        leads = split_investors(lead_text)
        others = split_investors(part_text) if part_text else []
    pm = re.search(r"(?:participation from|also participated|alongside|existing investors)\s+(.+?)[.;]", text, re.I)
    if pm and not others:
        others = [i for i in split_investors(pm.group(1)) if i not in leads]
    first = next((s for s in re.split(r"(?<=[.!?])\s+", body) if company.split()[0].lower() in s.lower()), "")
    brief = first[:300]
    return {
        "is_funding_round": True,
        "is_indian_company": True,
        "company": company.strip(),
        "company_brief": brief,
        "sector": classify(f"{title} {brief} {art.get('description', '')}"),
        "sub_sector": "",
        "round": round_name,
        "amount_text": amount_text or "Undisclosed",
        "amount_usd_mn": usd,
        "amount_inr_cr": inr,
        "lead_investors": leads,
        "investors": others,
        "city": "",
        "use_of_funds": "",
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
