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
python3 {{SKILL_DIR}}/scripts/fetch_hn_discussion.py --ids-file /tmp/ai_post_ids.json --max-items 30 > /tmp/hn_discussions.json 2>/tmp/hn_disc.log
```

The script uses adaptive rate limiting — it starts with 3s between requests and increases the delay automatically if it hits 429s, then gradually recovers.

If there are many AI-relevant posts (>20), prioritize by points. For posts with very few comments (<3), skip fetching and note "Limited discussion."

## Step 5: Categorize posts

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

## Step 6: Write the Jekyll post

Write a single file: `<workspace>/_posts/<YYYY-MM-DD>-hn-ai-news.md`

This file is a markdown file with YAML frontmatter containing ALL the structured digest data. The Jekyll layout template in the repo handles rendering — you only produce the data.

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

That's it — no markdown body content is needed. The layout handles everything.

### Content guidelines for the structured fields

**themes** (3-5 sentences): High-level patterns you notice across the day's posts. Each theme should connect multiple posts or highlight a significant trend. These give the reader a quick "what happened today in AI" overview without reading individual posts.

**summary**: A concise, informative rewrite of what the post is about. Not the original title (that's in `title`), but your editorial summary that helps readers understand the story at a glance. If the original title is already clear, keep it similar.

**content_bullets** (3 per post): These summarize the *article or announcement itself* — NOT the HN comments. Write your own synthesis based on what the article is about, what it does or claims, and why it's significant. Structure:
  1. What it is or what happened — the core news in one line
  2. A key technical detail, finding, or specification worth knowing
  3. Why it matters, what's notable, or what the implications are

**discussion_bullets** (2-3 per post): These summarize the *most interesting ideas from the HN comment thread* — NOT the article content. Distill the key insights, counterarguments, technical experiences, or caveats that commenters raised. The goal is to capture what the community thinks is important, surprising, or wrong about the post. Don't copy-paste individual comments verbatim — synthesize the important points. If discussion is thin (<3 comments), use a single bullet: "Limited discussion."

### After writing the post

Run the validation script to verify the output is well-formed:

```bash
python3 {{SKILL_DIR}}/scripts/validate_post.py <workspace>/_posts/<YYYY-MM-DD>-hn-ai-news.md
```

The validator checks YAML structure, required fields, bullet counts, and detects common mistakes like copy-pasting HN comments into content_bullets (which should be your own synthesis of the article, not quotes from the thread). Fix any errors before committing. Warnings about pasted quotes or one-word bullets indicate the content_bullets need rewriting — they should describe the article, not echo comments.

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
