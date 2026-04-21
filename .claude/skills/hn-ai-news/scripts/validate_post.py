#!/usr/bin/env python3
"""
Validate a Jekyll post file for the hn-ai-news digest.

Checks:
  - Valid YAML frontmatter
  - All required top-level fields present and correctly typed
  - Categories structure: each has name + posts
  - Each post has all required fields with correct types
  - Content bullets are 3 per post (warns if not)
  - Discussion bullets are 2-3 per post (warns if not)
  - URLs look valid
  - No obvious copy-paste from comments (heuristic)

Exit code 0 = pass, 1 = errors found.

Usage:
    python3 validate_post.py <path-to-post.md>
"""

import os
import re
import sys
from datetime import datetime

import yaml


def load_frontmatter(path):
    """Extract and parse YAML frontmatter from a markdown file."""
    with open(path) as f:
        content = f.read()

    if not content.startswith("---"):
        return None, "File does not start with YAML frontmatter (---)"

    end = content.find("\n---", 3)
    if end == -1:
        return None, "No closing --- for frontmatter"

    yaml_str = content[4:end]
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        return None, f"YAML parse error: {e}"

    return data, None


def validate(path):
    """Validate a post file. Returns (errors: list[str], warnings: list[str])."""
    errors = []
    warnings = []

    data, err = load_frontmatter(path)
    if err:
        return [err], []

    if not isinstance(data, dict):
        return ["Frontmatter is not a YAML mapping"], []

    # Reject Jekyll reserved keys used for structured data
    if "categories" in data:
        errors.append(
            "'categories' is a reserved Jekyll key — use 'sections' instead. "
            "Jekyll appends extra string entries, causing empty section headers."
        )

    # Required top-level fields
    required_top = {
        "layout": str,
        "date": str,
        "title": str,
        "readable_date": str,
        "total_posts": int,
        "ai_posts": int,
        "themes": list,
        "sections": list,
    }

    for field, expected_type in required_top.items():
        if field not in data:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(data[field], expected_type):
            errors.append(
                f"Field '{field}' should be {expected_type.__name__}, "
                f"got {type(data[field]).__name__}"
            )

    # Date format
    if "date" in data and isinstance(data["date"], str):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", data["date"]):
            errors.append(f"Date format should be YYYY-MM-DD, got: {data['date']}")

    # Date consistency: filename, date field, readable_date, and title must agree
    basename = os.path.basename(path)
    fn_match = re.match(r"^(\d{4}-\d{2}-\d{2})-", basename)
    fn_date = fn_match.group(1) if fn_match else None

    fm_date = data.get("date", "")
    if isinstance(fm_date, str) and fn_date:
        if fm_date != fn_date:
            errors.append(
                f"Frontmatter date '{fm_date}' does not match filename date '{fn_date}'"
            )

    # Build the expected readable date from the digest date (filename or frontmatter)
    digest_date_str = fn_date or fm_date
    expected_readable = None
    if isinstance(digest_date_str, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", digest_date_str):
        try:
            dt = datetime.strptime(digest_date_str, "%Y-%m-%d")
            expected_readable = dt.strftime("%B %-d, %Y")  # e.g. "April 21, 2026"
        except ValueError:
            pass

    readable = data.get("readable_date", "")
    if expected_readable and isinstance(readable, str):
        if readable != expected_readable:
            errors.append(
                f"readable_date '{readable}' does not match digest date "
                f"(expected '{expected_readable}')"
            )

    title = data.get("title", "")
    if expected_readable and isinstance(title, str):
        # The title should contain the readable date
        if expected_readable not in title:
            errors.append(
                f"title does not contain the digest date — expected "
                f"'{expected_readable}' somewhere in '{title}'"
            )

    # Themes
    themes = data.get("themes", [])
    if isinstance(themes, list):
        if len(themes) < 2:
            warnings.append(f"Only {len(themes)} themes (expected 3-5)")
        for i, theme in enumerate(themes):
            if not isinstance(theme, str):
                errors.append(f"Theme {i} is not a string")
            elif len(theme) < 20:
                warnings.append(f"Theme {i} is very short ({len(theme)} chars)")

    # Sections (categories of posts)
    categories = data.get("sections", [])
    if not isinstance(categories, list):
        errors.append("'sections' is not a list")
        return errors, warnings

    # Empty sections is valid (zero AI-relevant posts day) but ai_posts should be 0
    if len(categories) == 0:
        if isinstance(data.get("ai_posts"), int) and data["ai_posts"] != 0:
            errors.append(
                f"No sections but ai_posts={data['ai_posts']} (expected 0)"
            )
        return errors, warnings

    total_posts = 0
    seen_links = {}  # link -> (category, index) for duplicate detection
    for ci, cat in enumerate(categories):
        if not isinstance(cat, dict):
            errors.append(f"Category {ci} is not a mapping")
            continue
        if "name" not in cat:
            errors.append(f"Category {ci} missing 'name'")
        if "posts" not in cat:
            errors.append(f"Category {ci} missing 'posts'")
            continue

        posts = cat["posts"]
        if not isinstance(posts, list):
            errors.append(f"Category '{cat.get('name', ci)}' posts is not a list")
            continue

        for pi, post in enumerate(posts):
            total_posts += 1
            post_errs, post_warns = validate_post(post, cat.get("name", "?"), pi)
            errors.extend(post_errs)
            warnings.extend(post_warns)

            # Detect duplicate source URLs across the digest
            link = post.get("link", "")
            if isinstance(link, str) and link:
                if link in seen_links:
                    prev_cat, prev_idx = seen_links[link]
                    warnings.append(
                        f"[{cat.get('name', '?')}] post {pi}: duplicate link "
                        f"also appears in [{prev_cat}] post {prev_idx}: "
                        f"{link[:80]}"
                    )
                else:
                    seen_links[link] = (cat.get("name", "?"), pi)

    # Cross-check ai_posts count
    if isinstance(data.get("ai_posts"), int) and total_posts != data["ai_posts"]:
        warnings.append(
            f"ai_posts={data['ai_posts']} but found {total_posts} posts in categories"
        )

    return errors, warnings


def validate_post(post, category_name, index):
    """Validate a single post entry."""
    errors = []
    warnings = []
    label = f"[{category_name}] post {index}"

    if not isinstance(post, dict):
        return [f"{label}: not a mapping"], []

    # Required fields
    required_fields = {
        "title": str,
        "link": str,
        "domain": str,
        "summary": str,
        "points": int,
        "hn_url": str,
        "comments": int,
        "time": str,
        "content_bullets": list,
        "discussion_bullets": list,
    }

    for field, expected_type in required_fields.items():
        if field not in post:
            errors.append(f"{label}: missing '{field}'")
        elif not isinstance(post[field], expected_type):
            errors.append(
                f"{label}: '{field}' should be {expected_type.__name__}, "
                f"got {type(post[field]).__name__}"
            )

    # URL checks
    link = post.get("link", "")
    if isinstance(link, str) and link and not link.startswith("http"):
        errors.append(f"{label}: 'link' doesn't look like a URL: {link[:60]}")

    hn_url = post.get("hn_url", "")
    if isinstance(hn_url, str) and hn_url:
        if "news.ycombinator.com/item?id=" not in hn_url:
            errors.append(f"{label}: 'hn_url' doesn't look like an HN URL")

    # Domain vs link consistency
    domain = post.get("domain", "")
    if isinstance(link, str) and isinstance(domain, str) and link and domain:
        # Extract domain from the link URL
        m = re.match(r"https?://(?:www\.)?([^/]+)", link)
        if m:
            link_domain = m.group(1).lower().rstrip(".")
            stated_domain = domain.lower().rstrip(".")
            # Allow subdomain stripping (e.g., "blog.example.com" stated as
            # "example.com") but flag completely different domains
            if link_domain != stated_domain and not link_domain.endswith("." + stated_domain):
                warnings.append(
                    f"{label}: domain '{domain}' does not match link URL "
                    f"(expected '{link_domain}')"
                )

    # Bullet counts
    content_bullets = post.get("content_bullets", [])
    if isinstance(content_bullets, list):
        if len(content_bullets) != 3:
            warnings.append(
                f"{label}: has {len(content_bullets)} content_bullets (expected 3)"
            )
        # Heuristic: detect copy-pasted comments
        for bi, bullet in enumerate(content_bullets):
            if isinstance(bullet, str):
                if bullet.startswith(">") or bullet.startswith("&gt;"):
                    warnings.append(
                        f"{label}: content_bullet {bi} starts with '>' "
                        f"(looks like a pasted HN quote, not a summary)"
                    )
                if re.match(r"^(Yes|No|Exactly|Agreed|This)[.\s]*$", bullet):
                    warnings.append(
                        f"{label}: content_bullet {bi} looks like a pasted "
                        f"one-word comment, not a summary: \"{bullet[:40]}\""
                    )

    disc_bullets = post.get("discussion_bullets", [])
    if isinstance(disc_bullets, list):
        if len(disc_bullets) < 1:
            warnings.append(f"{label}: no discussion_bullets")
        elif len(disc_bullets) > 4:
            warnings.append(
                f"{label}: has {len(disc_bullets)} discussion_bullets (expected 2-3)"
            )

    # Summary should differ from title
    title = post.get("title", "")
    summary = post.get("summary", "")
    if isinstance(title, str) and isinstance(summary, str):
        if title and summary and title.lower() == summary.lower():
            warnings.append(f"{label}: summary is identical to title")

    return errors, warnings


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_post.py <path-to-post.md>", file=sys.stderr)
        sys.exit(2)

    path = sys.argv[1]
    errors, warnings = validate(path)

    # Print results
    if warnings:
        print(f"\n{'='*60}")
        print(f"WARNINGS ({len(warnings)}):")
        print(f"{'='*60}")
        for w in warnings:
            print(f"  ⚠  {w}")

    if errors:
        print(f"\n{'='*60}")
        print(f"ERRORS ({len(errors)}):")
        print(f"{'='*60}")
        for e in errors:
            print(f"  ✗  {e}")
        print(f"\n❌ Validation FAILED — {len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1)
    else:
        total_warnings = len(warnings)
        suffix = f" ({total_warnings} warning(s))" if total_warnings else ""
        print(f"\n✓ Validation PASSED{suffix}")
        sys.exit(0)


if __name__ == "__main__":
    main()
