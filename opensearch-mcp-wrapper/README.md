# OpenSearch MCP Server with Cookie Authentication

An MCP (Model Context Protocol) server that enables Claude to query OpenSearch clusters protected by OpenID/OAuth authentication (like Azure AD).

## Why This Exists

The official [opensearch-mcp-server-py](https://github.com/opensearch-project/opensearch-mcp-server-py) supports basic auth, AWS IAM, and header-based auth, but doesn't support cookie/session-based authentication used by OpenSearch Dashboards with OpenID Connect.

This wrapper proxies requests through the OpenSearch Dashboards API with your session cookie attached.

## Setup

### 1. Create Virtual Environment

```bash
cd opensearch-mcp-wrapper
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Get Your Session Cookie

Since your OpenSearch uses OpenID authentication, you need to extract the session cookie from your browser:

**Option A: From Browser DevTools**

1. Open your OpenSearch Dashboard in the browser
2. Log in if not already logged in
3. Open DevTools (F12 or Cmd+Option+I on Mac)
4. Go to **Application** tab → **Cookies** → select your domain
5. Find cookies starting with `security_authentication` (e.g., `security_authentication_oidc`)
6. Copy the name and value

**Option B: From Browser Console**

1. Open your OpenSearch Dashboard
2. Open DevTools Console
3. Run: `document.cookie`
4. Copy the relevant authentication cookies

### 3. Configure Claude Code

Edit `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "opensearch": {
      "command": "/Users/YOUR_USER/path/to/opensearch-mcp-wrapper/venv/bin/python",
      "args": ["/Users/YOUR_USER/path/to/opensearch-mcp-wrapper/server.py"],
      "env": {
        "OPENSEARCH_URL": "https://your-opensearch-dashboard.example.com",
        "OPENSEARCH_COOKIE": "security_authentication_oidc=YOUR_COOKIE_VALUE_HERE",
        "OPENSEARCH_VERIFY_SSL": "true"
      }
    }
  }
}
```

### 4. Restart Claude Code

After configuring, restart Claude Code for the MCP server to be loaded.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENSEARCH_URL` | Yes | Base URL of your OpenSearch Dashboard |
| `OPENSEARCH_COOKIE` | Yes | Session cookie(s) for authentication |
| `OPENSEARCH_VERIFY_SSL` | No | Set to `false` to disable SSL verification (default: `true`) |

## Available Tools

Once configured, Claude will have access to these tools:

| Tool | Description |
|------|-------------|
| `opensearch_search` | Search documents with full Query DSL support |
| `opensearch_get_indices` | List all indices with health and doc counts |
| `opensearch_get_mappings` | Get field mappings for an index |
| `opensearch_aggregate` | Run aggregation queries (counts, terms, histograms) |
| `opensearch_count` | Count documents matching a query |
| `opensearch_cluster_health` | Get cluster health status |
| `opensearch_sql` | Execute SQL queries via the SQL plugin |
| `opensearch_raw_api` | Make raw API calls for advanced operations |

## Example Usage

Once set up, you can ask Claude things like:

- "List all indices in OpenSearch"
- "Search for error logs in the last hour"
- "Show me the top 10 error messages by count"
- "Get the mapping for the logs-* index"
- "How many documents are in the application-logs index?"

## Cookie Expiration

Session cookies typically expire after some time (hours to days depending on your IdP configuration). When your queries start failing with authentication errors, you'll need to:

1. Log in to OpenSearch Dashboard again in your browser
2. Extract the new cookie value
3. Update `~/.claude/mcp.json` with the new cookie
4. Restart Claude Code

## Troubleshooting

### "HTTP Error 401" or "HTTP Error 403"
- Your cookie has expired. Get a new one from the browser.

### "Connection refused" or "SSL error"
- Check that `OPENSEARCH_URL` is correct
- Try setting `OPENSEARCH_VERIFY_SSL=false` if using self-signed certificates

### MCP server not loading
- Check Claude Code logs: `~/.claude/debug/`
- Verify the path to Python and server.py in mcp.json
- Make sure dependencies are installed in the venv

## How It Works

This server proxies requests through the OpenSearch Dashboards console API (`/api/console/proxy`), which:
1. Accepts your session cookie for authentication
2. Forwards requests to the underlying OpenSearch cluster
3. Returns results back to Claude

This approach works because you're going through the same API that the Dashboards Dev Tools console uses.
