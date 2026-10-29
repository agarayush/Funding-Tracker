"""Crawl, extract, dedupe and publish the funding dataset.

    python -m scraper.run --days 90     # first run / backfill
    python -m scraper.run               # weekly incremental (since last run, 7-day overlap)
"""
import argparse
import hashlib
import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import insights
from .article import parse_article
from .extract import make_extractor
from .http import PoliteClient
from .sitemaps import parse_dt
from .sources import VieStories, YourStory

log = logging.getLogger("tracker")
DATA = Path(__file__).resolve().parent.parent / "docs" / "data"
IST = timezone(timedelta(hours=5, minutes=30))


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def save(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str) + "\n")


def norm_company(name):
    name = re.sub(r"\(.*?\)", "", name.lower())
    name = re.sub(r"\b(pvt|private|ltd|limited|inc|technologies|technology|labs|india|\.com|\.ai)\b", "", name)
    return re.sub(r"[^a-z0-9]", "", name)


def iso_week(date_str):
    y, w, _ = datetime.fromisoformat(date_str).isocalendar()
    return f"{y}-W{w:02d}"


def crawl_source(source, start, end, processed, max_pages):
    """Discover candidates and fetch+parse the ones not processed before."""
    cands = source.discover(start, end, max_pages=max_pages)
    log.info("%s: %d candidate URLs via %s", source.name, len(cands), dict(source.channels))
    arts = []
    for url, meta in sorted(cands.items()):
        if url in processed:
            continue
        html = source.client.get(url)
        if not html:
            arts.append({"url": url, "error": "fetch_failed", "lastmod": meta["lastmod"]})
            continue
        art = parse_article(html, url)
        art["title"] = art["title"] or meta["title"] or ""
        published = parse_dt(art["published"]) or meta["lastmod"]
        art["published"] = published.isoformat() if published else None
        arts.append(art)
    return arts


def build_deal(art, x, site):
    date = parse_dt(art["published"]).astimezone(IST).date().isoformat()
    return {
        "id": hashlib.sha1(f"{norm_company(x['company'])}|{x['round']}|{date[:7]}".encode()).hexdigest()[:12],
        "date": date,
        "company": x["company"].strip(),
        "company_brief": x.get("company_brief", "").strip(),
        "sector": x["sector"],
        "sub_sector": x.get("sub_sector", ""),
        "round": x["round"],
        "amount_text": x.get("amount_text") or "Undisclosed",
        "amount_usd_mn": x.get("amount_usd_mn"),
        "amount_inr_cr": x.get("amount_inr_cr"),
        "lead_investors": x.get("lead_investors") or [],
        "investors": x.get("investors") or [],
        "city": x.get("city", ""),
        "use_of_funds": x.get("use_of_funds", ""),
        "headline": art["title"],
        "sources": [{"site": site, "url": art["url"]}],
        "extraction": x.get("extraction", ""),
    }


