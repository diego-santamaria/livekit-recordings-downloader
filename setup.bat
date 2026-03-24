@echo off
echo ============================================================
echo  LiveKit Recordings Downloader - First-time Setup
echo ============================================================
echo.

:: Create virtual environment if it doesn't exist
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

:: Activate and install dependencies
call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt

echo Installing Playwright browser...
playwright install chromium

echo.
echo ============================================================
echo  Setup complete!
echo  Copy .env.example to .env and fill in your values, then
echo  run:  download.bat --login-only   (to save your session once)
echo  then: download.bat                (or download.bat --project-id p_xxxxxxx)
echo ============================================================
pause
