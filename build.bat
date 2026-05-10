@echo off
setlocal EnableDelayedExpansion

REM PDF Diff Tool - PyInstaller build script for Windows 11
REM Usage: Double-click or run from Developer Command Prompt

cd /d "%~dp0"

echo ============================================================
echo PDF Diff Tool - Build Script
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+.
    pause
    exit /b 1
)

REM Install / upgrade dependencies
echo [1/4] Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)
echo Done.
echo.

REM Locate tkinterdnd2 package directory
echo [2/4] Locating tkinterdnd2...
for /f "delims=" %%i in ('python -c "import tkinterdnd2, os; print(os.path.dirname(tkinterdnd2.__file__))"') do set TKDND_PATH=%%i
if "!TKDND_PATH!"=="" (
    echo [ERROR] Could not locate tkinterdnd2. Is it installed?
    pause
    exit /b 1
)
echo Found: !TKDND_PATH!
echo.

REM Clean previous build
echo [3/4] Cleaning previous build artifacts...
if exist build   rmdir /s /q build
if exist dist    rmdir /s /q dist
if exist PDFDiff.spec del /q PDFDiff.spec
echo Done.
echo.

REM Build single-file EXE
echo [4/4] Building PDFDiff.exe (this may take a few minutes)...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "PDFDiff" ^
    --add-data "!TKDND_PATH!;tkinterdnd2" ^
    --hidden-import tkinterdnd2 ^
    --hidden-import fitz ^
    --collect-all PyMuPDF ^
    pdf_diff.py

echo.
if exist dist\PDFDiff.exe (
    echo ============================================================
    echo  BUILD SUCCESSFUL
    echo  Output: dist\PDFDiff.exe
    echo ============================================================
) else (
    echo ============================================================
    echo  BUILD FAILED - Check the output above for errors.
    echo ============================================================
    pause
    exit /b 1
)

echo.
pause
endlocal
