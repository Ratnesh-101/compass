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

:: 6. Launch Backend in a new terminal window
start "Compass Backend (FastAPI)" cmd /k "python -m uvicorn backend.main:app --port 8000 --reload"

:: 7. Launch Frontend in a new terminal window
start "Compass Frontend (Vite)" cmd /k "cd frontend && npm run dev"

:: 8. Wait 3 seconds and open browser
timeout /t 3 /nobreak >nul
start http://localhost:5173

echo Compass is now running! Keep the terminal windows open while using the app.
echo Press any key in this window to close this launcher.
pause >nul
