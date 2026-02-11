# I Built Claude's OpenSearch Extension... Using Claude

Here's what I wanted: to ask my AI assistant "Get me a report of errors that occurred in the Dev EU cluster in the last hour" — in plain English — and get back logs analysed, summarized, and presented in a readable manner — saving hours of manual grinding.

## The Problem

Usually enterprise OpenSearch clusters sit behind OpenSearch Dashboards with OpenID Connect authentication. You log in through a browser, manually grind through log lines, or copy-paste them into an AI chat like it's 2024. No direct API access. No service account tokens. The official OpenSearch MCP server supports basic auth and AWS IAM — not OIDC. With billions of documents across hundreds of shards, you can't afford sloppy queries.

## The Architecture

The system has five core components:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  In CLI                                                                          │
│  "Get me a report of errors that occurred in the Dev EU cluster in the last hour"│
└────────────────────────────────────┬─────────────────────────────────────────────┘
                                     │ natural language
                                     ▼
┌────────────────────────────────────────────────────────────────────┐
│  CLAUDE + SKILL FILE                                               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Skill: "count first → sample → aggregate → full fetch"      │  │
│  │  Reads _meta flags from previous responses to adapt          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  Translates question → optimized OpenSearch query                  │
└────────────────────────────────────┬───────────────────────────────┘
                                     │ MCP tool calls (stdio)
                                     ▼
┌──────────────────────────────────────────┐ ┌──────────────────────────┐
│  MCP SERVER                              │ │  AUTH HANDLER            │
│                                          │ │                          │
│  - Impersonates browser                  │ │  - Headless Playwright   │
│    (cookies, headers, CSRF)              │ │  - SSO via Azure AD      │
│  - Context optimization                  │ │  - Writes cookies        │
│    (field filter, auto-prune,            │ │                          │
│     truncation, 15KB cap)                │ │  Triggered on 401        │
│  - Attaches _meta flags                  │ │  or cluster switch       │
│                                          │ │                          │
│              on 401 ─────────────────────┼▶│                          │
│              ◀────── fresh cookies ──────┼─│                          │
└────────────────────┬─────────────────────┘ └──────────────────────────┘
                     │ HTTP POST (cookie auth)
                     ▼
