---
name: opensearch
description: Guide for efficiently querying OpenSearch logs via MCP tools with minimal context consumption
---

# OpenSearch MCP Usage Guide

You have access to an OpenSearch MCP server that queries container logs via OpenSearch Dashboards.
The cluster has billions of documents. **Always include time ranges to avoid timeouts.**

## Available Tools

| Tool | Purpose |
|------|---------|
| `opensearch_search` | Search logs with Lucene/KQL query syntax (primary tool) |
| `opensearch_search_raw` | Raw Query DSL for advanced queries |
| `opensearch_aggregate` | Aggregations (counts, terms, histograms) |
| `opensearch_get_indices` | List indices with doc counts |
| `opensearch_get_mappings` | Get field names/types from a sample doc |
| `opensearch_cluster_health` | Basic cluster health |
| `opensearch_switch_cluster` | Switch to a different cluster on-the-fly (no restart needed) |
| `opensearch_get_active_cluster` | Show currently active cluster name, URL, and cookie age |

## Context Optimization Strategy (CRITICAL)

The MCP server applies operations to reduce response size. **Always optimize for minimal context usage.**

### Step 1: Start with summary_only to get counts
```
opensearch_search(index="container-logs-*", query_string="...", summary_only=true)
```
This returns only total_hits and time_range — costs ~100 tokens.

### Step 2: If you need actual logs, use field filtering
```
opensearch_search(
  index="container-logs-*",
  query_string="...",
  fields=["@timestamp", "log", "kubernetes.namespace_name", "kubernetes.pod_name"],
  size=10
)
```
Only returns specified fields — saves 70-80% context vs full documents.

### Step 3: For high-volume analysis, use aggregations instead of fetching docs
```
opensearch_aggregate(
  index="container-logs-*",
  aggs={"by_namespace": {"terms": {"field": "kubernetes.namespace_name.keyword", "size": 20}}},
  query={"bool": {"must": [...], "filter": [{"range": {"@timestamp": {"gte": "now-1h"}}}]}}
)
```

## Key Parameters for opensearch_search

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `summary_only` | false | Set true to get only hit count, no documents |
| `auto_prune` | true | Strips kubernetes.labels and kubernetes.annotations automatically |
| `fields` | null | Array of specific fields to return (e.g., `["log", "@timestamp"]`) |
| `max_chars_per_hit` | 2000 | Truncates individual hits exceeding this size |
| `size` | 100 | Number of docs to return (max 1000) |
| `time_from` | now-15m | Start time (ISO 8601 or relative like `now-1h`) |
| `time_to` | now | End time |

## Reading _meta Flags

Every response includes a `_meta.applied_operations` array showing what the server did:

| Flag | Meaning |
|------|---------|
| `summary_only` | Only counts returned, no documents |
| `field_filter:field1,field2` | Only these fields were returned |
| `auto_prune:kubernetes.labels,kubernetes.annotations` | Verbose k8s fields were removed |
| `hits_truncated:N/M` | N out of M hits exceeded max_chars_per_hit and were truncated |
| `partial_results:100_of_50000` | Only 100 of 50000 total hits returned |
| `response_truncated_at_15KB` | Entire response exceeded 15KB and was cut off |

### When you see `response_truncated_at_15KB`:
1. Reduce `size` (e.g., size=5)
2. Use `fields` to select only needed fields
3. Use `summary_only=true` if you only need counts
4. Use `opensearch_aggregate` for analysis instead

### When you see `partial_results`:
The query matched more documents than returned. If the user needs broader analysis, use aggregations.

### When you see `hits_truncated`:
Individual log entries were too large. Use `fields` to pick only the fields you need, or increase `max_chars_per_hit`.

## CRITICAL: Searching the `log` Field (Cluster-Specific Strategy)

The `log` field search strategy **depends on the cluster type**:

### OnPrem Clusters (dev-onprem-*, stg-onprem-*, prod-onprem-*)

For **onprem clusters**, use `query_string` with `analyze_wildcard: true` and **quoted wildcard patterns**:

#### Search errors in logs (OnPrem)
```json
opensearch_search_raw(
  index="container-logs-*",
  body={
    "query": {"bool": {"must": [
      {"query_string": {
        "query": "log:\"*level*error*\"",
        "analyze_wildcard": true,
        "time_zone": "Asia/Colombo"
      }}
    ], "filter": [
      {"range": {"@timestamp": {"gte": "now-5m", "lte": "now"}}}
    ]}},
    "size": 20,
    "_source": ["@timestamp", "log", "kubernetes.namespace_name", "kubernetes.pod_name"]
  }
)
```

