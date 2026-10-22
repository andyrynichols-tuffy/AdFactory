@echo off
cd /d "%~dp0"
rem Already running in the background (it starts with Windows)? Then just open it.
netstat -ano | findstr /r /c:":8770 .*LISTENING" >nul && (start "" http://127.0.0.1:8770 & exit /b)
start "" http://127.0.0.1:8770
.venv\Scripts\python.exe -m adcut serve
