@echo off
cd /d "d:\AKU News\aku-data-transformation-pipeline-news-master"
echo ==== started %DATE% %TIME% ==== >> "d:\AKU News\aku-data-transformation-pipeline-news-master\data\migrate\overnight.log"
"d:\AKU News\.venv\Scripts\python.exe" -u "d:\AKU News\aku-data-transformation-pipeline-news-master\scripts\migrate\run_media_all.py" --workers 6 >> "d:\AKU News\aku-data-transformation-pipeline-news-master\data\migrate\overnight.log" 2>&1
echo ==== finished %DATE% %TIME% exit=%ERRORLEVEL% ==== >> "d:\AKU News\aku-data-transformation-pipeline-news-master\data\migrate\overnight.log"
