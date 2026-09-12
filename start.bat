@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=.build\venv\Scripts\python.exe"
set "PYTHON_ARGS="
if exist "%PYTHON_EXE%" goto run

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
    goto run
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    goto run
)
echo No Python interpreter found. Install Python 3.10+ with project dependencies, or use the portable build.
pause
exit /b 1

:run
echo Starting the source-configured OCSJS service ...
"%PYTHON_EXE%" %PYTHON_ARGS% -u "%~dp0source_launcher.py" %*
set "LAUNCH_EXIT_CODE=%ERRORLEVEL%"
if not "%LAUNCH_EXIT_CODE%"=="0" (
    echo Service startup or execution failed. Exit code: %LAUNCH_EXIT_CODE%
)
pause
exit /b %LAUNCH_EXIT_CODE%
