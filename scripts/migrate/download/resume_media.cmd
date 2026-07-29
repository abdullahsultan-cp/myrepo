@echo off
REM ===================================================================
REM  AKU news - resolve, download and map every asset
REM
REM  Double-click any time. Safe to close the laptop mid-run: every
REM  stage is resumable, so this always continues where it stopped.
REM
REM    1  resolve URLs for stories that have media
REM    2  resolve URLs for everything else
REM    3  download every resolved file to assets\News\media\
REM    4  export the asset map + failure report
REM    5  rebuild the viewer index
REM
REM  Runs as ONE process behind a lock file. Two resolver passes share
REM  media_urls.json and the slower one rewrites the whole file from its
REM  own memory - that silently reverted corrected entries once already.
REM ===================================================================
setlocal

set "REPO=d:\AKU News\aku-data-transformation-pipeline-news-master"
set "PY=d:\AKU News\.venv\Scripts\python.exe"
set "WORKERS=6"

title AKU media - resolve, download, map

if not exist "%PY%" (
  echo.
  echo   ERROR: python not found at
  echo     %PY%
  echo.
  pause
  exit /b 1
)

cd /d "%REPO%" || (echo ERROR: cannot cd to %REPO% & pause & exit /b 1)

echo.
echo ==========================================================
echo   AKU news - media resolve, download and map
echo   repo    : %REPO%
echo   workers : %WORKERS%
echo ==========================================================

REM -u keeps output unbuffered so progress shows live
"%PY%" -u "%REPO%\scripts\migrate\download\run_media_all.py" --workers %WORKERS%
if errorlevel 1 goto failed

echo.
echo ==========================================================
echo   DONE.
echo   Files : assets\News\media\
echo   Map   : data\migrate\asset_map.csv
echo   Viewer: http://localhost:4000
echo ==========================================================
echo.
pause
exit /b 0

:failed
echo.
echo ==========================================================
echo   Stopped with an error. Nothing is lost - every stage saves
echo   as it goes. Run this file again to continue.
echo.
echo   If it says another run is already going and you know it is
echo   dead, delete:  data\migrate\.media.lock
echo ==========================================================
echo.
pause
exit /b 1