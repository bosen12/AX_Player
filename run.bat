@echo off
setlocal
cd /d "%~dp0"
py -3.10 -m pip install -r requirements.txt -q
if not exist "mpv-runtime\libmpv-2.dll" if not exist "C:\mpv\libmpv-2.dll" py -3.10 setup_mpv.py
py -3.10 -m ax_player %*
endlocal
