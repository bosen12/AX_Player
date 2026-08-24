@echo off
setlocal
cd /d "%~dp0"
py -3.10 -m pip install -r requirements.txt -q
py -3.10 -m ax_player %*
endlocal
