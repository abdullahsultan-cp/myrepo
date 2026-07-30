@echo off
REM ===================================================================
REM  AKU NEWS -> STORYBLOK : the full migration
REM
REM  Double-click any time. Safe to close the laptop or press Ctrl-C:
REM  every stage records what it finished, so running this again
REM  continues from where it stopped and never creates anything twice.
REM
REM    1  assets   ~3,850 files -> Storyblok, folders mirror the tree
REM    2  stories  3,606 stories -> each into its own folder
REM    3  read back from the space
REM    4  reports + backup
REM
REM  Progress:  data\migrate\migration.log
REM  Reports :  data\migrate\reports\
REM ===================================================================
setlocal

set "REPO=d:\AKU News\aku-data-transformation-pipeline-news-master"
set "PY=d:\AKU News\.venv\Scripts\python.exe"

title AKU news migration

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
echo   AKU NEWS MIGRATION
echo   repo : %REPO%
echo   log  : data\migrate\migration.log
echo.
echo   Expect 2-4 hours. Ctrl-C once stops it cleanly;
echo   run this file again to continue.
echo ==========================================================
echo.

REM -u keeps output unbuffered so progress appears live
"%PY%" -u "%REPO%\scripts\migrate\upload\run_migration.py" %*
if errorlevel 1 goto failed

echo.
echo ==========================================================
echo   DONE.
echo   Review sheet : data\migrate\reports\links.csv
echo   Per story    : data\migrate\reports\stories.csv
echo   Per folder   : data\migrate\reports\folders.csv
echo   Summary      : data\migrate\reports\summary.json
echo ==========================================================
echo.
pause
exit /b 0

:failed
echo.
echo ==========================================================
echo   Stopped. Nothing is lost - every finished story and asset
echo   is recorded. Run this file again to continue where it
echo   stopped; it will not duplicate anything.
echo.
echo   If it says another migration is already running and you
echo   know it is dead, delete:
echo     data\migrate\.migration.lock
echo ==========================================================
echo.
pause
exit /b 1
