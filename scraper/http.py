"""Polite HTTP client: per-host rate limiting, retries, robots.txt checks."""
import logging
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 FundingTracker/1.0 (+https://github.com/agarayush/Funding-Tracker)"
)


class PoliteClient:
    def __init__(self, delay=1.0, timeout=30, max_retries=4):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        })
        self._last_hit = {}
        self._robots = {}
        self.stats = {"requests": 0, "errors": 0, "robots_blocked": 0}

    def _robots_for(self, url):
        host = urlparse(url).netloc
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.session.get(f"https://{host}/robots.txt", timeout=self.timeout)
                rp.parse(r.text.splitlines() if r.ok else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[host] = rp
        return self._robots[host]

    def allowed(self, url):
        return self._robots_for(url).can_fetch("*", url)

    def _wait(self, host):
        elapsed = time.monotonic() - self._last_hit.get(host, 0)
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_hit[host] = time.monotonic()

    def get(self, url):
        """Return response text, or None on failure / robots disallow."""
        if not self.allowed(url):
            log.warning("robots.txt disallows %s", url)
            self.stats["robots_blocked"] += 1
            return None
        host = urlparse(url).netloc
        for attempt in range(self.max_retries):
            self._wait(host)
            self.stats["requests"] += 1
            try:
                r = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                log.warning("GET %s failed (%s), attempt %d", url, e, attempt + 1)
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                r.encoding = r.encoding or "utf-8"
                return r.text
            if r.status_code in (429, 500, 502, 503, 504):
                wait = int(r.headers.get("Retry-After", 0) or 0) or 2 ** (attempt + 1)
                log.warning("GET %s -> %d, retrying in %ss", url, r.status_code, wait)
                time.sleep(min(wait, 60))
                continue
            log.warning("GET %s -> %d", url, r.status_code)
            break
        self.stats["errors"] += 1
        return None
