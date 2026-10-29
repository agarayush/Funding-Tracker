"""AI-written sector briefs with India-specific tailwinds and headwinds."""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "brief": {"type": "string", "description": "3-4 sentences on the sector in India today: size, business models, who is funding it."},
        "tailwinds": {"type": "array", "items": {"type": "string"}, "description": "4-5 concise India-specific tailwinds (policy, demand, infra, capital)."},
        "headwinds": {"type": "array", "items": {"type": "string"}, "description": "4-5 concise India-specific headwinds or risks."},
        "funding_pulse": {"type": "string", "description": "1-2 sentences reading the recent deals listed below: stage mix, cheque sizes, active investors, themes."},
    },
    "required": ["brief", "tailwinds", "headwinds", "funding_pulse"],
    "additionalProperties": False,
}

PROMPT = """You are a venture analyst covering Indian startups. Write a sector note for "{sector}" in India
as of {today}. Be specific to India (regulation such as RBI/SEBI/IRDAI/MeitY, government schemes,
consumer behaviour, infrastructure, capital availability). Keep each bullet under 25 words.

Recent Indian deals in this sector tracked over the last few months ({n} deals, about ${total:.0f}M disclosed):
{deals}"""


def sector_stats(deals):
    out = {}
    for d in deals:
        s = out.setdefault(d["sector"], {"deals": 0, "usd_mn": 0.0, "rounds": Counter(), "investors": Counter()})
        s["deals"] += 1
        s["usd_mn"] += d.get("amount_usd_mn") or 0
        s["rounds"][d["round"]] += 1
        for inv in d.get("lead_investors", []) + d.get("investors", []):
            s["investors"][inv] += 1
    return out


def refresh(sectors, deals, llm, force=False, max_age_days=21):
    """Regenerate notes for sectors that are new, stale, or have notably more deals."""
    now = datetime.now(timezone.utc)
    stats = sector_stats(deals)
    for name, st in stats.items():
        entry = sectors.get(name, {})
        entry.update({
            "deal_count": st["deals"],
            "total_usd_mn": round(st["usd_mn"], 2),
            "top_rounds": st["rounds"].most_common(4),
            "top_investors": st["investors"].most_common(8),
        })
        sectors[name] = entry
        if llm is None:
            continue
        generated = entry.get("generated_at")
        stale = not generated or now - datetime.fromisoformat(generated) > timedelta(days=max_age_days)
        grew = st["deals"] - entry.get("deals_at_generation", 0) >= 5
        if not (force or stale or grew or entry.get("source") != "ai-pipeline"):
            continue
        recent = sorted((d for d in deals if d["sector"] == name), key=lambda d: d["date"], reverse=True)[:40]
        lines = "\n".join(
            f"- {d['date']}: {d['company']} ({d.get('sub_sector') or ''}) {d['round']}, {d['amount_text']}, "
            f"led by {', '.join(d.get('lead_investors') or []) or 'n/a'}" for d in recent)
        try:
            note = llm.generate_json(
                PROMPT.format(sector=name, today=now.date().isoformat(), n=st["deals"], total=st["usd_mn"], deals=lines),
                SCHEMA, effort="medium", max_tokens=8000)
        except Exception as e:
            log.warning("sector note failed for %s: %s", name, e)
            continue
        entry.update(note)
        entry.update({"generated_at": now.isoformat(), "deals_at_generation": st["deals"], "source": "ai-pipeline"})
        log.info("refreshed sector note: %s", name)
    return sectors
