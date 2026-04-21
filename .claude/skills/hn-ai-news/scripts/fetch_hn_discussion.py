#!/usr/bin/env python3
"""
Fetch HN discussion threads via the Algolia API and extract high-signal
comment data in a compact format.

For each discussion, returns:
- Post metadata (title, points, comment count)
- Top comments ranked by points, each with their best reply for
  threaded context

Uses hn.algolia.com/api/v1/items/{id} which returns the full comment
tree with point counts, letting us surface quality over quantity.

Usage:
    python3 fetch_hn_discussion.py <item_id_or_url> [...]
    python3 fetch_hn_discussion.py --ids-file items.json --max-items 30

Outputs JSON array to stdout, logs to stderr.
"""

import argparse
import json
import re
import sys
import time

import requests

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 7
INITIAL_BACKOFF = 3
INTER_REQUEST_DELAY = 1.0  # Algolia is more generous than HN HTML


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


def strip_html(text):
    """Remove HTML tags from comment text, keeping line breaks."""
    if not text:
        return ""
    # Convert <p> and <br> to newlines before stripping
    text = re.sub(r"<(?:p|br)\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def count_descendants(node):
    """Count total descendant comments."""
    count = 0
    for child in node.get("children", []):
        if child.get("type") == "comment":
            count += 1 + count_descendants(child)
    return count


def best_reply(parent_node):
    """Find the highest-signal reply to a comment node.

    HN returns replies in display order (voted). We pick the first
    reply — HN's algorithm already ranked it highest. If it's very
    short (<30 chars, e.g. "Yes." or "Agreed."), we skip to the next
    one since those add little context for summarization.
    """
    for child in parent_node.get("children", []):
        if child.get("type") != "comment":
            continue
        text = strip_html(child.get("text", ""))
        if not text or len(text) < 30:
            continue
        return {
            "author": child.get("author", ""),
            "text": text[:800],
            "replies": count_descendants(child),
        }
    return None


def extract_discussion(data, max_comments=10):
    """Extract top comments with their best reply from an Algolia item response.

    Returns a compact structure: the top N comments by quality, each
    paired with its highest-signal reply for threaded context.
    """
    item_id = str(data.get("id", ""))

    result = {
        "item_id": item_id,
        "hn_url": f"https://news.ycombinator.com/item?id={item_id}",
        "title": data.get("title", ""),
        "source_url": data.get("url", ""),
        "points": data.get("points") or 0,
        "comments_count": count_descendants(data),
        "threads": [],
    }

    # Get top-level comments — Algolia returns them in HN's display
    # order, which is already ranked by HN's voting algorithm.  We
    # trust that ordering as the primary quality signal and use
    # descendant count (engagement) as a secondary filter to skip
    # low-signal comments when we have plenty to choose from.
    top_level = []
    for position, child in enumerate(data.get("children", [])):
        if child.get("type") != "comment":
            continue
        text = strip_html(child.get("text", ""))
        if not text:
            continue
        top_level.append({
            "text": text,
            "author": child.get("author", ""),
            "position": position,
            "n_descendants": count_descendants(child),
            "_raw_node": child,
        })

    for comment in top_level[:max_comments]:
        thread = {
            "author": comment["author"],
            "text": comment["text"][:1000],
            "replies": comment["n_descendants"],
        }
        reply = best_reply(comment["_raw_node"])
        if reply:
            thread["top_reply"] = reply
        result["threads"].append(thread)

    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch HN discussions via Algolia API")
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
        help="Maximum number of discussions to fetch (default: 50)",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=20,
        help="Top comments per discussion (default: 20)",
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
    current_delay = INTER_REQUEST_DELAY

    for i, item_id in enumerate(unique_refs):
        url = f"https://hn.algolia.com/api/v1/items/{item_id}"
        print(f"  [{i + 1}/{len(unique_refs)}] Fetching {item_id}", file=sys.stderr)

        resp = fetch_with_retry(url)
        if resp:
            try:
                data = resp.json()
                result = extract_discussion(data, max_comments=args.max_comments)
                results.append(result)
                # Recover delay after success
                current_delay = max(INTER_REQUEST_DELAY, current_delay * 0.8)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"  [error] Bad JSON for {item_id}: {e}", file=sys.stderr)
                results.append({
                    "item_id": item_id,
                    "hn_url": f"https://news.ycombinator.com/item?id={item_id}",
                    "error": f"JSON parse error: {e}",
                })
        else:
            results.append({
                "item_id": item_id,
                "hn_url": f"https://news.ycombinator.com/item?id={item_id}",
                "error": "Failed to fetch after retries",
            })
            current_delay = min(current_delay * 2, 60)
            print(
                f"  [rate-limit] Increasing delay to {current_delay:.1f}s",
                file=sys.stderr,
            )

        # Rate limiting between requests
        if i < len(unique_refs) - 1:
            time.sleep(current_delay)

    json.dump(results, sys.stdout, indent=2)
    print(f"\nFetched {len(results)} discussions", file=sys.stderr)


if __name__ == "__main__":
    main()
