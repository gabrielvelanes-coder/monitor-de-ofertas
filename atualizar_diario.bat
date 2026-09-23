@echo off
cd /d "%~dp0"
echo ==== %date% %time% ==== >> atualizacao_diaria.log
.venv\Scripts\python.exe manage.py importar_do_banco todas --dias 7 >> atualizacao_diaria.log 2>&1
