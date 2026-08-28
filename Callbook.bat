@echo off
setlocal
cd /d "%~dp0"
where pythonw.exe >nul 2>&1
if %errorlevel%==0 (
    start "N1MM Callbook" pythonw.exe n1mm_callbook.py %*
) else (
    start "N1MM Callbook" python.exe n1mm_callbook.py %*
)
