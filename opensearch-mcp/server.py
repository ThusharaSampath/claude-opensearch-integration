#!/usr/bin/env python3
"""
OpenSearch MCP Server Wrapper with Cookie Authentication

This MCP server wraps OpenSearch Dashboards API calls with session cookie authentication,
enabling Claude to query OpenSearch clusters that use OpenID/OAuth authentication.

It uses the same internal API endpoint and request format as the OpenSearch Dashboards UI.

Cookie management:
  - Reads cookies from cookies.json (written by get-cookies.py) at request time
  - Falls back to OPENSEARCH_COOKIE env var if cookies.json not found
  - On 401, auto-refreshes cookies via Playwright headless SSO
  - If auto-refresh fails, returns error with manual instructions
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from clusters import CLUSTERS

# Configuration from environment (used as fallbacks)
OPENSEARCH_URL_ENV = os.environ.get("OPENSEARCH_URL", "").rstrip("/")
OPENSEARCH_COOKIE = os.environ.get("OPENSEARCH_COOKIE", "")
OPENSEARCH_VERIFY_SSL = os.environ.get("OPENSEARCH_VERIFY_SSL", "true").lower() == "true"
OSD_VERSION = os.environ.get("OSD_VERSION", "2.18.0")

# Paths
SERVER_DIR = Path(__file__).parent
COOKIES_FILE = SERVER_DIR / "cookies.json"
BROWSER_DATA_DIR = SERVER_DIR / ".browser-data"
LOG_FILE = SERVER_DIR / "server.log"


def log(msg: str):
    """Write a timestamped log line to both stderr and server.log for debugging."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# Cookie names required for OpenSearch Dashboards OIDC auth
REQUIRED_COOKIES = ["security_authentication", "security_authentication_oidc1"]

server = Server("opensearch-cookie-auth")


# ── Cookie & URL Management ───────────────────────────────────────────────────

