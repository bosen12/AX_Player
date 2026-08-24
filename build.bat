@echo off
setlocal
cd /d "%~dp0"

rem Usage:  build.bat            -> onedir  (default, faster startup)
rem         build.bat onefile    -> single portable AXPlayer.exe
set "AXPLAYER_ONEFILE="
if /i "%~1"=="onefile" set "AXPLAYER_ONEFILE=1"

py -3 -m pip install -r requirements.txt pyinstaller -q
py -3 -m PyInstaller --noconfirm --clean AXPlayer.spec
if errorlevel 1 (
  python -m pip install -r requirements.txt pyinstaller -q
  python -m PyInstaller --noconfirm --clean AXPlayer.spec
  if errorlevel 1 goto :failed
)

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
