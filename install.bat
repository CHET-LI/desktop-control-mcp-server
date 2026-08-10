@echo off
setlocal
title Desktop Control MCP Server - Installer

echo ==================================================
echo   Desktop Control MCP Server - One-click Installer
echo ==================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Please install Python 3.12+ from https://www.python.org/downloads/
    echo and make sure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)

echo [1/2] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/2] Installing dependencies: mcp + pyautogui...
call ".venv\Scripts\activate.bat"
pip install --quiet mcp==1.29.0 pyautogui
if errorlevel 1 (
    echo [ERROR] pip install failed. Check your network and retry.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo   Installation complete!
echo ==================================================
echo.
echo   Start the server with:
echo       .venv\Scripts\python.exe server.py
echo.
echo   NOTE: OCR semantic clicking (click_text / ocr_all /
echo   find_text) is OPTIONAL and needs a one-time extra
echo   install (downloads a deep-learning model, ~100MB):
echo       .venv\Scripts\pip install easyocr
echo.
echo   Without easyocr, mouse/keyboard tools still work.
echo.
pause
