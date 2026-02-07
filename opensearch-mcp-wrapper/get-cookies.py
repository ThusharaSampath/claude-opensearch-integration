#!/usr/bin/env python3
"""
Fetch OpenSearch Dashboards session cookies via browser SSO.

Uses Playwright to open a real browser, lets Azure AD SSO complete automatically,
then extracts the session cookies and updates .mcp.json.

Usage:
    ./get-cookies.py <cluster>        # Fetch cookies and update .mcp.json
    ./get-cookies.py <cluster> --print # Just print the cookie string
    ./get-cookies.py --list           # List available clusters

Examples:
    ./get-cookies.py prod
    ./get-cookies.py dev --print
"""

import argparse
import json
import sys
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── Cluster registry ──────────────────────────────────────────────────────────
# Mapping: short_name -> (url_or_None, description)
# url=None means no OpenSearch for that cluster.

CLUSTERS = {
    # ── Development ──
    "dev-aws-eu-cp":            ("https://opensearch-cp.dv.eu.example.com/", "Dev AWS EU CP"),
    "dev-aws-eu-cdp":           ("https://opensearch.e1-eu-central-cdp.dv.example.com", "Dev AWS EU CDP"),
    "dev-azure-us-cp":          (None, "Dev Azure US CP — No OpenSearch (use Log Analytics Workspace)"),
    "dev-azure-us-cdp":         ("https://opensearch-dashboard.e1-us-east-azure.preview-dv.example.com", "Dev Azure US CDP"),
    "dev-azure-eu-cdp":         ("https://opensearch-dashboard.e1-eu-north-azure.preview-dv.example.com", "Dev Azure EU CDP"),
    "dev-azure-pdp-userdev":    ("https://opensearch-dashboard.dev.example-dev.example.com", "Dev Azure PDP (Userdev)"),
    "dev-azure-pdp-userprod":   ("https://opensearch-dashboard.example-dev.example.com", "Dev Azure PDP (Userprod)"),
    "dev-aws-pdp":              ("https://opensearch-dashboard.dv.dap.example.com/", "Dev AWS PDP"),
    "dev-onprem-cp":            ("https://opensearch-dashboard-cp.preview-dv.example.com", "Dev OnPrem CP"),
    "dev-onprem-dp":            ("https://opensearch-dashboard.e1-us-east-azure.preview-dv.example.com", "Dev OnPrem DP"),
    "dev-onprem-e2e-pdp":       ("https://opensearch-dashboard.nonprod.e2e-dv.preview-dv.example.com", "Dev OnPrem e2e PDP"),

    # ── Staging ──
    "stg-aws-eu-cp":            ("https://opensearch-cp.stv.eu.example.com", "Staging AWS EU CP"),
    "stg-aws-eu-cdp":           ("https://opensearch.e1-eu-west-cdp.st.example.com", "Staging AWS EU CDP"),
    "stg-azure-us-cp":          (None, "Staging Azure US CP — No OpenSearch (use Log Analytics Workspace)"),
    "stg-azure-us-cdp":         ("https://opensearch-dashboard.e1-us-east-azure.st.example.com", "Staging Azure US CDP"),
    "stg-azure-eu-cdp":         ("https://opensearch-dashboard.e1-eu-north-azure.st.example.com", "Staging Azure EU CDP"),
    "stg-azure-pdp-userdev":    ("https://opensearch-dashboard.dev.example-stg.example.com/", "Staging Azure PDP (Userdev)"),
    "stg-azure-pdp-userprod":   ("https://opensearch-dashboard.example-stg.example.com/", "Staging Azure PDP (Userprod)"),
    "stg-onprem-e2e-pdp":       ("https://opensearch-dashboard.nonprod.e2e-stg.st.example.com", "Staging OnPrem e2e PDP"),

    # ── Production ──
    "prod-aws-eu-cp":           ("https://opensearch-cp.eu.example.com", "Prod AWS EU CP"),
    "prod-azure-us-cp":         (None, "Prod Azure US CP — No OpenSearch (use Log Analytics Workspace)"),
    "prod-aws-eu-cdp":          ("https://opensearch.e1-eu-west-cdp.example.com", "Prod AWS EU CDP"),
    "prod-azure-us-cdp":        ("https://opensearch-dashboard.e1-us-east-azure.example.com", "Prod Azure US CDP"),
    "prod-azure-eu-cdp":        ("https://opensearch-dashboard.e1-eu-north-azure.example.com", "Prod Azure EU CDP"),
    "prod-tenant-a-userprod":        ("https://opensearch-dashboard.prod.tenant-a.example.com", "Prod Tenant-A UserProd PDP"),
    "prod-tenant-a-nonprod-onprem":  ("https://opensearch-dashboard.nonprod.tenant-a.example.com", "Prod Tenant-A User Non-Prod OnPrem PDP (requires FortiClient VPN)"),
    "prod-tenant-b":               ("https://opensearch-dashboard.dv.tb.example.com", "Prod Tenant-B UserNonProd PDP"),
    "prod-tenant-c":             ("https://opensearch-dashboard.prod.tc.example.com", "Prod Tenant-C UserProd PDP"),
    "prod-tenant-d":            ("https://opensearch-dashboard.prod.td.example.com", "Prod Tenant-D UserProd PDP"),
}

# Cookies we need from the OpenSearch Dashboards session
REQUIRED_COOKIES = ["security_authentication", "security_authentication_oidc1"]

