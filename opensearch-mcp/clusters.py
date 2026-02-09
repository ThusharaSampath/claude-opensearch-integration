"""
Shared cluster registry for OpenSearch MCP tools.

Maps cluster short names to (url, description) tuples.
Imported by both server.py and get-cookies.py.
"""

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
