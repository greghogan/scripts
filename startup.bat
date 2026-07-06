@echo off
title Initializing WorkSpaces Environment
echo Restoring configurations...

:: After Workspaces client configuration format changes the json files must be copied with:
:: cmd /k xcopy "%USERPROFILE%\AppData\Local\Amazon Web Services\Amazon WorkSpaces\*.json" "U:\_sys\Redirection\Downloads\Amazon WorkSpaces\" /y /i

:: 1. Force the hidden directory to exist via script execution
md "%USERPROFILE%\AppData\Local\Amazon Web Services\Amazon WorkSpaces" >nul 2>&1

:: 2. Push the files directly into the restricted folder path
copy /y "U:\_sys\Redirection\Downloads\Amazon WorkSpaces\RegistrationList.json" "%USERPROFILE%\AppData\Local\Amazon Web Services\Amazon WorkSpaces\" >nul 2>&1
copy /y "U:\_sys\Redirection\Downloads\Amazon WorkSpaces\UserSettings.json" "%USERPROFILE%\AppData\Local\Amazon Web Services\Amazon WorkSpaces\" >nul 2>&1

:: 3. Wipe out the hardware acceleration registry key
reg add "HKCU\SOFTWARE\Amazon Web Services. LLC\Amazon WorkSpaces" /f >nul 2>&1
reg delete "HKCU\SOFTWARE\Amazon Web Services. LLC\Amazon WorkSpaces" /v EnableHwAcc /f >nul 2>&1

:: 4. Fire up your portable AutoHotkey environment
start "" "U:\_sys\Redirection\Downloads\AutoHotkey_2.0.26\AutoHotkey64.exe" "U:\_sys\Redirection\Downloads\swap.ahk"

echo Launching Amazon WorkSpaces
start "" "C:\Program Files\Amazon Web Services, Inc\Amazon WorkSpaces\workspaces.exe"

:: Launch Firefox pointing to the persistent drive directory
start "" "U:\_sys\Redirection\Downloads\phyrox-portable\phyrox-portable.exe"

exit
