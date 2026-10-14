@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
rem Use the installed Python 3.14 runtime, or an explicitly supplied Python.
if not defined PPTX_VIDEO_PYTHON set "PPTX_VIDEO_PYTHON=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not exist "%PPTX_VIDEO_PYTHON%" set "PPTX_VIDEO_PYTHON=python"
set "PPTX_VIDEO_BUILD_DEBUG=0"
if /I "%~1"=="debug" set "PPTX_VIDEO_BUILD_DEBUG=1"
echo Building PPT-to-Video with the checked-in spec...
"%PPTX_VIDEO_PYTHON%" -m PyInstaller --noconfirm --distpath dist --workpath build "PPT转视频工具.spec"
if errorlevel 1 (
  echo Build failed. Existing source and spec files have been preserved.
  exit /b 1
)
copy /y "使用说明.txt" "dist\使用说明.txt" >nul
copy /y "UI_THEMES_REPORT.md" "dist\UI_THEMES_REPORT.md" >nul
echo.
echo Built: %CD%\dist\PPT转视频工具.exe
echo BGM and UI themes are included. Existing .env is preserved.
endlocal