def merge(deals, new):
    """Same company + same round within 45 days = same deal reported twice."""
    key = norm_company(new["company"])
    nd = datetime.fromisoformat(new["date"])
    for d in deals:
        if norm_company(d["company"]) != key:
            continue
        same_round = d["round"] == new["round"] or "Undisclosed" in (d["round"], new["round"])
        if same_round and abs((datetime.fromisoformat(d["date"]) - nd).days) <= 45:
            for s in new["sources"]:
                if s["url"] not in {x["url"] for x in d["sources"]}:
                    d["sources"].append(s)
            for k, v in new.items():
                if k not in ("sources", "id", "date") and v and (not d.get(k) or d.get(k) in ("Undisclosed", "Other")):
                    d[k] = v
            d["date"] = min(d["date"], new["date"])
            return False
    deals.append(new)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, help="look back N days (default: since last run, or 90 on first run)")
    ap.add_argument("--max-pages", type=int, default=150, help="max listing pages per source")
    ap.add_argument("--sources", default="viestories,yourstory")
    ap.add_argument("--reprocess", action="store_true", help="ignore the processed-URL cache")
    ap.add_argument("--refresh-insights", action="store_true")
    ap.add_argument("--workers", type=int, default=8, help="parallel AI extraction calls")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    state = load("state.json", {})
    deals = load("deals.json", [])
    sectors = load("sectors.json", {})
    coverage = load("coverage.json", {"weeks": {}, "runs": []})
    processed = {} if args.reprocess else load("processed.json", {})

    end = datetime.now(timezone.utc)
    if args.days:
        start = end - timedelta(days=args.days)
    elif state.get("last_run_end"):
        start = datetime.fromisoformat(state["last_run_end"]) - timedelta(days=7)
    else:
        start = end - timedelta(days=90)
    log.info("window %s -> %s", start.date(), end.date())
    if args.reprocess:
        # rebuild the window from scratch so re-extracted fields replace the old ones
        cutoff = start.astimezone(IST).date().isoformat()
        deals = [d for d in deals if d["date"] < cutoff]
        coverage["weeks"] = {w: v for w, v in coverage["weeks"].items() if w < iso_week(cutoff)}

    classes = {"viestories": VieStories, "yourstory": YourStory}
    sources = [classes[s](PoliteClient()) for s in args.sources.split(",")]
    with ThreadPoolExecutor(len(sources)) as pool:  # one polite crawler per host, in parallel
        results = list(pool.map(lambda s: crawl_source(s, start, end, processed, args.max_pages), sources))

    extract = make_extractor()
    run_stats = {"started": end.isoformat(), "window": [start.date().isoformat(), end.date().isoformat()],
                 "extraction": "ai" if extract.llm else "rules", "sources": {}}
    weeks = coverage["weeks"]
    added = 0
    for source, arts in zip(sources, results):
        st = defaultdict(int, candidates=len(source.candidates), new_urls=len(arts))
        st["channels"] = dict(source.channels)
        in_window = []
        for a in arts:
            if a.get("error"):
                st["fetch_failed"] += 1
                continue
            pub = parse_dt(a["published"])
            if not pub or not (start - timedelta(days=1) <= pub <= end + timedelta(days=1)):
                st["outside_window"] += 1
                continue
            in_window.append(a)
        with ThreadPoolExecutor(args.workers if extract.llm else 1) as pool:
            extracted = list(pool.map(extract, in_window))
        for a, x in zip(in_window, extracted):
            week = iso_week(parse_dt(a["published"]).astimezone(IST).date().isoformat())
            wk = weeks.setdefault(week, {}).setdefault(source.name, {"articles": 0, "deals": 0, "rejected": 0})
            wk["articles"] += 1
            if not x or not x.get("company"):
                reason = "unparsed"
            elif not x["is_funding_round"]:
                reason = "not_a_funding_round"
            elif not x["is_indian_company"]:
                reason = "not_indian"
            else:
                reason = None
            if reason:
                st[reason] += 1
                wk["rejected"] += 1
                processed[a["url"]] = reason
                continue
            wk["deals"] += 1
            st["deals"] += 1
            processed[a["url"]] = "deal"
            if merge(deals, build_deal(a, x, source.name)):
                added += 1
        st["http"] = source.client.stats
        run_stats["sources"][source.name] = dict(st)
        log.info("%s: %s", source.name, dict(st))

    deals.sort(key=lambda d: (d["date"], d["company"]), reverse=True)
    sectors = insights.refresh(sectors, deals, extract.llm, force=args.refresh_insights)
    fields = ["company_brief", "sub_sector", "amount_usd_mn", "lead_investors", "investors", "city", "use_of_funds"]
    window_deals = [d for d in deals if d["date"] >= start.astimezone(IST).date().isoformat()]
    run_stats["fill_rates"] = {f: round(sum(1 for d in window_deals if d.get(f)) / max(len(window_deals), 1), 3) for f in fields}
    run_stats["fill_rates"]["round_known"] = round(sum(1 for d in window_deals if d["round"] != "Undisclosed") / max(len(window_deals), 1), 3)
    run_stats["fill_rates"]["sector_known"] = round(sum(1 for d in window_deals if d["sector"] != "Other") / max(len(window_deals), 1), 3)
    run_stats["new_deals"] = added
    run_stats["total_deals"] = len(deals)
    coverage["runs"] = (coverage["runs"] + [run_stats])[-60:]
    coverage["weeks"] = dict(sorted(weeks.items(), reverse=True))

    save("deals.json", deals)
    save("sectors.json", sectors)
    save("coverage.json", coverage)
    save("processed.json", processed)
    save("state.json", {"last_run_end": end.isoformat(), "updated": end.isoformat()})
    log.info("done: %d new deals, %d total", added, len(deals))


if __name__ == "__main__":
    main()
