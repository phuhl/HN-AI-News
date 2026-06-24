#!/usr/bin/env python3
"""Compile a weekly AI-news digest from the last 7 daily digest posts.

The daily skill (`hn-ai-news`) already does the expensive work: fetching HN,
filtering AI posts, summarizing each article, and writing a Jekyll post with
rich frontmatter. This script *reuses* that compiled data — it never re-fetches.

Two modes:

  select   — Parse the daily digests in a 7-day window, dedup stories that
             recur across days, rank everything by points, keep the top N, and
             regroup into the canonical categories. Emits a stories JSON that
             also carries every day's themes (so the caller can synthesize
             week-level themes from them). This is the read/condense phase.

  assemble — Take that stories JSON plus a themes JSON (the 3–5 week-level
             themes the caller wrote) and emit the final weekly Jekyll post.
             This is the write phase; it copies story fields verbatim so the
             weekly entries match their daily wording exactly.

Splitting the two means the only genuinely generative step — writing the
week's themes — stays with the model, while all the fiddly, error-prone YAML
parsing / dedup / ranking stays deterministic and testable here.
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "PyYAML is required. Install with:\n"
        "  pip3 install --break-system-packages pyyaml\n"
    )
    sys.exit(2)


# The daily skill assigns each post to exactly one of these categories. We keep
# the same order here so the weekly digest reads like a bigger daily one rather
# than a reshuffled stranger. Anything we don't recognize is appended after
# these, alphabetically, so a renamed/new category still shows up.
CANONICAL_CATEGORIES = [
    "New Models & Releases",
    "AI Products & Tools",
    "AI Agents & Automation",
    "AI Coding & Development",
    "Claude / Anthropic",
    "OpenAI / ChatGPT",
    "Google / DeepMind",
    "AI Industry & Business",
    "AI Policy, Legal & Regulation",
    "AI Safety & Ethics",
    "AI Infrastructure & Compute",
    "AI in Society",
    "AI Research",
    "Open Source AI",
]

# Fields copied verbatim from each daily story into the weekly story. Keeping
# these identical is the whole point of "reuse, don't regenerate".
POST_FIELDS = [
    "title", "link", "domain", "summary", "points",
    "hn_url", "comments", "time", "content_bullets", "discussion_bullets",
]

DAILY_NAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-hn-ai-news\.md$")
HN_ID_RE = re.compile(r"[?&]id=(\d+)")


def parse_frontmatter(path):
    """Return the YAML frontmatter dict of a Jekyll post, or None if absent."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    # Frontmatter is the block between the first two `---` fences.
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return None
    body = parts[0]
    # Strip the leading `---` line.
    body = body.split("\n", 1)[1] if "\n" in body else ""
    try:
        return yaml.safe_load(body)
    except yaml.YAMLError as exc:
        sys.stderr.write(f"WARN: could not parse {path.name}: {exc}\n")
        return None


def find_daily_posts(posts_dir):
    """Map date -> path for every daily (non-weekly) digest in posts_dir."""
    out = {}
    for p in sorted(posts_dir.glob("*-hn-ai-news.md")):
        m = DAILY_NAME_RE.match(p.name)
        if not m:
            continue  # skips *-hn-ai-news-weekly.md and anything off-pattern
        date = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        out[date] = p
    return out


def normalize_link(link):
    """Collapse a URL to a comparable key (scheme/www/trailing-slash agnostic)."""
    if not link:
        return ""
    s = str(link).strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    s = s.split("#", 1)[0]
    return s.rstrip("/")


def story_keys(post):
    """Identity keys for a story: HN item id (strong) and normalized link."""
    hn_id = None
    m = HN_ID_RE.search(str(post.get("hn_url", "")))
    if m:
        hn_id = m.group(1)
    return hn_id, normalize_link(post.get("link"))


def collect_stories(daily_paths_in_window):
    """Flatten all posts across the window, tagging each with its category/date."""
    stories = []
    for date, path in daily_paths_in_window:
        fm = parse_frontmatter(path)
        if not fm:
            continue
        for section in fm.get("sections") or []:
            cat = section.get("name", "Uncategorized")
            for post in section.get("posts") or []:
                rec = {f: post.get(f) for f in POST_FIELDS}
                rec["category"] = cat
                rec["digest_date"] = date.isoformat()
                rec["points"] = _as_int(post.get("points"))
                rec["comments"] = _as_int(post.get("comments"))
                stories.append(rec)
    return stories


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def dedup_stories(stories):
    """Merge stories that recur across days; keep the highest-points instance.

    A story trending for several days, or resubmitted under a new HN item, would
    otherwise eat multiple of our 50 slots. We collapse on HN id first, then on
    the normalized article link, always keeping the copy with the most points
    (that's the version readers will recognize) and recording how many days it
    appeared so the caller can highlight persistent stories if it wants.
    """
    by_id = {}
    by_link = {}
    merged = []

    for s in sorted(stories, key=lambda x: x["points"], reverse=True):
        hn_id, link = story_keys(s)
        existing = None
        if hn_id and hn_id in by_id:
            existing = by_id[hn_id]
        elif link and link in by_link:
            existing = by_link[link]

        if existing is not None:
            existing["days_seen"] += 1
            existing.setdefault("also_dates", []).append(s["digest_date"])
            # Keep the higher comment count we've seen for context.
            existing["comments"] = max(existing["comments"], s["comments"])
            continue

        s = dict(s)
        s["days_seen"] = 1
        merged.append(s)
        if hn_id:
            by_id[hn_id] = s
        if link:
            by_link[link] = s

    return merged


