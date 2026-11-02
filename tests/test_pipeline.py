from datetime import datetime, timezone

from scraper.article import parse_article
from scraper.extract import heuristic_extract, parse_amount
from scraper.run import merge
from scraper.sectors import classify, normalize_round
from scraper.sources import VieStories, YourStory, looks_like_funding


def test_amounts():
    assert parse_amount("raises $1.3 Million in seed")[1] == 1.3
    assert parse_amount("Rs 9.7 Crore")[2] == 9.7
    assert parse_amount("Rs 100 Cr in Series B")[2] == 100
    assert parse_amount("bags $15 Mn")[1] == 15
    assert parse_amount("INR 50 lakh")[2] == 0.5
    assert parse_amount("₹2,000 crore")[2] == 2000
    assert parse_amount("no money here") == (None, None, None)


def test_rounds():
    assert normalize_round("Pre-Series A round") == "Pre-Series A"
    assert normalize_round("Series B") == "Series B"
    assert normalize_round("Pre-Series B round") == "Pre-Series B"
    assert normalize_round("Series F funding") == "Series E+"
    assert normalize_round("pre-seed round") == "Pre-Seed"
    assert normalize_round("seed round") == "Seed"
    assert normalize_round("funding") == "Undisclosed"


def test_heuristic_headlines():
    art = {"url": "u", "title": "ReplyAll Raises Rs 9.7 Crore in Pre-Series A Round Led by Sadev Ventures and Atom XVII",
           "description": "", "body": "ReplyAll, an AI customer support platform, has raised Rs 9.7 crore."}
    x = heuristic_extract(art)
    assert x["company"] == "ReplyAll"
    assert x["round"] == "Pre-Series A"
    assert x["amount_inr_cr"] == 9.7
    assert x["lead_investors"] == ["Sadev Ventures", "Atom XVII"]
    assert x["company_brief"] == "ReplyAll is an AI customer support platform."
    assert x["sub_sector"] == "AI customer support platform"

    x = heuristic_extract({"url": "u", "title": "Rotoris bags Rs 70 Cr to expand its luxury watch business",
                           "description": "", "body": ""})
    assert x["company"] == "Rotoris" and x["amount_inr_cr"] == 70

    x = heuristic_extract({"url": "u", "title": "Fintech startup Cent raises $15 million in Series A round led by Blume Ventures",
                           "description": "", "body": ""})
    assert x["company"] == "Cent" and x["amount_usd_mn"] == 15 and x["round"] == "Series A"
    x = heuristic_extract({"url": "u", "title": "CHOSEN raises $5 million in Series A led by Fireside Ventures, with participation from BOLD and other angel investors",
                           "description": "", "body": "Angel investors also joined."})
    assert x["round"] == "Series A" and x["lead_investors"] == ["Fireside Ventures"] and x["investors"] == ["BOLD"]
    assert heuristic_extract({"url": "u", "title": "From Homemade Badi to GomatiRoots: Shital Kumari raises Rs 1 lakh", "description": "", "body": ""}) is None
    assert heuristic_extract({"url": "u", "title": "Paytm Q2 results: profit rises", "description": "", "body": ""}) is None


def test_body_only_extraction():
    # YourStory-style headline that doesn't follow "X raises $Y"
    art = {"url": "u", "title": "This Pune startup wants to fix cold-chain logistics for pharma",
           "description": "",
           "body": "Pune-based ColdCart, a cold-chain logistics platform for pharma distributors, has raised $4 million "
                   "in a Series A round led by Chiratae Ventures, with participation from Venture Catalysts and Blume Founders Fund. "
                   "Founded in 2021 by Asha Rao, ColdCart runs temperature-controlled warehouses across 12 cities. "
                   "The startup will use the funds to expand into tier-2 cities and build its tracking software."}
    x = heuristic_extract(art)
    assert x["company"] == "ColdCart"
    assert x["round"] == "Series A" and x["amount_usd_mn"] == 4
    assert x["lead_investors"] == ["Chiratae Ventures"]
    assert x["investors"] == ["Venture Catalysts", "Blume Founders Fund"]
    assert x["city"] == "Pune" and x["sector"] == "Logistics & Supply Chain"
    assert x["company_brief"].startswith("ColdCart is a cold-chain logistics platform")
    assert "Founded in 2021" in x["company_brief"]
    assert x["use_of_funds"].startswith("expand into tier-2 cities")
    assert x["is_indian_company"]


