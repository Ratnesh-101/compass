#!/usr/bin/env bash
set -e

echo "======================================================================"
echo "  🧭 Compass — One-Command Turnkey Launcher (Linux / macOS)"
echo "  Your personal AI that remembers every hackathon, repo, and deadline."
echo "======================================================================"
echo ""

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 is not installed or not in PATH. Please install Python 3.11+."
    exit 1
fi

# 2. Check Node & npm
if ! command -v npm &>/dev/null; then
    echo "[ERROR] npm is not installed or not in PATH. Please install Node.js 18+."
    exit 1
fi

# 3. Configure .env if missing
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "[INFO] Creating .env from .env.example..."
        cp .env.example .env
        echo "[INFO] Created .env file. Please edit it with your NEBIUS_API_KEY if needed."
    fi
fi

# 4. Install backend dependencies
echo "[INFO] Verifying backend dependencies..."
pip3 install -q -r backend/requirements.txt

# 5. Install frontend dependencies
if [ ! -d "frontend/node_modules" ]; then
    echo "[INFO] Installing frontend dependencies (one-time setup)..."
    (cd frontend && npm install)
fi

echo ""
echo "======================================================================"
echo "  🚀 Starting Compass Services:"
echo "     • Backend API:      http://localhost:8000"
echo "     • Interactive Docs: http://localhost:8000/docs"
echo "     • Web Dashboard:    http://localhost:5173"
echo "======================================================================"
echo ""

cleanup() {
    echo ""
    echo "[INFO] Shutting down Compass services..."
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

python3 -m uvicorn backend.main:app --port 8000 --reload &
BACKEND_PID=$!

(cd frontend && npm run dev) &
FRONTEND_PID=$!

# Attempt to open browser
sleep 3
if command -v xdg-open &>/dev/null; then
    xdg-open http://localhost:5173 &>/dev/null || true
elif command -v open &>/dev/null; then
    open http://localhost:5173 &>/dev/null || true
fi

wait