def _read_cookies_json() -> dict | None:
    """Read and parse cookies.json, returning None on any error."""
    if COOKIES_FILE.exists():
        try:
            return json.loads(COOKIES_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def get_active_url() -> str:
    """Get the active OpenSearch URL, preferring cookies.json over env var.

    This is read on every request so cluster switches take effect immediately.
    """
    data = _read_cookies_json()
    if data:
        url = data.get("url", "").rstrip("/")
        if url:
            return url
    return OPENSEARCH_URL_ENV


def get_active_cluster() -> dict:
    """Get info about the currently active cluster."""
    data = _read_cookies_json()
    if data:
        return {
            "cluster": data.get("cluster", "unknown"),
            "url": data.get("url", ""),
            "updated_at": data.get("updated_at", ""),
        }
    return {
        "cluster": "unknown",
        "url": OPENSEARCH_URL_ENV,
        "updated_at": "",
    }


def load_cookies() -> str:
    """Load cookies from cookies.json, falling back to env var.

    cookies.json is read on every request so that refreshed cookies
    are picked up without restarting the MCP server.
    """
    data = _read_cookies_json()
    if data:
        cookie_str = data.get("cookie", "")
        if cookie_str:
            return cookie_str
    return OPENSEARCH_COOKIE


def save_cookies(cookie_str: str, url: str = None, cluster: str = None):
    """Persist cookies to cookies.json for future requests."""
    # Preserve existing cluster/url if not provided
    existing = _read_cookies_json() or {}
    data = {
        "cookie": cookie_str,
        "url": url or existing.get("url", OPENSEARCH_URL_ENV),
        "cluster": cluster or existing.get("cluster", "unknown"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    COOKIES_FILE.write_text(json.dumps(data, indent=2) + "\n")
    log(f"[cookie-refresh] Saved fresh cookies to {COOKIES_FILE}")


async def _refresh_cookies_for_url(url: str, headless: bool = True) -> str | None:
    """Attempt to refresh cookies for a specific URL using async Playwright.

    Returns the new cookie string on success, None on failure.
    Must be called from within an asyncio event loop.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log("[cookie-refresh] Playwright not installed, cannot auto-refresh")
        return None

    log(f"[cookie-refresh] Attempting {'headless' if headless else 'headed'} refresh for {url}")
    log(f"[cookie-refresh] Browser data dir: {BROWSER_DATA_DIR} (exists={BROWSER_DATA_DIR.exists()})")

    try:
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                str(BROWSER_DATA_DIR),
                headless=headless,
                accept_downloads=False,
            )
            log("[cookie-refresh] Browser launched successfully")

            page = await context.new_page()
            log(f"[cookie-refresh] Navigating to {url}")
            await page.goto(url, wait_until="domcontentloaded")
            log(f"[cookie-refresh] Page loaded. Current URL: {page.url}")
            log(f"[cookie-refresh] Page title: {await page.title()}")

            # Wait for SSO redirect to complete and cookies to appear
            cookies = {}
            final_url = page.url
            for i in range(60):  # poll for up to 30 seconds
                all_cookies = await context.cookies(url)
                for c in all_cookies:
                    if c["name"] in REQUIRED_COOKIES:
                        cookies[c["name"]] = c["value"]
                if len(cookies) == len(REQUIRED_COOKIES):
                    log(f"[cookie-refresh] Got both cookies after {i * 0.5}s")
                    break
                if i % 10 == 0:  # log every 5 seconds
                    all_names = [c["name"] for c in all_cookies]
                    final_url = page.url
                    log(f"[cookie-refresh] Poll {i}/60 — current URL: {final_url}")
                    log(f"[cookie-refresh] Poll {i}/60 — all cookie names: {all_names}")
                    log(f"[cookie-refresh] Poll {i}/60 — matched so far: {list(cookies.keys())}")
                await page.wait_for_timeout(500)

            await context.close()

            if len(cookies) == len(REQUIRED_COOKIES):
                cookie_str = "; ".join(f"{name}={value}" for name, value in cookies.items())
                log("[cookie-refresh] Refresh successful!")
                return cookie_str
            else:
                found = list(cookies.keys())
                log(f"[cookie-refresh] Refresh FAILED — only got: {found}")
                log(f"[cookie-refresh] Final page URL was: {final_url}")
                return None

    except Exception as e:
        log(f"[cookie-refresh] Refresh error: {type(e).__name__}: {e}")
        return None


async def auto_refresh_cookies() -> str | None:
    """Attempt to refresh cookies for the active URL using headless Playwright.

    Returns the new cookie string on success, None on failure.
    """
    url = get_active_url()
    cookie_str = await _refresh_cookies_for_url(url, headless=True)
    if cookie_str:
        save_cookies(cookie_str, url=url)
    return cookie_str


# ── HTTP Client ───────────────────────────────────────────────────────────────

def get_client(cookie_str: str = None) -> httpx.Client:
    """Create an HTTP client with cookie authentication matching browser headers."""
    if cookie_str is None:
        cookie_str = load_cookies()

    url = get_active_url()
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "osd-xsrf": "osd-fetch",
        "osd-version": OSD_VERSION,
        "Origin": url,
        "Referer": f"{url}/app/data-explorer/discover",
    }
    if cookie_str:
        headers["Cookie"] = cookie_str

    return httpx.Client(
        base_url=url,
        headers=headers,
        verify=OPENSEARCH_VERIFY_SSL,
        timeout=120.0,
    )


def make_search_request(client: httpx.Client, index: str, body: dict) -> dict:
    """Make a search request using the internal search endpoint (same as browser)."""
    payload = {
        "params": {
            "index": index,
            "body": body,
            "preference": int(time.time() * 1000),
        }
    }
    response = client.post("/internal/search/opensearch-with-long-numerals", json=payload)
    response.raise_for_status()
    result = response.json()
    return result.get("rawResponse", result)


def build_dashboard_query(query_str: str, time_from: str = None, time_to: str = None,
                          size: int = 100, sort_field: str = "@timestamp",
                          sort_order: str = "desc") -> dict:
    """Build a query body matching the exact format used by OpenSearch Dashboards UI."""
    must = []
    if query_str:
        must.append({
            "query_string": {
                "query": query_str,
                "analyze_wildcard": True,
                "time_zone": "Asia/Colombo"
            }
        })

    filters = []
    if time_from or time_to:
        range_filter = {}
        if time_from:
            range_filter["gte"] = time_from
        if time_to:
            range_filter["lte"] = time_to
        range_filter["format"] = "strict_date_optional_time"
        filters.append({"range": {"@timestamp": range_filter}})

    body = {
        "sort": [{sort_field: {"order": sort_order, "unmapped_type": "boolean"}}],
        "size": size,
        "version": True,
        "stored_fields": ["*"],
        "script_fields": {},
        "docvalue_fields": [{"field": "@timestamp", "format": "date_time"}],
        "_source": {"excludes": []},
        "query": {
            "bool": {
                "must": must if must else [{"match_all": {}}],
                "filter": filters,
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
    }
    return body


# ── MCP Tool Definitions ─────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available OpenSearch tools."""
    return [
        Tool(
            name="opensearch_search",
            description=(
                "Search logs/documents in OpenSearch using the same query syntax as the Dashboards UI. "
                "Supports Lucene/KQL query strings with wildcards. "
                "IMPORTANT: Always include a time range (time_from/time_to) to avoid timeouts on large indices. "
                "Use ISO 8601 format for times (e.g., '2026-02-05T04:00:00.000Z') or relative like 'now-15m'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "index": {
                        "type": "string",
                        "description": "Index name or pattern (e.g., 'container-logs-*')",
                    },
                    "query_string": {
                        "type": "string",
                        "description": "Lucene/KQL query string as used in Dashboards search bar (e.g., 'log:\"*error*\"', 'kubernetes.namespace_name:\"prod\"')",
                    },
                    "time_from": {
                        "type": "string",
                        "description": "Start time in ISO 8601 format (e.g., '2026-02-05T04:00:00.000Z'). Defaults to now-15m.",
                    },
                    "time_to": {
                        "type": "string",
                        "description": "End time in ISO 8601 format (e.g., '2026-02-05T04:15:00.000Z'). Defaults to now.",
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of results to return (default: 100, max: 1000)",
                        "default": 100,
                    },
                    "summary_only": {
                        "type": "boolean",
                        "description": "Return only summary (total hits, time range) without document contents. Useful for counting results.",
                        "default": False,
                    },
                    "auto_prune": {
                        "type": "boolean",
                        "description": "Auto-remove verbose fields (kubernetes.labels, kubernetes.annotations) to reduce response size. Default: true.",
                        "default": True,
                    },
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of specific fields to return (e.g., ['log', '@timestamp', 'kubernetes.namespace_name']). If specified, only these fields are returned.",
                    },
                    "max_chars_per_hit": {
                        "type": "integer",
                        "description": "Maximum characters per hit. Hits exceeding this are truncated. Default: 2000.",
                        "default": 2000,
                    },
                },
                "required": ["index"],
            },
        ),
        Tool(
            name="opensearch_search_raw",
            description=(
                "Search OpenSearch with a raw Query DSL body. For advanced queries not covered by opensearch_search. "
                "IMPORTANT: Always include a time range filter to avoid timeouts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "index": {
                        "type": "string",
                        "description": "Index name or pattern",
                    },
                    "body": {
                        "type": "object",
                        "description": "Full OpenSearch query body (query, size, sort, aggs, _source, etc.)",
                    },
                },
                "required": ["index", "body"],
            },
        ),
        Tool(
            name="opensearch_get_indices",
            description="List indices in the OpenSearch cluster with document counts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Index pattern to filter (e.g., 'logs-*'). Leave empty for all indices.",
                    },
                },
            },
        ),
        Tool(
            name="opensearch_get_mappings",
            description="Get field names and types for an index by inspecting a sample document.",
            inputSchema={
                "type": "object",
                "properties": {
                    "index": {
                        "type": "string",
                        "description": "Index name or pattern",
                    },
                },
                "required": ["index"],
            },
        ),
        Tool(
            name="opensearch_aggregate",
            description=(
                "Run aggregation queries on OpenSearch data (e.g., counts, averages, histograms, terms). "
                "IMPORTANT: Always include a time range in the query to avoid timeouts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "index": {
                        "type": "string",
                        "description": "Index name or pattern",
                    },
                    "aggs": {
                        "type": "object",
                        "description": "Aggregation definitions using OpenSearch aggregation DSL",
                    },
                    "query": {
                        "type": "object",
                        "description": "Optional query to filter documents before aggregating",
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of hits to return (set to 0 for aggregation-only)",
                        "default": 0,
                    },
                },
                "required": ["index", "aggs"],
            },
        ),
        Tool(
            name="opensearch_cluster_health",
            description="Get basic cluster health info (total docs, shards, response time).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="opensearch_switch_cluster",
            description=(
                "Switch to a different OpenSearch cluster. Fetches fresh cookies via headless SSO "
                "and updates the active cluster. No restart needed. "
                "Use opensearch_get_active_cluster to see the current cluster first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "cluster": {
                        "type": "string",
                        "description": (
                            "Cluster short name (e.g., 'prod-azure-us-cdp', 'dev-aws-eu-cp'). "
                            "Use opensearch_get_active_cluster or see the cluster registry for valid names."
                        ),
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Run browser in headless mode (default: true). Only works if SSO session is cached.",
                        "default": True,
                    },
                },
                "required": ["cluster"],
            },
        ),
        Tool(
            name="opensearch_get_active_cluster",
            description="Get the currently active OpenSearch cluster name, URL, and when cookies were last refreshed.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


# ── Tool Execution with Auto-Retry on 401 ────────────────────────────────────

def _update_mcp_json_url(url: str):
    """Update the OPENSEARCH_URL in .mcp.json so next restart picks up the right cluster."""
    mcp_json_path = SERVER_DIR.parent / ".mcp.json"
    if not mcp_json_path.exists():
        return
    try:
        config = json.loads(mcp_json_path.read_text())
        if "opensearch" in config.get("mcpServers", {}):
            config["mcpServers"]["opensearch"]["env"]["OPENSEARCH_URL"] = url
            mcp_json_path.write_text(json.dumps(config, indent=2) + "\n")
            log(f"[cluster-switch] Updated OPENSEARCH_URL in {mcp_json_path}")
    except Exception as e:
        log(f"[cluster-switch] Warning: could not update .mcp.json: {e}")


async def _handle_switch_cluster(arguments: dict[str, Any]) -> dict:
    """Handle the opensearch_switch_cluster tool."""
    cluster_name = arguments["cluster"]
    headless = arguments.get("headless", True)

    # Validate cluster name
    if cluster_name not in CLUSTERS:
        available = [k for k, (u, _) in CLUSTERS.items() if u is not None]
        return {
            "error": f"Unknown cluster: '{cluster_name}'",
            "available_clusters": available,
        }

    url, desc = CLUSTERS[cluster_name]
    if url is None:
        return {
            "error": f"'{cluster_name}' does not have OpenSearch",
            "description": desc,
        }

    url = url.rstrip("/")

    # Attempt to get cookies via Playwright SSO
    cookie_str = await _refresh_cookies_for_url(url, headless=headless)

    if cookie_str is None:
        return {
            "error": "Cookie refresh failed — SSO session may have expired",
            "cluster": cluster_name,
            "url": url,
            "action_required": "Run the cookie refresh script manually with a browser",
            "command": f"cd {SERVER_DIR} && ./get-cookies.py {cluster_name}",
            "note": "This opens a browser for you to log in. No Claude Code restart needed after.",
        }

    # Save cookies with cluster info
    save_cookies(cookie_str, url=url, cluster=cluster_name)

    # Update .mcp.json so next restart picks up the right cluster
    _update_mcp_json_url(url)

    return {
        "success": True,
        "cluster": cluster_name,
        "description": desc,
        "url": url,
        "message": f"Switched to {cluster_name} ({desc}). All subsequent queries will use this cluster.",
    }


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute an OpenSearch tool with automatic cookie refresh on 401."""
    # Handle tools that don't need an HTTP client
    if name == "opensearch_get_active_cluster":
        result = get_active_cluster()
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    if name == "opensearch_switch_cluster":
        result = await _handle_switch_cluster(arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    try:
        result = await _call_tool_with_retry(name, arguments)
        result_str = json.dumps(result, indent=2, default=str)

        # Track what the MCP server did to the response
        _meta = result.get("_meta", {}) if isinstance(result, dict) else {}
        applied = _meta.get("applied_operations", [])

        if len(result_str) > 15000:
            applied.append("response_truncated_at_15KB")
            meta_header = json.dumps({
                "_meta": {
                    "warning": "Response was truncated by MCP server. Use summary_only, fields filter, or reduce size to get complete results.",
                    "applied_operations": applied,
                    "original_size_bytes": len(result_str),
                    "truncated_to_bytes": 15000,
                }
            }, indent=2)
            result_str = meta_header + "\n" + result_str[:15000 - len(meta_header)]

        return [TextContent(type="text", text=result_str)]
    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:2000] if e.response else "No response body"
        return [TextContent(
            type="text",
            text=f"HTTP Error {e.response.status_code}: {error_body}"
        )]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _call_tool_with_retry(name: str, arguments: dict[str, Any]) -> Any:
    """Execute a tool, auto-refreshing cookies on 401 and retrying once."""
    # First attempt with current cookies
    failed_request = None
    try:
        with get_client() as client:
            return await execute_tool(client, name, arguments)
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 401:
            raise
        failed_request = e.request

    # Got 401 — try auto-refresh
    log("[cookie-refresh] Got 401, attempting automatic cookie refresh...")
    new_cookies = await auto_refresh_cookies()

    if new_cookies is None:
        # Auto-refresh failed — return helpful error
        cluster_info = get_active_cluster()
        cluster_name = cluster_info.get("cluster", "unknown")
        raise httpx.HTTPStatusError(
            message="Cookie refresh failed",
            request=failed_request,
            response=httpx.Response(
                status_code=401,
                text=json.dumps({
                    "error": "Unauthorized — cookies expired and auto-refresh failed",
                    "action_required": "Run the cookie refresh script manually",
                    "command": f"cd {SERVER_DIR} && ./get-cookies.py {cluster_name}",
                    "note": "SSO browser session may have expired. The script will open a browser for you to log in. No Claude Code restart needed after refresh.",
                }),
            ),
        )

    # Retry with fresh cookies
    log("[cookie-refresh] Retrying with fresh cookies...")
    with get_client(cookie_str=new_cookies) as client:
        return await execute_tool(client, name, arguments)


# ── Tool Implementation ───────────────────────────────────────────────────────

async def execute_tool(client: httpx.Client, name: str, arguments: dict[str, Any]) -> Any:
    """Execute the specified tool and return results."""

    if name == "opensearch_search":
        index = arguments["index"]
        query_str = arguments.get("query_string", "")
        size = min(arguments.get("size", 100), 1000)
        summary_only = arguments.get("summary_only", False)
        auto_prune = arguments.get("auto_prune", True)
        fields = arguments.get("fields")
        max_chars_per_hit = arguments.get("max_chars_per_hit", 2000)

        # Default time range: last 15 minutes
        now = datetime.now(timezone.utc)
        default_from = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        default_to = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        time_from = arguments.get("time_from", default_from)
        time_to = arguments.get("time_to", default_to)

        # For summary_only, we only need count
        if summary_only:
            size = 0

        body = build_dashboard_query(
            query_str=query_str,
            time_from=time_from,
            time_to=time_to,
            size=size,
        )
        result = make_search_request(client, index, body)

        # Extract total hits
        hits = result.get("hits", {})
        total = hits.get("total", 0)
        if isinstance(total, dict):
            total = total.get("value", 0)

        # Track what operations the server applied
        applied_ops = []

        response = {
            "total_hits": total,
            "time_range": {"from": time_from, "to": time_to},
        }

        # If summary_only, return just the count
        if summary_only:
            applied_ops.append("summary_only")
            response["_meta"] = {"applied_operations": applied_ops}
            return response

        # Process hits
        simplified_hits = []
        hits_truncated_count = 0
        for hit in hits.get("hits", []):
            source = hit.get("_source", {})

            # Field filtering: if fields specified, extract only those
            if fields:
                entry = {}
                for field in fields:
                    # Support nested fields like "kubernetes.namespace_name"
                    value = source
                    for part in field.split("."):
                        if isinstance(value, dict):
                            value = value.get(part)
                        else:
                            value = None
                            break
                    if value is not None:
                        entry[field] = value
            else:
                # No field filter: include everything but apply auto_prune
                entry = {
                    "_index": hit.get("_index"),
                    "@timestamp": source.get("@timestamp"),
                }
                entry.update(source)

                # Auto-prune: remove verbose kubernetes fields
                if auto_prune and "kubernetes" in entry:
                    k8s = entry["kubernetes"]
                    if isinstance(k8s, dict):
                        k8s.pop("annotations", None)
                        k8s.pop("labels", None)

            # Truncate if exceeds max_chars_per_hit
            entry_str = json.dumps(entry, default=str)
            if len(entry_str) > max_chars_per_hit:
                entry = {
                    "_truncated": True,
                    "_size_bytes": len(entry_str),
                    "preview": entry_str[:max_chars_per_hit],
                }
                hits_truncated_count += 1

            simplified_hits.append(entry)

        # Build metadata about what was applied
        if fields:
            applied_ops.append(f"field_filter:{','.join(fields)}")
        if auto_prune:
            applied_ops.append("auto_prune:kubernetes.labels,kubernetes.annotations")
        if hits_truncated_count > 0:
            applied_ops.append(f"hits_truncated:{hits_truncated_count}/{len(simplified_hits)}")
        if total > size:
            applied_ops.append(f"partial_results:{size}_of_{total}")

        response["returned"] = len(simplified_hits)
        response["hits"] = simplified_hits
        response["_meta"] = {"applied_operations": applied_ops}
        return response

    elif name == "opensearch_search_raw":
        index = arguments["index"]
        body = arguments["body"]
        return make_search_request(client, index, body)

    elif name == "opensearch_get_indices":
        pattern = arguments.get("pattern", "*")
        now = datetime.now(timezone.utc)
        time_from = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        time_to = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [{"range": {"@timestamp": {"gte": time_from, "lte": time_to, "format": "strict_date_optional_time"}}}]
                }
            },
            "aggs": {
                "indices": {
                    "terms": {
                        "field": "_index",
                        "size": 1000
                    }
                }
            }
        }
        result = make_search_request(client, pattern, body)
        indices = []
        if "aggregations" in result and "indices" in result["aggregations"]:
            for bucket in result["aggregations"]["indices"]["buckets"]:
                indices.append({
                    "index": bucket["key"],
                    "doc_count": bucket["doc_count"]
                })
        return {
            "total_indices": len(indices),
            "time_range": {"from": time_from, "to": time_to},
            "indices": sorted(indices, key=lambda x: x["doc_count"], reverse=True)
        }

    elif name == "opensearch_get_mappings":
        index = arguments["index"]
        now = datetime.now(timezone.utc)
        time_from = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        time_to = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body = build_dashboard_query(query_str="", time_from=time_from, time_to=time_to, size=1)
        result = make_search_request(client, index, body)

        fields = {}
        if result.get("hits", {}).get("hits"):
            sample = result["hits"]["hits"][0].get("_source", {})
            def extract_fields(obj, prefix=""):
                for key, value in obj.items():
                    full_key = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, dict):
                        extract_fields(value, full_key)
                    elif isinstance(value, list):
                        fields[full_key] = f"list ({type(value[0]).__name__ if value else 'empty'})"
                    else:
                        fields[full_key] = type(value).__name__
            extract_fields(sample)

        return {
            "index": index,
            "fields": fields,
        }

    elif name == "opensearch_aggregate":
        index = arguments["index"]
        body = {
            "size": arguments.get("size", 0),
            "aggs": arguments["aggs"],
        }
        if "query" in arguments:
            body["query"] = arguments["query"]
        return make_search_request(client, index, body)

    elif name == "opensearch_cluster_health":
        now = datetime.now(timezone.utc)
        time_from = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        time_to = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [{"range": {"@timestamp": {"gte": time_from, "lte": time_to, "format": "strict_date_optional_time"}}}]
                }
            }
        }
        result = make_search_request(client, "*", body)
        return {
            "docs_in_last_minute": result.get("hits", {}).get("total", {}).get("value", "unknown"),
            "shards": result.get("_shards", {}),
            "took_ms": result.get("took", "unknown"),
            "timed_out": result.get("timed_out", False),
        }

    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the MCP server."""
    if not OPENSEARCH_URL_ENV and not COOKIES_FILE.exists():
        print("Error: OPENSEARCH_URL environment variable is required (or cookies.json with url)", file=sys.stderr)
        sys.exit(1)

    if not OPENSEARCH_COOKIE and not COOKIES_FILE.exists():
        print("Warning: No cookies configured. Set OPENSEARCH_COOKIE env var or run get-cookies.py.", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
