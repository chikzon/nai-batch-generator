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
rem verify download integrity (SHA-256 pinned, python.org 3.12.8 embed amd64)
certutil -hashfile py.zip SHA256 | findstr /i "8d3f33be9eb810f23c102f08475af2854e50484b8e4e06275e937be61ce3d2fb" >nul
if errorlevel 1 goto badfile
mkdir python >nul 2>nul
tar -xf py.zip -C python
del py.zip >nul 2>nul
if not exist "python\python.exe" goto fail
powershell -NoProfile -Command "(Get-Content 'python\python312._pth') -replace '#import site','import site' | Set-Content 'python\python312._pth' -Encoding ascii"
rem get-pip.py pinned to a fixed commit (immutable URL) + SHA-256 check
curl -sL -o python\get-pip.py https://raw.githubusercontent.com/pypa/get-pip/5e84c8360eaf92009551b3eec69d734137f31cec/public/get-pip.py
certutil -hashfile python\get-pip.py SHA256 | findstr /i "a341e1a43e38001c551a1508a73ff23636a11970b61d901d9a1cad2a18f57055" >nul
if errorlevel 1 goto badfile
python\python.exe python\get-pip.py --no-warn-script-location --quiet
del python\get-pip.py >nul 2>nul
set "PY=python\python.exe"
echo  Python ready!
echo.

:deps
rem ?????? 2) libraries ??????
"%PY%" -c "from importlib.metadata import version as v; assert all(v(n)==x for n,x in (('requests','2.33.1'),('Pillow','12.2.0'),('certifi','2026.7.22'),('charset-normalizer','3.4.9'),('idna','3.18'),('urllib3','2.7.0')))" >nul 2>nul
if errorlevel 1 (
  echo Installing libraries...
  "%PY%" -m pip install -r requirements.txt --no-warn-script-location --quiet
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
exit /b

:badfile
echo.
echo  [!] Downloaded file hash mismatch - the download may be corrupted
echo      or tampered with. Nothing was installed.
echo      Delete py.zip and the 'python' folder, then retry.
echo      Or install Python manually: https://www.python.org/downloads/
del py.zip >nul 2>nul
del python\get-pip.py >nul 2>nul
echo.
pause
