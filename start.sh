#!/bin/bash

echo "========================================="
echo "  INICIANDO SERVICIOS DE TELEGRAM BOT    "
echo "========================================="

# 1. Inicia el Bot Principal en segundo plano usando nohup (persistencia)
echo "-> Iniciando Bot Principal (bot_main.py) con nohup..."
nohup python bot_main.py > /dev/null 2>&1 &

# 2. Inicia el Bot Administrador en segundo plano usando nohup (persistencia)
echo "-> Iniciando Bot Administrador (bot_admin.py) con nohup..."
nohup python bot_admin.py > /dev/null 2>&1 &

# 3. CRÍTICO: Mantener el contenedor VIVO
# Este comando corre indefinidamente y asegura que Railway no cierre el servicio.
echo "-> Proceso de persistencia activado (tail -f /dev/null)..."
tail -f /dev/null
