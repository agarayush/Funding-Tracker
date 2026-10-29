"""Candidate-URL discovery for viestories.com and yourstory.com.

Each source combines several channels (daily/monthly sitemaps, news sitemap,
RSS, paginated funding listings) so a gap in one channel is covered by the
others. Every channel's hit count is recorded for the coverage report.
"""
import logging
import re
from collections import Counter
from datetime import timedelta

from .sitemaps import links_matching, parse_rss, parse_sitemap

log = logging.getLogger(__name__)

FUNDING_SLUG = re.compile(
    r"(raise[sd]?|raising|bags?|secures?|nets|gets-|closes|fund(ing|raise)|series-[a-h]\b|"
    r"seed|pre-series|bridge-round|crore|-cr-|-cr$|million|-mn-|billion|invest(s|ment)|"
    r"led-by|round|backed|debt-financing|venture-debt|capital-infusion)"
)
EXCLUDE_SLUG = re.compile(
    r"(roundup|round-up|weekly-funding|funding-this-week|top-\d+|ipo|listing-day|q[1-4]-fy|"
    r"results|how-to|tips|guide-to|explained|podcast|webinar|webstory|layoff)"
)


def looks_like_funding(url, title=None):
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    text = slug + " " + re.sub(r"[^a-z0-9]+", "-", (title or "").lower())
    return bool(FUNDING_SLUG.search(text)) and not EXCLUDE_SLUG.search(text)


class Source:
    name = ""
    base = ""

    def __init__(self, client):
        self.client = client
        self.channels = Counter()
        self.candidates = {}  # url -> {"lastmod", "title", "via": set()}

    def add(self, url, channel, lastmod=None, title=None):
        url = url.split("?")[0].split("#")[0].rstrip("/")
        c = self.candidates.setdefault(url, {"lastmod": None, "title": None, "via": set()})
        c["lastmod"] = c["lastmod"] or lastmod
        c["title"] = c["title"] or title
        if channel not in c["via"]:
            c["via"].add(channel)
            self.channels[channel] += 1

    def in_window(self, dt, start, end):
        return dt is None or start <= dt <= end + timedelta(days=1)


class VieStories(Source):
    name = "viestories"
    base = "https://viestories.com"
    ARTICLE = r"^/funding-alert/[\w-]+-\d+$"

    def discover(self, start, end, max_pages=150):
        self._daily_sitemaps(start, end)
        self._news_sitemap(start, end)
        self._rss(start, end)
        self._listing(start, max_pages)
        return self.candidates

    def _keep(self, url, title=None):
        path = url[len(self.base):]
        if re.match(self.ARTICLE, path):
            return not EXCLUDE_SLUG.search(path)
        # funding news that was filed under another section (e.g. startupnews)
        return bool(re.match(r"^/(startupnews|insight/startup-insight|tech)/", path)) and looks_like_funding(url, title)

    def _daily_sitemaps(self, start, end):
        xml = self.client.get(f"{self.base}/webcontent-sitemap.xml")
        if not xml:
            return
        children, _ = parse_sitemap(xml)
        for child in children:
            m = re.search(r"sitemap_(\d{4}-\d{2}-\d{2})\.xml", child["loc"])
            if not m:
                continue
            day = m.group(1)
            if not (start.date().isoformat() <= day <= end.date().isoformat()):
                continue
            body = self.client.get(child["loc"])
            if not body:
                continue
            for u in parse_sitemap(body)[1]:
                if u["loc"].startswith(self.base) and self._keep(u["loc"]):
                    self.add(u["loc"], "daily_sitemap", u["lastmod"])

    def _news_sitemap(self, start, end):
        xml = self.client.get(f"{self.base}/news-sitemap.xml")
        for u in parse_sitemap(xml)[1] if xml else []:
            if self._keep(u["loc"], u["title"]) and self.in_window(u["lastmod"], start, end):
                self.add(u["loc"], "news_sitemap", u["lastmod"], u["title"])

    def _rss(self, start, end):
        xml = self.client.get(f"{self.base}/rss")
        for u in parse_rss(xml) if xml else []:
            if u["loc"].startswith(self.base) and self._keep(u["loc"], u["title"]) and self.in_window(u["lastmod"], start, end):
                self.add(u["loc"], "rss", u["lastmod"], u["title"])

    def _listing(self, start, max_pages):
        """Walk /funding-alert?page=N until the listing is older than `start`."""
        for page in range(1, max_pages + 1):
            html = self.client.get(f"{self.base}/funding-alert?page={page}")
            if not html:
                break
            links = links_matching(html, self.base, self.ARTICLE)
            if not links:
                break
            dates = []
            for link in links:
                known = self.candidates.get(link)
                if known and known["lastmod"]:
                    dates.append(known["lastmod"])
                if not EXCLUDE_SLUG.search(link):
                    self.add(link, "listing")
            # listing is newest-first: stop once the page is entirely older than start
            if dates and max(dates) < start:
                break


