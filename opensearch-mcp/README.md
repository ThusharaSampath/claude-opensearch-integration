# OpenSearch MCP Server with Cookie Authentication

An MCP (Model Context Protocol) server that enables Claude to query OpenSearch clusters protected by OpenID Connect / Azure AD authentication via OpenSearch Dashboards.

## Why This Exists

The official [opensearch-mcp-server-py](https://github.com/opensearch-project/opensearch-mcp-server-py) supports basic auth, AWS IAM, and header-based auth, but doesn't support cookie/session-based authentication used by OpenSearch Dashboards with OIDC.

This server makes direct HTTP calls to the Dashboards internal API (`/internal/search/opensearch-with-long-numerals`) with session cookies attached — the same endpoint the Dashboards UI uses.

## Setup

### 1. Create Virtual Environment

```bash
cd opensearch-mcp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Install Playwright (for cookie auto-refresh)

```bash
pip install playwright
playwright install chromium
```

### 3. Get Your Session Cookies

```bash
# List available clusters
./get-cookies.py --list

# Fetch cookies for a cluster (opens browser for SSO login)
./get-cookies.py prod-azure-us-cdp

# Print cookies without saving
./get-cookies.py prod-azure-us-cdp --print

# Headless mode (if SSO session is cached)
./get-cookies.py prod-azure-us-cdp --headless
```

This writes `cookies.json` which the server reads on every request — no restart needed.

### 4. Configure Claude Code

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "opensearch": {
      "type": "stdio",
      "command": "<path-to>/opensearch-mcp/venv/bin/python",
      "args": ["<path-to>/opensearch-mcp/server.py"],
      "env": {
        "OPENSEARCH_URL": "https://your-opensearch-dashboard-url",
        "OPENSEARCH_COOKIE": "<fallback cookie, used only if cookies.json is missing>",
        "OPENSEARCH_VERIFY_SSL": "true"
      }
    }
  }
}
```

> **Note:** MCP config goes in `.mcp.json` (project root) or `~/.claude.json` (user scope), **not** `~/.claude/mcp.json`.

### 5. Restart Claude Code

After configuring, restart Claude Code for the MCP server to load.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENSEARCH_URL` | Yes | Base URL of your OpenSearch Dashboards instance |
| `OPENSEARCH_COOKIE` | No | Fallback cookie string (used only if `cookies.json` is missing) |
| `OPENSEARCH_VERIFY_SSL` | No | Set to `false` to disable SSL verification (default: `true`) |
| `OSD_VERSION` | No | OpenSearch Dashboards version for the `osd-version` header (default: `2.18.0`) |

## Available Tools

| Tool | Description |
|------|-------------|
| `opensearch_search` | Search logs with Lucene/KQL query strings, time range, field filtering, summary mode |
| `opensearch_search_raw` | Search with raw OpenSearch Query DSL body |
| `opensearch_aggregate` | Aggregation queries (counts, terms, histograms) |
| `opensearch_get_indices` | List indices with document counts |
| `opensearch_get_mappings` | Get field names and types from a sample document |
| `opensearch_cluster_health` | Basic cluster health info |

### Key Parameters for `opensearch_search`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `index` | *(required)* | Index pattern (e.g., `container-logs-*`) |
| `query_string` | `""` | Lucene/KQL query |
| `time_from` | `now-15m` | Start time (ISO 8601 or relative) |
| `time_to` | `now` | End time |
| `size` | `100` | Number of docs to return (max 1000) |
| `summary_only` | `false` | Only return hit count and time range |
| `auto_prune` | `true` | Strip `kubernetes.labels` and `kubernetes.annotations` |
| `fields` | `null` | Array of specific fields to return |
| `max_chars_per_hit` | `2000` | Truncate individual hits exceeding this size |

## Context Optimization

The server optimizes responses to minimize Claude's context window usage:

| Feature | Description |
|---------|-------------|
| `summary_only` | Returns only hit count and time range (~100 tokens) |
| `auto_prune` | Strips verbose k8s label/annotation fields (on by default) |
| `fields` | Return only specified fields (saves 70-80% context) |
| `max_chars_per_hit` | Truncates oversized individual hits |
| Response cap | Overall response capped at 15KB |

Every response includes `_meta.applied_operations` indicating what was filtered or truncated.

## Cookie Management

### Priority chain (checked on every request)
1. `cookies.json` file — read at request time, no restart needed
2. `OPENSEARCH_COOKIE` env var — fallback, requires restart to change

### Auto-refresh on 401
1. Server detects 401 response
2. Launches headless Playwright with cached Azure AD SSO session
3. Gets fresh cookies and writes to `cookies.json`
4. Retries the original request transparently

### Manual refresh (when SSO session expires)
```bash
./get-cookies.py <cluster-short-name>
```
Opens a browser for interactive login. After login, cookies are saved — **no Claude Code restart needed**.

### Two cookies are required
Both must be present for authentication:
1. `security_authentication_oidc1` (~2326 bytes) — OIDC token
2. `security_authentication` (~443 bytes) — Session token

Order matters: `security_authentication_oidc1` must come first.

## Example Usage

Once set up, you can ask Claude things like:

- "Search for errors in the `my-namespace` namespace in the last hour"
- "How many logs were generated by pod `api-server-xyz` today?"
- "Show me logs containing request ID `77e71a17-2e52-404a-86d2-eed997fd2a57`"
- "What are the top 10 namespaces by log volume in the last 24 hours?"
- "List all indices in OpenSearch"
- "Check cluster health"

## Troubleshooting

### "HTTP Error 401" or "Unauthorized"
- Cookies have expired. The server auto-refreshes via Playwright if the SSO session is still valid.
- If auto-refresh fails, run `./get-cookies.py <cluster>` to log in again.
- No Claude Code restart needed after refreshing cookies.

### "502 Bad Gateway" or timeout
- You're likely querying without a time range filter. The cluster has 6.6B+ documents — always include `time_from`/`time_to`.

### "Connection refused" or "SSL error"
- Check that `OPENSEARCH_URL` is correct.
- Try setting `OPENSEARCH_VERIFY_SSL=false` if using self-signed certificates.

### MCP server not loading
- Verify `.mcp.json` is in the project root (not `~/.claude/mcp.json`).
- Check that the Python path and `server.py` path are correct.
- Make sure dependencies are installed in the venv.

## How It Works

The server uses the OpenSearch Dashboards internal search endpoint (`/internal/search/opensearch-with-long-numerals`), which:
1. Accepts session cookies for OIDC authentication
2. Requires `osd-xsrf` and `osd-version` headers (matching browser behavior)
3. Forwards queries to the underlying OpenSearch cluster
4. Returns results back through the MCP protocol to Claude

This is the same API that the Dashboards Discover UI uses internally.
