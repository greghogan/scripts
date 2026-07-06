@echo off
setlocal

title Initializing WorkSpaces Environment
echo Restoring configurations...

set "REDIR_ROOT=U:\_sys\Redirection\Downloads"
set "AWS_CFG_DIR=%USERPROFILE%\AppData\Local\Amazon Web Services\Amazon WorkSpaces"
set "AWS_BACKUP_DIR=%REDIR_ROOT%\Amazon WorkSpaces"
set "AHK_EXE=%REDIR_ROOT%\AutoHotkey_2.0.26\AutoHotkey64.exe"
set "AHK_SCRIPT=%REDIR_ROOT%\swap.ahk"
set "WORKSPACES_EXE=C:\Program Files\Amazon Web Services, Inc\Amazon WorkSpaces\workspaces.exe"
set "BROWSER_EXE=%REDIR_ROOT%\phyrox-portable\phyrox-portable.exe"
set "LOG_FILE=%TEMP%\startup.log"
set "REDIR_WAIT_SECONDS=20"
set /a REDIR_WAIT_COUNT=0

call :log INFO "Startup sequence initialized."

:: Wait briefly for redirected storage to appear during Windows logon.
:wait_for_redir
if exist "%REDIR_ROOT%\" goto redir_ready
if %REDIR_WAIT_COUNT% geq %REDIR_WAIT_SECONDS% (
    call :log ERROR "Redirected downloads path is unavailable: %REDIR_ROOT%"
    exit /b 1
)
set /a REDIR_WAIT_COUNT+=1
timeout /t 1 /nobreak >nul
goto wait_for_redir

:redir_ready
call :log INFO "Redirected downloads path is available."

:: Ensure the local WorkSpaces config directory exists before restoring files.
if not exist "%AWS_CFG_DIR%\" mkdir "%AWS_CFG_DIR%"
if errorlevel 1 (
    call :log ERROR "Failed to create WorkSpaces config directory: %AWS_CFG_DIR%"
    exit /b 1
)

:: Restore the persisted WorkSpaces client files that survive profile resets.
for %%F in (
    "RegistrationList.json"
    "UserSettings.json"
) do (
    call :copy_required_file "%AWS_BACKUP_DIR%\%%~F" "%AWS_CFG_DIR%\%%~F"
    if errorlevel 1 exit /b 1
)

:: Remove the hardware acceleration override so the client uses its default behavior.
reg add "HKCU\SOFTWARE\Amazon Web Services. LLC\Amazon WorkSpaces" /f >nul
if errorlevel 1 (
    call :log ERROR "Failed to ensure the Amazon WorkSpaces registry key exists."
    exit /b 1
)

reg delete "HKCU\SOFTWARE\Amazon Web Services. LLC\Amazon WorkSpaces" /v EnableHwAcc /f >nul 2>&1
if errorlevel 1 (
    call :log WARN "Registry value EnableHwAcc was not removed. It may already be absent."
)

:: Start the local input remapping script if the portable AutoHotkey runtime is available.
call :launch_optional_with_arg "%AHK_EXE%" "%AHK_SCRIPT%" "AutoHotkey remapping"

call :log INFO "Launching Amazon WorkSpaces."
call :launch_required "%WORKSPACES_EXE%" "Amazon WorkSpaces"
if errorlevel 1 exit /b 1

:: Start the portable browser from the redirected drive when available.
call :launch_optional "%BROWSER_EXE%" "Portable browser"

call :log INFO "Startup sequence completed."
exit /b 0

:copy_required_file
if not exist "%~1" (
    call :log ERROR "Required file not found: %~1"
    exit /b 1
)

copy /y "%~1" "%~2" >nul
if errorlevel 1 (
    call :log ERROR "Failed to copy %~1 to %~2"
    exit /b 1
)

call :log INFO "Restored file: %~nx1"
exit /b 0

:launch_required
if not exist "%~1" (
    call :log ERROR "%~2 executable not found: %~1"
    exit /b 1
)
start "" "%~1"
call :log INFO "%~2 launched."
exit /b 0

:launch_optional
if not exist "%~1" (
    call :log WARN "%~2 executable not found: %~1"
    exit /b 0
)
start "" "%~1"
call :log INFO "%~2 launched."
exit /b 0

:launch_optional_with_arg
if not exist "%~1" (
    call :log WARN "%~3 executable not found: %~1"
    exit /b 0
)
if not exist "%~2" (
    call :log WARN "%~3 argument file not found: %~2"
    exit /b 0
)
start "" "%~1" "%~2"
call :log INFO "%~3 launched."
exit /b 0

:log
echo [%date% %time%] %~1: %~2
>>"%LOG_FILE%" echo [%date% %time%] %~1: %~2
exit /b 0
