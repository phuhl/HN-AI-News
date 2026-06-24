---
name: hn-ai-news-weekly
description: Compile a weekly AI-news digest by condensing the last 7 daily HN AI digests into a single week-in-review. Use this skill whenever the user asks for a weekly AI roundup, a week summary, "this week in AI", a 7-day recap, a week-in-review, or wants to catch up on the week's top AI stories from Hacker News. Also trigger on "compile the week", "weekly digest", "weekly AI news", or "summarize the week of AI news". This is the weekly counterpart to the daily hn-ai-news skill — reach for it when the scope is a whole week rather than a single day.
allowed-tools: Bash, Read, Write
argument-hint: [end date YYYY-MM-DD, or "this week"]
---

# HN AI News — Weekly Digest

Compile a weekly digest that condenses the **last 7 daily digests** into one
week-in-review. The daily `hn-ai-news` skill already did the expensive work —
fetching Hacker News, filtering AI posts, reading each article, and writing a
Jekyll post with summaries, content bullets, discussion bullets, and points.

This skill **reuses that compiled data**. It does not re-fetch HN or re-read
articles. It reads the seven most recent `_posts/*-hn-ai-news.md` files, ranks
every story across the week by points, keeps the top **50**, regroups them into
the same categories, and writes a weekly post in the **same format** as a daily
one — so it renders through the existing `digest` layout with no template work.

Why reuse instead of re-summarize: the daily bullets were written from the
actual articles with full context. Copying them verbatim keeps the weekly
consistent with what readers already saw, costs almost nothing, and means the
only genuinely new writing you do is the week's themes. That's deliberate — your
attention should go to the cross-week synthesis, not to rephrasing 50 stories.

The heavy lifting (parsing, dedup, ranking, grouping, YAML assembly) lives in a
script so it stays deterministic and correct. You provide the one thing a script
can't: the week's themes.

## Step 1: Check the Python dependency

```bash
python3 -c "import yaml" 2>/dev/null || pip3 install --break-system-packages pyyaml
```

Only PyYAML is needed — no network libraries, since nothing is fetched.

## Step 2: Select and condense the week's stories

Run the `select` phase. It finds the daily digests in the 7-day window, drops
stories that recur across days (keeping the highest-points copy), ranks by
points, keeps the top 50, and regroups them into categories.

```bash
python3 {{SKILL_DIR}}/scripts/compile_week.py select \
    --posts-dir _posts \
    --max-stories 50 \
    > /tmp/week_stories.json 2>/tmp/week_select.log
cat /tmp/week_select.log
```

- **Default window**: the 7 days ending at the most recent daily digest. If the
  user named an end date (or you want a specific week), pass
  `--end-date YYYY-MM-DD` — the window is that date and the six days before it.
- The script writes a summary to stderr (how many posts collapsed to how many
  unique, how many were selected) and **notes any missing days** in the window.
  If days are missing, that's fine — the week is built from whatever digests
  exist — but mention the gap to the user so the smaller story count makes sense.

The output `/tmp/week_stories.json` carries the selected stories grouped into
sections, plus `meta` (date range, counts) and `daily_themes` (every theme from
each day, tagged with its date) — that last part is your raw material for Step 3.

## Step 3: Write the week's themes — the one part only you can do

This is where the weekly digest earns its keep. The daily themes tell you what
each day felt important; your job is to find the **arc across the week**.

Read `/tmp/week_stories.json`. Look at the top stories and the `daily_themes`
list, and write **3–5 themes** that capture the week as a whole. Good weekly
themes do something a daily theme can't:

- **Trace a thread across days** — a story that built, escalated, or got a
  rebuttal over the week (e.g. a model launch on Monday that the community had
  picked apart by Thursday).
- **Name a pattern that only shows up at week scale** — several independent
  stories pointing the same direction (e.g. three separate signs of pressure on
  the AI job market).
- **Call the week's biggest story** — if one thing clearly dominated, say so and
  why, rather than burying it among equals.

Avoid just concatenating daily themes or listing "X happened, also Y happened."
Each theme is one or two sentences of plain English a tech-curious reader gets
without insider acronyms. Write them to a JSON file as a list of strings:

```bash
cat > /tmp/week_themes.json <<'EOF'
[
  "First theme — a trend or arc that spans several of the week's stories.",
  "Second theme.",
  "Third theme."
]
EOF
```

## Step 4: Assemble the weekly post

Run the `assemble` phase. It joins your themes with the selected stories and
writes the Jekyll post, copying every story field verbatim from the daily data.

```bash
python3 {{SKILL_DIR}}/scripts/compile_week.py assemble \
    --stories /tmp/week_stories.json \
    --themes /tmp/week_themes.json \
    --posts-dir _posts
```

This writes `_posts/<end-date>-hn-ai-news-weekly.md`. The frontmatter uses
`layout: digest` (the existing template) plus `digest_type: weekly`, a
"Weekly AI Digest — Week of …" title, and a "Week of …" `readable_date` so it
reads as a week everywhere it appears.

It also sets an explicit `permalink: /hn-ai-news-weekly-<end-date>.html`. This
matters: `_config.yml` derives every post's URL from its **date alone**
(`/hn-ai-news-:year-:month-:day.html`), ignoring the filename, so the weekly and
the daily for the same end date would otherwise resolve to the *same* URL and
silently clobber each other on the live site. The `weekly` segment keeps them
apart — the validator fails if it's missing.

## Step 5: Validate

```bash
python3 {{SKILL_DIR}}/scripts/validate_week.py _posts/<end-date>-hn-ai-news-weekly.md
```

The validator checks the structure that matters for a *weekly* post: valid YAML,
`digest_type: weekly`, 3–5 themes, every story field present, the 50-story cap,
date agreement across filename/frontmatter/title, and that no story slipped
through dedup and appears twice. It reports over-length bullets as a single
informational line, not an error — those are inherited verbatim from the daily
digests and aren't this skill's job to fix. Fix any real errors before committing.

## Step 6: Make sure the index lists weekly digests distinctly

Weekly posts appear in `index.html`'s archive list automatically (it loops all
posts). To make them stand out inline — without a separate section that would
push the daily list down — the index branches on `digest_type == 'weekly'` to
add a "WEEK" badge and a "Weekly Digest — …" label.

This is a **one-time** site change. Check whether it's already in place:

```bash
grep -q "digest_type == 'weekly'" index.html && echo "index already weekly-aware" || echo "PATCH NEEDED"
```

If it prints `PATCH NEEDED` (e.g. on a fresh clone), update the archive loop in
`index.html` so weekly entries render with the badge, and add the `.entry-weekly`
/ `.weekly-badge` styles to `style.css`. Keep them **inline in the single
chronological list** — do not create a separate weekly section, since that makes
the daily digests harder to scroll to as the archive grows.

## Step 7: Commit and publish

The repo is a GitHub Pages site, so the post must land on `master` to go live —
the same flow the daily skill uses.

```bash
git add _posts/<end-date>-hn-ai-news-weekly.md
# include these too only if Step 6 had to patch them:
#   git add index.html style.css
git commit -m "Add weekly AI digest for week ending <end-date>"
git push origin HEAD:master
```

Use `HEAD:master` rather than pushing the current branch — this lands the post
on master even when you're on a worktree branch (e.g. `claude/…`), and never
pushes the worktree branch itself.

## Notes

- **The daily digests are the source of truth.** Story metadata and bullets are
  copied as-is; never edit them here. If a daily digest looks wrong, fix it in
  the daily flow, not in the weekly one.
- **Re-running is safe.** `assemble` overwrites the same `-weekly.md` file for a
  given end date, so regenerating a week (e.g. after a late daily digest lands)
  just updates it.
- **Cap and ranking** are deterministic: top 50 by points, ties broken by the
  script's stable order. If a week is quiet and fewer than 50 AI stories exist,
  you simply get all of them — that's expected, not an error.
- **Don't touch the layout.** `_layouts/digest.html` already renders everything
  from the frontmatter fields; the weekly post deliberately reuses them. The
  stat line will read "Week of … — 50 AI-relevant posts from N total", where N
  is the week's unique AI-story count — i.e. the 50 shown out of N that week.
