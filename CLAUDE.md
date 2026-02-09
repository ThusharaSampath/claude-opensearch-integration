# OpenSearch MCP - Knowledge Base & Learnings

## Problem Statement

We need to query OpenSearch logs from Claude Code, but:
- The OpenSearch cluster is behind **OpenSearch Dashboards** with **OpenID Connect (Azure AD)** authentication
- There is no direct CLI access to the OpenSearch cluster
- We cannot modify the OpenSearch deployment or its settings
- The official [opensearch-mcp-server-py](https://github.com/opensearch-project/opensearch-mcp-server-py) supports basic auth, AWS IAM, and header-based auth, but **not cookie/session-based OIDC auth**

## Solution Architecture

A custom MCP server (`server.py`) that:
1. Authenticates using browser session cookies (auto-refreshed or manually extracted)
2. Uses the **same internal API endpoint** that the Dashboards UI uses
3. Exposes tools for Claude Code to search, aggregate, and inspect OpenSearch data
4. Optimizes responses for minimal context consumption (auto-prune, field filtering, summary mode, truncation)
5. Auto-refreshes cookies on 401 via headless Playwright SSO

### How It Works (Not a Proxy)

The MCP server makes **direct HTTP calls** to OpenSearch Dashboards. There is no standalone OpenSearch MCP server involved. The flow is:

```
Claude Code → MCP protocol (stdio) → server.py → HTTP POST → OpenSearch Dashboards → OpenSearch cluster
```

## What Was Done

### Phase 1: HAR File Analysis & Discovery
- Analyzed a 93MB HAR file from visiting the OpenSearch Dashboard
- Discovered the dashboard uses **OpenID Connect via Azure AD** (`login.microsoftonline.com`)
- Client ID: `00000000-0000-0000-0000-000000000000`
- Tenant: `00000000-0000-0000-0000-000000000001`
- Found that HAR files from Chrome **do not include cookies** (filtered for security)
- Identified the actual API endpoint: `/internal/search/opensearch-with-long-numerals`
- Identified OSD version: `2.18.0`

### Phase 2: MCP Server Development
- Created a Python MCP server at `opensearch-mcp/server.py`
- Set up a virtual environment with `mcp`, `httpx`, and `playwright` dependencies
- Iteratively tested endpoints until finding the correct internal search endpoint

### Phase 3: MCP Configuration Fix
- **Problem**: MCP config was at `~/.claude/mcp.json` which is NOT a recognized location
- **Fix**: Moved to `.mcp.json` in project root (project-scope MCP config)
- Claude Code looks for MCP config in:
  - `~/.claude.json` (user scope — all projects)
  - `.mcp.json` in project root (project scope — team-shared)

### Phase 4: Context Optimization
Large OpenSearch responses were consuming Claude's context window rapidly. Implemented:

1. **`summary_only` mode** — Returns only hit count and time range, no documents (~100 tokens)
2. **`auto_prune` mode** (enabled by default) — Strips `kubernetes.labels` and `kubernetes.annotations` automatically
3. **`fields` parameter** — Return only specified fields (e.g., `["log", "@timestamp", "kubernetes.pod_name"]`)
4. **`max_chars_per_hit`** — Truncates individual hits exceeding this size (default: 2000 chars)
5. **Response truncation** — Overall response capped at 15KB
6. **`_meta` flags** — Every response includes metadata about what operations the server applied

### Phase 5: Response Metadata Flags
Every response includes `_meta.applied_operations` so Claude knows what happened:

| Flag | Meaning |
|------|---------|
| `summary_only` | Only counts returned |
| `field_filter:field1,field2` | Only these fields returned |
| `auto_prune:kubernetes.labels,kubernetes.annotations` | Verbose k8s fields removed |
| `hits_truncated:N/M` | N of M hits exceeded max_chars_per_hit |
| `partial_results:100_of_50000` | Only 100 of 50K total returned |
| `response_truncated_at_15KB` | Entire response exceeded 15KB |

When response is truncated at 15KB, a `_meta` header is injected at the top so Claude always sees the warning.

### Phase 6: Cookie Auto-Refresh
Eliminated the need to manually copy cookies and restart Claude Code:

**Cookie priority chain** (checked on every request):
1. `cookies.json` file (written by `get-cookies.py` or auto-refresh) — read at request time, no restart needed
2. `OPENSEARCH_COOKIE` env var from `.mcp.json` (fallback, requires restart)

**On 401 error:**
1. Server detects 401
2. Launches headless Playwright with cached Azure AD SSO session
3. Gets fresh cookies → writes to `cookies.json`
4. Retries the original request automatically
5. Claude never sees the error

**If auto-refresh fails** (SSO session also expired):
- Returns structured error with manual instructions
- User runs `./get-cookies.py <cluster>` (opens browser for login)
- Script writes `cookies.json` — **no Claude Code restart needed**

### Phase 7: Multi-Cluster Support
Added 29 cluster entries covering Development, Staging, and Production environments. The `get-cookies.py` script accepts cluster short names (e.g., `prod-azure-us-cdp`, `dev-onprem-cp`).

### Phase 8: Claude Skill
Created `.claude/skills/opensearch/SKILL.md` teaching Claude:
- All available tools and when to use each
- Cost-conscious query plan (count → sample → aggregate → full fetch)

### Phase 9: Dynamic Cluster Switching
- Added `opensearch_switch_cluster` and `opensearch_get_active_cluster` MCP tools
- Extracted cluster registry to shared `clusters.py` module (imported by both `server.py` and `get-cookies.py`)
- Made `OPENSEARCH_URL` dynamic — read from `cookies.json` on every request, not just at startup
- Added `cluster` field to `cookies.json` to track which cluster is active
- `opensearch_switch_cluster` fetches cookies via headless Playwright, saves to `cookies.json`, updates `.mcp.json`
- Fixed critical bug: Playwright sync API cannot run inside asyncio event loop — switched to `async_playwright`
- Fixed scoping bug: `e` (exception var) not accessible outside `except` block in Python 3

### Phase 10: Initialization Script
Created `init.sh` automation script to solve the "fresh clone" setup problem:
- **Problem**: When cloning to a new location, hardcoded paths in `.mcp.json` break, and `venv/` doesn't exist (gitignored)
- **Solution**: Auto-setup script that:
  1. Detects project root using `pwd` and script location
  2. Creates virtual environment if missing
  3. Installs all dependencies (mcp, httpx, playwright + chromium)
  4. Generates `.mcp.json` with correct absolute paths
  5. Verifies setup and provides next steps
- **Usage**: Simply run `./init.sh` after cloning — no manual path editing needed
- How to read and react to `_meta` flags
- Cluster map and common aliases
- IST↔UTC time conversion
- Cookie management and 401 handling

## Critical Learnings

### Authentication

**Two cookies are required** (both must be present):
1. `security_authentication` (size ~443 bytes) - Session token
2. `security_authentication_oidc1` (size ~2326 bytes) - OIDC token

**Cookie order matters**: `security_authentication_oidc1` should come **first**, then `security_authentication` (based on browser behavior).

### Required Headers

The following headers are required (matching exactly what the browser sends):

```
osd-xsrf: osd-fetch          # CSRF protection
osd-version: 2.18.0          # Must match the deployed OSD version
Content-Type: application/json
Origin: <OPENSEARCH_URL>
Referer: <OPENSEARCH_URL>/app/data-explorer/discover
```

### Query Format

**The `log` field in `container-logs-*` is mapped as `keyword` (not analyzed text).** This has major implications for how you search log content:

| Query Type | Works on `log` field? | Why |
|---|---|---|
| `query_string` with `log:*error*` | **No** — returns 0 hits | Keyword fields are not tokenized; there are no "error" tokens to match |
| `match_phrase` / `term` | **No** — returns 0 hits | Same reason — looks for analyzed tokens that don't exist |
| `wildcard` query (Query DSL) | **Yes** | Scans the raw stored string character by character |

**Always use `wildcard` queries via `opensearch_search_raw` when searching inside the `log` field:**
```json
{
  "wildcard": {"log": "*level*error*"}
}
```

**Exception**: `query_string` works fine for **non-keyword fields** like `kubernetes.namespace_name`, `kubernetes.pod_name`, `stream`, etc.

**Exception**: `query_string` with `analyze_wildcard: true` may work on some clusters where `log` is mapped as `text`. Always verify with a test query first.

Example - searching for a UUID in logs (use wildcard):
```json
{
  "wildcard": {"log": "*77e71a17-2e52-404a-86d2-eed997fd2a57*"}
}
```

Example - combining wildcard log search with time range:
```json
{
  "bool": {
    "must": [
      {"range": {"@timestamp": {"gte": "now-5m", "lte": "now"}}},
      {"wildcard": {"log": "*level*error*"}}
    ]
  }
}
```

### Time Range Filters are CRITICAL

**Without a time range filter, queries WILL timeout (502 Bad Gateway)** because the cluster has **6.6+ billion documents** across 300+ shards.

The default in the UI is 15 minutes. For searching specific IDs or rare strings, you may need to widen the range (e.g., 24 hours), but avoid querying without any time bounds.

### curl: Use `-b` not `-H 'Cookie:'`

When using curl, pass cookies with the `-b` flag, not as a `-H 'Cookie: ...'` header. The `-H` approach can cause issues with special characters in the cookie values (especially `**` in the Fe26.2 iron-sealed tokens).

## Failures & Issues Encountered

| # | Issue | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | `/api/console/proxy` returns 404 | This endpoint doesn't exist on this OSD deployment | Use `/internal/search/opensearch-with-long-numerals` instead |
| 2 | Wildcard query returns 502 Bad Gateway | Wildcard queries without time range scan all 6.6B docs and timeout | Always include `@timestamp` range filter |
| 3 | Cookie header with `-H` flag causes curl errors | `**` characters in Fe26.2 iron tokens get interpreted by shell | Use `-b` flag or single-quote the Cookie header value |
| 4 | HAR file didn't contain cookies | Chrome strips HttpOnly/Secure cookies from HAR exports | Extract cookies manually from DevTools → Application → Cookies |
| 5 | MCP server not loading in Claude Code | Config was at `~/.claude/mcp.json` (wrong location) | Move to `.mcp.json` in project root (project-scope config) |
| 6 | Old cookies stop working | Session cookies expire periodically | Auto-refresh via Playwright on 401, or run `get-cookies.py` |
| 7 | `match_phrase` query didn't match UUID | The UUID is embedded inside a JSON string in the `log` field | Use `query_string` with `analyze_wildcard: true` |
| 8 | Large responses filling Claude's context | Full docs with k8s metadata are huge | Added auto_prune, fields, summary_only, max_chars_per_hit, 15KB cap |
| 9 | Cookie refresh requires Claude Code restart | Env vars read at process start | Server now reads `cookies.json` at request time, no restart needed |
| 10 | Auto cookie refresh silently fails | Playwright sync API cannot run inside asyncio event loop (MCP server is async) | Switched to `async_playwright` (async API) in `_refresh_cookies_for_url` |
| 11 | `e` variable not accessible after except block | Python 3 deletes exception variable after `except` block exits | Saved `e.request` to `failed_request` before leaving the except block |
| 12 | `query_string` with `log:*error*` returns 0 hits | `log` field is mapped as `keyword` (not analyzed text) — no tokens exist to match | Use `wildcard` query via `opensearch_search_raw` instead (e.g., `{"wildcard": {"log": "*level*error*"}}`) |
| 13 | "Invalid cookie header" after fresh clone | `.mcp.json` had hardcoded paths to old location, `venv/` gitignored | Created `init.sh` script to auto-generate `.mcp.json` with correct paths and setup venv |
| 14 | MCP server fails with "no such file or directory" for venv/bin/python | Virtual environment wasn't created in fresh clone (gitignored) | Run `./init.sh` to create venv and install dependencies automatically |

## Cluster Registry

Cluster URLs are configured in `opensearch-mcp/clusters.py`. Edit this file to add your OpenSearch cluster URLs.

### Format

The `CLUSTERS` dictionary maps short names to `(url, description)` tuples:

```python
CLUSTERS = {
    "dev-aws-eu-cluster":    ("https://opensearch-dashboard.dev.example.com", "Dev AWS EU Cluster"),
    "stg-azure-us-cluster":  ("https://opensearch-dashboard.staging-us.example.com", "Staging Azure US Cluster"),
    "prod-aws-eu-cluster":   ("https://opensearch-dashboard.prod.example.com", "Prod AWS EU Cluster"),
    "prod-special-cluster":  (None, "Prod Special Cluster — No OpenSearch (alternative logging solution)"),
}
```

Use `None` as the URL for clusters without OpenSearch.

## Cluster Details

- **OSD Version**: 2.18.0
- **Total Documents**: ~6.67 billion (production)
- **Total Shards**: ~305
- **Auth**: OpenID Connect via Azure AD
- **Main Index Pattern**: `container-logs-*`
- **Key Fields in container-logs**:
  - `@timestamp` - Log timestamp
  - `log` - The log message (often contains JSON)
  - `stream` - stdout/stderr
  - `kubernetes.namespace_name` - K8s namespace
  - `kubernetes.pod_name` - Pod name
  - `kubernetes.container_name` - Container name
  - `kubernetes.labels.*` - Pod labels (component_id, env_name, organization_id, etc.)
  - `kubernetes.host` - Node name
  - `kubernetes.pod_ip` - Pod IP

## File Structure

```
opensearch-agent/
├── init.sh                             # Setup automation script (run this first!)
├── .mcp.json                           # MCP server config (auto-generated by init.sh, gitignored)
├── .gitignore                          # Ignores venv/, .mcp.json, cookies.json, etc.
├── README.md                           # User-facing documentation
├── CLAUDE.md                           # This file (project knowledge base & learnings)
├── .claude/
│   └── skills/
│       └── opensearch/
│           └── SKILL.md                # Claude skill for efficient OpenSearch querying
└── opensearch-mcp/
    ├── server.py                       # MCP server with cookie auth, auto-refresh, cluster switching, context optimization
    ├── clusters.py                     # Shared cluster registry (imported by server.py and get-cookies.py)
    ├── get-cookies.py                  # Playwright-based cookie fetcher (SSO, multi-cluster)
    ├── cookies.json                    # Auto-managed cookie store (includes cluster name, read at request time, gitignored)
    ├── server.log                      # Debug log file (written by server.py for diagnosing refresh issues, gitignored)
    ├── .browser-data/                  # Playwright persistent browser profile (caches SSO session, gitignored)
    ├── requirements.txt                # Python dependencies (mcp, httpx, playwright)
    ├── pyproject.toml                  # Project metadata
    └── venv/                           # Python virtual environment (created by init.sh, gitignored)
```

## Configuration

### .mcp.json (project root)
```json
{
  "mcpServers": {
    "opensearch": {
      "type": "stdio",
      "command": ".../opensearch-mcp/venv/bin/python",
      "args": [".../opensearch-mcp/server.py"],
      "env": {
        "OPENSEARCH_URL": "https://opensearch-dashboard.example.com",
        "OPENSEARCH_COOKIE": "<fallback cookie, used if cookies.json missing>",
        "OPENSEARCH_VERIFY_SSL": "true"
      }
    }
  }
}
```

### cookies.json (auto-managed)
```json
{
  "cookie": "security_authentication_oidc1=...; security_authentication=...",
  "url": "https://opensearch-dashboard.example.com",
  "cluster": "prod-cluster-name",
  "updated_at": "2026-02-07T14:00:00+00:00"
}
```

## MCP Server Tools

| Tool | Description |
|------|-------------|
| `opensearch_search` | Search using Dashboards-style query strings with time range, field filtering, summary mode |
| `opensearch_search_raw` | Search with raw Query DSL body |
| `opensearch_get_indices` | List indices with doc counts |
| `opensearch_get_mappings` | Get field names/types from a sample document |
| `opensearch_aggregate` | Run aggregation queries (counts, terms, histograms) |
| `opensearch_cluster_health` | Basic cluster health info |
| `opensearch_switch_cluster` | Switch to a different cluster on-the-fly via headless SSO (no restart needed) |
| `opensearch_get_active_cluster` | Get the currently active cluster name, URL, and cookie age |

### opensearch_search Parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `index` | (required) | Index pattern (e.g., `container-logs-*`) |
| `query_string` | `""` | Lucene/KQL query |
| `time_from` | now-15m | Start time (ISO 8601 or relative) |
| `time_to` | now | End time |
| `size` | 100 | Number of docs (max 1000) |
| `summary_only` | false | Only return hit count |
| `auto_prune` | true | Strip kubernetes.labels and annotations |
| `fields` | null | Array of specific fields to return |
| `max_chars_per_hit` | 2000 | Truncate individual hits |

## Cookie Management

### get-cookies.py Usage
```bash
./get-cookies.py prod-aws-eu-cluster       # Fetch cookies for a cluster
./get-cookies.py prod-aws-eu-cluster --print  # Print cookies only
./get-cookies.py --list                    # List all clusters
./get-cookies.py --url https://opensearch-dashboard.example.com  # Custom URL
./get-cookies.py prod-aws-eu-cluster --headless  # Headless (if SSO cached)
```

### Cookie Refresh Flow
1. **Automatic**: On 401, server launches async headless Playwright → SSO → cookies.json → retry
2. **Cluster switch**: `opensearch_switch_cluster` tool → headless Playwright for target cluster → cookies.json + .mcp.json updated → no restart needed
3. **Manual fallback**: If SSO session expired, user runs `./get-cookies.py <cluster>` → browser opens → login → cookies.json written → no restart needed
4. **Legacy**: Cookie in `.mcp.json` env var (requires restart, used as fallback)

### Debugging Cookie Refresh
Server writes debug logs to `opensearch-mcp/server.log` with timestamps. Check this file to diagnose refresh failures — it shows page URLs, cookie polling progress, and error details.

### Phase 9: Dynamic Cluster Switching
- Added `opensearch_switch_cluster` and `opensearch_get_active_cluster` MCP tools
- Extracted cluster registry to shared `clusters.py` module (imported by both `server.py` and `get-cookies.py`)
- Made `OPENSEARCH_URL` dynamic — read from `cookies.json` on every request, not just at startup
- Added `cluster` field to `cookies.json` to track which cluster is active
- `opensearch_switch_cluster` fetches cookies via headless Playwright, saves to `cookies.json`, updates `.mcp.json`
- Fixed critical bug: Playwright sync API cannot run inside asyncio event loop — switched to `async_playwright`
- Fixed scoping bug: `e` (exception var) not accessible outside `except` block in Python 3

## TODO / Next Steps

- [ ] Add support for PPL (Piped Processing Language) query support
- [x] ~~Add a tool to switch between clusters without running external script~~ → `opensearch_switch_cluster`
- [ ] Consider adding log tail / live streaming capability
- [ ] Explore using service account tokens instead of browser cookies for non-interactive auth
