@echo off
setlocal
cd /d "%~dp0"
echo Pokemon Center - Free visible-browser monitor
if not exist "pokemon_center_browser.py" goto missingfiles
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 goto pylauncher
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 goto pythonlauncher
echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
goto done
:pylauncher
py -3 -c "import playwright" >nul 2>&1
if not errorlevel 1 goto pyrun
py -3 -m pip install playwright
if errorlevel 1 goto installfailed
:pyrun
py -3 pokemon_center_browser.py
goto done
:pythonlauncher
python -c "import playwright" >nul 2>&1
if not errorlevel 1 goto pythonrun
python -m pip install playwright
if errorlevel 1 goto installfailed
:pythonrun
python pokemon_center_browser.py
goto done
:installfailed
echo Could not install the free Playwright dependency. Check the error above.
goto done
:missingfiles
echo Extract the entire ZIP before running this launcher.
:done
pause
endlocal
