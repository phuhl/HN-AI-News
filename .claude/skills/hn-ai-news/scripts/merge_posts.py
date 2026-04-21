#!/usr/bin/env python3
"""
Merge post metadata (from fetch_hn_posts.py) with discussion data
(from fetch_hn_discussion.py), resolve URLs, and merge duplicate threads.

This is the deterministic Step 5a+5b of the digest pipeline. It takes two
JSON files, joins them on item_id, and produces a single merged JSON file
ready for the model to categorize (Step 5c) and the subagents to summarize
(Step 6).

Input:
  --posts     /tmp/hn_posts.json       (from fetch_hn_posts.py)
  --discussions /tmp/hn_discussions.json (from fetch_hn_discussion.py)
  --ai-ids    /tmp/ai_post_ids.json    (AI-relevant post IDs + duplicate groups)

The --ai-ids file is a JSON array of objects:
  [
    {"item_id": "123", "duplicates": ["456", "789"]},
    {"item_id": "321"},
    ...
  ]
Each entry is one AI-relevant post. The "duplicates" field (optional) lists
item_ids that cover the same story and whose discussions should be merged.

Output: JSON array to stdout, one entry per deduplicated AI-relevant post.

Usage:
    python3 merge_posts.py \\
        --posts /tmp/hn_posts.json \\
        --discussions /tmp/hn_discussions.json \\
        --ai-ids /tmp/ai_post_ids.json \\
        > /tmp/hn_ai_merged.json
"""

import argparse
import json
import re
import sys
from urllib.parse import urlparse


def extract_domain(url):
    """Extract display domain from a URL, stripping www. prefix."""
    try:
        host = urlparse(url).hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def resolve_url(post_url, discussion_url):
    """Pick the best source URL.

    Prefer the Algolia URL (from discussion data) when available, since it
    reflects HN's canonical submission URL. Fall back to the hckrnews URL.
    """
    # Algolia sometimes returns empty url for Ask HN / self posts
    if discussion_url and discussion_url.startswith("http"):
        return discussion_url
    if post_url and post_url.startswith("http"):
        return post_url
    return ""


def format_time(created_at):
    """Convert ISO timestamp to display format: 'Mon DD, HH:MM UTC'."""
    if not created_at:
        return ""
    # Parse "2026-04-20T14:30:00Z" format
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", created_at)
    if not m:
        return created_at
    year, month, day, hour, minute = m.groups()
    months = [
        "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    try:
        mon = months[int(month)]
    except (IndexError, ValueError):
        mon = month
    return f"{mon} {int(day)}, {hour}:{minute} UTC"


def main():
    parser = argparse.ArgumentParser(
        description="Merge HN posts with discussion data"
    )
    parser.add_argument(
        "--posts", required=True,
        help="Path to posts JSON (from fetch_hn_posts.py)",
    )
    parser.add_argument(
        "--discussions", required=True,
        help="Path to discussions JSON (from fetch_hn_discussion.py)",
    )
    parser.add_argument(
        "--ai-ids", required=True,
        help="Path to AI-relevant post IDs JSON (with optional duplicate groups)",
    )
    args = parser.parse_args()

    # Load inputs
    with open(args.posts) as f:
        posts_list = json.load(f)
    with open(args.discussions) as f:
        discussions_list = json.load(f)
    with open(args.ai_ids) as f:
        ai_ids_list = json.load(f)

    # Index by item_id for fast lookup
    posts_by_id = {}
    for p in posts_list:
        posts_by_id[str(p.get("item_id", ""))] = p

    discussions_by_id = {}
    for d in discussions_list:
        discussions_by_id[str(d.get("item_id", ""))] = d

    # Build merged output
    results = []
    for entry in ai_ids_list:
        # Support both {"item_id": "123"} and bare string "123"
        if isinstance(entry, dict):
            primary_id = str(entry.get("item_id", ""))
            duplicate_ids = [str(x) for x in entry.get("duplicates", [])]
        else:
            primary_id = str(entry)
            duplicate_ids = []

        if not primary_id:
            continue

        post = posts_by_id.get(primary_id, {})
        discussion = discussions_by_id.get(primary_id, {})

        # Resolve source URL: prefer Algolia's canonical URL
        post_url = post.get("source_url", "")
        disc_url = discussion.get("source_url", "")
        source_url = resolve_url(post_url, disc_url)

        # Collect threads from primary discussion
        threads = list(discussion.get("threads", []))

        # Merge threads from duplicate posts
        for dup_id in duplicate_ids:
            dup_disc = discussions_by_id.get(dup_id, {})
            dup_threads = dup_disc.get("threads", [])
            if dup_threads:
                print(
                    f"  Merging {len(dup_threads)} threads from duplicate "
                    f"{dup_id} into {primary_id}",
                    file=sys.stderr,
                )
                threads.extend(dup_threads)

        # Use discussion's comment count if available (more accurate than
        # hckrnews since it comes from the Algolia API)
        comments_count = (
            discussion.get("comments_count")
            or post.get("num_comments", 0)
        )

        result = {
            "item_id": primary_id,
            "title": post.get("title", discussion.get("title", "")),
            "source_url": source_url,
            "domain": extract_domain(source_url),
            "hn_url": post.get(
                "hn_url",
                f"https://news.ycombinator.com/item?id={primary_id}",
            ),
            "points": post.get("points", discussion.get("points", 0)),
            "num_comments": comments_count,
            "created_at": post.get("created_at", ""),
            "time": format_time(post.get("created_at", "")),
            "threads": threads,
        }

        # Flag if duplicates were merged, for transparency in logs
        if duplicate_ids:
            result["merged_from"] = [primary_id] + duplicate_ids

        results.append(result)

    json.dump(results, sys.stdout, indent=2)
    print(
        f"\nMerged {len(results)} posts "
        f"({sum(1 for r in results if r.get('merged_from'))} with duplicates)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
