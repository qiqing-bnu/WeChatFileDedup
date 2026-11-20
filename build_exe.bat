@echo off
rem 一键打包：生成 dist\微信文件去重助手.exe（单文件、无控制台窗口）
cd /d "%~dp0"
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --name "微信文件去重助手" --collect-data sv_ttk main.py
if %errorlevel%==0 (
  echo.
  echo 打包完成：%~dp0dist\微信文件去重助手.exe
) else (
  echo.
  echo 打包失败，请确认已安装 PyInstaller：py -3.12 -m pip install pyinstaller
)
pause
