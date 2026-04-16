#!/usr/bin/env python3
"""
Fetch Hacker News posts from hckrnews.com for a given day, enriched with
metadata from the HN Algolia API (points, comments, time).

Outputs JSON with post metadata.
Includes retry logic with exponential backoff for 429/5xx errors.

Usage:
    python3 fetch_hn_posts.py [--day YYYY-MM-DD] [--min-points N]
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 7
INITIAL_BACKOFF = 3


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


def extract_item_id(url):
    """Extract HN item ID from a URL."""
    m = re.search(r"item\?id=(\d+)", url)
    return m.group(1) if m else None


def fetch_hckrnews_ids(day_str):
    """Scrape hckrnews.com to get the list of HN item IDs for a given day."""
    url = f"https://hckrnews.com/?day={day_str}"
    print(f"  Fetching hckrnews.com for {day_str}...", file=sys.stderr)
    resp = fetch_with_retry(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    item_ids = []
    seen = set()

    for link in soup.find_all("a"):
        href = link.get("href", "")
        item_id = extract_item_id(href)
        if item_id and item_id not in seen:
            seen.add(item_id)
            item_ids.append(item_id)

    print(f"  Found {len(item_ids)} item IDs from hckrnews.com", file=sys.stderr)
    return item_ids


def fetch_algolia_metadata(item_ids):
    """
    Fetch metadata for HN items via the Algolia API.
    Batches requests to avoid rate limits.
    Returns dict mapping item_id -> metadata.
    """
    metadata = {}
    batch_size = 20  # Algolia can handle multiple IDs via tags

    for i in range(0, len(item_ids), batch_size):
        batch = item_ids[i : i + batch_size]
        # Use Algolia search with story IDs
        tags = ",".join(f"story_{iid}" for iid in batch)
        url = f"https://hn.algolia.com/api/v1/search?tags=({tags})&hitsPerPage={len(batch)}"

        print(
            f"  Fetching Algolia batch {i // batch_size + 1} "
            f"({len(batch)} items)...",
            file=sys.stderr,
        )
        resp = fetch_with_retry(url)
        if not resp:
            # Fallback: fetch individually
            for iid in batch:
                individual_url = f"https://hn.algolia.com/api/v1/items/{iid}"
                print(f"  Fetching individual item {iid}...", file=sys.stderr)
                iresp = fetch_with_retry(individual_url)
                if iresp:
                    try:
                        item = iresp.json()
                        metadata[str(item.get("id", iid))] = {
                            "title": item.get("title", ""),
                            "points": item.get("points", 0),
                            "num_comments": len(item.get("children", [])),
                            "url": item.get("url", ""),
                            "created_at": item.get("created_at", ""),
                            "author": item.get("author", ""),
                        }
                    except (json.JSONDecodeError, KeyError):
                        pass
                time.sleep(0.5)
            continue

        try:
            data = resp.json()
            for hit in data.get("hits", []):
                oid = str(hit.get("objectID", ""))
                metadata[oid] = {
                    "title": hit.get("title", ""),
                    "points": hit.get("points", 0),
                    "num_comments": hit.get("num_comments", 0),
                    "url": hit.get("url", ""),
                    "created_at": hit.get("created_at", ""),
                    "author": hit.get("author", ""),
                }
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  [warn] Failed to parse Algolia response: {e}", file=sys.stderr)

        time.sleep(0.5)

    return metadata


def fetch_hn_front_page(day_str):
    """
    Fallback: use HN's front page API endpoint for a given day.
    """
    url = f"https://news.ycombinator.com/front?day={day_str}"
    print(f"  Fetching HN front page for {day_str}...", file=sys.stderr)
    resp = fetch_with_retry(url)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    item_ids = []
    seen = set()

    for row in soup.select("tr.athing"):
        item_id = row.get("id", "")
        if item_id and item_id not in seen:
            seen.add(item_id)
            item_ids.append(item_id)

    print(f"  Found {len(item_ids)} items from HN front page", file=sys.stderr)
    return item_ids


def main():
    parser = argparse.ArgumentParser(description="Fetch HN posts for a day")
    parser.add_argument("--day", default=None, help="Day to fetch (YYYY-MM-DD)")
    parser.add_argument("--min-points", type=int, default=0, help="Minimum points")
    args = parser.parse_args()

    day_str = args.day or datetime.now().strftime("%Y-%m-%d")

    # Step 1: Get item IDs from hckrnews.com
    item_ids = fetch_hckrnews_ids(day_str)

    # Fallback to HN front page
    if not item_ids:
        item_ids = fetch_hn_front_page(day_str)

    if not item_ids:
        print("No posts found.", file=sys.stderr)
        json.dump([], sys.stdout)
        sys.exit(0)

    # Step 2: Enrich with Algolia metadata
    print(f"  Enriching {len(item_ids)} items via Algolia API...", file=sys.stderr)
    metadata = fetch_algolia_metadata(item_ids)

    # Step 3: Build output
    posts = []
    for iid in item_ids:
        meta = metadata.get(iid, {})
        title = meta.get("title", f"[Item {iid}]")
        points = meta.get("points", 0) or 0
        num_comments = meta.get("num_comments", 0) or 0
        source_url = meta.get("url", "")
        created_at = meta.get("created_at", "")
        author = meta.get("author", "")

        posts.append({
            "item_id": iid,
            "title": title,
            "hn_url": f"https://news.ycombinator.com/item?id={iid}",
            "source_url": source_url,
            "points": points,
            "num_comments": num_comments,
            "created_at": created_at,
            "author": author,
        })

    # Filter by minimum points
    if args.min_points > 0:
        posts = [p for p in posts if p["points"] >= args.min_points]

    # Sort by points descending
    posts.sort(key=lambda x: x["points"], reverse=True)

    json.dump(posts, sys.stdout, indent=2)
    print(f"\nTotal: {len(posts)} posts", file=sys.stderr)


if __name__ == "__main__":
    main()
