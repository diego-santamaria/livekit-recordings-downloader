@echo off
echo ============================================================
echo  LiveKit Recordings Downloader
echo ============================================================
echo.

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Pass all arguments through to the script
:: Examples:
::   download.bat                            (auto-detects session, logs in if needed)
::   download.bat --login-only               (login and save session, no downloading)
::   download.bat --project-id p_xxxxxxx     (specific project)
python auto_download_recordings.py %*

echo.
pause
