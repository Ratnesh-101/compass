# Compass — Windows PowerShell Test Runner
param (
    [switch]$Local = $false,
    [switch]$Live = $false
)

$ErrorActionPreference = "Stop"

if ($Local) {
    Write-Host "Starting local test database container via docker compose..." -ForegroundColor Cyan
    docker compose -f docker-compose.test.yml up -d
    Write-Host "Waiting for database readiness..." -ForegroundColor Cyan
    docker compose -f docker-compose.test.yml exec -T test-postgres sh -c 'until pg_isready -U compass -d compass_test; do sleep 1; done'
    
    $env:TEST_DATABASE_URL = "postgresql://compass:compass@localhost:5432/compass_test"
    Write-Host "Running tests against local database..." -ForegroundColor Green
    python -m pytest tests/ -v --timeout=60 -m "not live"
} elseif ($Live) {
    Write-Host "Running live integration tests..." -ForegroundColor Yellow
    python -m pytest tests/ -v --timeout=90 -m "live"
} else {
    Write-Host "Running standard test suite against configured TEST_DATABASE_URL..." -ForegroundColor Green
    python -m pytest tests/ -v --timeout=60 -m "not live"
}
