import os
import logging
import sys
from dotenv import load_dotenv
import subprocess

# --- Configuración ---
load_dotenv(os.path.join(os.getcwd(), '.env'))
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- Verificación de Token ---
ADMIN_TOKEN = os.getenv('BOT_ADMIN_TOKEN')
if not ADMIN_TOKEN:
    print("------------------------------------------------------------------")
    print("🚨 ERROR FATAL: BOT_ADMIN_TOKEN no encontrado.")
    sys.exit(1)

print(f"Cargando BOT ADMINISTRADOR (Token: {ADMIN_TOKEN[:5]}...{ADMIN_TOKEN[-5:]})")

try:
    subprocess.run([sys.executable, 'bot_admin.py'])

except KeyboardInterrupt:
    print("\nDeteniendo BOT ADMINISTRADOR por el usuario.")
except Exception as e:
    logging.error(f"Error inesperado durante la ejecución del Bot Administrador: {e}")