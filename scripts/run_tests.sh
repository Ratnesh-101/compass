#!/usr/bin/env bash
set -eo pipefail

# Compass — POSIX Test Runner for macOS/Linux
# Starts docker compose test DB if docker is running, or falls back to TEST_DATABASE_URL.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# Activate virtual environment if present
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d ".venv312" ]; then
    source .venv312/bin/activate
fi

# Load .env if present
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs -0) 2>/dev/null || true
fi

# Check for Docker
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "Starting local test database container via docker compose..."
    docker compose -f docker-compose.test.yml up -d
    echo "Waiting for test database readiness..."
    docker compose -f docker-compose.test.yml exec -T test-postgres sh -c 'until pg_isready -U compass -d compass_test; do sleep 1; done'
    export TEST_DATABASE_URL="postgresql://compass:compass@localhost:5432/compass_test"
else
    echo "Docker is not running or not installed. Using configured TEST_DATABASE_URL..."
    if [ -z "${TEST_DATABASE_URL:-}" ]; then
        if [ -n "${DATABASE_URL:-}" ]; then
            echo "Warning: TEST_DATABASE_URL not set, falling back to DATABASE_URL"
            export TEST_DATABASE_URL="${DATABASE_URL}"
        else
            echo "Error: Neither Docker nor TEST_DATABASE_URL is available."
            exit 1
        fi
    fi
fi

echo "Running pytest with timeout=60..."
python -m pytest tests/ "$@" --timeout=60
