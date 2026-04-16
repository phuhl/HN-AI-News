---
name: hn-ai-news
description: Compile an executive summary of AI-related Hacker News posts from the last 24 hours. Use this skill when the user asks for AI news, HN AI digest, tech news summary, what's happening in AI, AI headlines, or any request for a curated AI news briefing from Hacker News. Also trigger when the user asks about recent AI developments, AI news roundup, or wants to catch up on AI/ML/LLM news.
allowed-tools: Bash, Read, WebFetch, Write
argument-hint: [YYYY-MM-DD or "today"]
---

# HN AI News Digest

Compile an executive summary of AI-relevant Hacker News posts, organized into thematic categories with structured summaries and discussion highlights. Produce both a markdown summary in the conversation AND an HTML file for GitHub Pages.

## Step 1: Fetch posts

Run the fetch script to get all HN posts for the target day. If the user provided a date argument, use it; otherwise default to today.

Save the output to a temp file for processing:
```bash
python3 {{SKILL_DIR}}/scripts/fetch_hn_posts.py --day <YYYY-MM-DD> --min-points 3 > /tmp/hn_posts.json 2>/tmp/hn_fetch.log
```

The script scrapes hckrnews.com for item IDs, enriches via the HN Algolia API, and has retry with exponential backoff for 429/5xx. If it fails, fall back to WebFetch on `https://hckrnews.com/`.

## Step 2: Identify AI-relevant posts

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

## Step 3: Fetch discussion details for AI-relevant posts

For each AI-relevant post, fetch the HN discussion page to get comment content:

```bash
echo '<JSON array of HN URLs or item IDs>' > /tmp/ai_post_ids.json
python3 {{SKILL_DIR}}/scripts/fetch_hn_discussion.py --ids-file /tmp/ai_post_ids.json --max-items 30 > /tmp/hn_discussions.json 2>/tmp/hn_disc.log
```

The script uses adaptive rate limiting — it starts with 3s between requests and increases the delay automatically if it hits 429s, then gradually recovers. This prevents the cascading failures we saw with shorter delays.

If there are many AI-relevant posts (>20), prioritize by points. For posts with very few comments (<3), skip fetching and note "Limited discussion."

## Step 4: Categorize posts

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

## Step 5: Output

Produce TWO outputs:

### Output A: Markdown in conversation

Print the digest directly in the conversation using this format per post:

```
**<Summary headline>** (<original title> - <date, time of posting>) [<X> pts, <Y> comments]
- <bullet 1: what it is / what happened>
- <bullet 2: key detail or finding>
- <bullet 3: why it matters or what's notable>

Discussion (<HN URL>):
- <key discussion point 1>
- <key discussion point 2>
- <key discussion point 3>
```

End with a `## Key Themes` section (3-5 sentences).

### Output B: HTML day file + index

**1. Day file** — write `<workspace>/hn-ai-news-<YYYY-MM-DD>.html`.

Read `{{SKILL_DIR}}/assets/template.html` and replace:
- `__TITLE__` → `AI News from HN — <readable date>` (e.g. `April 16, 2026`)
- `__GENERATED_AT__` → current UTC timestamp
- `__BODY__` → HTML built from the structure below

The template produces a page that looks like the Hacker News frontpage: orange top bar, tan background, Verdana font, items in a numbered list. Use the following HTML structure for `__BODY__`:

```html
<!-- Subtitle line -->
<p style="font-size:8pt; color:#828282; margin-bottom:4px;">
  April 16, 2026 &mdash; 20 AI-relevant posts from 137 total
</p>

<!-- For each non-empty category -->
<div class="category-header">Category Name</div>

<!-- For each post, rank counting up from 1 within the page -->
<div class="item">
  <div class="item-title-row">
    <span class="rank">1.</span>
    <span class="item-title">Summary headline</span>
    <span class="source-domain">(domain.com)</span>
  </div>
  <div class="item-meta">
    <span class="pts">281 points</span>
    &nbsp;|&nbsp; Apr 15, 14:30 UTC
    &nbsp;|&nbsp; 171 comments
    &nbsp;|&nbsp; <span class="orig-title">Original HN title unchanged</span>
  </div>
  <details>
    <summary>key points &amp; discussion</summary>
    <ul class="content-bullets">
      <li>Bullet point 1</li>
      <li>Bullet point 2</li>
      <li>Bullet point 3</li>
    </ul>
    <div class="disc-header">
      Discussion: <a href="https://news.ycombinator.com/item?id=...">HN thread</a>
    </div>
    <ul class="discussion-bullets">
      <li>Discussion point 1</li>
      <li>Discussion point 2</li>
      <li>Discussion point 3</li>
    </ul>
  </details>
</div>

<!-- Key themes at the end -->
<div class="themes">
  <div class="themes-title">Key Themes</div>
  <ul>
    <li>Theme sentence 1</li>
    <li>Theme sentence 2</li>
  </ul>
</div>
```

`<details>` is collapsed by default — clicking `summary` expands it. Headlines and metadata are always visible. Escape `<`, `>`, `&` in any titles or content. No `<script>` tags.

**2. Index file** — after writing the day file, regenerate `<workspace>/index.html`.

List all `hn-ai-news-YYYY-MM-DD.html` files that exist in the workspace, sort them newest-first, then write `index.html` using `{{SKILL_DIR}}/assets/index-template.html`.

Replace in the index template:
- `__GENERATED_AT__` → current UTC timestamp
- `__ENTRIES__` → one `.entry` div per file, newest at top:

```html
<div class="entry">
  <span class="entry-rank">1.</span>
  <a class="entry-link" href="hn-ai-news-2026-04-16.html">AI News — April 16, 2026</a>
  <span class="entry-meta">N posts</span>
</div>
```

Include the post count for each day in `entry-meta` if you know it (you do for the day you just generated; for older files you can omit or leave blank).

**3. Commit** — after writing both files:

```bash
cd <workspace>
git add hn-ai-news-<YYYY-MM-DD>.html index.html
git commit -m "Add AI news digest for <YYYY-MM-DD>"
```

Push only if the user explicitly asks.

## Formatting rules

- **Summary headline**: Concise, informative rewrite. If the original is clear, keep it similar.
- **Original title**: Exact HN title, unchanged.
- **Date, time**: `Apr 15, 14:30 UTC` from the `created_at` field.
- **Bullets**: Short, scannable, one line each. Facts not opinions.
- **Discussion bullets**: Most interesting/insightful top-comment points. If discussion is thin, write "Limited discussion."

## Notes

- The scripts require `requests` and `beautifulsoup4`. If missing: `pip3 install --break-system-packages requests beautifulsoup4`
- For busy days (>30 AI posts), focus on posts with 20+ points.
- If scripts fail completely, fall back to WebFetch on `https://hckrnews.com/` and individual discussion pages.
