@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Missing Python environment: .venv\Scripts\python.exe
    echo Please follow the installation instructions in README.md.
    popd
    pause
    exit /b 1
)
if "%~1"=="" (
    ".venv\Scripts\python.exe" -B run.py --config config.yaml --resume-gui
) else (
    ".venv\Scripts\python.exe" -B run.py --config config.yaml %*
)
set "runExit=%errorlevel%"
popd
if not "%runExit%"=="0" pause
exit /b %runExit%
