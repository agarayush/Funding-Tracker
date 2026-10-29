"""Turn an article page into title / date / description / body text."""
import json
import re

from bs4 import BeautifulSoup

from .sitemaps import parse_dt

BOILERPLATE = re.compile(
    r"(subscribe|newsletter|follow us|also read|read more|download the app|sign up|"
    r"click here|join our|whatsapp|telegram|copyright|all rights reserved)",
    re.I,
)


def _meta(soup, *names):
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n}) \
            or soup.find("meta", attrs={"itemprop": n})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _json_ld(soup):
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and str(item.get("@type", "")).endswith(("NewsArticle", "Article", "BlogPosting")):
                return item
    return {}


def parse_article(html, url):
    soup = BeautifulSoup(html, "lxml")
    ld = _json_ld(soup)
    title = ld.get("headline") or _meta(soup, "og:title", "twitter:title") \
        or (soup.title.get_text(strip=True) if soup.title else "")
    title = re.sub(r"\s*[|\-–]\s*(YourStory|Viestories|VIE Stories).*$", "", title, flags=re.I).strip()
    published = parse_dt(ld.get("datePublished")) or parse_dt(_meta(
        soup, "article:published_time", "datePublished", "publish-date", "og:published_time"))
    if not published:
        t = soup.find("time", attrs={"datetime": True})
        published = parse_dt(t["datetime"]) if t else None
    description = ld.get("description") or _meta(soup, "og:description", "description") or ""

    for junk in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe"]):
        junk.decompose()
    container = soup.find("article") or soup.find(attrs={"itemprop": "articleBody"}) or soup.find("main") or soup
    paras = []
    for p in container.find_all(["p", "li", "h2", "h3"]):
        text = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        if len(text) < 40 or BOILERPLATE.search(text[:60]):
            continue
        if text not in paras:
            paras.append(text)
    body = "\n".join(paras)
    if len(body) < 200 and ld.get("articleBody"):
        body = ld["articleBody"]

    tags = _meta(soup, "news_keywords", "keywords") or ""
    return {
        "url": url,
        "title": title,
        "published": published.isoformat() if published else None,
        "description": description,
        "body": body[:12000],
        "keywords": [k.strip() for k in tags.split(",") if k.strip()][:15],
    }
