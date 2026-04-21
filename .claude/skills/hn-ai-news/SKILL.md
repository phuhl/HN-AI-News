---
name: hn-ai-news
description: Compile an executive summary of AI-related Hacker News posts from the last 24 hours. Use this skill when the user asks for AI news, HN AI digest, tech news summary, what's happening in AI, AI headlines, or any request for a curated AI news briefing from Hacker News. Also trigger when the user asks about recent AI developments, AI news roundup, or wants to catch up on AI/ML/LLM news.
allowed-tools: Bash, Read, WebFetch, Write
argument-hint: [YYYY-MM-DD or "today"]
---

# HN AI News Digest

Compile an executive summary of AI-relevant Hacker News posts, organized into thematic categories with structured summaries and discussion highlights.

The output is a Jekyll post file (markdown with YAML frontmatter) containing structured data. The repository is a Jekyll site deployed via GitHub Pages — layouts and styles already exist in the repo, so you only need to produce the data file and commit it.

## Step 1: Check Python dependencies

```bash
python3 -c "import requests, bs4" 2>/dev/null || pip3 install --break-system-packages requests beautifulsoup4
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

## Step 4: Fetch discussion details for AI-relevant posts

For each AI-relevant post, fetch the HN discussion page to get comment content:

```bash
echo '<JSON array of HN URLs or item IDs>' > /tmp/ai_post_ids.json
python3 {{SKILL_DIR}}/scripts/fetch_hn_discussion.py --ids-file /tmp/ai_post_ids.json --max-items 40 > /tmp/hn_discussions.json 2>/tmp/hn_disc.log
```

The script uses the HN Algolia API to fetch the full comment tree for each discussion. It returns the top comments (in HN's ranked order) paired with each comment's best reply for threaded context. It uses adaptive rate limiting with exponential backoff on 429s.

If there are many AI-relevant posts (>20), prioritize by points. For posts with very few comments (<3), skip fetching and note "Limited discussion."

## Step 5: Categorize and assign posts

Assign each AI-relevant post to exactly one category. Drop empty categories from output:

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

After categorizing, save the full list of posts with their metadata, category assignments, and discussion data to `/tmp/hn_ai_categorized.json`. This file will be the input for the summarization step.

## Step 6: Summarize articles via subagents

This is the most important step for content quality. Each post needs two things:
- **content_bullets**: a synthesis of the *actual article* (not HN comments)
- **discussion_bullets**: a synthesis of the *HN thread*

To produce good content_bullets, the article itself must be read. To keep the main context window lean, spawn subagents using the **Agent tool** to do the heavy lifting. Split the posts into batches of ~5 and spawn one subagent per batch, running them in parallel.

Each subagent prompt should include:
1. The batch of posts (metadata + discussion threads from `/tmp/hn_ai_categorized.json`)
2. Instructions to **WebFetch each article's source URL** and read the content
3. Instructions to produce the structured YAML output per post (see format below)
4. Instructions to save output to `/tmp/hn_summaries_batch_<N>.json`

Here is a template for the subagent prompt — adapt as needed:

```
You are summarizing articles for an AI news digest. For each post below,
do the following:

1. WebFetch the article URL to read the actual article content
2. Write 3 content_bullets that summarize THE ARTICLE (not the HN comments):
   - Bullet 1: What it is or what happened — the core news
   - Bullet 2: A key technical detail, finding, or specification
   - Bullet 3: Why it matters or what's notable
3. Write 2-3 discussion_bullets synthesizing the HN thread highlights
   (the interesting insights, counterarguments, or caveats from commenters)
4. Write a summary field: a concise editorial headline for the post

If WebFetch fails (paywall, 404, timeout), write content_bullets based on
the article title and any clues from the HN discussion, and note that the
article was not directly accessible.

If discussion is thin (<3 comments), use: "Limited discussion."

Do NOT copy-paste HN comments verbatim into content_bullets. Those must be
YOUR synthesis of the article. discussion_bullets should synthesize comment
themes, not quote individual users.

Posts to process:
<paste the batch JSON here>

Save the results as a JSON array to: /tmp/hn_summaries_batch_<N>.json
Each entry should have: item_id, summary, content_bullets, discussion_bullets
```

After all subagents complete, read and merge the batch result files.

## Step 7: Assemble the Jekyll post

Write a single file: `<workspace>/_posts/<YYYY-MM-DD>-hn-ai-news.md`

This is a markdown file with YAML frontmatter containing ALL the structured digest data. The Jekyll layout template handles rendering — you only produce the data file.

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
      - title: "<exact original HN title, unchanged>"
        link: "<source URL>"
        domain: "<domain.com>"
        summary: "<your concise summary headline — informative rewrite of what this is about>"
        points: <number>
        hn_url: "https://news.ycombinator.com/item?id=<id>"
        comments: <number>
        time: "<Mon DD, HH:MM UTC>"
        content_bullets:
          - "<what it is or what happened — the core news>"
          - "<key technical detail or finding worth knowing>"
          - "<why it matters or what's notable about this>"
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

**summary**: A concise, informative rewrite of what the post is about. Not the original title (that's in `title`), but your editorial summary that helps readers understand the story at a glance. If the original title is already clear, keep it similar.

**content_bullets** (3 per post): These summarize the *article or announcement itself* — NOT the HN comments. The subagents WebFetched each article to produce these. Structure:
  1. What it is or what happened — the core news in one line
  2. A key technical detail, finding, or specification worth knowing
  3. Why it matters, what's notable, or what the implications are

**discussion_bullets** (2-3 per post): These summarize the *most interesting ideas from the HN comment thread* — NOT the article content. Distill the key insights, counterarguments, technical experiences, or caveats that commenters raised. Don't copy-paste individual comments verbatim — synthesize the important points. If discussion is thin (<3 comments), use a single bullet: "Limited discussion."

### After writing the post

Run the validation script to verify the output is well-formed:

```bash
python3 {{SKILL_DIR}}/scripts/validate_post.py <workspace>/_posts/<YYYY-MM-DD>-hn-ai-news.md
```

The validator checks YAML structure, required fields, bullet counts, date consistency (filename vs frontmatter vs title), and detects common mistakes like copy-pasting HN comments into content_bullets. Fix any errors before committing.

Once validation passes cleanly, commit:

```bash
cd <workspace>
git add _posts/<YYYY-MM-DD>-hn-ai-news.md
git commit -m "Add AI news digest for <YYYY-MM-DD>"
```

Push only if the user explicitly asks.

## Notes

- For busy days (>30 AI posts), focus on posts with 20+ points.
- If scripts fail completely, fall back to WebFetch on `https://hckrnews.com/` and individual discussion pages.
- The Jekyll site structure (layouts, config, styles) is already in the repo — do not modify those files.
- If a subagent's WebFetch fails for an article, it should still produce content_bullets from the title and HN discussion context — just note the limitation.
