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
