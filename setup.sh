#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Meridian - Project Setup Script
# ═══════════════════════════════════════════════════════════════
# All dependencies are LOCAL - no global packages required
# Python: uses apps/api/.venv
# Node.js: uses local node_modules + .pnpm-store
# ═══════════════════════════════════════════════════════════════

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Meridian RAG System - Project Setup${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"

# ─────────────────────────────────────────────────────────────────
# Check prerequisites
# ─────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[1/6] Checking prerequisites...${NC}"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}✗ Node.js is not installed${NC}"
    echo "  Install from: https://nodejs.org/ (v18+ required)"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo -e "${RED}✗ Node.js 18+ required (found v$NODE_VERSION)${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Node.js $(node -v)"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 is not installed${NC}"
    echo "  Install from: https://python.org/ (v3.11+ required)"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_VERSION" -lt 11 ]; then
    echo -e "${RED}✗ Python 3.11+ required${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Python $(python3 --version | cut -d' ' -f2)"

# ─────────────────────────────────────────────────────────────────
# Test npm registry connectivity
# ─────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[2/6] Testing npm registry...${NC}"

# Test registry connectivity
if curl -s --max-time 5 https://registry.npmjs.org/ > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} npm registry is accessible"
    NPM_REGISTRY="https://registry.npmjs.org/"
else
    echo -e "  ${YELLOW}⚠${NC} npm registry blocked, trying mirror..."
    if curl -s --max-time 5 https://registry.npmmirror.com/ > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Using npmmirror.com"
        NPM_REGISTRY="https://registry.npmmirror.com/"
        echo "registry=$NPM_REGISTRY" > .npmrc
    else
        echo -e "${RED}✗ Cannot reach any npm registry${NC}"
        echo "  Please check your network/VPN settings"
        exit 1
    fi
fi

# ─────────────────────────────────────────────────────────────────
# Install pnpm locally (no global install needed)
# ─────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[3/6] Setting up pnpm...${NC}"

# Try corepack first (built into Node.js)
if command -v corepack &> /dev/null; then
    corepack enable 2>/dev/null || true
fi

# Check if pnpm is available
if command -v pnpm &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} pnpm $(pnpm -v)"
else
    echo "  Installing pnpm locally..."
    npm install pnpm --save-dev
    export PATH="./node_modules/.bin:$PATH"
    echo -e "  ${GREEN}✓${NC} pnpm installed locally"
fi

# ─────────────────────────────────────────────────────────────────
# Install frontend dependencies
# ─────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[4/6] Installing frontend dependencies...${NC}"

# Set registry if needed
if [ -n "$NPM_REGISTRY" ]; then
    export npm_config_registry="$NPM_REGISTRY"
fi

# Install with retry
MAX_RETRIES=3
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if pnpm install 2>&1; then
        echo -e "  ${GREEN}✓${NC} Frontend dependencies installed"
        break
    else
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
            echo -e "  ${YELLOW}⚠${NC} Retry $RETRY_COUNT/$MAX_RETRIES..."
            sleep 2
        else
            echo -e "${RED}✗ Failed to install frontend dependencies${NC}"
            echo "  Try running manually: pnpm install"
            exit 1
        fi
    fi
done

# ─────────────────────────────────────────────────────────────────
# Setup Python virtual environment
# ─────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[5/6] Setting up Python environment...${NC}"

cd apps/api

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate and install
echo "  Installing Python dependencies..."
source .venv/bin/activate
pip install --upgrade pip -q
pip install -e ".[dev]" -q

echo -e "  ${GREEN}✓${NC} Python environment ready"

cd ../..

# ─────────────────────────────────────────────────────────────────
# Setup environment file
# ─────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[6/6] Environment configuration...${NC}"

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "  ${GREEN}✓${NC} Created .env from .env.example"
    echo -e "  ${YELLOW}⚠ Edit .env with your API keys${NC}"
else
    echo -e "  ${GREEN}✓${NC} .env exists"
fi

# ─────────────────────────────────────────────────────────────────
# Done!
# ─────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ Setup complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Edit .env with your API keys"
echo "  2. Run: make dev"
echo ""
echo -e "${BLUE}Commands:${NC}"
echo "  make dev       Start frontend + backend"
echo "  make help      Show all commands"
echo ""
