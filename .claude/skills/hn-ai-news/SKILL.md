---
name: hn-ai-news
description: Compile an executive summary of AI-related Hacker News posts from the last 24 hours. Use this skill when the user asks for AI news, HN AI digest, tech news summary, what's happening in AI, AI headlines, or any request for a curated AI news briefing from Hacker News. Also trigger when the user asks about recent AI developments, AI news roundup, or wants to catch up on AI/ML/LLM news.
allowed-tools: Agent, Bash, Read, WebFetch, Write
argument-hint: [YYYY-MM-DD or "today"]
---

# HN AI News Digest

Compile an executive summary of AI-relevant Hacker News posts, organized into thematic categories with structured summaries and discussion highlights.

The output is a Jekyll post file (markdown with YAML frontmatter) containing structured data. The repository is a Jekyll site deployed via GitHub Pages — layouts and styles already exist in the repo, so you only need to produce the data file and commit it.

## Step 1: Check Python dependencies

```bash
python3 -c "import requests, bs4, yaml" 2>/dev/null || pip3 install --break-system-packages requests beautifulsoup4 pyyaml
```

## Step 2: Fetch posts

Run the fetch script to get all HN posts for the target day. If the user provided a date argument, use it; otherwise default to today.

```bash
python3 {{SKILL_DIR}}/scripts/fetch_hn_posts.py --day <YYYY-MM-DD> --min-points 3 > /tmp/hn_posts.json 2>/tmp/hn_fetch.log
```

The script fetches from hckrnews.com — HTML for recent days (last ~2 days), static `.js` day files for older dates. The digest named `YYYY-MM-DD` covers the 24 hours **before** that date (i.e. the data day is `date - 1`). If it fails, fall back to WebFetch on `https://hckrnews.com/`.

## Step 3: Identify AI-relevant posts

Read `/tmp/hn_posts.json` and filter for AI-relevant posts. A post is AI-relevant if its title or topic relates to:

- New AI models, releases, benchmarks, model performance
- AI products, tools, frameworks, SDKs, APIs (ChatGPT, Claude, Gemini, Llama, etc.)
- AI agents, autonomous systems, agentic workflows
- AI coding tools, vibe coding, AI-assisted development
- LLMs, inference, fine-tuning, training, embeddings
- AI policy, regulation, legal rulings about AI
- AI safety, ethics, alignment, whistleblowers
- AI business news (valuations, funding, acquisitions, pivots)
- AI infrastructure, compute, GPUs, data centers
- AI impact on society, jobs, education, deepfakes
- AI research papers, breakthroughs
- Robotics with AI/ML components
- Open source AI, model weights, local inference

Be inclusive rather than exclusive. When in doubt, include the post.

### Deduplication

HN often has multiple posts about the same topic (e.g., two submissions of the same article, or a blog post and its HN Show post). Before proceeding, group posts that cover the same underlying story. Keep the post with the most points as the primary entry — its `item_id`, `source_url`, `title`, `points`, and `hn_url` will be used in the final output. But note all duplicate item IDs so that Step 4 fetches discussions for all of them — the comments from smaller threads often contain unique insights that the main thread missed.

### Zero AI-relevant posts

If no posts pass the AI-relevance filter, still produce a digest. Use a single theme like "A quiet day for AI on Hacker News — no posts met the relevance threshold" and write an empty `sections: []`. The validator and Jekyll layout both handle this gracefully.

## Step 4: Fetch discussion details for AI-relevant posts

For each AI-relevant post (including duplicate item IDs from Step 3), fetch the HN discussion via the Algolia API:

```bash
echo '<JSON array of objects with item_id fields — include duplicates>' > /tmp/ai_post_ids.json
python3 {{SKILL_DIR}}/scripts/fetch_hn_discussion.py --ids-file /tmp/ai_post_ids.json --max-items 40 > /tmp/hn_discussions.json 2>/tmp/hn_disc.log
```