┌────────────────────────────────────────────────────────────────────┐
│  OPENSEARCH DASHBOARDS (internal API)                              │
│  /internal/search/opensearch-with-long-numerals                    │
│  → OpenSearch Cluster                                              │
└────────────────────────────────────────────────────────────────────┘
```

### The [Claude Skill](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
A markdown document loaded into Claude's context when OpenSearch queries are relevant
Teaches Claude how to query: which of the 8 MCP tools to use, the 4-step query plan (count → sample → aggregate → fetch), cluster-specific syntax, time zone conversions, common aliases (e.g., "prod" → main production cluster)
Teaches Claude how to read _meta flags and adapt (see below)
**Without it**, Claude executes full unfiltered queries and blows through the context window in two requests. **With it**, Claude behaves like someone who's been querying this cluster for years

### The [MCP Server](https://code.claude.com/docs/en/mcp)
The bridge between Claude and OpenSearch. Impersonates a browser — same internal API endpoint, same cookies, same CSRF headers. To the dashboard, it looks like a normal browser session
**Context optimization** — field filtering, auto-pruning verbose kubernetes metadata, per-hit truncation, 15KB response cap. Raw responses can be huge; this keeps them AI-friendly
**_meta flags** — every response includes a _meta.applied_operations array telling Claude what the server did: summary_only, field_filter:..., auto_prune:..., hits_truncated:3/10, partial_results:100_of_50000, response_truncated_at_15KB. Claude reads these and **adapts its next query** — reduces size, adds filtering, or switches to aggregations. It's a closed feedback loop between server and AI

### The Auth Handler
Runs a headless Playwright browser through the SSO flow to extract session cookies
**Solves**: cookie expiry. The MCP server calls it automatically on 401 — the user never sees the auth failure
Also triggered on cluster switches — different clusters require different cookies, so it ensures the right credentials are always in place
If the SSO session itself has expired, opens a visible browser for one manual login, then it's cached again

### OpenSearch Dashboards
The existing dashboard deployment — unchanged, unmodified. We just talk to its internal API (/internal/search/opensearch-with-long-numerals) the same way the browser does

## What Goes In, What Comes Out

With the architecture in place, here's what it looks like in practice. A user types:

> "Are there any OOM errors in the prod cluster in the last 30 minutes?"

Claude reads the skill file and follows its cost-conscious query plan: **count first** (summary_only=true, ~100 tokens), **sample if large** (size=5 with field filtering), **aggregate if analytical**, **full fetch only when needed**.

Instead of blindly fetching 1000 full documents, Claude first asks "how many hits?" — gets back total_hits: 47 in ~100 tokens. The _meta flags say summary_only — no documents consumed. Then it fetches a sample with only the fields it needs — the _meta comes back with field_filter:..., auto_prune:..., saving 80% context vs full documents. If the user needs a breakdown, Claude switches to aggregations. Each step is informed by the previous response's feedback.

What the user gets:

> **Found 47 OOM-related errors in prod over the last 30 minutes.**
>
> **Top affected pods:**
> | Pod | Count | Last seen |
> |---|---|---|
> | payments-worker-7b4f9 | 18 | 2 min ago |
> | checkout-api-3d8a1 | 12 | 5 min ago |
> | inventory-sync-9c2e4 | 9 | 11 min ago |
> | 8 other pods | 8 | — |
>
> **Pattern:** 63% of OOM kills are in the payments namespace,
> mostly hitting containers with a 512Mi memory limit.
> The spike started ~25 minutes ago.
>
> Want me to pull the full stack traces from payments-worker?

Natural language in, analysed report out. No query syntax. No JSON. No copy-pasting from a dashboard.

## The Journey: Building It with AI

I used Claude Code's /plan mode with the Opus model throughout — describe what I want, review the proposed approach, approve, let it implement, iterate.

**It started with a HAR file.** I opened the OpenSearch dashboard in Chrome, recorded a 93MB network capture, masked sensitive values, and gave it to Claude. "How does this dashboard authenticate?" Within minutes it had mapped out the entire OIDC flow — the Azure AD tenant, the client ID, the internal API endpoint the UI actually calls. That analysis would have taken me an hour of scrolling through network requests.

**Then came the auth puzzle.** Claude built the first version of the MCP server. It didn't work. We discovered two cookies were required, in a specific order, with specific CSRF headers. Claude also caught that Chrome's HAR export silently strips HttpOnly cookies — so the credentials I thought I was providing were incomplete. That was a subtle one.

**First successful query — and a new problem.** The moment it worked, it broke something else. A single OpenSearch response with full kubernetes metadata consumed so much of Claude's context window that it couldn't do anything useful with the data. So I /plan'd the next phase: context optimization. I proposed the layered system — summary mode, field filtering, auto-prune, the _meta feedback flags. Claude designed and implemented it.

**Cookies kept expiring.** Every few hours, the session would die and queries would 401. I didn't want to manually re-login each time. I suggested "What if we had an under-the-hood auth handler?". Then Claude built the auth handler — a Playwright script that re-runs the SSO flow headlessly using cached browser state. The MCP server triggers it automatically on 401. But here Claude caught its own bug: Playwright's sync API can't run inside an asyncio event loop (the MCP server is async). It refactored to async_playwright before I even noticed the issue.

**Multi-cluster came next.** Different environments need different cookies, different URLs. We added a cluster registry and a switch tool — Claude can now hop between dev, staging, and prod clusters mid-conversation without restarting.

**The skill file grew incrementally.** It didn't start as a 300-line document. First version just listed the tools. Then I noticed Claude was fetching full documents when it only needed counts — so I added the 4-step query plan. Then it was ignoring _meta flags — so Claude added a section explaining each flag and how to react. Then it was using the wrong query syntax on different clusters (keyword vs. text field mappings) — so Claude added cluster-specific examples. Each real usage session revealed a gap, and the skill file grew to close it. The skill and the server co-evolved: as the server added new optimizations, the skill taught Claude to use them.

**Finally, init.sh.** I cloned the repo to a different machine and everything broke — .mcp.json had hardcoded paths, venv/ was gitignored and missing. Classic "works on my machine" problem. So we /plan'd a setup script: auto-detect project root, create venv, install dependencies (including Playwright browsers), generate .mcp.json with correct paths. One command, fresh machine to working setup.


## Takeaway

This pattern — browser impersonation via cookie replay, with a skill file and feedback metadata — works for any dashboard-only system. The code is a few hundred lines of Python. The real value was the iterative process and having an AI that could build, debug, and then teach itself how to use the result.

AI isn't perfect. But when you guide it correctly with lean context, it comes to harmony.