"""Sitemap, RSS and listing-page helpers shared by both sources."""
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup


def parse_dt(value):
    """Parse ISO-8601 or RFC-822 date strings into aware UTC datetimes."""
    if not value:
        return None
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_sitemap(xml):
    """Return (child_sitemaps, urls). Each item is a dict with loc/lastmod/title."""
    soup = BeautifulSoup(xml, "xml")
    children = [
        {"loc": s.find("loc").get_text(strip=True),
         "lastmod": parse_dt(s.find("lastmod").get_text() if s.find("lastmod") else None)}
        for s in soup.find_all("sitemap") if s.find("loc")
    ]
    urls = []
    for u in soup.find_all("url"):
        loc = u.find("loc")
        if not loc:
            continue
        item = {"loc": loc.get_text(strip=True), "lastmod": None, "title": None}
        lm = u.find("lastmod")
        pub = u.find("publication_date")  # news:publication_date
        item["lastmod"] = parse_dt((pub or lm).get_text()) if (pub or lm) else None
        title = u.find("title")  # news:title
        if title:
            item["title"] = title.get_text(strip=True)
        urls.append(item)
    return children, urls


def parse_rss(xml):
    soup = BeautifulSoup(xml, "xml")
    out = []
    for it in soup.find_all("item"):
        link = it.find("link")
        if not link:
            continue
        out.append({
            "loc": link.get_text(strip=True),
            "lastmod": parse_dt(it.find("pubDate").get_text() if it.find("pubDate") else None),
            "title": it.find("title").get_text(strip=True) if it.find("title") else None,
        })
    return out


def links_matching(html, base, pattern):
    """All absolute links on a page whose path matches `pattern` (regex)."""
    soup = BeautifulSoup(html, "lxml")
    rx = re.compile(pattern)
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].split("?")[0]
        if href.startswith("/"):
            href = base.rstrip("/") + href
        if not href.startswith(base):
            continue
        path = href[len(base.rstrip("/")):]
        if rx.search(path) and href not in seen:
            seen.add(href)
            out.append(href)
    return out
