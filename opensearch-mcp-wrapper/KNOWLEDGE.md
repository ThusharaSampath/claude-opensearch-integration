# OpenSearch MCP Wrapper - Knowledge Base & Learnings

## Problem Statement

We need to query OpenSearch logs from Claude Code, but:
- The OpenSearch cluster is behind **OpenSearch Dashboards** with **OpenID Connect (Azure AD)** authentication
- There is no direct CLI access to the OpenSearch cluster
- We cannot modify the OpenSearch deployment or its settings
- The official [opensearch-mcp-server-py](https://github.com/opensearch-project/opensearch-mcp-server-py) supports basic auth, AWS IAM, and header-based auth, but **not cookie/session-based OIDC auth**

## Solution Architecture

A custom MCP server wrapper (`server.py`) that:
1. Authenticates using browser session cookies extracted from the OpenSearch Dashboard
2. Uses the **same internal API endpoint** that the Dashboards UI uses
3. Exposes tools for Claude Code to search, aggregate, and inspect OpenSearch data

## What Was Done

### 1. HAR File Analysis
- Analyzed a 93MB HAR file from visiting the OpenSearch Dashboard
- Discovered the dashboard uses **OpenID Connect via Azure AD** (`login.microsoftonline.com`)
- Client ID: `00000000-0000-0000-0000-000000000000`
- Tenant: `00000000-0000-0000-0000-000000000001`
- Found that HAR files from Chrome **do not include cookies** (filtered for security)
- Identified the actual API endpoint: `/internal/search/opensearch-with-long-numerals`
- Identified OSD version: `2.18.0`

### 2. MCP Server Development
- Created a Python MCP server at `opensearch-mcp-wrapper/server.py`
- Set up a virtual environment with `mcp` and `httpx` dependencies
- Configured Claude Code MCP integration at `~/.claude/mcp.json`

### 3. Iterative Fixes

#### Attempt 1: `/api/console/proxy` endpoint
- **Failed** with 404 Not Found
- The console proxy API is not available or has a different path on this deployment

#### Attempt 2: Direct OpenSearch API paths
- **Failed** - The dashboard doesn't expose direct OpenSearch REST APIs

#### Attempt 3: `/internal/search/opensearch-with-long-numerals` endpoint
- **Success** - This is the same endpoint the browser UI uses for all searches
- Requires wrapping queries in `{"params": {"index": "...", "body": {...}}}`
- Response wraps the actual OpenSearch response in `{"rawResponse": {...}}`

## Critical Learnings

### Authentication

**Two cookies are required** (both must be present):
1. `security_authentication` (size ~443 bytes) - Session token
2. `security_authentication_oidc1` (size ~2326 bytes) - OIDC token

**Cookie order matters**: `security_authentication_oidc1` should come **first**, then `security_authentication` (based on browser behavior).

**Cookies expire**: These are session cookies. When queries start failing with 401/302, you need to:
1. Log into OpenSearch Dashboard in the browser
2. Extract fresh cookies from DevTools → Application → Cookies
3. Update `~/.claude/mcp.json`
4. Restart Claude Code

**How to extract cookies from browser**:
- DevTools (F12) → Application tab → Cookies → select the domain
- Or use DevTools Console: `document.cookie`
- Or right-click a request in Network tab → Copy as cURL → extract from `-b` flag

### Required Headers

The following headers are required (matching exactly what the browser sends):

```
osd-xsrf: osd-fetch          # CSRF protection
osd-version: 2.18.0          # Must match the deployed OSD version
Content-Type: application/json
Origin: https://opensearch-dashboard.e1-us-east-azure.example.com
Referer: https://opensearch-dashboard.e1-us-east-azure.example.com/app/data-explorer/discover
```

### Query Format

**The browser uses `query_string` with `analyze_wildcard: true`**, not `wildcard` or `match_phrase` queries.

Example - searching for a UUID in logs:
```json
{
  "query_string": {
    "query": "log:\"*77e71a17-2e52-404a-86d2-eed997fd2a57*\"",
    "analyze_wildcard": true,
    "time_zone": "Asia/Colombo"
  }
}
```

### Time Range Filters are CRITICAL

**Without a time range filter, queries WILL timeout (502 Bad Gateway)** because the cluster has **6.6+ billion documents** across 300+ shards.

The browser always includes a time range filter:
```json
{
  "filter": [
    {
      "range": {
        "@timestamp": {
          "gte": "2026-02-05T04:05:19.148Z",
          "lte": "2026-02-05T04:20:19.148Z",
          "format": "strict_date_optional_time"
        }
      }
    }
  ]
}
```

The default in the UI is 15 minutes. For searching specific IDs or rare strings, you may need to widen the range (e.g., 24 hours), but avoid querying without any time bounds.

### Full Request Body Format (matching browser)

```json
{
  "params": {
    "index": "container-logs-*",
    "body": {
      "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "boolean"}}],
      "size": 1000,
      "version": true,
      "stored_fields": ["*"],
      "script_fields": {},
      "docvalue_fields": [{"field": "@timestamp", "format": "date_time"}],
      "_source": {"excludes": []},
      "query": {
        "bool": {
          "must": [
            {
              "query_string": {
                "query": "log:\"*search-term*\"",
                "analyze_wildcard": true,
                "time_zone": "Asia/Colombo"
              }
            }
          ],
          "filter": [
            {
              "range": {
                "@timestamp": {
                  "gte": "2026-02-05T04:05:19.148Z",
                  "lte": "2026-02-05T04:20:19.148Z",
                  "format": "strict_date_optional_time"
                }
              }
            }
          ],
          "should": [],
          "must_not": []
        }
      },
      "highlight": {
        "pre_tags": ["@opensearch-dashboards-highlighted-field@"],
        "post_tags": ["@/opensearch-dashboards-highlighted-field@"],
        "fields": {"*": {}},
        "fragment_size": 2147483647
      }
    },
    "preference": 1770264795173
  }
}
```

### curl: Use `-b` not `-H 'Cookie:'`

When using curl, pass cookies with the `-b` flag, not as a `-H 'Cookie: ...'` header. The `-H` approach can cause issues with special characters in the cookie values (especially `**` in the Fe26.2 iron-sealed tokens).

```bash
# Correct
curl -b 'security_authentication_oidc1=Fe26...; security_authentication=Fe26...' ...

# Can cause issues
curl -H 'Cookie: security_authentication_oidc1=Fe26...' ...
```

## Failures & Issues Encountered

| # | Issue | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | `/api/console/proxy` returns 404 | This endpoint doesn't exist on this OSD deployment | Use `/internal/search/opensearch-with-long-numerals` instead |
| 2 | Wildcard query returns 502 Bad Gateway | Wildcard queries without time range scan all 6.6B docs and timeout | Always include `@timestamp` range filter |
| 3 | Cookie header with `-H` flag causes curl errors | `**` characters in Fe26.2 iron tokens get interpreted by shell | Use `-b` flag or single-quote the Cookie header value |
| 4 | HAR file didn't contain cookies | Chrome strips HttpOnly/Secure cookies from HAR exports | Extract cookies manually from DevTools → Application → Cookies |
| 5 | MCP server not loading as tools in Claude Code | Server file changes require Claude Code restart | Restart Claude Code after each server.py change |
| 6 | Old cookies stop working | Session cookies expire periodically | Re-extract from browser and update mcp.json |
| 7 | `match_phrase` query didn't match UUID | The UUID is embedded inside a JSON string in the `log` field; tokenization may split differently | Use `query_string` with `analyze_wildcard: true` matching the browser's approach |

## Cluster Details

- **URL**: `https://opensearch-dashboard.e1-us-east-azure.example.com`
- **OSD Version**: 2.18.0
- **Total Documents**: ~6.67 billion
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
opensearch-mcp-wrapper/
├── server.py           # MCP server with cookie auth
├── requirements.txt    # Python dependencies (mcp, httpx)
├── pyproject.toml      # Project metadata
├── get_cookie.py       # Helper to extract cookies (limited use)
├── README.md           # Setup & usage documentation
├── KNOWLEDGE.md        # This file
└── venv/               # Python virtual environment
```

## Configuration

### ~/.claude/mcp.json
```json
{
  "mcpServers": {
    "opensearch": {
      "command": "/path/to/opensearch-agent/opensearch-mcp-wrapper/venv/bin/python",
      "args": ["/path/to/opensearch-agent/opensearch-mcp-wrapper/server.py"],
      "env": {
        "OPENSEARCH_URL": "https://opensearch-dashboard.e1-us-east-azure.example.com",
        "OPENSEARCH_COOKIE": "<security_authentication_oidc1=...>; <security_authentication=...>",
        "OPENSEARCH_VERIFY_SSL": "true"
      }
    }
  }
}
```

## MCP Server Tools

| Tool | Description |
|------|-------------|
| `opensearch_search` | Search using Dashboards-style query strings with time range |
| `opensearch_search_raw` | Search with raw Query DSL body |
| `opensearch_get_indices` | List indices with doc counts |
| `opensearch_get_mappings` | Get field names/types from a sample document |
| `opensearch_aggregate` | Run aggregation queries |
| `opensearch_cluster_health` | Basic cluster health info |

## Example Queries

### Search for a specific request ID
```
index: container-logs-*
query_string: log:"*77e71a17-2e52-404a-86d2-eed997fd2a57*"
time_from: 2026-02-04T00:00:00.000Z
time_to: 2026-02-05T12:00:00.000Z
```

### Search for errors in a namespace
```
index: container-logs-*
query_string: kubernetes.namespace_name:"prod-choreo-apim" AND log:"*error*"
time_from: (now - 15m)
time_to: now
```

### Search by pod name pattern
```
index: container-logs-*
query_string: kubernetes.pod_name:"choreo-nginx-service-*"
time_from: (now - 1h)
time_to: now
```

## TODO / Next Steps

- [ ] MCP tools not loading in Claude Code - need to debug why the MCP server isn't registering tools after restart
- [ ] Consider adding a cookie refresh mechanism (e.g., a script that opens browser and extracts fresh cookies)
- [ ] Add support for multiple OpenSearch clusters
- [ ] Consider adding PPL (Piped Processing Language) query support
