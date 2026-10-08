#!/usr/bin/env bash
set -e

echo "=== Compass Test Suite Runner ==="

# 1. Check Docker availability
if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker is not installed or not in PATH."
    echo "Please install Docker Desktop for Mac:"
    echo "  brew install --cask docker"
    echo "  or download from https://www.docker.com/products/docker-desktop/"
    echo "Then launch Docker Desktop and re-run this script."
    exit 1
fi

# 2. Check if Docker daemon is running
if ! docker info &>/dev/null; then
    echo "Docker daemon is not running. Attempting to launch Docker Desktop..."
    open -a Docker 2>/dev/null || true
    echo "Waiting for Docker daemon to become responsive..."
    for i in {1..30}; do
        if docker info &>/dev/null; then
            break
        fi
        sleep 2
    done
    if ! docker info &>/dev/null; then
        echo "ERROR: Docker daemon failed to start. Please open Docker Desktop manually."
        exit 1
    fi
fi

# 3. Start pgvector test container if not already running
CONTAINER_NAME="compass-test-db"
if docker ps --filter "name=${CONTAINER_NAME}" --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Local test database container '${CONTAINER_NAME}' is already running."
elif docker ps -a --filter "name=${CONTAINER_NAME}" --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Starting existing stopped container '${CONTAINER_NAME}'..."
    docker start "${CONTAINER_NAME}"
else
    echo "Creating and starting new '${CONTAINER_NAME}' container on port 5433..."
    docker run -d --name "${CONTAINER_NAME}" \
        -e POSTGRES_USER=compass \
        -e POSTGRES_PASSWORD=compass \
        -e POSTGRES_DB=compass_test \
        -p 5433:5432 \
        pgvector/pgvector:pg16
fi

# 4. Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to accept connections on port 5433..."
for i in {1..20}; do
    if docker exec "${CONTAINER_NAME}" pg_isready -U compass -d compass_test &>/dev/null; then
        echo "PostgreSQL is ready!"
        break
    fi
    sleep 1
done

# 5. Set environment and run pytest
export TEST_DATABASE_URL="postgresql://compass:compass@localhost:5433/compass_test"
echo "TEST_DATABASE_URL set to: ${TEST_DATABASE_URL}"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "Running full test suite with 60s timeout..."
python3 -m pytest tests -q --timeout=60 -p no:cacheprovider "$@"
