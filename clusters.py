"""
Shared cluster registry for OpenSearch MCP tools.

Maps cluster short names to (url, description) tuples.
Imported by both server.py and get-cookies.py.

URLs are loaded from the .env file (see .env.example for the template).
Descriptions are defined statically below.
"""

from pathlib import Path

# ── Descriptions (not sensitive — kept in source) ──

DESCRIPTIONS = {
    # Development
    "dev-aws-eu-cp":            "Dev AWS EU CP",
    "dev-aws-eu-cdp":           "Dev AWS EU CDP",
    "dev-azure-us-cp":          "Dev Azure US CP — No OpenSearch (use Log Analytics Workspace)",
    "dev-azure-us-cdp":         "Dev Azure US CDP",
    "dev-azure-eu-cdp":         "Dev Azure EU CDP",
    "dev-azure-pdp-userdev":    "Dev Azure PDP (Userdev)",
    "dev-azure-pdp-userprod":   "Dev Azure PDP (Userprod)",
    "dev-aws-pdp":              "Dev AWS PDP",
    "dev-onprem-cp":            "Dev OnPrem CP",
    "dev-onprem-dp":            "Dev OnPrem DP",
    "dev-onprem-e2e-pdp":       "Dev OnPrem e2e PDP",

    # Staging
    "stg-aws-eu-cp":            "Staging AWS EU CP",
    "stg-aws-eu-cdp":           "Staging AWS EU CDP",
    "stg-azure-us-cp":          "Staging Azure US CP — No OpenSearch (use Log Analytics Workspace)",
    "stg-azure-us-cdp":         "Staging Azure US CDP",
    "stg-azure-eu-cdp":         "Staging Azure EU CDP",
    "stg-azure-pdp-userdev":    "Staging Azure PDP (Userdev)",
    "stg-azure-pdp-userprod":   "Staging Azure PDP (Userprod)",
    "stg-onprem-e2e-pdp":       "Staging OnPrem e2e PDP",

    # Production
    "prod-aws-eu-cp":           "Prod AWS EU CP",
    "prod-azure-us-cp":         "Prod Azure US CP — No OpenSearch (use Log Analytics Workspace)",
    "prod-aws-eu-cdp":          "Prod AWS EU CDP",
    "prod-azure-us-cdp":        "Prod Azure US CDP",
    "prod-azure-eu-cdp":        "Prod Azure EU CDP",
    "prod-wdt-userprod":        "Prod WDT UserProd PDP",
    "prod-wdt-nonprod-onprem":  "Prod WDT User Non-Prod OnPrem PDP (requires FortiClient VPN)",
    "prod-devry":               "Prod Devry UserNonProd PDP",
    "prod-cutndry":             "Prod CutNDry UserProd PDP",
    "prod-bcentral":            "Prod BCentral UserProd PDP",
}


# ── Load URLs from .env (no external dependency) ──

def _load_env():
    """Parse CLUSTER_* variables from the .env file next to this script."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return {}
    result = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key.startswith("CLUSTER_"):
            short_name = key[8:].lower().replace("_", "-")
            result[short_name] = value if value else None
    return result


# ── Build the CLUSTERS dict (same shape as before) ──
# Mapping: short_name -> (url_or_None, description)

_urls = _load_env()
CLUSTERS = {}
for _name, _url in _urls.items():
    _desc = DESCRIPTIONS.get(_name, _name)
    CLUSTERS[_name] = (_url, _desc)
