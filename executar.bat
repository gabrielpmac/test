@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale o Python 3.10+ em https://www.python.org/downloads/ ^(marque "Add Python to PATH"^).
  pause
  exit /b 1
)
echo Iniciando MOE Thrones Assistente em http://127.0.0.1:8765  ^(feche esta janela para sair^)
python -m app.server
pause
