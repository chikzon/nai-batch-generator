@echo off
cd /d "%~dp0"
setlocal

rem ?????? 1) find python: system -> local portable -> auto-download ??????
set "PY=python"
where python >nul 2>nul
if %errorlevel%==0 goto deps

if exist "python\python.exe" (
  set "PY=python\python.exe"
  goto deps
)

echo.
echo  Python not found. Downloading portable Python (15MB, 1-2 min)...
echo  (installed only inside this folder)
echo.
curl -L -o py.zip https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip
if not exist py.zip goto fail
mkdir python >nul 2>nul
tar -xf py.zip -C python
del py.zip >nul 2>nul
if not exist "python\python.exe" goto fail
powershell -NoProfile -Command "(Get-Content 'python\python312._pth') -replace '#import site','import site' | Set-Content 'python\python312._pth' -Encoding ascii"
curl -sL -o python\get-pip.py https://bootstrap.pypa.io/get-pip.py
python\python.exe python\get-pip.py --no-warn-script-location --quiet
del python\get-pip.py >nul 2>nul
set "PY=python\python.exe"
echo  Python ready!
echo.

:deps
rem ?????? 2) libraries ??????
"%PY%" -c "import requests, PIL" >nul 2>nul
if errorlevel 1 (
  echo Installing libraries...
  "%PY%" -m pip install requests pillow --no-warn-script-location --quiet
)

rem ?????? 3) run (UTF-8 console for Korean output) ??????
chcp 65001 >nul
rem Pass through arguments, e.g.  run.bat --profile second
rem   (second account in the same folder: settings/state/output are kept apart)
"%PY%" start.py %*
echo.
pause
exit /b

:fail
echo.
echo  [!] Auto-install failed. Check your internet connection and retry.
echo      Or install Python manually: https://www.python.org/downloads/
echo      (check "Add Python to PATH" during install)
echo.
pause
