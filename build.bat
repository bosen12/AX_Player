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

:failed
echo.
echo BUILD FAILED -- dist\AXPlayer\AXPlayer.exe was not produced.
echo If AX Player is running, close it first: PyInstaller cannot overwrite locked files.
endlocal
exit /b 1
