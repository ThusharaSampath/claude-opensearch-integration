"""
Shared cluster registry for OpenSearch MCP tools.

Maps cluster short names to (url, description) tuples.
Imported by both server.py and get-cookies.py.

IMPORTANT: This file contains SAMPLE data for public repository.
"""

# Mapping: short_name -> (url_or_None, description)
# url=None means no OpenSearch for that cluster.

CLUSTERS = {
    # ── Development ──
    "dev-aws-eu-cluster":       ("https://opensearch-dashboard.dev.example.com", "Dev AWS EU Cluster"),
    "dev-azure-us-cluster":     ("https://opensearch-dashboard.dev-us.example.com", "Dev Azure US Cluster"),
    "dev-onprem-cluster":       ("https://opensearch.dev-onprem.example.com", "Dev OnPrem Cluster"),

    # ── Staging ──
    "stg-aws-eu-cluster":       ("https://opensearch-dashboard.staging.example.com", "Staging AWS EU Cluster"),
    "stg-azure-us-cluster":     ("https://opensearch-dashboard.staging-us.example.com", "Staging Azure US Cluster"),

    # ── Production ──
    "prod-aws-eu-cluster":      ("https://opensearch-dashboard.prod.example.com", "Prod AWS EU Cluster"),
    "prod-azure-us-cluster":    ("https://opensearch-dashboard.prod-us.example.com", "Prod Azure US Cluster"),

    # ── Example: No OpenSearch (alternative logging) ──
    "prod-special-cluster":     (None, "Prod Special Cluster — No OpenSearch (uses alternative logging solution)"),
}