#### Search by trace/request ID (OnPrem)
```json
opensearch_search_raw(
  index="container-logs-*",
  body={
    "query": {"bool": {"must": [
      {"query_string": {
        "query": "log:\"*1d4867ac-65cb-4de8-8d46-aaef62f6b5fb*\"",
        "analyze_wildcard": true,
        "time_zone": "Asia/Colombo"
      }}
    ], "filter": [
      {"range": {"@timestamp": {"gte": "now-1h", "lte": "now"}}}
    ]}},
    "size": 100,
    "sort": [{"@timestamp": "asc"}],
    "_source": ["@timestamp", "log", "kubernetes.namespace_name", "kubernetes.pod_name", "kubernetes.container_name"]
  }
)
```

**Key points for OnPrem:**
- Use `query_string` with `analyze_wildcard: true`
- Wrap the pattern in **double quotes**: `"*pattern*"` not `*pattern*`
- Include `time_zone: "Asia/Colombo"` for consistency with dashboard
- This approach matches what OpenSearch Dashboards UI does

### Cloud Clusters (AWS/Azure: dev-aws-*, prod-azure-*, stg-azure-*)

For **cloud clusters** (AWS/Azure), the `log` field is mapped as **keyword** (not analyzed text). Use `wildcard` queries:

#### Search errors in logs (Cloud)
```json
opensearch_search_raw(
  index="container-logs-*",
  body={
    "query": {"bool": {"must": [
      {"range": {"@timestamp": {"gte": "now-5m", "lte": "now"}}},
      {"wildcard": {"log": "*level*error*"}}
    ]}},
    "size": 20,
    "_source": ["@timestamp", "log", "kubernetes.namespace_name", "kubernetes.pod_name"]
  }
)
```

#### Search by trace/request ID (Cloud)
```json
opensearch_search_raw(
  index="container-logs-*",
  body={
    "query": {"bool": {"must": [
      {"range": {"@timestamp": {"gte": "now-1h", "lte": "now"}}},
      {"wildcard": {"log": "*77e71a17-2e52-404a-86d2-eed997fd2a57*"}}
    ]}},
    "size": 20,
    "_source": ["@timestamp", "log", "kubernetes.namespace_name", "kubernetes.pod_name"]
  }
)
```

**Key points for Cloud:**
- Use `wildcard` query (NOT `query_string`)
- No quotes needed around the pattern
- `query_string` with `log:*pattern*` returns 0 hits on these clusters

### Aggregate error logs by namespace (Works on both)
```json
opensearch_aggregate(
  index="container-logs-*",
  query={"bool": {"must": [
    {"range": {"@timestamp": {"gte": "now-5m", "lte": "now"}}},
    {"wildcard": {"log": "*level*error*"}}
  ]}},
  aggs={"namespaces": {"terms": {"field": "kubernetes.namespace_name", "size": 10}}}
)
```

### How to Determine Cluster Type

Check the active cluster name using `opensearch_get_active_cluster`:
- If cluster name contains **`onprem`** → use `query_string` with `analyze_wildcard: true`
- Otherwise (AWS/Azure) → use `wildcard` queries

**Note**: `query_string` and `opensearch_search` work fine for **non-keyword fields** like `kubernetes.namespace_name`, `stream`, `kubernetes.pod_name`, etc. on **all clusters**.

## Common Query Patterns (non-log fields — use opensearch_search)

### Search by namespace
```
query_string: 'kubernetes.namespace_name:"my-namespace"'
```

### Search by pod name
```
query_string: 'kubernetes.pod_name:"my-pod-abc123"'
```

### Search stderr logs
```
query_string: 'stream:stderr'
```

### Combine namespace filter with log content search (use opensearch_search_raw)
```json
opensearch_search_raw(
  index="container-logs-*",
  body={
    "query": {"bool": {"must": [
      {"range": {"@timestamp": {"gte": "now-5m", "lte": "now"}}},
      {"term": {"kubernetes.namespace_name": "my-namespace"}},
      {"wildcard": {"log": "*timeout*"}}
    ]}},
    "size": 20,
    "_source": ["@timestamp", "log", "kubernetes.pod_name"]
  }
)
```

## Useful Fields for `fields` Parameter

