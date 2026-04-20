@echo off
setlocal

REM Config
set DB_PORT=5433
set DB_USER=openclaw
set DB_PASS=openclaw
set DB_NAME=openclaw_mako
set PYTHONIOENCODING=utf-8

REM Auto-select available API port (try 8000, 8001, 8080, 9000, 9001)
set API_PORT=
for %%P in (8000 8001 8080 9000 9001) do (
    if not defined API_PORT (
        netstat -ano 2>nul | findstr "LISTENING" | findstr ":%%P " >nul
        if errorlevel 1 (
            set API_PORT=%%P
        ) else (
            echo [warn] Port %%P is occupied, trying next...
        )
    )
)
if not defined API_PORT (
    echo ERROR: No free port found in range 8000/8001/8080/9000/9001.
    pause
    exit /b 1
)
echo [info] Using API port %API_PORT%.

set DATABASE_URL=postgresql+asyncpg://%DB_USER%:%DB_PASS%@localhost:%DB_PORT%/%DB_NAME%
set API_BASE_URL=http://localhost:%API_PORT%

REM Step 1: PostgreSQL via Docker
echo [1/3] Starting PostgreSQL (Docker)...
docker compose up -d db >nul 2>&1
if errorlevel 1 (
    echo ERROR: docker compose failed. Is Docker Desktop running?
    pause
    exit /b 1
)

echo     Waiting for DB...
set /a i=0
:wait_db
docker exec openclaw_mako_db pg_isready -U %DB_USER% -d %DB_NAME% >nul 2>&1
if not errorlevel 1 goto db_ready
set /a i+=1
if %i% geq 20 (
    echo ERROR: DB did not become ready in 20s.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait_db
:db_ready
echo     DB ready on localhost:%DB_PORT%.

REM Step 2: API server
echo [2/3] Starting API on port %API_PORT%...
start "OpenClaw API" cmd /k "cd /d %~dp0 && set DATABASE_URL=%DATABASE_URL%&& set PYTHONIOENCODING=utf-8&& python -m uvicorn main:app --host 127.0.0.1 --port %API_PORT% --no-access-log"

echo     Waiting for API...
set /a j=0
:wait_api
timeout /t 1 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://localhost:%API_PORT%/health 2>nul | findstr "200" >nul
if not errorlevel 1 goto api_ready
set /a j+=1
if %j% geq 20 (
    echo ERROR: API did not start in 20s.
    pause
    exit /b 1
)
goto wait_api
:api_ready
echo     API ready at http://localhost:%API_PORT%/docs

REM Step 3: Review UI
echo [3/3] Launching Review UI...
start "OpenClaw UI" cmd /c "cd /d %~dp0 && set API_BASE_URL=%API_BASE_URL%&& set PYTHONIOENCODING=utf-8&& python ui_launcher.py"

echo.
echo  =========================================================
echo   OpenClaw Mako YouTube Pipeline is running
echo   API:   http://localhost:%API_PORT%
echo   Docs:  http://localhost:%API_PORT%/docs
echo   DB:    localhost:%DB_PORT%  db=%DB_NAME%
echo  =========================================================
echo.
pause
endlocal
