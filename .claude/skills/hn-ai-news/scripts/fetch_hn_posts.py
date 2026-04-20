#!/usr/bin/env python3
"""
Fetch Hacker News posts for a given day via hckrnews.com.

Source priority:
  1. hckrnews.com HTML — used for recent days (the page shows the current
     and previous day). Parses the <ul id="YYYYMMDD"> section for the
     target date.
  2. hckrnews.com/data/YYYYMMDD.js — static JSON file, used for older days
     when the target date is not present in the HTML.

In both cases, a 24-hour date filter is applied: only posts whose hckrnews
timestamp falls within [target_date 00:00 UTC, target_date+1 00:00 UTC) are
kept. This guards against edge cases where hckrnews includes posts from
neighbouring days.

Outputs a JSON array of post metadata to stdout.

Usage:
    python3 fetch_hn_posts.py [--day YYYY-MM-DD] [--min-points N]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 7
INITIAL_BACKOFF = 3


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_with_retry(url, max_retries=MAX_RETRIES, timeout=DEFAULT_TIMEOUT):
    """Fetch a URL with exponential backoff on 429 and 5xx errors."""
    backoff = INITIAL_BACKOFF
    last_error = None

    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "HN-AI-News-Skill/1.0"},
            )
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                wait = int(retry_after) if retry_after else backoff
                print(
                    f"  [retry] {resp.status_code} on {url}, waiting {wait}s "
                    f"(attempt {attempt + 1}/{max_retries})",
                    file=sys.stderr,
                )
                time.sleep(wait)
                backoff *= 2
                last_error = f"HTTP {resp.status_code}"
                continue
            print(f"  [warn] HTTP {resp.status_code} for {url}", file=sys.stderr)
            return None
        except requests.exceptions.RequestException as e:
            print(
                f"  [retry] {e} (attempt {attempt + 1}/{max_retries})",
                file=sys.stderr,
            )
            time.sleep(backoff)
            backoff *= 2
            last_error = str(e)

    print(f"  [failed] Gave up on {url}: {last_error}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def day_window(day_str):
    """
    Return (data_day_str, start_epoch, end_epoch) for the 24-hour UTC window
    that ends at midnight of day_str — i.e. the day BEFORE day_str.

    A digest file named 2026-04-20 covers the 24 hours of 2026-04-19:
      "2026-04-20" -> data_day="2026-04-19", window [Apr19 00:00, Apr20 00:00)
    """
    end_dt = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_dt = end_dt - timedelta(days=1)
    data_day_str = start_dt.strftime("%Y-%m-%d")
    return data_day_str, int(start_dt.timestamp()), int(end_dt.timestamp())


def epoch_to_iso(epoch):
    """Convert an integer Unix timestamp to an ISO-8601 UTC string."""
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (TypeError, ValueError):
        return ""


def in_window(epoch, start, end):
    """Return True if epoch (int or str) falls within [start, end)."""
    try:
        return start <= int(epoch) < end
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Source 1: hckrnews.com HTML (recent days)
# ---------------------------------------------------------------------------

def fetch_from_html(day_str, start_epoch, end_epoch):
    """
    Scrape hckrnews.com and return posts for the target day, or [] if the
    target date is not present in the page.

    The page contains one <ul class="entries" id="YYYYMMDD"> per day.
    Each <li> has:
      - id="<hn_item_id>"
      - <a class="hn" data-date="<epoch>">  (hckrnews ranking timestamp)
      - <span class="comments">N</span>
      - <span class="points">N</span>
      - <a class="link" href="<source_url>">Title <span class="source">...</span></a>
    """
    compact = day_str.replace("-", "")  # "2026-04-18" -> "20260418"
    url = "https://hckrnews.com/"
    print(f"  Fetching hckrnews.com HTML...", file=sys.stderr)
    resp = fetch_with_retry(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    day_ul = soup.find("ul", id=compact)
    if not day_ul:
        print(
            f"  Date {day_str} not found in hckrnews HTML (probably too old).",
            file=sys.stderr,
        )
        return []

    posts = []
    skipped = 0
    for li in day_ul.find_all("li", class_="entry"):
        item_id = li.get("id", "")
        if not item_id:
            continue

        hn_a = li.find("a", class_="hn")
        link_a = li.find("a", class_="link")
        if not hn_a or not link_a:
            continue

        raw_epoch = hn_a.get("data-date", "")

        # 24-hour sanity filter
        if not in_window(raw_epoch, start_epoch, end_epoch):
            skipped += 1
            continue

        # Extract title (strip the nested <span class="source"> text)
        source_span = link_a.find("span", class_="source")
        source_text = source_span.get_text(strip=True) if source_span else ""
        if source_span:
            source_span.extract()
        title = link_a.get_text(strip=True)

        comments_span = li.find("span", class_="comments")
        points_span = li.find("span", class_="points")

        def to_int(span):
            try:
                return int(span.get_text(strip=True))
            except (AttributeError, ValueError):
                return 0

        posts.append({
            "item_id": item_id,
            "title": title,
            "hn_url": f"https://news.ycombinator.com/item?id={item_id}",
            "source_url": link_a.get("href", ""),
            "points": to_int(points_span),
            "num_comments": to_int(comments_span),
            "created_at": epoch_to_iso(raw_epoch),
            "author": "",
        })

    if skipped:
        print(f"  Skipped {skipped} entries outside 24h window.", file=sys.stderr)
    print(f"  Found {len(posts)} posts from hckrnews HTML.", file=sys.stderr)
    return posts


# ---------------------------------------------------------------------------
# Source 2: hckrnews.com/data/YYYYMMDD.js (older days)
# ---------------------------------------------------------------------------

def fetch_from_js_file(day_str, start_epoch, end_epoch):
    """
    Fetch the static hckrnews day file and return posts.
    Returns [] if the file does not exist (404) or cannot be parsed.

    Each JSON entry has:
      id, link_text, link, submitter, time (epoch str), date (epoch int),
      points, comments, dead, type
    """
    compact = day_str.replace("-", "")
    url = f"https://hckrnews.com/data/{compact}.js"
    print(f"  Fetching hckrnews day file {compact}.js...", file=sys.stderr)
    resp = fetch_with_retry(url)
    if not resp:
        return []

    try:
        entries = resp.json()
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  [warn] Failed to parse {url}: {e}", file=sys.stderr)
        return []

    posts = []
    skipped = 0
    for entry in entries:
        if entry.get("dead"):
            continue
        if entry.get("type") not in ("story", "ask", "show", None):
            continue
        item_id = str(entry.get("id", ""))
        if not item_id:
            continue

        # hckrnews uses 'date' as its ranking/logging timestamp
        raw_epoch = entry.get("date") or entry.get("time")

        # 24-hour sanity filter
        if not in_window(raw_epoch, start_epoch, end_epoch):
            skipped += 1
            continue

        posts.append({
            "item_id": item_id,
            "title": entry.get("link_text", f"[Item {item_id}]"),
            "hn_url": f"https://news.ycombinator.com/item?id={item_id}",
            "source_url": entry.get("link", ""),
            "points": entry.get("points", 0) or 0,
            "num_comments": entry.get("comments", 0) or 0,
            "created_at": epoch_to_iso(raw_epoch),
            "author": entry.get("submitter", ""),
        })

    if skipped:
        print(f"  Skipped {skipped} entries outside 24h window.", file=sys.stderr)
    print(f"  Found {len(posts)} posts from hckrnews day file.", file=sys.stderr)
    return posts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fetch HN posts for a day")
    parser.add_argument("--day", default=None, help="Day to fetch (YYYY-MM-DD)")
    parser.add_argument("--min-points", type=int, default=0, help="Minimum points")
    args = parser.parse_args()

    day_str = args.day or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    data_day_str, start_epoch, end_epoch = day_window(day_str)

    print(
        f"  Digest date: {day_str}  "
        f"Data window: {data_day_str} [{start_epoch}, {end_epoch})",
        file=sys.stderr,
    )

    # Step 1: Try HTML (covers the 2 most recent days on hckrnews)
    posts = fetch_from_html(data_day_str, start_epoch, end_epoch)

    # Step 2: Fall back to static JS file (covers older days)
    if not posts:
        print(
            f"  HTML did not have {data_day_str}, trying JS file...",
            file=sys.stderr,
        )
        posts = fetch_from_js_file(data_day_str, start_epoch, end_epoch)

    if not posts:
        print(f"  No posts found for {day_str}.", file=sys.stderr)
        json.dump([], sys.stdout)
        sys.exit(0)

    # Filter by minimum points
    if args.min_points > 0:
        before = len(posts)
        posts = [p for p in posts if p["points"] >= args.min_points]
        print(
            f"  After min-points={args.min_points} filter: "
            f"{len(posts)} / {before} posts.",
            file=sys.stderr,
        )

    # Sort by points descending
    posts.sort(key=lambda x: x["points"], reverse=True)

    json.dump(posts, sys.stdout, indent=2)
    print(f"\nTotal: {len(posts)} posts", file=sys.stderr)


if __name__ == "__main__":
    main()
