import os
import logging
import sys
from dotenv import load_dotenv
import subprocess

# --- Configuración ---
load_dotenv(os.path.join(os.getcwd(), '.env'))
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- Verificación de Token ---
TOKEN = os.getenv('BOT_MAIN_TOKEN')
if not TOKEN:
    print("------------------------------------------------------------------")
    print("🚨 ERROR FATAL: BOT_MAIN_TOKEN no encontrado.")
    sys.exit(1)

print(f"Cargando BOT PRINCIPAL (Token: {TOKEN[:5]}...{TOKEN[-5:]})")

try:
    subprocess.run([sys.executable, 'bot_main.py'])

except KeyboardInterrupt:
    print("\nDeteniendo BOT PRINCIPAL por el usuario.")
except Exception as e:
    logging.error(f"Error inesperado durante la ejecución del Bot Principal: {e}")
