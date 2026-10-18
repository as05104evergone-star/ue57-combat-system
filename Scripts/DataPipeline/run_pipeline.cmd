@echo off
rem ==========================================================================
rem  DataPipeline one-click entry
rem    xlsx (numeric design table)  ->  csv/json  ->  UE DataTable (headless)
rem
rem  Usage:   run_pipeline.cmd [run|struct|verify|selftest]
rem    run       (default) export csv/json, create/refresh 9 DT_*, verify readback
rem    struct    only create the empty S_GameParam row struct (then add 4 members by hand)
rem    verify    export csv/json, then verify readback only (no asset written)
rem    selftest  prove the import chain on an existing struct; touches no business asset
rem
rem  Env:     UE_CMD=<path to UnrealEditor-Cmd.exe>   (default E:\UE_5.7\...)
rem           DT_NOPAUSE=1                            (do not pause at the end)
rem ==========================================================================
setlocal
set "HERE=%~dp0"
for %%I in ("%HERE%..\..") do set "PROJ_ROOT=%%~fI"

set "UPROJ="
for %%F in ("%PROJ_ROOT%\*.uproject") do if exist "%%~fF" set "UPROJ=%%~fF"
if not defined UPROJ (
  echo [X] no .uproject found under "%PROJ_ROOT%"
  goto :end
)

if not defined UE_CMD set "UE_CMD=E:\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
if not exist "%UE_CMD%" (
  echo [X] UnrealEditor-Cmd.exe not found: "%UE_CMD%"
  echo     set UE_CMD=^<full path to UnrealEditor-Cmd.exe^> and retry
  goto :end
)

set "DT_MODE=%~1"
if "%DT_MODE%"=="" set "DT_MODE=run"

echo [i] project : %UPROJ%
echo [i] ue cmd  : %UE_CMD%
echo [i] mode    : %DT_MODE%
echo.

if /I "%DT_MODE%"=="selftest" goto :noexport
if /I "%DT_MODE%"=="struct"   goto :noexport

echo [1/2] export xlsx -^> csv/json ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%export_datatables.ps1"
if errorlevel 1 goto :exportfail
goto :import

:noexport
echo [1/2] skipped (mode=%DT_MODE%)

:import
echo.
rem ---- preflight: an open editor keeps the OLD rows in memory and overwrites ----
rem (2026-10-18: headless import saved DT_Combat with 23 rows at 20:55:00, then the
rem  open editor wrote its stale 21-row copy back at 20:56:05 -> "xlsx has the new
rem  rows but UE doesn't". Close the editor before importing.)
if /I not "%DT_MODE%"=="run" goto :importgo
if defined DT_ALLOW_OPEN_EDITOR goto :importgo
tasklist /FI "IMAGENAME eq UnrealEditor.exe" 2>nul | find /I "UnrealEditor.exe" >nul
if errorlevel 1 goto :importgo
echo [W] UnrealEditor.exe is still running.
echo     The headless import will write the 9 DT_* assets to disk, but the open
echo     editor still holds the OLD rows in memory and will overwrite the new
echo     file the next time it saves those assets.
echo     Close the editor first (answer "No" if it asks to save DataTables),
echo     then run this pipeline again.
echo     To skip this check: set DT_ALLOW_OPEN_EDITOR=1
echo.
choice /C NY /N /M "Continue anyway? [Y=continue / N=abort] "
if errorlevel 2 goto :abort
:importgo
echo [2/2] headless import into DataTable ...
"%UE_CMD%" "%UPROJ%" -run=PythonScript -Script="%HERE%import_datatables.py" -unattended -nosplash -nop4 -nullrhi -EnablePlugins=PythonScriptPlugin -stdout
echo.
echo [i] report : %HERE%_import_report.json
echo [i] note   : UE returns exit code 1 whenever it logged ANY error, so trust the
echo              report JSON, not the exit code.
goto :end

:abort
echo [X] aborted: close UnrealEditor.exe first, then re-run this pipeline.

:exportfail
echo [X] export step failed - see the output above.

:end
if not defined DT_NOPAUSE pause
endlocal
