@echo off
setlocal enabledelayedexpansion

echo ======================================================================
echo   🧭 Compass — One-Command Turnkey Launcher (Windows)
echo   Your personal AI that remembers every hackathon, repo, and deadline.
echo ======================================================================
echo.

:: 1. Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH. Please install Python 3.11+.
    pause
    exit /b 1
)

:: 2. Check Node & npm
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] npm is not installed or not in PATH. Please install Node.js 18+.
    pause
    exit /b 1
)

:: 3. Configure .env if missing
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] Creating .env from .env.example...
        copy ".env.example" ".env" >nul
        echo [INFO] Created .env file. Please edit it with your NEBIUS_API_KEY if needed.
    ) else (
        echo [WARNING] No .env or .env.example found. Backend will use fallback defaults.
    )
)

:: 4. Install backend dependencies if needed
echo [INFO] Verifying backend dependencies...
pip install -q -r backend/requirements.txt

:: 5. Install frontend dependencies if needed
if not exist "frontend\node_modules" (
    echo [INFO] Installing frontend dependencies (one-time setup)...
    cd frontend && npm install && cd ..
)

echo.
echo ======================================================================
echo   🚀 Starting Compass Services:
echo      • Backend API:      http://localhost:8000
echo      • Interactive Docs: http://localhost:8000/docs
echo      • Web Dashboard:    http://localhost:5173
echo ======================================================================
echo.

:: 6. Launch Backend if not already running
netstat -ano | findstr :8000 | findstr LISTENING >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Backend is already running on http://localhost:8000.
) else (
    echo [INFO] Starting Backend server on http://localhost:8000...
    start "Compass Backend (FastAPI)" cmd /k "python -m uvicorn backend.main:app --port 8000 --reload"
)

:: 7. Launch Frontend if not already running
netstat -ano | findstr :5173 | findstr LISTENING >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Frontend is already running on http://localhost:5173.
) else (
    echo [INFO] Starting Frontend dev server on http://localhost:5173...
    start "Compass Frontend (Vite)" cmd /k "cd frontend && npm run dev"
)

:: 8. Wait for Backend health check to pass before launching browser
echo [INFO] Waiting for backend to be live and healthy...
for /l %%i in (1, 1, 20) do (
    powershell -Command "try { (Invoke-WebRequest -Uri 'http://localhost:8000/health' -UseBasicParsing -TimeoutSec 1).StatusCode } catch { exit 1 }" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [INFO] Backend is live and connected!
        goto :open_browser
    )
    timeout /t 1 /nobreak >nul
)

:open_browser
echo [INFO] Opening Web Dashboard at http://localhost:5173...
timeout /t 1 /nobreak >nul
start http://localhost:5173

echo.
echo ======================================================================
echo   Compass is now live! Keep terminal windows open while using the app.
echo   Press any key in this window to exit this launcher.
echo ======================================================================
pause >nul
