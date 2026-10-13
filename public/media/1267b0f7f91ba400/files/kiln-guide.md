# Hardening the Serge Bulaev LinkedIn Claude Skills Bundle for Draft-Only Workflows

Researched 2026-10-12.

### 1. Reel Claims vs. Official Documentation

A viral Instagram reel from creator [Shashwat Agarwal](https://www.instagram.com/reel/Dd73i1bz_Nu/) presents a high-gloss automation funnel around autonomous LinkedIn operations. Evaluating the reel against the official [sergebulaev/linkedin-skills](https://github.com/sergebulaev/linkedin-skills) documentation reveals key distinctions:

* **Model Tie-in:** The reel frames this as an "Opus 5.5" system. In reality, the skills are model-agnostic prompt/tool definitions compatible with any Claude Code, Codex, or agentskills.io harness.
* **Skill Count:** The reel claims 11 skills; the current repository ships 12 skills (adding *Interviewer*, which builds a persistent "Story Bank").
* **Automation vs. Draft Gates:** The reel suggests full hands-off automation, yet the official repository enforces an approve-before-publish flow where every tool produces an explicit draft card before touching an API.
* **AI Detector Scores:** The reel advertises running drafts through five AI detectors to ensure a clean score before posting. The official repo documentation disclaims this, noting that "no edit reliably beats detectors" and uses multi-detector testing (GPTZero, Originality.ai, ZeroGPT, Sapling, Copyleaks) specifically to demonstrate detector variance and disagreement rather than to promise detection evasion.
* **Access Gate:** The creator requires users to comment to receive setup instructions. In truth, the repository is fully open-source (MIT license) and directly accessible.

---

### 2. Confirmed Skills & Architecture

The 12 skills in [sergebulaev/linkedin-skills](https://github.com/sergebulaev/linkedin-skills) divide into content creation, profile strategy, and external data reading:

1. **Post Writer:** Applies 20 hook formulas (e.g., controlled A/B, curiosity gap, founder angles) tailored to engagement goals.
2. **Comment Drafter:** Writes contextual comments on external posts.
3. **Reply Handler:** Handles LinkedIn's two-level thread hierarchy, batch drafting replies.
4. **Post Audit:** Reviews drafts against character limits and structural algorithm guidelines.
5. **Humanizer:** Eliminates common LLM vocabulary tells, staccato stacks, and excessive em dashes without claiming to guarantee detection bypass.
6. **Hook Extractor:** Deconstructs viral posts into structural reusable templates.
7. **Content Planner:** Produces a 7-day content schedule aligned with audience ICPs.
8. **Engagement Monitor:** Groups post engagers (likers/commenters) by ICP fit in a 6-24 hour post window.
9. **Profile Optimizer:** Rewrites headline, About, and Experience sections for profile conversion.
10. **Employee Advocacy:** Structures 14-day launch plans and brand governance for teams.
11. **Repurposer:** Re-formats threads, newsletters, and YouTube transcripts into 900-1,300 character native posts.
12. **Interviewer:** Conducts an interactive interview to establish a factual "Story Bank" (metrics, inflection points, positions) to ground subsequent writing.

---

### 3. Account Risks, Scrapers, and LinkedIn Terms of Service

* **LinkedIn User Agreement §8.2:** Explicitly bars unauthorized scrapers, bots, and automated engagement (auto-liking, auto-commenting, automated connection requests). Automating browser interactions directly risks temporary account restriction or permanent identity loss.
* **Scraping Degradation:** Four skills (*Comment Drafter*, *Reply Handler*, *Hook Extractor*, *Engagement Monitor*) can optionally fetch external data using cookie-less Apify scrapers ($1-$5 per 1,000 runs). When an `APIFY_TOKEN` is absent, the skills safely fall back to manual copy-paste mode without triggering LinkedIn bot defenses.
* **Direct Publishing:** Optional scheduling connects to [Publora](https://app.publora.com/signup) (15 free posts/month via API or connector). If Publora is omitted, skills remain copy-paste drafts.

---

### 4. Verified Setup & Diagnostics

#### Direct Universal Installation
To install across Claude Code, Codex, or Cursor using the standard package manager:
```bash
npx skills add sergebulaev/linkedin-skills
```

#### Local Clone & Codex Setup
```bash
git clone https://github.com/sergebulaev/linkedin-skills.git
cd linkedin-skills
codex plugin marketplace add .
codex plugin add linkedin-skills@linkedin-skills
```

#### Claude Code Native Directory Setup
Cloning into your project directory activates symlinked skills in `.claude/skills/`:
```bash
git clone https://github.com/sergebulaev/linkedin-skills.git
cd linkedin-skills
```
*(Windows Note: Symlinks require elevated Developer Mode or directory junctions via `for /d %s in (skills\*) do mklink /J .claude\skills\%~nxs ..\..\%s`)*

#### Publishing & Scraper Dependencies (Optional)
```bash
pip install requests python-dotenv
cp .env.example .env
```

#### Diagnostics
Verify API configuration and check which skills are operational without consuming credits:
```bash
python3 scripts/selftest.py
python3 scripts/selftest.py --fresh
```
*(Note: The reel's claimed 2-minute web-only setup without prerequisites is unverified for data-scraping workflows, which require Python execution or manual pasting).* 

---

### 5. Common Pitfalls

1. **Assuming Full Autonomy:** Treating LLM drafts as publish-ready without reviewing them creates generic output and risks hallucinating metrics.
2. **Relying on Detector "Scores":** AI detectors generate high false-positive rates on formal professional prose. Optimize for specificity and real receipts, not third-party detector percentages.
3. **Using Cookie-Based Scrapers:** Injecting session cookies into unapproved scraping tools exposes accounts to immediate session termination.
4. **Windows Symlink Breakage:** Cloning on Windows without symlink privileges leaves empty stub files in `.claude/skills/`, preventing Claude Code from finding tools.

---

### 6. Reusable Hardening Prompt

Run this prompt inside your agent harness to enforce a strict draft-only policy:

```text
You are operating as an executive LinkedIn ghostwriting assistant using ./linkedin-skills/.

OPERATING RULES:
1. DRAFT-ONLY DISCIPLINE: Never attempt automated publishing, headless posting, or unprompted network requests. Always return a draft container and wait for manual user review.
2. DATA PRIVACY: If Apify or Publora tokens are missing, gracefully prompt for manual text input instead of raising runtime errors.
3. ZERO AI TELLS: Enforce the Humanizer rules - strip synthetic transitions ('delve into', 'in summary'), minimize performative em-dashes, and ground claims in specific metrics from our Story Bank.
4. PROFILE SAFETY: Never emulate bot behavior, mass outreach, or high-frequency comment sweeps.

Review the current Story Bank or interview me on our primary product metric before proposing our next 7-day content plan.
```

## Original sources
- https://www.instagram.com/reel/Dd73i1bz_Nu/