| Field | Description |
|-------|-------------|
| `@timestamp` | Log timestamp |
| `log` | The actual log message |
| `stream` | stdout or stderr |
| `kubernetes.namespace_name` | K8s namespace |
| `kubernetes.pod_name` | K8s pod name |
| `kubernetes.container_name` | Container name |
| `kubernetes.host` | Node name |
| `kubernetes.pod_ip` | Pod IP address |
| `kubernetes.labels.organization_id` | Org ID (when auto_prune=false or use aggs) |
| `kubernetes.labels.env_name` | Environment name |
| `kubernetes.labels.component_name` | Component name |

## Time Handling

- The cluster stores timestamps in **UTC**
- The user is in **IST (UTC+5:30)** — convert accordingly
- IST 10:45 AM = UTC 05:15 AM
- Use relative times when possible: `now-5m`, `now-1h`, `now-24h`

## Cluster Map

**IMPORTANT**: When the user mentions a cluster, first read `opensearch-mcp/clusters.py` to get the available clusters and their short names. The cluster registry is defined in the `CLUSTERS` dictionary in that file.

### Example Cluster Format
Users configure their clusters in `opensearch-mcp/clusters.py`. Example entries:
```python
CLUSTERS = {
    "dev-aws-eu-cluster": ("https://opensearch-dashboard.dev.example.com", "Dev AWS EU Cluster"),
    "prod-aws-cluster": ("https://opensearch-dashboard.prod.example.com", "Prod AWS Cluster"),
}
```

### Common aliases
When the user says any of these, map to the corresponding cluster:
- "prod" / "production" → `prod-azure-us-cdp`
- "dev" / "development" → `dev-azure-us-cdp`
- "stg" / "staging" → `stg-us-cdp`
- "dev onprem" → `dev-onprem-cp` or `dev-onprem-dp` (ask which)
- "prod eu" → `prod-eu-cdp`
- "dev eu" → `dev-eu-cdp`
- "tenant-a" → `prod-tenant-a-userprod`
- "tenant-c" / "tc" → `prod-tenant-c`
- "tenant-d" → `prod-tenant-d`
- "tenant-b" → `prod-tenant-b`

If the user asks to query a cluster that has **No OpenSearch**, inform them it uses Azure Log Analytics Workspace instead and is not queryable through this MCP.

### Switching Clusters

When the user wants to query a different cluster, use the `opensearch_switch_cluster` tool:
```
opensearch_switch_cluster(cluster="prod-azure-eu-cdp")
```
This automatically fetches cookies via headless SSO and switches all subsequent queries to the new cluster. No restart needed.

If the tool returns an error (SSO session expired), instruct the user to run:
```
cd /path/to/opensearch-agent/opensearch-mcp
./get-cookies.py <cluster-short-name>
```
This opens a browser for manual login. After login, retry — no restart needed.

Use `opensearch_get_active_cluster` to check which cluster is currently active before switching.

## Cookie Management and 401 Handling

The MCP server has **automatic cookie refresh**. Here's how it works:

### Auto-refresh (transparent to you)
1. When a request gets 401, the server automatically launches a headless Playwright browser
2. It uses the cached Azure AD SSO session to get fresh cookies
3. Saves them to `cookies.json` and retries the request
4. You (Claude) never see the 401 — it's handled internally

### Cluster switching also refreshes cookies
When you call `opensearch_switch_cluster`, it fetches fresh cookies for the target cluster via headless SSO. If that fails, the tool returns an error with manual instructions.

### When auto-refresh fails
If the SSO session itself has expired (user hasn't logged in via browser recently), auto-refresh fails.
The server returns a structured error with `action_required` and a `command` to run.

**When you see this error, instruct the user:**
```
The OpenSearch cookies have expired and automatic refresh failed (SSO session expired).
To fix, run:

  cd /path/to/opensearch-agent/opensearch-mcp
  ./get-cookies.py <cluster-name>

This opens a browser for you to log in. After login completes, cookies are
saved automatically. **No Claude Code restart needed** — just retry the query.

Available clusters: ./get-cookies.py --list
```

**Important:** After the user runs the script, you CAN retry the query immediately — no restart needed. The server reads `cookies.json` fresh on every request.

## Cost-Conscious Query Plan

For any user request, follow this order:
1. **Count first** — `summary_only=true` to understand volume
2. **Sample if large** — `size=5, fields=[...]` to understand shape
3. **Aggregate if analytical** — use `opensearch_aggregate` for breakdowns
4. **Full fetch only when needed** — small result sets with field filtering