def test_investor_clauses_dropped():
    from scraper.extract import split_investors
    assert split_investors("Soundous Moufakir, MoroMaa combines Moroccan beauty traditions") == ["Soundous Moufakir"]
    assert split_investors("strategic investors and a consortium of CXOs") == []


def test_foreign_company_flagged():
    x = heuristic_extract({"url": "u", "title": "US-based Acme raises $5 million in seed round", "description": "", "body": ""})
    assert x and not x["is_indian_company"]


def test_classify():
    assert classify("swipe-based trivia and puzzle app") == "Media, Gaming & Content"
    assert classify("digital lending NBFC for MSMEs") == "Fintech"
    assert classify("venture capital firm") == "Other"  # 'capital' must not match 'api'


def test_slug_filter():
    assert looks_like_funding("https://yourstory.com/2026/10/rotoris-bags-rs-70-cr-to-expand-its-luxury-watch-business")
    assert not looks_like_funding("https://yourstory.com/2026/10/lessons-in-chemistry-5-takeaways-bonnie-garmus-novel")
    assert not looks_like_funding("https://yourstory.com/2026/10/weekly-funding-roundup-oct-19-23")


def test_merge_dedupes_across_sites():
    deals = []
    a = {"company": "Rotoris", "round": "Series A", "date": "2026-10-27", "amount_text": "Rs 70 crore",
         "sources": [{"site": "viestories", "url": "v"}], "city": ""}
    b = {"company": "Rotoris", "round": "Series A", "date": "2026-10-28", "amount_text": "Rs 70 Cr",
         "sources": [{"site": "yourstory", "url": "y"}], "city": "Mumbai"}
    assert merge(deals, a) is True
    assert merge(deals, b) is False
    assert len(deals) == 1 and len(deals[0]["sources"]) == 2 and deals[0]["city"] == "Mumbai"


def test_parse_article_meta():
    html = """<html><head><title>X raises $2M | YourStory</title>
    <meta property="article:published_time" content="2026-10-27T10:30:00+05:30">
    <meta property="og:description" content="desc"></head>
    <body><nav>menu</nav><article><p>X, a Bengaluru-based SaaS startup, has raised $2 million in seed funding.</p>
    <p>Subscribe to our newsletter for more updates and news.</p></article></body></html>"""
    art = parse_article(html, "https://yourstory.com/2026/10/x-raises-2m")
    assert art["title"] == "X raises $2M"
    assert art["published"] == "2026-10-27T05:00:00+00:00"
    assert "Subscribe" not in art["body"] and "Bengaluru" in art["body"]


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.stats = {}

    def get(self, url):
        return self.pages.get(url)


def test_viestories_discovery():
    base = "https://viestories.com"
    pages = {
        f"{base}/webcontent-sitemap.xml": """<sitemapindex><sitemap><loc>https://viestories.com/sitemap_2026-10-27.xml</loc></sitemap>
            <sitemap><loc>https://viestories.com/sitemap_2026-01-01.xml</loc></sitemap></sitemapindex>""",
        f"{base}/sitemap_2026-10-27.xml": """<urlset>
            <url><loc>https://viestories.com/funding-alert/cent-raises-15-million-in-series-a-round-led-by-blume-ventures-12757597</loc><lastmod>2026-10-27T15:45:28+05:30</lastmod></url>
            <url><loc>https://viestories.com/press-release/linen-shirts-12757439</loc><lastmod>2026-10-27T14:54:19+05:30</lastmod></url>
            <url><loc>https://viestories.com/funding-alert/indian-startup-funding-roundup-this-week-oct-19-oct-23-12744688</loc></url>
            </urlset>""",
        f"{base}/funding-alert?page=1": '<a href="/funding-alert/maasi-raises-rs-6-crore-in-pre-seed-round-led-by-better-capital-12757350">x</a>',
    }
    src = VieStories(FakeClient(pages))
    c = src.discover(datetime(2026, 8, 1, tzinfo=timezone.utc), datetime(2026, 10, 29, tzinfo=timezone.utc), max_pages=3)
    assert len(c) == 2
    assert src.channels == {"daily_sitemap": 1, "listing": 1}


