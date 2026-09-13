@echo off
rem Baut das TW1 Minimap Tool als eine Exe (PyInstaller, onefile, ohne Konsole).
rem Ergebnis: %~dp0dist\TW1 Minimap Tool.exe - danach auf den Desktop kopieren.
setlocal
pushd "%~dp0"
"C:\Users\marco\AppData\Local\Programs\Python\Python313\python.exe" -m PyInstaller --noconfirm --onefile --windowed ^
  --name "TW1 Minimap Tool" --icon "%~dp0minimap_tool.ico" --add-data "%~dp0minimap_tool.ico;." ^
  --hidden-import packer ^
  --hidden-import wdio --hidden-import theme --hidden-import wd_metadaten ^
  --distpath "%~dp0dist" --workpath "%TEMP%\minimap_tool_build" --specpath "%TEMP%\minimap_tool_build" minimap_tool.py
set rc=%errorlevel%
popd
if %rc% neq 0 (echo BUILD FEHLGESCHLAGEN & exit /b %rc%)
echo BUILD OK: %~dp0dist\TW1 Minimap Tool.exe
