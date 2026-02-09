#!/usr/bin/env bash
set -euo pipefail

# OpenSearch MCP Agent Initialization Script
# This script sets up the project with correct paths and dependencies

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the absolute path to the project root (where this script lives)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_WRAPPER_DIR="${PROJECT_ROOT}/opensearch-mcp-wrapper"
VENV_DIR="${MCP_WRAPPER_DIR}/venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"
MCP_JSON="${PROJECT_ROOT}/.mcp.json"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  OpenSearch MCP Agent - Initialization Script                 ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Project root:${NC} ${PROJECT_ROOT}"
echo -e "${GREEN}MCP wrapper:${NC} ${MCP_WRAPPER_DIR}"
echo ""

# Step 1: Check Python version
echo -e "${YELLOW}[1/5] Checking Python version...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found. Please install Python 3.10 or higher.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "       Found Python ${PYTHON_VERSION}"

# Step 2: Create virtual environment if it doesn't exist
echo -e "${YELLOW}[2/5] Setting up virtual environment...${NC}"
if [ ! -d "${VENV_DIR}" ]; then
    echo "       Creating new virtual environment at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
    echo -e "${GREEN}       ✓ Virtual environment created${NC}"
else
    echo -e "${GREEN}       ✓ Virtual environment already exists${NC}"
fi

# Step 3: Install/upgrade dependencies
echo -e "${YELLOW}[3/5] Installing Python dependencies...${NC}"
if [ ! -f "${MCP_WRAPPER_DIR}/requirements.txt" ]; then
    echo -e "${RED}Error: requirements.txt not found at ${MCP_WRAPPER_DIR}/requirements.txt${NC}"
    exit 1
fi

echo "       Installing: mcp, httpx"
"${PIP_BIN}" install -q --upgrade pip
"${PIP_BIN}" install -q -r "${MCP_WRAPPER_DIR}/requirements.txt"
echo -e "${GREEN}       ✓ Core dependencies installed${NC}"

# Check if playwright is installed, if not, prompt user
if "${PIP_BIN}" list | grep -q playwright; then
    echo -e "${GREEN}       ✓ Playwright already installed${NC}"
else
    echo -e "${YELLOW}       Installing playwright (for cookie auto-refresh)...${NC}"
    "${PIP_BIN}" install -q playwright
    echo "       Installing Chromium browser..."
    "${VENV_DIR}/bin/playwright" install chromium --with-deps 2>&1 | grep -v "^Downloading" || true
    echo -e "${GREEN}       ✓ Playwright installed${NC}"
fi

# Step 4: Generate .mcp.json with correct paths
echo -e "${YELLOW}[4/5] Generating .mcp.json configuration...${NC}"

# Default cluster URL (user can change this)
DEFAULT_CLUSTER_URL="https://opensearch-dashboard.e1-us-east-azure.example.com"

cat > "${MCP_JSON}" <<EOF
{
  "mcpServers": {
    "opensearch": {
      "type": "stdio",
      "command": "${PYTHON_BIN}",
      "args": [
        "${MCP_WRAPPER_DIR}/server.py"
      ],
      "env": {
        "OPENSEARCH_URL": "${DEFAULT_CLUSTER_URL}",
        "OPENSEARCH_VERIFY_SSL": "true"
      }
    }
  }
}
EOF

echo -e "${GREEN}       ✓ .mcp.json created at ${MCP_JSON}${NC}"
echo "       Default cluster: ${DEFAULT_CLUSTER_URL}"

# Step 5: Verify setup
echo -e "${YELLOW}[5/5] Verifying setup...${NC}"

# Check if server.py exists
if [ ! -f "${MCP_WRAPPER_DIR}/server.py" ]; then
    echo -e "${RED}       ✗ server.py not found at ${MCP_WRAPPER_DIR}/server.py${NC}"
    exit 1
fi
echo -e "${GREEN}       ✓ server.py found${NC}"

# Check if get-cookies.py exists and is executable
if [ ! -f "${MCP_WRAPPER_DIR}/get-cookies.py" ]; then
    echo -e "${RED}       ✗ get-cookies.py not found${NC}"
    exit 1
fi
if [ ! -x "${MCP_WRAPPER_DIR}/get-cookies.py" ]; then
    echo "       Making get-cookies.py executable..."
    chmod +x "${MCP_WRAPPER_DIR}/get-cookies.py"
fi
echo -e "${GREEN}       ✓ get-cookies.py found and executable${NC}"

# Check if clusters.py exists
if [ ! -f "${MCP_WRAPPER_DIR}/clusters.py" ]; then
    echo -e "${YELLOW}       ⚠ clusters.py not found (needed for multi-cluster support)${NC}"
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Setup Complete! 🎉                                            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo ""
echo -e "  ${YELLOW}1.${NC} Navigate to the MCP wrapper directory:"
echo -e "     ${GREEN}cd ${MCP_WRAPPER_DIR}${NC}"
echo ""
echo -e "  ${YELLOW}2.${NC} List available OpenSearch clusters:"
echo -e "     ${GREEN}./get-cookies.py --list${NC}"
echo ""
echo -e "  ${YELLOW}3.${NC} Fetch cookies for your desired cluster (opens browser for login):"
echo -e "     ${GREEN}./get-cookies.py prod-azure-us-cdp${NC}"
echo -e "     (This is one-time setup. MCP will auto-refresh cookies after this.)"
echo ""
echo -e "  ${YELLOW}4.${NC} Go back to the project root:"
echo -e "     ${GREEN}cd ${PROJECT_ROOT}${NC}"
echo ""
echo -e "  ${YELLOW}5.${NC} Start Claude Code:"
echo -e "     ${GREEN}claude${NC}"
echo ""
echo -e "  ${YELLOW}6.${NC} Try querying logs:"
echo -e "     ${BLUE}\"Search for errors in the last 10 minutes\"${NC}"
echo ""
