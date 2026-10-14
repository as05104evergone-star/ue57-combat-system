@echo off
chcp 65001 >nul
setlocal

REM ===================================================================
REM  KBaseUE / one-shot verification
REM
REM  Usage (no editor required):
REM    check.cmd                      check the default interface
REM    check.cmd /Game/Path/BPI_X     check any blueprint interface
REM    check.cmd --facts "keyword"    query the distilled engine facts
REM    check.cmd --test               run the regression test
REM
REM  Why a .cmd wrapper: passing Chinese JSON arguments to python.exe from
REM  PowerShell gets mangled by quoting rules (observed: "unrecognized
REM  arguments"). Going through %* in cmd avoids that entirely.
REM
REM  NOTE: comments in this file are ASCII on purpose. cmd.exe parses a
REM  batch file in the ANSI codepage *before* `chcp 65001` takes effect,
REM  so non-ASCII comments get executed as commands and the script dies
REM  before it starts. Keep this file ASCII.
REM ===================================================================

set "SCRIPT_DIR=%~dp0"
set "PYTHON_DIR=%SCRIPT_DIR%Content\Python"
set "DEFAULT_ASSET=/Game/Combo_Demo/BP/Interfaces/BPI_CombatComponent"

REM ---- locate the Python bundled with UE (no usable system python here)
set "PY="
for %%D in (
    "E:\UE_5.7"
    "D:\UE_5.7"
    "C:\Program Files\Epic Games\UE_5.7"
    "E:\UE_5.6\UE_5.6"
) do (
    if not defined PY (
        if exist "%%~D\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" (
            set "PY=%%~D\Engine\Binaries\ThirdParty\Python3\Win64\python.exe"
        )
    )
)

if not defined PY (
    echo [ERROR] UE's bundled Python not found. Add your engine path to the list above.
    exit /b 1
)
set PYTHONIOENCODING=utf-8
REM Unbuffered stdout. Python block-buffers when its output is redirected to a
REM file or a pipe, so a 45-minute crawl looks completely silent until it ends
REM -- and "silent" is indistinguishable from "hung". Cost of this line: zero.
set PYTHONUNBUFFERED=1

REM ---------------------------------------------------------------- branches
REM  NOTE: `%*` expands to the ORIGINAL argument list and is NOT affected by
REM  `shift`. Forwarding with `%*` after a shift therefore leaks the flag into
REM  the Python script ("unrecognized arguments: --index"). Use positional
REM  args (%2..%9) instead.
if "%~1"=="--facts" (
    if "%~2"=="" (
        "%PY%" "%PYTHON_DIR%\kbase.py"
    ) else (
        "%PY%" "%PYTHON_DIR%\kbase.py" %2 %3 %4 %5 %6 %7 %8 %9
    )
    exit /b %errorlevel%
)

if "%~1"=="--test" (
    "%PY%" "%PYTHON_DIR%\test_iface_check.py"
    exit /b %errorlevel%
)

REM ---- engine source index (whole UE 5.7 source tree, local SQLite)
if "%~1"=="--index" (
    if "%~2"=="" (
        "%PY%" "%PYTHON_DIR%\engine_query.py" status
    ) else (
        "%PY%" "%PYTHON_DIR%\engine_query.py" %2 %3 %4 %5 %6 %7 %8 %9
    )
    exit /b %errorlevel%
)

if "%~1"=="--index-build" (
    "%PY%" "%PYTHON_DIR%\engine_index.py" --build
    exit /b %errorlevel%
)

REM ---- Epic official documentation mirror (dev.epicgames.com, UE 5.7)
REM   --docs priority   Plan A in one shot: enumerate -> crawl -> index -> retry
REM   Safe to re-run: every step resumes from where it stopped.
if "%~1"=="--docs" (
    if "%~2"=="" (
        "%PY%" "%PYTHON_DIR%\docs_mirror.py" status
    ) else (
        "%PY%" "%PYTHON_DIR%\docs_mirror.py" %2 %3 %4 %5 %6 %7 %8 %9
    )
    exit /b %errorlevel%
)

REM ---- verify the toolchain itself (index + knowledge + checker + docs)
if "%~1"=="--selftest" (
    "%PY%" "%PYTHON_DIR%\selftest.py"
    exit /b %errorlevel%
)

if "%~1"=="" (
    "%PY%" "%PYTHON_DIR%\iface_check.py" "%DEFAULT_ASSET%"
) else (
    "%PY%" "%PYTHON_DIR%\iface_check.py" %*
)
exit /b %errorlevel%
