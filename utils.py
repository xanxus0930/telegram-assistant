import asyncio
import re
from datetime import datetime, timedelta, time as dt_time

import aiohttp
import feedparser
import pytz
from bs4 import BeautifulSoup

# ── Web Search (DuckDuckGo) ───────────────────────────────────────────────────

SEARCH_KEYWORDS = [
    # 時間性
    "今天", "今日", "昨天", "現在", "最近", "最新", "剛才", "目前",
    "today", "now", "latest", "current", "recent", "news",
    # 價格行情
    "價格", "多少錢", "幾塊", "漲", "跌", "行情", "匯率",
    "price", "worth", "cost", "rate",
    # 事件新聞
    "新聞", "消息", "事件", "發生", "怎麼了", "為什麼跌", "為什麼漲",
    # 加密貨幣即時
    "btc", "eth", "sol", "bnb", "xrp", "doge", "比特幣", "以太幣",
]

def _needs_search(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in SEARCH_KEYWORDS)

async def web_search(query: str, max_results: int = 5) -> str:
    """Search DuckDuckGo and return formatted results."""
    try:
        from duckduckgo_search import DDGS
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=max_results, region="tw-tzh"))
        )
        if not results:
            return ""
        lines = [f"【網路搜尋結果 for: {query}】"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title','')}\n   {r.get('body','')}\n   來源: {r.get('href','')}")
        return "\n\n".join(lines)
    except Exception as e:
        return ""

NEWS_FEEDS = [
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt",       "https://decrypt.co/feed"),
    ("CryptoSlate",   "https://cryptoslate.com/feed/"),
]


async def fetch_crypto_news(max_per_feed: int = 8) -> list[dict]:
    articles = []
    for source, url in NEWS_FEEDS:
        try:
            feed = await asyncio.to_thread(feedparser.parse, url)
            for entry in feed.entries[:max_per_feed]:
                articles.append({
                    "title": entry.get("title", "").strip(),
                    "url":   entry.get("link", ""),
                    "source": source,
                })
        except Exception:
            continue
    # Deduplicate by title
    seen, unique = set(), []
    for a in articles:
        if a["title"] and a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)
    return unique[:20]

TIMEZONE = pytz.timezone("Asia/Taipei")
URL_PATTERN = re.compile(r"https?://[^\s]+")


def extract_urls(text: str) -> list[str]:
    return URL_PATTERN.findall(text)


async def fetch_webpage(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return ""
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        lines = [ln.strip() for ln in soup.get_text(separator="\n").splitlines() if ln.strip()]
        return "\n".join(lines)[:6000]
    except Exception:
        return ""


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _parse_time_str(s: str) -> dt_time | None:
    s = s.lower().strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mn < 60:
            return dt_time(h, mn)
    m = re.match(r"^(\d{1,2})(am|pm)$", s)
    if m:
        h = int(m.group(1))
        if m.group(2) == "pm" and h != 12:
            h += 12
        elif m.group(2) == "am" and h == 12:
            h = 0
        if 0 <= h < 24:
            return dt_time(h, 0)
    return None


def parse_remind_time(text: str) -> tuple[datetime, str] | None:
    """
    Supports:
      in 2h <msg>  |  in 30m <msg>
      tomorrow [9am|10:30] <msg>
      10:30 <msg>
      2026-01-15 10:00 <msg>
    """
    now = datetime.now(TIMEZONE)
    text = text.strip()

    # "in Xh/Xm message"
    m = re.match(r"^in\s+(\d+)\s*(h|m|小時|分鐘|分)\s+(.+)$", text, re.IGNORECASE)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        msg = m.group(3)
        delta = timedelta(hours=amount) if unit in ("h", "小時") else timedelta(minutes=amount)
        return now + delta, msg

    # "tomorrow [time] message"
    m = re.match(r"^(tomorrow|明天|明日)\s*(\S+)?\s+(.+)$", text, re.IGNORECASE)
    if m:
        time_str = m.group(2) or ""
        msg = m.group(3)
        base = (now + timedelta(days=1)).date()
        t = _parse_time_str(time_str) if time_str else dt_time(9, 0)
        if t:
            remind_at = TIMEZONE.localize(datetime.combine(base, t))
            return remind_at, msg

    # "HH:MM message"
    m = re.match(r"^(\d{1,2}:\d{2})\s+(.+)$", text)
    if m:
        t = _parse_time_str(m.group(1))
        msg = m.group(2)
        if t:
            remind_at = TIMEZONE.localize(datetime.combine(now.date(), t))
            if remind_at <= now:
                remind_at += timedelta(days=1)
            return remind_at, msg

    # "YYYY-MM-DD HH:MM message"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s+(.+)$", text)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
            return TIMEZONE.localize(dt), m.group(3)
        except ValueError:
            pass

    return None