# Path to the project .mcp.json
MCP_JSON_PATH = Path(__file__).parent.parent / ".mcp.json"

# Playwright user data dir for persistent browser context (keeps Azure AD session)
BROWSER_DATA_DIR = Path(__file__).parent / ".browser-data"


def fetch_cookies(url: str, headless: bool = False, timeout: int = 60) -> str:
    """Open the dashboard URL in a browser, wait for SSO, return cookie string."""
    with sync_playwright() as p:
        # Use persistent context so Azure AD session is cached across runs.
        # After the first manual login, subsequent runs will auto-SSO.
        context = p.chromium.launch_persistent_context(
            str(BROWSER_DATA_DIR),
            headless=headless,
            accept_downloads=False,
        )

        page = context.new_page()
        print(f"Opening {url} ...")
        page.goto(url, wait_until="domcontentloaded")

        # Wait until the OpenSearch Dashboards page is loaded (SSO redirect completes).
        # The dashboard sets the security cookies once authenticated.
        print("Waiting for SSO to complete ...")
        try:
            page.wait_for_url(f"{url}/**", timeout=timeout * 1000)
        except Exception:
            # Even if URL pattern doesn't match exactly, check cookies
            pass

        # Poll for the required cookies (they appear after OIDC redirect completes)
        cookies = {}
        for attempt in range(timeout * 2):  # check every 0.5s
            all_cookies = context.cookies(url)
            for c in all_cookies:
                if c["name"] in REQUIRED_COOKIES:
                    cookies[c["name"]] = c["value"]
            if len(cookies) == len(REQUIRED_COOKIES):
                break
            page.wait_for_timeout(500)
        else:
            found = list(cookies.keys())
            print(f"Warning: Only found cookies: {found}", file=sys.stderr)
            if not cookies:
                context.close()
                print("Error: No session cookies found. You may need to log in manually.", file=sys.stderr)
                print("Try running again — the browser should show a login page.", file=sys.stderr)
                sys.exit(1)

        context.close()

    cookie_str = "; ".join(f"{name}={value}" for name, value in cookies.items())
    return cookie_str


def update_mcp_json(cookie_str: str, url: str):
    """Update the .mcp.json file with new cookies and URL."""
    if MCP_JSON_PATH.exists():
        with open(MCP_JSON_PATH) as f:
            config = json.load(f)
    else:
        config = {"mcpServers": {}}

    if "opensearch" not in config.get("mcpServers", {}):
        config["mcpServers"]["opensearch"] = {
            "type": "stdio",
            "command": str(Path(__file__).parent / "venv" / "bin" / "python"),
            "args": [str(Path(__file__).parent / "server.py")],
            "env": {},
        }

    env = config["mcpServers"]["opensearch"]["env"]
    env["OPENSEARCH_URL"] = url
    env["OPENSEARCH_COOKIE"] = cookie_str
    env.setdefault("OPENSEARCH_VERIFY_SSL", "true")

    with open(MCP_JSON_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"Updated {MCP_JSON_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Fetch OpenSearch Dashboards session cookies via browser SSO")
    parser.add_argument("cluster", nargs="?", help="Cluster name (see --list)")
    parser.add_argument("--list", action="store_true", help="List available clusters")
    parser.add_argument("--print", action="store_true", dest="print_only", help="Print cookie string instead of updating .mcp.json")
    parser.add_argument("--url", help="Use a custom URL instead of a registered cluster")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (only works if SSO session is cached)")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds waiting for SSO (default: 60)")
    args = parser.parse_args()

    if args.list:
        current_env = ""
        for name, (url, desc) in CLUSTERS.items():
            env = name.split("-")[0]  # dev, stg, prod
            if env != current_env:
                current_env = env
                label = {"dev": "Development", "stg": "Staging", "prod": "Production"}
                print(f"\n  {'─' * 60}")
                print(f"  {label.get(env, env.upper())}")
                print(f"  {'─' * 60}")
            status = "✗ NO OPENSEARCH" if url is None else url
            print(f"  {name:30s} {status}")
            if url is None:
                print(f"  {'':30s} ({desc})")
        print()
        return

    if not args.cluster and not args.url:
        parser.print_help()
        sys.exit(1)

    if args.url:
        url = args.url.rstrip("/")
        cluster_name = "custom"
    else:
        cluster_name = args.cluster
        if cluster_name not in CLUSTERS:
            print(f"Error: Unknown cluster '{cluster_name}'", file=sys.stderr)
            print(f"Available: {', '.join(k for k, (u, _) in CLUSTERS.items() if u)}", file=sys.stderr)
            print(f"Or use --url to specify a custom URL", file=sys.stderr)
            sys.exit(1)
        url, desc = CLUSTERS[cluster_name]
        if url is None:
            print(f"Error: '{cluster_name}' does not have OpenSearch.", file=sys.stderr)
            print(f"  → {desc}", file=sys.stderr)
            sys.exit(1)

    print(f"Cluster: {cluster_name}")
    print(f"URL:     {url}")

    cookie_str = fetch_cookies(url, headless=args.headless, timeout=args.timeout)

    if args.print_only:
        print(f"\nCookies:\n{cookie_str}")
    else:
        update_mcp_json(cookie_str, url)
        print(f"\nDone! Restart Claude Code to use the new cookies.")


if __name__ == "__main__":
    main()
