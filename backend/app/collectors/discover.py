"""Auto-discovery: from just a domain, suggest the sources to track.

Only a handful of polite requests (robots.txt respected, cached, >= 2 s per host):
  1. the homepage: name, pricing / changelog / blog / careers links, <link rel="alternate"> feeds
  2. the careers page if one was linked (to find a Greenhouse or Lever board)
  3. a few well-known paths only when the homepage didn't link them (/pricing, /feed, ...)
  4. the Greenhouse / Lever public APIs for the slug, to confirm a job board really exists
Everything returned is a SUGGESTION shown in the form for the user to review before saving.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.collectors.base import FetchError, fetcher

PRICING = re.compile(r"\b(pricing|prices|plans|plans-and-pricing|subscribe|membership)\b", re.I)
CHANGELOG = re.compile(r"\b(changelog|release[- ]?notes|what'?s[- ]?new|updates|product[- ]updates)\b", re.I)
BLOG = re.compile(r"\b(blog|news|newsroom|press|stories|insights)\b", re.I)
CAREERS = re.compile(r"\b(careers?|jobs|join[- ]us|work[- ]with[- ]us|hiring)\b", re.I)
GREENHOUSE = re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I)
LEVER = re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.I)
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")
GUESS_PRICING = ("/pricing", "/plans")
GUESS_FEEDS = ("/feed", "/rss.xml", "/atom.xml", "/blog/feed", "/blog/rss.xml", "/feed.xml", "/index.xml")


@dataclass
class Discovery:
    domain: str
    name: str | None = None
    pricing_url: str | None = None
    product_urls: list[str] = field(default_factory=list)
    feed_urls: list[str] = field(default_factory=list)
    careers_provider: str | None = None
    careers_token: str | None = None
    news_query: str | None = None
    notes: list[str] = field(default_factory=list)  # what was found / not found, shown to the user


def normalize_domain(raw: str) -> str:
    raw = raw.strip().lower()
    host = urlparse(raw if "://" in raw else f"https://{raw}").netloc or raw
    return host.removeprefix("www.").split(":")[0].strip("/")


def _same_site(url: str, domain: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def _get(url: str, timeout: float = 15) -> str | None:
    try:
        return fetcher().get(url, ttl_s=24 * 3600, timeout=timeout).text
    except FetchError:
        return None


def _links(html: str, base: str) -> list[tuple[str, str]]:
    tree = HTMLParser(html)
    out = []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        out.append((urljoin(base, href).split("#")[0], (a.text() or "").strip()[:80]))
    return out


def _feeds_in(html: str, base: str) -> list[str]:
    tree = HTMLParser(html)
    return [urljoin(base, n.attributes["href"]) for n in tree.css('link[rel="alternate"][href]')
            if (n.attributes.get("type") or "").lower() in FEED_TYPES]


def _pick(links: list[tuple[str, str]], rx: re.Pattern, domain: str) -> str | None:
    """Prefer same-site links whose PATH matches (e.g. /pricing) over links whose text alone matches."""
    path_hits = [u for u, _ in links if _same_site(u, domain) and rx.search(urlparse(u).path)]
    if path_hits:
        return min(path_hits, key=len)  # shortest = most canonical (/pricing over /pricing/enterprise)
    text_hits = [u for u, t in links if _same_site(u, domain) and rx.search(t)]
    return min(text_hits, key=len) if text_hits else None


def _site_name(html: str, domain: str) -> str:
    tree = HTMLParser(html)
    og = tree.css_first('meta[property="og:site_name"]')
    if og and og.attributes.get("content"):
        return og.attributes["content"].strip()[:60]
    title = (tree.css_first("title").text() if tree.css_first("title") else "") or ""
    first = re.split(r"\s+[|\-–—:]\s+", title.strip())[0].strip()
    label = domain.split(".")[0]
    # titles are often slogans ("Build faster"): only trust them if they mention the domain label
    return first[:60] if first and label.lower() in first.lower().replace(" ", "") else label.capitalize()


def _is_feed(text: str | None) -> bool:
    return bool(text) and bool(re.search(r"<(rss|feed)[\s>]", text[:2000], re.I) or text.lstrip().startswith('{"version": "https://jsonfeed'))


def _board_exists(provider: str, token: str) -> bool:
    url = (f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs" if provider == "greenhouse"
           else f"https://api.lever.co/v0/postings/{token}?mode=json")
    text = _get(url)
    if not text:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(data, list) or (isinstance(data, dict) and "jobs" in data)


def discover(raw_domain: str) -> Discovery:
    domain = normalize_domain(raw_domain)
    d = Discovery(domain=domain)
    home_url = f"https://{domain}/"
    html = _get(home_url) or _get(f"https://www.{domain}/")
    if not html:
        d.notes.append("Couldn't load the homepage (blocked by robots.txt, offline, or the site needs JavaScript). "
                       "Fill the fields in by hand.")
        d.name = domain.split(".")[0].capitalize()
        d.news_query = d.name
        return d
    d.name = _site_name(html, domain)
    d.news_query = d.name
    links = _links(html, home_url)
    d.product_urls.append(home_url)

    # pricing: a homepage link, else a well-known path that actually loads
    d.pricing_url = _pick(links, PRICING, domain)
    if not d.pricing_url:
        for path in GUESS_PRICING:
            page = _get(f"https://{domain}{path}")
            # many sites answer unknown paths with their homepage (HTTP 200): require a real pricing page
            if page and page != html and re.search(r"[$€£₹]\s?\d|/\s?(mo|month|year|user)\b|per (month|user|seat)", page, re.I):
                d.pricing_url = f"https://{domain}{path}"
                break
    d.notes.append(f"Pricing page: {d.pricing_url}" if d.pricing_url else "No pricing page found.")

    changelog = _pick(links, CHANGELOG, domain)
    if changelog:
        d.product_urls.append(changelog)

    # feeds: <link rel=alternate> on the homepage, then on the blog page, then well-known paths
    feeds = _feeds_in(html, home_url)
    blog = _pick(links, BLOG, domain)
    if not feeds and blog:
        blog_html = _get(blog)
        if blog_html:
            feeds = _feeds_in(blog_html, blog)
    if not feeds:
        for path in GUESS_FEEDS:
            url = f"https://{domain}{path}"
            if _is_feed(_get(url)):
                feeds = [url]
                break
    seen: set[str] = set()
    d.feed_urls = [f for f in feeds if not (f in seen or seen.add(f)) and "comments" not in f.lower()][:3]
    d.notes.append(f"Feeds: {', '.join(d.feed_urls)}" if d.feed_urls else "No RSS/Atom feed found; news comes from Bing News only.")

    # careers: a Greenhouse/Lever link on the homepage or the careers page, else try the domain label as the slug
    blob = html
    careers = _pick(links, CAREERS, domain)
    if careers and not (GREENHOUSE.search(blob) or LEVER.search(blob)):
        blob += _get(careers) or ""
    found = [("greenhouse", m) for m in GREENHOUSE.findall(blob)] + [("lever", m) for m in LEVER.findall(blob)]
    label = domain.split(".")[0]
    found += [("greenhouse", label), ("lever", label)]
    for provider, token in dict.fromkeys((p, t.lower()) for p, t in found):
        if token in ("embed", "v1", "boards") or not _board_exists(provider, token):
            continue
        d.careers_provider, d.careers_token = provider, token
        break
    d.notes.append(f"Job board: {d.careers_provider}/{d.careers_token}" if d.careers_provider
                   else "No Greenhouse or Lever job board found; hiring signals won't be collected.")
    return d


def to_dict(d: Discovery) -> dict:
    return asdict(d)
