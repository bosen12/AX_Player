@echo off
setlocal
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt pyinstaller -q
py -3 -m PyInstaller --noconfirm --clean AXPlayer.spec
if errorlevel 1 (
  python -m pip install -r requirements.txt pyinstaller -q
  python -m PyInstaller --noconfirm --clean AXPlayer.spec
  if errorlevel 1 goto :failed
)
if not exist dist\AXPlayer.exe goto :failed
copy /Y dist\AXPlayer.exe AXPlayer.exe >nul
if errorlevel 1 (
  echo.
  echo Build succeeded but AXPlayer.exe is locked -- close the running app, then copy
  echo dist\AXPlayer.exe over it manually.
  endlocal
  exit /b 1
)
echo.
echo Built: dist\AXPlayer.exe
endlocal
exit /b 0

:failed
echo.
echo BUILD FAILED -- dist\AXPlayer.exe was not produced.
echo If AX Player is running, close it first: PyInstaller cannot overwrite a locked exe.
endlocal
exit /b 1