The script returns the top comments (in HN's ranked order) paired with each comment's best reply for threaded context. It uses adaptive rate limiting with exponential backoff on 429s.

If there are many AI-relevant posts (>20), prioritize by points. For posts with very few comments (<3), skip fetching and note "Limited discussion."

## Step 5: Merge data, categorize, and save

### 5a: Save AI-relevant post IDs with duplicate groups

From the filtering and deduplication in Step 3, save a JSON file listing the AI-relevant posts and their duplicate groups:

```bash
# Write to /tmp/ai_post_ids.json — example format:
# [
#   {"item_id": "12345", "duplicates": ["12399"]},
#   {"item_id": "12346"},
#   ...
# ]
```

Each entry has an `item_id` (the primary post) and an optional `duplicates` array listing item IDs that cover the same story. Posts without duplicates can omit the field.

### 5b: Run the merge script

The merge script deterministically joins post metadata with discussion data, resolves URLs (preferring the Algolia canonical URL over hckrnews), and merges discussion threads from duplicate posts:

```bash
python3 {{SKILL_DIR}}/scripts/merge_posts.py \
    --posts /tmp/hn_posts.json \
    --discussions /tmp/hn_discussions.json \
    --ai-ids /tmp/ai_post_ids.json \
    > /tmp/hn_ai_merged.json 2>/tmp/hn_merge.log
```

The output contains one entry per deduplicated post with resolved `source_url`, `domain`, `time`, and merged `threads`. All metadata fields are finalized at this point — later steps should not modify them.

### 5c: Categorize

Read `/tmp/hn_ai_merged.json` and assign each post to exactly one category. Drop empty categories from output:

| Category | What goes here |
|----------|---------------|
| **New Models & Releases** | New model announcements, version updates, benchmark results, model comparisons |
| **AI Products & Tools** | New AI products, features, SDKs, developer tools, integrations |
| **AI Agents & Automation** | Autonomous agents, agentic workflows, AI assistants, browser automation |
| **AI Coding & Development** | AI-assisted coding, vibe coding, IDE tools, code generation |
| **Claude / Anthropic** | Anything specifically about Claude, Anthropic, Claude Code |
| **OpenAI / ChatGPT** | Anything specifically about OpenAI, ChatGPT, GPT models |
| **Google / DeepMind** | Anything specifically about Gemini, Gemma, DeepMind, Google AI |
| **AI Industry & Business** | Valuations, funding, acquisitions, pivots, market trends |
| **AI Policy, Legal & Regulation** | Laws, court rulings, regulation, government AI policy |
| **AI Safety & Ethics** | Alignment, deepfakes, whistleblowers, AI risks, bias |
| **AI Infrastructure & Compute** | GPUs, data centers, inference infrastructure, on-device AI |
| **AI in Society** | Impact on jobs, education, culture, creative work |
| **AI Research** | Papers, breakthroughs, techniques, benchmarks methodology |
| **Open Source AI** | Open model releases, open source tools, local inference |

Company-specific categories take priority when applicable.

Save the categorized result to `/tmp/hn_ai_categorized.json` — add a `category` field to each entry from the merged data. This file is the single source of truth for Steps 6 and 7.

## Step 6: Summarize articles via subagents

This is the most important step for content quality. Each post needs two things:
- **content_bullets**: a synthesis of the *actual article* (not HN comments)
- **discussion_bullets**: a synthesis of the *HN thread*

To produce good content_bullets, the article itself must be read. To keep the main context window lean, spawn **one subagent per post** using the Agent tool. Each agent handles exactly one article — this prevents cross-contamination between posts with similar topics.

Read `/tmp/hn_ai_categorized.json` and spawn all agents in parallel (use `run_in_background: true`). Embed the single post's JSON directly in the prompt — the subagent has no access to the parent's files. Each agent saves its result to `/tmp/hn_summary_<item_id>.json`.

If there are more than 15 posts, spawn them in two waves to avoid throughput issues — launch the first wave, wait for completion, then launch the second.

Here is the subagent prompt template:

```
You are summarizing a single article for an AI news digest.

Article to summarize:
<embed the single post JSON here, including title, source_url, and threads>

Steps:
1. Fetch the article using this fallback chain (stop at the first success):
   a. WebFetch the source_url
   b. WebFetch https://webcache.googleusercontent.com/search?q=cache:<source_url>
   c. WebFetch https://web.archive.org/web/2/<source_url>
   If all three fail, work from the title and discussion threads.
2. Write 3–5 content_bullets summarizing THE ARTICLE (not HN comments).
   Each bullet is a tight, standalone one-liner — aim for scan-ability over completeness.
   IMPORTANT — no rehashing: The reader has already seen the title and your summary
   headline. Your first bullet must NOT restate what they say. Jump straight to the
   details, specifics, or context that the headlines couldn't convey. Every bullet
   should teach the reader something new.
   ONE EXCEPTION — context for obscure terms: If the title or summary mentions a
   lesser-known technology, language, company, or concept (e.g. "Zig", "Mojo",
   "Anduril"), weave a brief parenthetical explanation into whichever bullet first
   uses it — e.g. "a single Zig (low-level programming language) binary" or
   "Anduril (defense-tech startup)". You don't need this for household names like
   Python, TypeScript, AWS, OpenAI, Google, etc. — only for things a tech-curious
   reader might not immediately recognize.
   Keep bullets SHORT — under 200 characters each (hard cap: 300). If a bullet needs
   more than one sentence, split it into two bullets or cut the less important half.
   Cover: key specifics, notable numbers, why it matters. Don't pad to hit a count;
   don't cram two ideas into one sentence. Plain English — spell out any acronyms or
   jargon that a smart non-specialist wouldn't immediately recognize.
3. Write 2-3 discussion_bullets synthesizing the HN thread highlights
   (interesting insights, counterarguments, or caveats from commenters).
   If discussion is thin (<3 comments): single bullet "Limited discussion."
4. Write a summary: a plain-English editorial headline. Avoid insider abbreviations —
   if you use an acronym, it should be one any tech-curious reader would know (AI, API are fine;
   things like RLHF, MoE, KV-cache are not — spell them out or rephrase).

content_bullets must be your synthesis of the article itself — not rephrased
HN comments. discussion_bullets should synthesize comment themes, not quote
verbatim.

If WebFetch fails, write the best summary you can from the title and thread
context. Never mention fetch failures in the output.

Save the result as JSON to: /tmp/hn_summary_<item_id>.json
Format: { "item_id": "...", "summary": "...", "content_bullets": [...], "discussion_bullets": [...] }
```

After all subagents complete, read the per-post files and match each back to `/tmp/hn_ai_categorized.json` by `item_id`.

## Step 7: Assemble the Jekyll post

Write a single file: `<workspace>/_posts/<YYYY-MM-DD>-hn-ai-news.md`

This is a markdown file with YAML frontmatter containing ALL the structured digest data. The Jekyll layout template handles rendering — you only produce the data file.

All metadata fields (`link`, `domain`, `title`, `points`, `hn_url`, `comments`, `time`) come directly from `/tmp/hn_ai_categorized.json` — they were resolved in Step 5 and should be copied as-is. The only fields that come from the Step 6 subagents are `summary`, `content_bullets`, and `discussion_bullets`.

**Important date rule**: The `date`, `readable_date`, and the date in `title` must ALL use the digest date (the `--day` value / filename date), NOT the data-fetch day. If the digest is for 2026-04-21, everything says April 21 — even though the HN posts are from April 20.

### YAML frontmatter structure

```yaml
---
layout: digest
date: "YYYY-MM-DD"
title: "AI News from HN — <readable date>"
readable_date: "<Month Day, Year>"
total_posts: <total HN posts that day>
ai_posts: <number of AI-relevant posts selected>
themes:
  - "<theme sentence 1 — a key trend or pattern across multiple posts>"
  - "<theme sentence 2>"
  - "<theme sentence 3>"
sections:
  - name: "<Category Name>"
    posts:
      - title: "<exact original HN title>"
        link: "<source_url from Step 5 data>"
        domain: "<domain extracted from link>"
        summary: "<your concise summary headline — informative rewrite of what this is about>"
        points: <number>
        hn_url: "https://news.ycombinator.com/item?id=<id>"
        comments: <number>
        time: "<Mon DD, HH:MM UTC>"
        content_bullets:
          - "<tight one-liner: what happened or what this is>"
          - "<tight one-liner: a key detail or spec>"
          - "<tight one-liner: why it matters — add more bullets if useful, up to 5>"
        discussion_bullets:
          - "<key insight or counterargument from the HN thread>"
          - "<notable technical experience or perspective shared>"
          - "<important caveat or broader implication raised>"
---
```

No markdown body content is needed. The layout handles everything.

**Do NOT use `categories:` as the key** — it is a reserved Jekyll frontmatter field. Always use `sections:`.

### Content guidelines for the structured fields

**themes** (3-5 sentences): High-level patterns you notice across the day's posts. Each theme should connect multiple posts or highlight a significant trend. These give the reader a quick "what happened today in AI" overview without reading individual posts.

**summary**: A plain-English editorial headline — not a restatement of the HN title, but a rewrite that makes the story immediately clear to any tech-curious reader. Avoid insider abbreviations and acronyms unless they're universally known (AI, API: fine; RLHF, MoE, KV-cache: spell out or rephrase). Aim for the kind of headline you'd see in a well-written newsletter.

**content_bullets** (3–5 per post): These summarize the *article or announcement itself* — NOT the HN comments. Think scannable one-liners: each bullet should stand alone and deliver one crisp fact or takeaway. Don't cap at 3 if there's more worth knowing; don't pad to 5 if 3 covers it. Prefer shorter sentences over structured sub-bullets. Plain English throughout — define any jargon a non-specialist might not know.

**Bullet brevity and non-redundancy**: The reader sees title → summary → bullets in that order. By the time they hit the bullets, they already know *what* the thing is and roughly *why it matters* — the title and summary covered that. So bullets should skip the setup and go straight to the interesting specifics, numbers, caveats, or context. Each bullet should be under 200 characters (the validator warns above 200 and errors above 300). If you can't fit a point in 200 chars, either split it or cut the weaker half.

**discussion_bullets** (2-3 per post): These summarize the *most interesting ideas from the HN comment thread* — NOT the article content. Distill the key insights, counterarguments, technical experiences, or caveats that commenters raised. Don't copy-paste individual comments verbatim — synthesize the important points. If discussion is thin (<3 comments), use a single bullet: "Limited discussion."

### After writing the post

Run the validation script to verify the output is well-formed:

```bash
python3 {{SKILL_DIR}}/scripts/validate_post.py <workspace>/_posts/<YYYY-MM-DD>-hn-ai-news.md
```

The validator checks YAML structure, required fields, bullet counts, date consistency (filename vs frontmatter vs title), and detects common mistakes like copy-pasting HN comments into content_bullets. Fix any errors before committing.

Once validation passes cleanly, commit and push to master:

```bash
cd <workspace>
git add _posts/<YYYY-MM-DD>-hn-ai-news.md
git commit -m "Add AI news digest for <YYYY-MM-DD>"
git push origin HEAD:master
```

Use `HEAD:master` rather than pushing the current branch — this ensures the post lands on master on the remote even if you are running on a worktree branch (e.g. `claude/festive-cerf-sHr3K`). Never push the worktree branch itself.

## Notes

- For busy days (>30 AI posts), focus on posts with 20+ points.
- If scripts fail completely, fall back to WebFetch on `https://hckrnews.com/` and individual discussion pages.
- The Jekyll site structure (layouts, config, styles) is already in the repo — do not modify those files.
- If a subagent's WebFetch fails for an article, it should still produce content_bullets from the title and HN discussion context. Never surface technical failures in the reader-facing output.
