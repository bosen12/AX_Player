@echo off
setlocal
cd /d "%~dp0"
py -3.10 -m pip install -r requirements.txt -q
rem default_mpv_root() prefers mpv-runtime over C:\mpv whenever mpv-runtime
rem has libmpv-2.dll -- so setup is needed either when neither has mpv at
rem all, or when mpv-runtime is the one that's going to be used but is
rem still missing yt-dlp.exe (e.g. an install fetched before yt-dlp support
rem was added).
set NEED_SETUP=0
if not exist "C:\mpv\libmpv-2.dll" if not exist "mpv-runtime\libmpv-2.dll" set NEED_SETUP=1
if exist "mpv-runtime\libmpv-2.dll" if not exist "mpv-runtime\yt-dlp.exe" set NEED_SETUP=1
if %NEED_SETUP%==1 py -3.10 setup_mpv.py
py -3.10 -m ax_player %*
endlocal
