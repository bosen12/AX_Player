@echo off
setlocal
cd /d "%~dp0"

rem Usage:  build.bat            -> onedir  (default, faster startup)
rem         build.bat onefile    -> single portable AXPlayer.exe
rem
rem Pinned to 3.14 on purpose. This used to say `py -3`, which resolves to
rem whatever the py launcher's default happens to be -- 3.14 today, and every
rem release so far was built with it. If that default ever moves, `py -3`
rem would ship a different interpreter with no sign that anything changed:
rem the same commit built on 3.10 produces a visibly smaller, different
rem bundle. Failing loudly when 3.14 is absent is the point.
set "AXPLAYER_ONEFILE="
if /i "%~1"=="onefile" set "AXPLAYER_ONEFILE=1"

py -3.14 -m pip install -r requirements.txt pyinstaller -q
if errorlevel 1 goto :failed
py -3.14 -m PyInstaller --noconfirm --clean AXPlayer.spec
if errorlevel 1 goto :failed

if "%AXPLAYER_ONEFILE%"=="1" goto :onefile

if not exist dist\AXPlayer\AXPlayer.exe goto :failed
robocopy dist\AXPlayer AXPlayer /MIR /NFL /NDL /NJH /NJS
if errorlevel 8 (
  echo.
  echo Build succeeded but AXPlayer\AXPlayer.exe is locked -- close the running app,
  echo then copy the dist\AXPlayer folder over it manually.
  endlocal
  exit /b 1
)
echo.
echo Built: dist\AXPlayer\AXPlayer.exe  (copied to AXPlayer\AXPlayer.exe)
endlocal
exit /b 0

:onefile
if not exist dist\AXPlayer.exe goto :failed
copy /Y dist\AXPlayer.exe AXPlayer-onefile.exe >nul
if errorlevel 1 (
  echo.
  echo Build succeeded but AXPlayer-onefile.exe is locked -- close the running app,
  echo then copy dist\AXPlayer.exe over it manually.
  endlocal
  exit /b 1
)
echo.
echo Built: dist\AXPlayer.exe  (copied to AXPlayer-onefile.exe)
endlocal
exit /b 0

:failed
echo.
echo BUILD FAILED -- no exe was produced.
echo If AX Player is running, close it first: PyInstaller cannot overwrite locked files.
endlocal
exit /b 1
