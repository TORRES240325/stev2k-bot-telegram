import os
import logging
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from sqlalchemy.exc import IntegrityError
from db_models import Usuario, Producto, Key, get_session, inicializar_db 

# =================================================================
# 1. Configuración Inicial (Lectura de Variables de Entorno)
# =================================================================

load_dotenv() 
ADMIN_TOKEN_STR = os.getenv('BOT_ADMIN_TOKEN')
if not ADMIN_TOKEN_STR:
    raise ValueError("Error: BOT_ADMIN_TOKEN no encontrado. Verifica las variables de entorno.")

# Inicializa la base de datos (se hace después de cargar ENV)
inicializar_db() 

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Estados para ConversationHandlers ---
ADJUST_USER_ID, ADJUST_AMOUNT = range(2)
ADD_KEYS_PRODUCT, ADD_KEYS_LICENSES = range(2, 4)
CREATE_USER_NAME, CREATE_USER_LOGIN_KEY, CREATE_USER_SALDO, CREATE_USER_ADMIN = range(4, 8)
CREATE_PRODUCT_NAME, CREATE_PRODUCT_CATEGORY, CREATE_PRODUCT_PRICE, CREATE_PRODUCT_DESC = range(8, 12)
DELETE_PRODUCT_ID = 12


# =================================================================
# 2. Seguridad y Login de Administradores
# =================================================================

def check_admin(update: Update) -> bool:
    """Verifica si el usuario está logueado y tiene permisos de administrador."""
    if not update.effective_user:
        return False

    user_id_telegram = update.effective_user.id
    
    with get_session() as session_db:
        usuario = session_db.query(Usuario).filter_by(
            telegram_id=user_id_telegram, 
            es_admin=True
        ).first()

    if usuario:
        return True
    else:
        if update.message and update.message.text and not update.message.text.lower().startswith('/login'):
            update.message.reply_text(
                "❌ Acceso denegado. Debes iniciar sesión como administrador.\n"
                "Usa el formato: `/login [USERNAME] [CLAVE]`",
                parse_mode='Markdown'
            )
        return False

async def admin_login_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Permite a un usuario administrador loguearse en el bot."""
    
    text = update.message.text
    parts = text.split()
    
    if len(parts) != 3 or parts[0].lower() != '/login':
        await update.message.reply_text(
            "❌ Formato incorrecto. Uso: `/login USUARIO CLAVE`",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    username, login_key_input = parts[1], parts[2]
    user_id_telegram = update.effective_user.id

    session_db = get_session()
    try:
        usuario = session_db.query(Usuario).filter_by(
            username=username, 
            login_key=login_key_input, 
            es_admin=True
        ).first()

        if usuario:
            existing_user_with_id = session_db.query(Usuario).filter(
                Usuario.telegram_id == user_id_telegram, 
                Usuario.id != usuario.id
            ).first()
            
            if existing_user_with_id:
                await update.message.reply_text(
                    f"❌ Error: Tu ID de Telegram ya está asociada a la cuenta '{existing_user_with_id.username}'. Desloguea esa cuenta primero si es necesario."
                )
                return ConversationHandler.END

            usuario.telegram_id = user_id_telegram
            session_db.commit()

            await update.message.reply_text(
                f"✅ **¡Bienvenido, {usuario.username}!** Eres administrador.\n"
                "Usa /start para acceder al panel.",
                parse_mode='Markdown',
                reply_markup=get_admin_keyboard()
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                "❌ Login fallido. Credenciales incorrectas o el usuario no es administrador."
            )
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error en login de administrador: {e}")
        session_db.rollback()
        await update.message.reply_text("Ha ocurrido un error inesperado durante el login.")
        return ConversationHandler.END
    finally:
        session_db.close()

def get_admin_keyboard():
    """Genera el teclado principal de administración."""
    keyboard = [
        [KeyboardButton("💰 Ajustar Saldo"), KeyboardButton("👤 Listar Socios"), KeyboardButton("➕ Crear Socio")],
        [KeyboardButton("📦 Gestión Productos"), KeyboardButton("🔑 Añadir Keys"), KeyboardButton("🗑️ Eliminar Producto")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela el flujo actual y vuelve al menú principal."""
    if not check_admin(update): return ConversationHandler.END
    await update.message.reply_text("Operación cancelada. Volviendo al menú principal.", reply_markup=get_admin_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra el menú principal si es el administrador."""
    if not check_admin(update):
        return ConversationHandler.END 

    await update.message.reply_text(
        "👋 **Panel de Administración**\nElige una opción:",
        parse_mode='Markdown',
        reply_markup=get_admin_keyboard()
    )
    return ConversationHandler.END 


# =================================================================
# 3. Gestión de Socios
# =================================================================

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de usuarios y su saldo."""
    if not check_admin(update): return

    with get_session() as session_db:
        usuarios = session_db.query(Usuario).all() 

    message = "**Socios Registrados (ID | Username | Saldo):**\n\n"
    if not usuarios:
        message += "No hay socios registrados."
    else:
        for u in usuarios:
            admin_tag = " [ADMIN]" if u.es_admin else ""
            message += (
                f"ID: `{u.id}` | **{u.username}**{admin_tag}\n"
                f"   Saldo: `${u.saldo:.2f}`\n"
                f"   Key: `{u.login_key}`\n"
                "----------------------------------\n"
            )
    
    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=get_admin_keyboard())

