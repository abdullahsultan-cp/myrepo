@echo off
REM ===================================================================
REM  AKU news - resume SharePoint media URL resolution
REM
REM  Safe to close the laptop and double-click this again: the cache is
REM  written every 200 stories and already-fetched pages are skipped, so
REM  it always picks up where it stopped.
REM
REM  Order of work:
REM    1. the 20 uploaded sample stories   (already done, seconds)
REM    2. stories that HAVE media          (the ones worth reviewing)
REM    3. everything else
REM ===================================================================
setlocal

set "REPO=d:\AKU News\aku-data-transformation-pipeline-news-master"
set "PY=d:\AKU News\.venv\Scripts\python.exe"
REM -u keeps stdout unbuffered so progress shows live instead of in bursts
set "PYFLAGS=-u"
set "SCRIPT=%REPO%\scripts\migrate\resolve_media_urls.py"
set "WORKERS=10"

title AKU media resolver

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
echo   AKU news - resolving SharePoint media URLs
echo   repo    : %REPO%
echo   workers : %WORKERS%
echo ==========================================================
echo.
echo   Progress so far:
"%PY%" %PYFLAGS% "%REPO%\scripts\migrate\media_progress.py"
echo.

echo [1/3] uploaded sample stories ...
"%PY%" %PYFLAGS% "%SCRIPT%" --sample --workers %WORKERS%
if errorlevel 1 goto failed

echo.
echo [2/3] stories that have media ...
"%PY%" %PYFLAGS% "%SCRIPT%" --priority with-media --workers %WORKERS%
if errorlevel 1 goto failed

echo.
echo [3/3] the remaining stories ...
"%PY%" %PYFLAGS% "%SCRIPT%" --workers %WORKERS%
if errorlevel 1 goto failed

echo.
echo   Rebuilding the viewer index ...
"%PY%" %PYFLAGS% "%REPO%\scripts\migrate\build_viewer_index.py"

echo.
echo ==========================================================
echo   DONE. All media URLs resolved.
echo   Refresh the viewer at http://localhost:4000
echo ==========================================================
echo.
pause
exit /b 0

:failed
echo.
echo ==========================================================
echo   Stopped with an error. Nothing is lost - the cache is
echo   saved as it goes. Just run this file again.
echo ==========================================================
echo.
pause
exit /b 1
