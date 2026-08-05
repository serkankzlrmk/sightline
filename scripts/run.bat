@echo off
REM =============================================================================
REM Sightline — Run script (Windows)
REM =============================================================================
REM Starts Sightline in Docker mode (recommended).
REM
REM Usage:
REM   scripts\run.bat              # Docker mode (production-like)
REM   scripts\run.bat --build      # Rebuild Docker image
REM   scripts\run.bat --local      # Local Python mode (no Docker)
REM   scripts\run.bat --desktop    # Desktop mode (DESKTOP_MODE=true, no Firebase)
REM =============================================================================

setlocal

set MODE=%1
if "%MODE%"=="" set MODE=docker

REM Check .env exists
if not exist ".env" (
    echo [WARN] No .env file found. Copying from .env.example...
    copy .env.example .env
    echo   Edit .env with your API keys, then re-run this script.
    echo   Required: OPENROUTER_API_KEY, RELIEFWEB_APPNAME
    exit /b 1
)

if "%MODE%"=="--local" goto local
if "%MODE%"=="local" goto local
if "%MODE%"=="--desktop" goto desktop
if "%MODE%"=="desktop" goto desktop
if "%MODE%"=="--build" goto build
if "%MODE%"=="build" goto build

:docker
echo [INFO] Starting Sightline in Docker...
docker compose up -d
echo [OK] Sightline is running at http://localhost:5001
echo   Logs: docker compose logs -f sightline
echo   Stop: docker compose down
goto end

:build
echo [INFO] Building and starting Sightline in Docker...
docker compose up -d --build
echo [OK] Sightline is running at http://localhost:5001
docker compose logs -f sightline
goto end

:local
echo [INFO] Starting Sightline in LOCAL mode (Python)...
if not exist ".venv" (
    echo   Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
    .venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
)
set SERVER_HOST=127.0.0.1
set SERVER_PORT=5001
.venv\Scripts\python server.py
goto end

:desktop
echo [INFO] Starting Sightline in DESKTOP mode (local, no Firebase)...
if not exist ".venv" (
    echo   Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
    .venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
)
set SERVER_HOST=127.0.0.1
set DESKTOP_MODE=true
set SERVER_DEBUG=true
.venv\Scripts\python server.py
goto end

:end
endlocal
