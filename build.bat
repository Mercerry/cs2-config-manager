@echo off
:: CS2 Config Manager – Windows build script
:: Produces a single-file executable: dist\CS2ConfigManager.exe

echo ============================================================
echo  CS2 Config Manager – Build Script
echo ============================================================

:: Ensure PyInstaller is installed
pip install -r requirements.txt --quiet
if ERRORLEVEL 1 (
    echo [ERROR] Failed to install requirements.
    exit /b 1
)

:: Clean previous build artefacts
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

:: Build the single-file executable
pyinstaller build.spec --noconfirm
if ERRORLEVEL 1 (
    echo [ERROR] PyInstaller build failed.
    exit /b 1
)

echo.
echo ============================================================
echo  Build complete!  Output: dist\CS2ConfigManager.exe
echo ============================================================
