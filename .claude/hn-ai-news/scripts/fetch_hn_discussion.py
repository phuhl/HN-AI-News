#!/usr/bin/env python3
"""
Fetch HN discussion page(s) and extract key data:
- Post title, points, comment count, submission time
- Top-level comments (text + author + points)

Outputs JSON. Handles 429s with exponential backoff.

Usage:
    python3 fetch_hn_discussion.py <item_id_or_url> [<item_id_or_url> ...]
    python3 fetch_hn_discussion.py --ids-file items.json  # JSON array of IDs/URLs

    Fetches multiple discussions with rate limiting between requests.
"""

import argparse
import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 7
INITIAL_BACKOFF = 3
INTER_REQUEST_DELAY = 3.0  # seconds between requests to avoid 429


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
            print(f"  [error] HTTP {resp.status_code} for {url}", file=sys.stderr)
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


def extract_item_id(ref):
    """Extract HN item ID from a URL or bare ID string."""
    ref = str(ref).strip()
    m = re.search(r"item\?id=(\d+)", ref)
    if m:
        return m.group(1)
    if ref.isdigit():
        return ref
    return None


def parse_hn_discussion(html, item_id):
    """Parse an HN discussion page and extract structured data."""
    soup = BeautifulSoup(html, "html.parser")

    result = {
        "item_id": item_id,
        "hn_url": f"https://news.ycombinator.com/item?id={item_id}",
        "title": "",
        "source_url": "",
        "points": 0,
        "comments_count": 0,
        "posted_time": "",
        "top_comments": [],
    }

    # Title
    title_el = soup.select_one(".titleline > a")
    if title_el:
        result["title"] = title_el.get_text(strip=True)
        result["source_url"] = title_el.get("href", "")

    # Points
    score_el = soup.select_one(".score")
    if score_el:
        m = re.search(r"(\d+)", score_el.get_text())
        if m:
            result["points"] = int(m.group(1))

    # Time
    age_el = soup.select_one(".age")
    if age_el:
        result["posted_time"] = age_el.get_text(strip=True)

    # Comments - find top-level comments (indent level 0)
    comment_trees = soup.select(".comtr")
    top_comments = []

    for ct in comment_trees:
        # Check indent level
        indent_el = ct.select_one(".ind img, .ind")
        indent = 0
        if indent_el:
            width = indent_el.get("width", "0")
            try:
                indent = int(width) // 40  # Each level is 40px
            except (ValueError, TypeError):
                indent = 0

        if indent > 0:
            continue  # Skip replies, only want top-level

        comment_el = ct.select_one(".commtext")
        if not comment_el:
            continue

        author_el = ct.select_one(".hnuser")
        author = author_el.get_text(strip=True) if author_el else ""

        # Get comment text, preserving paragraph breaks
        comment_text = comment_el.get_text(separator="\n", strip=True)

        # Truncate very long comments
        if len(comment_text) > 800:
            comment_text = comment_text[:800] + "..."

        top_comments.append(
            {
                "author": author,
                "text": comment_text,
            }
        )

        if len(top_comments) >= 15:
            break

    result["top_comments"] = top_comments
    result["comments_count"] = len(comment_trees)

    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch HN discussion pages")
    parser.add_argument(
        "items",
        nargs="*",
        help="HN item IDs or URLs to fetch",
    )
    parser.add_argument(
        "--ids-file",
        help="JSON file containing array of item IDs/URLs",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=50,
        help="Maximum number of items to fetch (default: 50)",
    )
    args = parser.parse_args()

    item_refs = list(args.items or [])

    if args.ids_file:
        with open(args.ids_file) as f:
            data = json.load(f)
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict):
                        ref = entry.get("hn_url") or entry.get("item_id") or entry.get("id", "")
                        if ref:
                            item_refs.append(str(ref))
                    else:
                        item_refs.append(str(entry))

    if not item_refs:
        print("No items to fetch. Provide IDs/URLs or --ids-file.", file=sys.stderr)
        sys.exit(1)

    # Deduplicate while preserving order
    seen = set()
    unique_refs = []
    for ref in item_refs:
        item_id = extract_item_id(ref)
        if item_id and item_id not in seen:
            seen.add(item_id)
            unique_refs.append(item_id)

    unique_refs = unique_refs[: args.max_items]
    print(f"Fetching {len(unique_refs)} discussions...", file=sys.stderr)

    results = []
    consecutive_429s = 0
    current_delay = INTER_REQUEST_DELAY

    for i, item_id in enumerate(unique_refs):
        url = f"https://news.ycombinator.com/item?id={item_id}"
        print(f"  [{i + 1}/{len(unique_refs)}] Fetching {url}", file=sys.stderr)

        resp = fetch_with_retry(url)
        if resp:
            result = parse_hn_discussion(resp.text, item_id)
            results.append(result)
            consecutive_429s = 0
            # Gradually reduce delay back toward baseline after successes
            current_delay = max(INTER_REQUEST_DELAY, current_delay * 0.8)
        else:
            results.append(
                {
                    "item_id": item_id,
                    "hn_url": url,
                    "error": "Failed to fetch after retries",
                }
            )
            consecutive_429s += 1
            # Increase delay after failures to let rate limit window reset
            current_delay = min(current_delay * 2, 60)
            print(
                f"  [rate-limit] Increasing inter-request delay to {current_delay:.1f}s",
                file=sys.stderr,
            )

        # Rate limiting between requests
        if i < len(unique_refs) - 1:
            time.sleep(current_delay)

    json.dump(results, sys.stdout, indent=2)
    print(f"\nFetched {len(results)} discussions", file=sys.stderr)


if __name__ == "__main__":
    main()