# Flujo: ➕ Crear Socio
async def prompt_create_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not check_admin(update): return ConversationHandler.END
    await update.message.reply_text("Ingresa el **Username** para el nuevo socio:", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return CREATE_USER_NAME

async def get_create_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['temp_username'] = update.message.text.strip()
    await update.message.reply_text("Ingresa la **Login Key/Contraseña** para el socio:", parse_mode='Markdown')
    return CREATE_USER_LOGIN_KEY

async def get_create_user_login_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['temp_login_key'] = update.message.text.strip()
    await update.message.reply_text("Ingresa el **Saldo Inicial ($)** (ej: 50.00):", parse_mode='Markdown')
    return CREATE_USER_SALDO

async def get_create_user_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        saldo = float(update.message.text)
        context.user_data['temp_saldo'] = saldo
        
        keyboard = [[KeyboardButton("Sí"), KeyboardButton("No")]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text("¿Será este socio un administrador? (Sí/No):", reply_markup=reply_markup)
        return CREATE_USER_ADMIN
    except ValueError:
        await update.message.reply_text("❌ Saldo no válido. Ingresa un número (ej: 50.00).")
        return CREATE_USER_SALDO

async def finish_create_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    is_admin = update.message.text.lower() == 'sí'
    
    db_session = get_session()
    try:
        nuevo_usuario = Usuario(
            username=context.user_data['temp_username'],
            login_key=context.user_data['temp_login_key'],
            saldo=context.user_data['temp_saldo'],
            es_admin=is_admin
        )
        db_session.add(nuevo_usuario)
        db_session.commit()
        
        await update.message.reply_text(
            f"✅ Socio **{nuevo_usuario.username}** creado exitosamente:\n"
            f"Key: `{nuevo_usuario.login_key}` | Saldo: `${nuevo_usuario.saldo:.2f}`", 
            parse_mode='Markdown', 
            reply_markup=get_admin_keyboard()
        )
    except IntegrityError:
        db_session.rollback()
        await update.message.reply_text("❌ Error: Ya existe un socio con ese nombre de usuario. Usa /cancelar.", reply_markup=get_admin_keyboard())
    except Exception as e:
        logger.error(f"Error al crear socio: {e}")
        db_session.rollback()
        await update.message.reply_text("❌ Error al guardar el socio. Usa /cancelar.", reply_markup=get_admin_keyboard())
    finally:
        db_session.close()
    
    context.user_data.clear()
    return ConversationHandler.END

# Flujo: 💰 Ajustar Saldo
async def prompt_adjust_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not check_admin(update): return ConversationHandler.END
    await update.message.reply_text(
        "Ingresa el **ID** del Socio cuyo saldo quieres ajustar:\n"
        "O escribe /cancelar para volver.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return ADJUST_USER_ID

async def select_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id_input = update.message.text
    try:
        user_id = int(user_id_input)
        
        with get_session() as session_db:
            usuario = session_db.query(Usuario).filter_by(id=user_id).first()
            if not usuario:
                await update.message.reply_text("❌ ID de usuario no encontrado. Ingresa un ID válido.")
                return ADJUST_USER_ID

            context.user_data['user_to_adjust_id'] = user_id
            
            await update.message.reply_text(
                f"Socio: **{usuario.username}** (Saldo actual: `${usuario.saldo:.2f}`)\n"
                "Ingresa el **monto a ajustar** (Ej: `10.00` para agregar, `-5.50` para restar).",
                parse_mode='Markdown'
            )
            return ADJUST_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ Por favor, ingresa solo el número ID.")
        return ADJUST_USER_ID

async def adjust_saldo_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        monto = float(update.message.text)
        user_id = context.user_data.get('user_to_adjust_id')
        
        if not user_id: return await cancel_conversation(update, context)

        with get_session() as session_db:
            usuario = session_db.query(Usuario).filter_by(id=user_id).first()
            
            if usuario:
                usuario.saldo += monto
                session_db.commit()
                
                await update.message.reply_text(
                    f"✅ Saldo de **{usuario.username}** ajustado.\n"
                    f"Monto aplicado: **${monto:.2f}**\n"
                    f"Nuevo saldo: **${usuario.saldo:.2f}**",
                    parse_mode='Markdown',
                    reply_markup=get_admin_keyboard()
                )
    
    except ValueError:
        await update.message.reply_text("❌ Monto no válido. Ingresa un número (ej: 10.00 o -5.50).")
        return ADJUST_AMOUNT
    except Exception as e:
        logger.error(f"Error al ajustar saldo: {e}")
        await update.message.reply_text("❌ Error inesperado. Usa /start para volver.", reply_markup=get_admin_keyboard())

    context.user_data.clear()
    return ConversationHandler.END


# =================================================================
# 4. Gestión de Productos/Keys
# =================================================================

async def manage_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de productos y un menú de acciones."""
    if not check_admin(update): return

    with get_session() as session_db:
        productos = session_db.query(Producto).all()
        message = "**Catálogo de Productos (ID | Nombre | Stock):**\n\n"
        if not productos:
            message += "No hay productos registrados. Usa '➕ Crear Producto'."
        else:
            for p in productos:
                stock_available = session_db.query(Key).filter(Key.producto_id == p.id, Key.estado == 'available').count()
                message += (
                    f"ID: `{p.id}` | **{p.nombre}** (${p.precio:.2f})\n"
                    f"   Stock: **{stock_available}**\n"
                    "----------------------------------\n"
                )
    
    keyboard = [
        [KeyboardButton("➕ Crear Producto")],
        [KeyboardButton("🔑 Añadir Keys"), KeyboardButton("🗑️ Eliminar Producto")], 
        [KeyboardButton("Go back")] 
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    await update.message.reply_text(
        message + "\nElige una acción:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
# Flujo: ➕ Crear Producto
async def prompt_create_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not check_admin(update): return ConversationHandler.END
    await update.message.reply_text("Ingresa el **Nombre del Producto**:", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
    return CREATE_PRODUCT_NAME

async def get_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['temp_nombre'] = update.message.text
    await update.message.reply_text("Ingresa la **Categoría**:", parse_mode='Markdown')
    return CREATE_PRODUCT_CATEGORY

async def get_product_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['temp_categoria'] = update.message.text
    await update.message.reply_text("Ingresa el **Precio ($)** (ej: 10.00):", parse_mode='Markdown')
    return CREATE_PRODUCT_PRICE

async def get_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        price = float(update.message.text)
        context.user_data['temp_precio'] = price
        await update.message.reply_text("Ingresa la **Descripción** (opcional, /skip para omitir):", parse_mode='Markdown')
        return CREATE_PRODUCT_DESC
    except ValueError:
        await update.message.reply_text("❌ Precio no válido. Ingresa un número (ej: 10.00).")
        return CREATE_PRODUCT_PRICE

async def finish_create_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    desc = update.message.text if update.message.text and update.message.text != "/skip" else ""
    
    db_session = get_session()
    try:
        nuevo_producto = Producto(
            nombre=context.user_data['temp_nombre'],
            categoria=context.user_data['temp_categoria'],
            precio=context.user_data['temp_precio'],
            descripcion=desc
        )
        db_session.add(nuevo_producto)
        db_session.commit()
        
        await update.message.reply_text(
            f"✅ Producto **{nuevo_producto.nombre}** (ID: {nuevo_producto.id}) creado exitosamente.", 
            parse_mode='Markdown', 
            reply_markup=get_admin_keyboard()
        )
    except Exception as e:
        logger.error(f"Error al crear producto: {e}")
        db_session.rollback()
        await update.message.reply_text("❌ Error al guardar el producto en la DB. Usa /cancelar.", reply_markup=get_admin_keyboard())
    finally:
        db_session.close()
    
    context.user_data.clear()
    return ConversationHandler.END


# Flujo: 🗑️ Eliminar Producto
async def prompt_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not check_admin(update): return ConversationHandler.END
    
    await update.message.reply_text(
        "**ADVERTENCIA:** Esto eliminará el producto y TODAS las keys asociadas.\n"
        "Ingresa el **ID** del Producto a eliminar:",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return DELETE_PRODUCT_ID

async def process_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        product_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ ID no válido. Ingresa el número ID del producto.")
        return DELETE_PRODUCT_ID

    db_session = get_session()
    try:
        producto = db_session.query(Producto).filter_by(id=product_id).first()
        if not producto:
            await update.message.reply_text("❌ Producto no encontrado. Ingresa un ID válido.")
            return DELETE_PRODUCT_ID

        db_session.query(Key).filter_by(producto_id=product_id).delete()
        db_session.delete(producto)
        db_session.commit()

        await update.message.reply_text(
            f"✅ Producto **{producto.nombre}** y sus keys eliminados con éxito.",
            parse_mode='Markdown',
            reply_markup=get_admin_keyboard()
        )
    except Exception as e:
        logger.error(f"Error al eliminar producto: {e}")
        db_session.rollback()
        await update.message.reply_text("❌ Error inesperado al eliminar. Usa /cancelar.", reply_markup=get_admin_keyboard())
    finally:
        db_session.close()
    
    return ConversationHandler.END

# Flujo: 🔑 Añadir Keys
async def show_key_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not check_admin(update): return ConversationHandler.END
    
    with get_session() as session_db:
        productos = session_db.query(Producto).all() 

    if not productos:
        await update.message.reply_text("❌ No hay productos registrados. Usa '➕ Crear Producto'.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END
    
    keyboard_rows = []
    message = "**Productos disponibles para añadir Keys:**\n\n"
    for p in productos:
        with get_session() as s:
            stock = s.query(Key).filter(Key.producto_id == p.id, Key.estado == 'available').count()
        message += f"ID: `{p.id}` | **{p.nombre}** - Stock: {stock}\n"
        keyboard_rows.append([KeyboardButton(f"ID {p.id}: {p.nombre}")])

    keyboard_rows.append([KeyboardButton("Back to Admin Menu")])
    reply_markup = ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False)

    await update.message.reply_text(
        f"{message}\n\nSelecciona un producto o ingresa su ID para añadir Keys:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    return ADD_KEYS_PRODUCT

async def select_product_for_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if text == "Back to Admin Menu":
        return await start(update, context) 

    try:
        product_id = int(text.split(':')[0].replace('ID', '').strip().split()[0])
    except Exception:
        await update.message.reply_text("❌ Opción no válida. Ingresa el ID numérico del producto.")
        return ADD_KEYS_PRODUCT

    with get_session() as session_db:
        producto = session_db.query(Producto).filter_by(id=product_id).first()
        
    if not producto:
        await update.message.reply_text("❌ Producto no encontrado. Ingresa un ID válido.")
        return ADD_KEYS_PRODUCT
    
    context.user_data['product_to_add_keys_id'] = product_id
    context.user_data['product_to_add_keys_name'] = producto.nombre

    await update.message.reply_text(
        f"Producto seleccionado: **{producto.nombre}**\n\n"
        "Ahora, **pega las licencias/keys, una por línea**.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return ADD_KEYS_LICENSES

async def process_add_licenses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    licencias_raw = update.message.text
    product_id = context.user_data.get('product_to_add_keys_id')
    product_name = context.user_data.get('product_to_add_keys_name')
    
    if not product_id:
        return await cancel_conversation(update, context)

    if not licencias_raw:
        await update.message.reply_text("❌ No ingresaste ninguna key.")
        return ADD_KEYS_LICENSES

    keys_list = [lic.strip() for lic in licencias_raw.splitlines() if lic.strip()]
    if not keys_list:
        await update.message.reply_text("❌ No se detectó ninguna key válida. Intenta de nuevo.")
        return ADD_KEYS_LICENSES
        
    added_keys = 0
    db_session = get_session() 
    try:
        for lic in keys_list:
            existing_key = db_session.query(Key).filter_by(licencia=lic).first()
            if not existing_key:
                nueva_key = Key(producto_id=product_id, licencia=lic, estado='available')
                db_session.add(nueva_key)
                added_keys += 1
            else:
                logger.warning(f"Key duplicada omitida: {lic}")
        
        db_session.commit()

        await update.message.reply_text(
            f"✅ Keys agregadas a **{product_name}**:\n"
            f"Se agregaron **{added_keys}** nuevas licencias.",
            parse_mode='Markdown',
            reply_markup=get_admin_keyboard()
        )
    except Exception as e:
        logger.error(f"Error al añadir keys: {e}")
        db_session.rollback()
        await update.message.reply_text("❌ Error al guardar las keys. Usa /cancelar.", reply_markup=get_admin_keyboard())
    finally:
        db_session.close()
    
    context.user_data.clear()
    return ConversationHandler.END

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_admin(update) and update.message: 
        await update.message.reply_text("Opción no reconocida. Usa los botones o /start para volver al menú principal.", reply_markup=get_admin_keyboard())

# =================================================================
# 5. Función Principal de Ejecución del Bot Administrador
# =================================================================

def main_admin() -> None:
    """Ejecuta el bot administrador."""
    application = Application.builder().token(ADMIN_TOKEN_STR).build()
    
    # LOGIN DE ADMINISTRADORES (maneja el comando /login)
    application.add_handler(CommandHandler("login", admin_login_prompt))
    
    # Handlers para comandos y botones simples
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^Go back$") | filters.Regex("^Back to Admin Menu$"), start))
    application.add_handler(MessageHandler(filters.Regex("^👤 Listar Socios$"), list_users))
    application.add_handler(MessageHandler(filters.Regex("^📦 Gestión Productos$"), manage_products_menu))

    # Flujo de Ajuste de Saldo
    saldo_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💰 Ajustar Saldo$"), prompt_adjust_saldo)],
        states={
            ADJUST_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_user_id)],
            ADJUST_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adjust_saldo_final)],
        },
        fallbacks=[CommandHandler("cancelar", cancel_conversation), CommandHandler("start", start)],
        per_user=True
    )
    application.add_handler(saldo_conv_handler)
    
    # Flujo de Creación de Socio (Usuario)
    create_user_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Crear Socio$"), prompt_create_user_name)],
        states={
            CREATE_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_create_user_name)],
            CREATE_USER_LOGIN_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_create_user_login_key)],
            CREATE_USER_SALDO: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_create_user_saldo)],
            CREATE_USER_ADMIN: [MessageHandler(filters.Regex("^(Sí|No)$"), finish_create_user)],
        },
        fallbacks=[CommandHandler("cancelar", cancel_conversation), CommandHandler("start", start)],
        per_user=True
    )
    application.add_handler(create_user_conv_handler)

    # Flujo de Creación de Producto
    product_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Crear Producto$"), prompt_create_product)],
        states={
            CREATE_PRODUCT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_name)],
            CREATE_PRODUCT_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_category)],
            CREATE_PRODUCT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_product_price)],
            CREATE_PRODUCT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_create_product), CommandHandler("skip", finish_create_product)],
        },
        fallbacks=[CommandHandler("cancelar", cancel_conversation), CommandHandler("start", start)],
        per_user=True
    )
    application.add_handler(product_conv_handler)
    
    # Flujo de Eliminar Producto
    delete_product_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🗑️ Eliminar Producto$"), prompt_delete_product)],
        states={
            DELETE_PRODUCT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_delete_product)],
        },
        fallbacks=[CommandHandler("cancelar", cancel_conversation), CommandHandler("start", start)],
        per_user=True
    )
    application.add_handler(delete_product_conv_handler)
    
    # Flujo de Añadir Keys
    keys_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔑 Añadir Keys$"), show_key_management_menu)],
        states={
            ADD_KEYS_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_product_for_keys)],
            ADD_KEYS_LICENSES: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_licenses)],
        },
        fallbacks=[CommandHandler("cancelar", cancel_conversation), CommandHandler("start", start)],
        per_user=True
    )
    application.add_handler(keys_conv_handler)
    
    # Manejador general para texto no reconocido
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    logger.info("El Bot ADMINISTRADOR se está iniciando...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main_admin()
