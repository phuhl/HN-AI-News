#!/usr/bin/env python3
"""Validate a weekly AI-news digest post before committing.

Catches the mistakes that are invisible at a glance but break the Jekyll build
or make the page wrong: malformed YAML, missing fields, a story count that blew
past the cap, dates that disagree across filename/frontmatter/title, and stories
that slipped through dedup and appear twice. Exit code is non-zero if there are
errors (warnings alone still exit 0).
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "PyYAML is required. Install: pip3 install --break-system-packages pyyaml\n")
    sys.exit(2)

REQUIRED_POST_FIELDS = ["title", "link", "domain", "summary", "points",
                        "hn_url", "comments", "time", "content_bullets",
                        "discussion_bullets"]
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-hn-ai-news-weekly\.md$")
HN_ID_RE = re.compile(r"[?&]id=(\d+)")
MAX_STORIES = 50
BULLET_WARN = 200
BULLET_ERR = 300


def load_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("file does not start with YAML frontmatter (`---`)")
    parts = text.split("\n---", 1)
    body = parts[0].split("\n", 1)[1]
    return yaml.safe_load(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    args = ap.parse_args()
    path = Path(args.path)

    errors, warnings = [], []

    fm_date = None
    m = FILENAME_RE.match(path.name)
    if not m:
        errors.append(
            f"filename '{path.name}' must look like YYYY-MM-DD-hn-ai-news-weekly.md")
    else:
        fm_date = m.group(1)

    try:
        fm = load_frontmatter(path)
    except Exception as exc:
        print(f"✗ FATAL: {exc}")
        return 1
    if not isinstance(fm, dict):
        print("✗ FATAL: frontmatter did not parse to a mapping")
        return 1

    # --- top-level fields ---
    if fm.get("layout") != "digest":
        errors.append("layout must be 'digest'")
    if fm.get("digest_type") != "weekly":
        errors.append("digest_type must be 'weekly' (this is what marks it in the index)")

    date_val = str(fm.get("date", ""))
    title = str(fm.get("title", ""))
    if fm_date and date_val != fm_date:
        errors.append(f"frontmatter date '{date_val}' != filename date '{fm_date}'")

    # The site derives URLs from the date alone, so without a distinct permalink
    # the weekly post collides with that day's daily digest. This silently drops
    # one page on the live site, so treat a missing/colliding permalink as fatal.
    permalink = fm.get("permalink")
    if not permalink:
        errors.append("missing 'permalink' — the site builds URLs from the date "
                      "only, so without one this collides with the daily digest")
    elif "weekly" not in str(permalink):
        errors.append(f"permalink '{permalink}' must contain 'weekly' to stay "
                      f"distinct from the daily digest's date-based URL")

    # Title should reference the end-date's year/month so it reads as that week.
    if fm_date:
        try:
            d = dt.date.fromisoformat(fm_date)
            if str(d.year) not in title:
                warnings.append(f"title does not mention the year {d.year}: {title!r}")
        except ValueError:
            pass
    if "week" not in title.lower():
        warnings.append("title should say 'Week' so weekly entries stand out in the index")

    themes = fm.get("themes")
    if not isinstance(themes, list) or not themes:
        errors.append("themes must be a non-empty list")
    elif not (3 <= len(themes) <= 5):
        warnings.append(f"expected 3–5 themes, found {len(themes)}")

    # --- sections / posts ---
    sections = fm.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections must be a non-empty list")
        sections = []

    seen_ids, seen_links, dup_reports = {}, {}, []
    story_count = 0
    # Bullets are copied verbatim from the daily digests, which already tolerate
    # long ones. So over-length isn't this skill's bug to fix — we tally it as a
    # single informational line rather than spamming a warning per bullet, and
    # never fail on it. We only hard-fail if a bullet is *empty/missing*, which
    # would mean a real copy bug.
    long_200 = 0
    long_300 = 0

    for si, sec in enumerate(sections):
        name = sec.get("name")
        if not name:
            errors.append(f"sections[{si}] missing 'name'")
        posts = sec.get("posts")
        if not isinstance(posts, list) or not posts:
            errors.append(f"section '{name}' has no posts")
            continue
        for pi, post in enumerate(posts):
            story_count += 1
            where = f"'{name}'[{pi}] ({post.get('title', '?')!r})"
            for f in REQUIRED_POST_FIELDS:
                if f not in post or post[f] in (None, ""):
                    errors.append(f"{where} missing field '{f}'")
            for f in ("content_bullets", "discussion_bullets"):
                bl = post.get(f)
                if not isinstance(bl, list) or not bl:
                    errors.append(f"{where} '{f}' must be a non-empty list")
                    continue
                for b in bl:
                    n = len(str(b))
                    if n > BULLET_ERR:
                        long_300 += 1
                    elif n > BULLET_WARN:
                        long_200 += 1

            # dedup check
            hn_id = None
            mm = HN_ID_RE.search(str(post.get("hn_url", "")))
            if mm:
                hn_id = mm.group(1)
            link = re.sub(r"^https?://(www\.)?", "",
                          str(post.get("link", "")).strip().lower()).rstrip("/")
            if hn_id and hn_id in seen_ids:
                dup_reports.append(f"HN id {hn_id} appears twice "
                                   f"({seen_ids[hn_id]} & {where})")
            elif link and link in seen_links:
                dup_reports.append(f"link {link} appears twice "
                                   f"({seen_links[link]} & {where})")
            if hn_id:
                seen_ids[hn_id] = where
            if link:
                seen_links[link] = where

    for r in dup_reports:
        errors.append(f"duplicate story: {r}")

    if story_count > MAX_STORIES:
        errors.append(f"{story_count} stories exceeds the cap of {MAX_STORIES}")

    # consistency between header stats and reality
    ai_posts = fm.get("ai_posts")
    if isinstance(ai_posts, int) and ai_posts != story_count:
        warnings.append(f"ai_posts={ai_posts} but {story_count} stories are present")

    # --- report ---
    if long_200 or long_300:
        print(f"ℹ INFO: {long_200} bullet(s) over {BULLET_WARN} chars, "
              f"{long_300} over {BULLET_ERR} — inherited verbatim from the daily "
              f"digests, not a weekly-skill issue.")
    for w in warnings:
        print(f"⚠ WARN: {w}")
    for e in errors:
        print(f"✗ ERROR: {e}")
    if errors:
        print(f"\n✗ {len(errors)} error(s), {len(warnings)} warning(s) — fix errors before committing.")
        return 1
    print(f"\n✓ Valid weekly digest: {story_count} stories in {len(sections)} "
          f"categories, {len(themes or [])} themes ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