def test_yourstory_discovery():
    base = "https://yourstory.com"
    pages = {
        f"{base}/sitemap_index.xml": """<sitemapindex><sitemap><loc>https://yourstory.com/sitemap-2026-10.xml</loc></sitemap>
            <sitemap><loc>https://yourstory.com/sitemap-2025-01.xml</loc></sitemap></sitemapindex>""",
        f"{base}/sitemap-2026-10.xml": """<urlset>
            <url><loc>https://yourstory.com/2026/10/rotoris-bags-rs-70-cr-to-expand-its-luxury-watch-business</loc></url>
            <url><loc>https://yourstory.com/2026/10/lessons-in-chemistry-5-takeaways</loc></url></urlset>""",
        f"{base}/category/funding?page=1": '<a href="/2026/10/matiks-pre-series-a">a</a><a href="/2025/01/old-one">b</a>',
    }
    src = YourStory(FakeClient(pages))
    c = src.discover(datetime(2026, 8, 1, tzinfo=timezone.utc), datetime(2026, 10, 29, tzinfo=timezone.utc), max_pages=3)
    assert set(c) == {f"{base}/2026/10/rotoris-bags-rs-70-cr-to-expand-its-luxury-watch-business",
                      f"{base}/2026/10/matiks-pre-series-a"}


def test_custom_range_limits():
    import pytest
    from scraper.run import parse_range
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    start, end = parse_range("2026-05-01", "2026-06-30", now)
    assert start.isoformat() == "2026-04-30T18:30:00+00:00"  # midnight IST
    assert end.date().isoformat() == "2026-06-30"
    _, end = parse_range("2026-10-01", "2027-01-01", now)  # future end is clipped to now
    assert end == now
    with pytest.raises(SystemExit):
        parse_range("2025-10-01", "2026-01-01", now)  # more than a year back
    with pytest.raises(SystemExit):
        parse_range("2026-06-01", "2026-05-01", now)  # reversed
    with pytest.raises(SystemExit):
        parse_range("01/05/2026", None, now)


def test_non_deal_stories_rejected():
    for url, title in [
        ("https://yourstory.com/2026/08/indian-deeptech-investments-reach-114-billion-report", "The deeptech sector raised $11.4 billion: report"),
        ("https://yourstory.com/2026/09/indias-tech-cos-raise-usd-103b-in-2026-tracxn-report", "India's tech companies raise $10.3B in 2026"),
        ("https://viestories.com/funding-alert/accel-raises-550-million-for-ninth-india-early-stage-fund-12252285", "Accel raises $550 Million for ninth India early-stage fund"),
        ("u1", "Odisha announces 870-acre Silicon Valley, receives Rs 23,600 Cr investment"),
        ("u2", "Elevation Capital closes $500 million Fund IX to back AI startups"),
        ("u3", "Ola Electric gets board nod to invest ₹2,000 cr in EV, Cell Manufacturing"),
        ("https://yourstory.com/2026/08/ola-electric-secures-5-year-pli-window-get-upto-7240cr-incentives", "Ola Electric secures 5-year PLI window, gets up to Rs 7,240cr incentives"),
    ]:
        assert heuristic_extract({"url": url, "title": title, "description": "", "body": ""}) is None, title


def test_weekday_trimmed_from_company():
    x = heuristic_extract({"url": "u", "title": "Simple Energy on Wednesday raised Rs 1,750 Cr in Series C", "description": "", "body": ""})
    assert x["company"] == "Simple Energy"


def test_deals_led_by_funds_kept():
    x = heuristic_extract({"url": "https://viestories.com/funding-alert/onto-raises-1-mn-led-by-stargazer-fund-12759698",
                           "title": "Travel Platform Onto Raises $1 Mn in Pre-Seed Round Led By Stargazer Fund", "description": "", "body": ""})
    assert x["company"] == "Onto" and x["lead_investors"] == ["Stargazer Fund"]