def category_sort_key(name):
    try:
        return (0, CANONICAL_CATEGORIES.index(name))
    except ValueError:
        return (1, name.lower())


def group_into_sections(stories):
    """Group the chosen stories back into ordered category sections."""
    buckets = {}
    for s in stories:
        buckets.setdefault(s["category"], []).append(s)

    sections = []
    for name in sorted(buckets, key=category_sort_key):
        posts = sorted(buckets[name], key=lambda x: x["points"], reverse=True)
        clean = []
        for s in posts:
            clean.append({f: s.get(f) for f in POST_FIELDS})
        sections.append({"name": name, "posts": clean})
    return sections


def fmt_readable_range(start, end):
    """'Week of Jun 18 – 24, 2026' (collapses month/year when shared)."""
    if start.year == end.year and start.month == end.month:
        return f"Week of {start:%b} {start.day}–{end.day}, {end.year}"
    if start.year == end.year:
        return f"Week of {start:%b} {start.day} – {end:%b} {end.day}, {end.year}"
    return f"Week of {start:%b} {start.day}, {start.year} – {end:%b} {end.day}, {end.year}"


def cmd_select(args):
    posts_dir = Path(args.posts_dir)
    daily = find_daily_posts(posts_dir)
    if not daily:
        sys.stderr.write(f"ERROR: no daily digests found in {posts_dir}\n")
        return 1

    end = (dt.date.fromisoformat(args.end_date) if args.end_date
           else max(daily))
    start = end - dt.timedelta(days=args.days - 1)

    in_window = [(d, p) for d, p in sorted(daily.items()) if start <= d <= end]
    if not in_window:
        sys.stderr.write(
            f"ERROR: no daily digests between {start} and {end}\n")
        return 1

    used_dates = [d.isoformat() for d, _ in in_window]
    missing = [
        (start + dt.timedelta(days=i)).isoformat()
        for i in range(args.days)
        if (start + dt.timedelta(days=i)) not in dict(in_window)
    ]

    stories = collect_stories(in_window)
    total_seen = len(stories)
    deduped = dedup_stories(stories)
    total_unique = len(deduped)

    ranked = sorted(deduped, key=lambda x: x["points"], reverse=True)
    selected = ranked[: args.max_stories]
    sections = group_into_sections(selected)

    # Gather each day's themes so the caller can synthesize week-level ones.
    daily_themes = []
    for d, p in in_window:
        fm = parse_frontmatter(p) or {}
        for t in fm.get("themes") or []:
            daily_themes.append({"date": d.isoformat(), "theme": t})

    out = {
        "meta": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "readable_range": fmt_readable_range(start, end),
            "days_requested": args.days,
            "days_found": used_dates,
            "days_missing": missing,
            "total_posts_seen": total_seen,
            "total_unique_stories": total_unique,
            "selected_count": len(selected),
            "max_stories": args.max_stories,
        },
        "daily_themes": daily_themes,
        "sections": sections,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    if missing:
        sys.stderr.write(
            f"NOTE: {len(missing)} day(s) missing in window: {', '.join(missing)}\n")
    sys.stderr.write(
        f"OK: {total_seen} posts → {total_unique} unique → "
        f"{len(selected)} selected across {len(sections)} categories\n")
    return 0


def cmd_assemble(args):
    stories = json.loads(Path(args.stories).read_text(encoding="utf-8"))
    themes = json.loads(Path(args.themes).read_text(encoding="utf-8"))

    if isinstance(themes, dict) and "themes" in themes:
        themes = themes["themes"]
    if not isinstance(themes, list) or not all(isinstance(t, str) for t in themes):
        sys.stderr.write("ERROR: themes file must be a JSON list of strings\n")
        return 1

    meta = stories["meta"]
    end = dt.date.fromisoformat(meta["end_date"])
    readable = meta["readable_range"]

    frontmatter = {
        "layout": "digest",
        "digest_type": "weekly",
        "date": end.isoformat(),
        "title": f"Weekly AI Digest — {readable}",
        "readable_date": readable,
        # For the weekly view we repurpose the daily layout's stat line:
        # ai_posts = stories shown, total_posts = unique AI stories that week.
        "total_posts": meta["total_unique_stories"],
        "ai_posts": meta["selected_count"],
        "themes": themes,
        "sections": [
            {
                "name": sec["name"],
                "posts": [
                    {f: post.get(f) for f in POST_FIELDS}
                    for post in sec["posts"]
                ],
            }
            for sec in stories["sections"]
        ],
    }

    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1000,
    )
    content = f"---\n{yaml_text}---\n"

    out_path = Path(args.out) if args.out else Path(
        args.posts_dir) / f"{end.isoformat()}-hn-ai-news-weekly.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    sys.stderr.write(f"OK: wrote {out_path}\n")
    print(out_path)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)

    sel = sub.add_parser("select", help="parse daily digests -> stories JSON")
    sel.add_argument("--posts-dir", default="_posts")
    sel.add_argument("--end-date", default=None,
                     help="last day of the window (YYYY-MM-DD); default = latest digest")
    sel.add_argument("--days", type=int, default=7)
    sel.add_argument("--max-stories", type=int, default=50)
    sel.set_defaults(func=cmd_select)

    asm = sub.add_parser("assemble", help="stories JSON + themes JSON -> post")
    asm.add_argument("--stories", required=True)
    asm.add_argument("--themes", required=True)
    asm.add_argument("--posts-dir", default="_posts")
    asm.add_argument("--out", default=None)
    asm.set_defaults(func=cmd_assemble)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
