@echo off
setlocal
cd /d "%~dp0"
echo Pokemon Stock Monitor - Free Windows version
echo.
if not exist "worker.py" goto missingfiles
if not exist "watchlist.json" goto missingfiles
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto pythonlauncher
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 goto pythoncommand
echo Python 3.10 or newer was not found.
echo Install Python from https://www.python.org/downloads/windows/
echo Then reopen this launcher.
goto done
:pythonlauncher
py -3 worker.py
goto done
:pythoncommand
python worker.py
goto done
:missingfiles
echo Extract the entire downloaded ZIP before opening Start-Monitor.cmd.
:done
pause
endlocal
