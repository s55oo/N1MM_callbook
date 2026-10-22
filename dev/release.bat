@echo off
rem Usage (from the repo root): dev\release.bat 1.12
rem        release.bat 1.12 -Download   (re-download the exe from the Actions run first)
set VER=%1
if "%VER%"=="" set VER=1.12
shift
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release.ps1" -Version %VER% %1 %2 %3
pause