class YourStory(Source):
    name = "yourstory"
    base = "https://yourstory.com"
    # /2026/10/slug or /ai-story/2026/10/slug
    ARTICLE = r"^/(?:[\w-]+/)?(\d{4})/(\d{2})/[\w-]+$"
    SECTIONS = ["", "/ai-story", "/enterprise-story", "/smbstory", "/herstory", "/socialstory"]

    def discover(self, start, end, max_pages=80):
        months = self._months(start, end)
        for section in self.SECTIONS:
            self._sitemap_index(f"{self.base}{section}/sitemap_index.xml", months, start, end)
        self._news_sitemap(start, end)
        self._rss(start, end)
        self._listing(start, max_pages)
        return self.candidates

    @staticmethod
    def _months(start, end):
        months, d = set(), start.replace(day=1)
        while d <= end:
            months.add((d.year, d.month))
            d = (d + timedelta(days=32)).replace(day=1)
        return months

    def _url_month(self, url):
        m = re.match(self.ARTICLE, url[len(self.base):])
        return (int(m.group(1)), int(m.group(2))) if m else None

    def _keep(self, url, title, months):
        if not url.startswith(self.base):
            return False
        month = self._url_month(url)
        return month in months and looks_like_funding(url, title)

    def _sitemap_index(self, index_url, months, start, end, depth=0):
        xml = self.client.get(index_url)
        if not xml:
            return
        children, urls = parse_sitemap(xml)
        for u in urls:
            if self._keep(u["loc"], u["title"], months):
                self.add(u["loc"], "sitemap", u["lastmod"], u["title"])
        for child in children:
            loc = child["loc"]
            if re.search(r"(compan|topic|tag|author|categor|page|video|webstor|hindi|tamil)", loc):
                continue
            # child names usually carry a year/month; otherwise rely on lastmod
            ym = re.search(r"(20\d{2})[-_/]?(\d{2})", loc)
            if ym and (int(ym.group(1)), int(ym.group(2))) not in months:
                continue
            if not ym and child["lastmod"] and child["lastmod"] < start:
                continue
            if depth < 2:
                self._sitemap_index(loc, months, start, end, depth + 1)

    def _news_sitemap(self, start, end):
        months = self._months(start, end)
        xml = self.client.get(f"{self.base}/news-sitemap.xml")
        for u in parse_sitemap(xml)[1] if xml else []:
            if self._keep(u["loc"], u["title"], months):
                self.add(u["loc"], "news_sitemap", u["lastmod"], u["title"])

    def _rss(self, start, end):
        months = self._months(start, end)
        xml = self.client.get(f"{self.base}/feed")
        for u in parse_rss(xml) if xml else []:
            if self._keep(u["loc"], u["title"], months) and self.in_window(u["lastmod"], start, end):
                self.add(u["loc"], "rss", u["lastmod"], u["title"])

    def _listing(self, start, max_pages):
        """/category/funding is entirely funding news, so keep every in-window link."""
        months = self._months(start, start.replace(year=start.year + 1))
        oldest_month = (start.year, start.month)
        for page in range(1, max_pages + 1):
            html = self.client.get(f"{self.base}/category/funding?page={page}")
            if not html:
                break
            links = links_matching(html, self.base, self.ARTICLE)
            if not links:
                break
            page_months = []
            for link in links:
                month = self._url_month(link)
                page_months.append(month)
                if month in months and not EXCLUDE_SLUG.search(link):
                    self.add(link, "funding_listing")
            dated = [m for m in page_months if m]
            if dated and max(dated) < oldest_month:
                break
