import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from sqlalchemy.orm.exc import NoResultFound
from db_models import Usuario, Producto, Key, inicializar_db, get_session 
from dotenv import load_dotenv

# =================================================================
# 1. Configuración Inicial (Lectura de Variables de Entorno)
# =================================================================
load_dotenv()
TOKEN = os.getenv('BOT_MAIN_TOKEN') 
if not TOKEN:
    raise ValueError("Error: BOT_MAIN_TOKEN no encontrado. Verifica las variables de entorno.")

inicializar_db() 

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Estados del ConversationHandler ---
LOGIN_KEY, BUY_CATEGORY, BUY_PRODUCT = range(3)

# =================================================================
# 2. Funciones de Utilidad y Teclados
# =================================================================

def get_keyboard_main(is_logged_in):
    """Genera el teclado principal basado en el estado de login."""
    if is_logged_in:
        keyboard = [
            [KeyboardButton("🛒 Buy keys")],
            [KeyboardButton("👤 Account"), KeyboardButton("🚀 Log out")]
        ]
    else:
        keyboard = [
            [KeyboardButton("🔒 Login"), KeyboardButton("➕ Create Account")]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# =================================================================
# 3. Handlers de Inicio y Login
# =================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra el mensaje de bienvenida y el teclado de login/menu."""
    user_id_telegram = update.effective_user.id
    
    with get_session() as session_db:
        usuario = session_db.query(Usuario).filter_by(telegram_id=user_id_telegram).first() 

    if usuario:
        await update.message.reply_text(
            f"**Welcome back, {usuario.username}!**\nYour session is active. Use the menu below to manage your panel.",
            parse_mode='Markdown',
            reply_markup=get_keyboard_main(True)
        )
    else:
        await update.message.reply_text(
            "✨ **Welcome to the Control Panel**\nYou're almost in. Choose how you want to continue:",
            parse_mode='Markdown',
            reply_markup=get_keyboard_main(False)
        )
    return ConversationHandler.END

async def show_login_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pide al usuario que ingrese las credenciales."""
    await update.message.reply_text(
        "🔒 Enter the credentials provided by the administrator in the following format:\n\n"
        "**LOGIN PASSWORD**",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    return LOGIN_KEY

async def handle_login_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Procesa el login_key y la contraseña ingresada."""
    text = update.message.text
    
    if text == "🔒 Login":
        return await show_login_prompt(update, context) 

    parts = text.split()
    
    session_db = get_session()
    try:
        if len(parts) != 2:
            await update.message.reply_text(
                "❌ Format error. Please use: `LOGIN PASSWORD`",
                parse_mode='Markdown'
            )
            return LOGIN_KEY

        username, login_key_input = parts
        user_id_telegram = update.effective_user.id

        usuario = session_db.query(Usuario).filter_by(username=username, login_key=login_key_input).first()

        if usuario:
            if usuario.telegram_id is None:
                if session_db.query(Usuario).filter_by(telegram_id=user_id_telegram).first() is None:
                    usuario.telegram_id = user_id_telegram
                    session_db.commit()
                else:
                    await update.message.reply_text(
                        "❌ Tu ID de Telegram ya está en uso. Desloguea la cuenta anterior o contacta al administrador."
                    )
                    return LOGIN_KEY

            await update.message.reply_text(
                "✅ **You have been successfully authorized!**",
                parse_mode='Markdown',
                reply_markup=get_keyboard_main(True)
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                "❌ Login failed. Incorrect credentials or user not found. Try again, or type /start."
            )
            return LOGIN_KEY
    except Exception as e:
        logger.error(f"Error en handle_login_key: {e}")
        session_db.rollback()
        await update.message.reply_text("Ha ocurrido un error inesperado. Intenta de nuevo o usa /start.")
        return ConversationHandler.END
    finally:
        session_db.close()

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cierra la sesión del usuario desasociando el telegram_id."""
    user_id_telegram = update.effective_user.id
    is_logged_in = False
    
    with get_session() as session_db:
        usuario = session_db.query(Usuario).filter_by(telegram_id=user_id_telegram).first()
        if usuario:
            usuario.telegram_id = None
            session_db.commit()
            is_logged_in = True
    
    if is_logged_in:
        await update.message.reply_text(
            "🚪 You have logged out. Use /start to log back in.",
            reply_markup=get_keyboard_main(False)
        )
    else:
        await update.message.reply_text(
            "You are not currently logged in.",
            reply_markup=get_keyboard_main(False)
        )
        
async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la información de la cuenta."""
    user_id_telegram = update.effective_user.id
    
    with get_session() as session_db:
        usuario = session_db.query(Usuario).filter_by(telegram_id=user_id_telegram).first()
    
    if usuario:
        message = (
            f"👤 **Your account:**\n"
            f"• Login: **{usuario.username}**\n"
            f"• Saldo: **${usuario.saldo:.2f}**\n\n"
            f"// Historial de compras/recargas no implementado //"
        )
        
        await update.message.reply_text(
            message,
            parse_mode='Markdown',
            reply_markup=get_keyboard_main(True)
        )
    else:
        await update.message.reply_text("Please log in first using /start or the Login button.")
        
# =================================================================
# 4. Handlers de Compra (Buy keys) - Lógica de Inventario
# =================================================================

async def show_buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Muestra las categorías de productos."""
    user_id_telegram = update.effective_user.id
    
    with get_session() as session_db:
        usuario = session_db.query(Usuario).filter_by(telegram_id=user_id_telegram).first()
        
        if not usuario:
            await update.message.reply_text("❌ Please log in first.")
            return ConversationHandler.END

        categorias = session_db.query(Producto.categoria).distinct().all()
    
    keyboard_rows = []
    for cat_tuple in categorias:
        categoria = cat_tuple[0]
        if categoria: 
            keyboard_rows.append([KeyboardButton(categoria)])
            
    keyboard_rows.append([KeyboardButton("Back")]) 

    reply_markup = ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, one_time_keyboard=False)

    await update.message.reply_text(
        "Choose a category:",
        reply_markup=reply_markup
    )
    return BUY_CATEGORY

async def handle_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Maneja la selección de la categoría y muestra los productos y acciones."""
    category = update.message.text
    
    if category == "Back":
        return await start(update, context) 

    with get_session() as session_db:
        productos = session_db.query(Producto).filter_by(categoria=category).all()

    if not productos:
        await update.message.reply_text(f"❌ No products found in category: **{category}**", parse_mode='Markdown')
        return BUY_CATEGORY

    context.user_data['selected_category'] = category

    product_keys = []
    
    for producto in productos:
        with get_session() as s:
            stock = s.query(Key).filter(Key.producto_id == producto.id, Key.estado == 'available').count()
        
        button_text = f"{producto.nombre} - ${producto.precio:.2f} (Stock: {stock})"
        product_keys.append([KeyboardButton(button_text)])
            
    product_keys.append([KeyboardButton("Go back")])
    
    reply_markup = ReplyKeyboardMarkup(product_keys, resize_keyboard=True, one_time_keyboard=False)
    
    await update.message.reply_text(
        f"Choose a product in category {category}:",
        reply_markup=reply_markup
    )
    return BUY_PRODUCT


async def handle_final_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Procesa las selecciones de compra (Buy)."""
    text = update.message.text
    user_id_telegram = update.effective_user.id
    
    if text == "Go back":
        return await show_buy_menu(update, context)
    
    session_db = get_session()
    try:
        parts = text.rsplit(' - $', 1) 
        if len(parts) != 2:
            raise ValueError("Invalid product format.")
            
        product_name = parts[0].strip()
        price_str = parts[1].split('(')[0].strip() 
        price = float(price_str.replace('$', '').replace(',', '.'))
        
        usuario = session_db.query(Usuario).filter_by(telegram_id=user_id_telegram).first()
        producto = session_db.query(Producto).filter_by(nombre=product_name).first()

        if not usuario or not producto:
            await update.message.reply_text("❌ Error interno: Usuario o producto no encontrado.", reply_markup=get_keyboard_main(True))
            return ConversationHandler.END

        # 1. Verificar Saldo
        if usuario.saldo < price:
            await update.message.reply_text(f"❌ Saldo insuficiente. Tu saldo es: ${usuario.saldo:.2f}", reply_markup=update.message.reply_markup)
            return BUY_PRODUCT
            
        # 2. Buscar Key Disponible (Inventario)
        available_key = session_db.query(Key).filter_by(
            producto_id=producto.id, 
            estado='available'
        ).with_for_update().first() 

        if not available_key:
            await update.message.reply_text(f"❌ Producto agotado. No hay claves disponibles para {producto.nombre}.", reply_markup=update.message.reply_markup)
            return BUY_PRODUCT
            
        # 3. Realizar la Transacción
        usuario.saldo -= price
        available_key.estado = 'used'
        
        session_db.commit()

        # 4. Éxito y Entrega de Clave
        await update.message.reply_text(
            f"🎉 **Compra Exitosa de {producto.nombre}!**\n"
            f"Costo: **${price:.2f}**\n"
            f"Tu nuevo saldo: **${usuario.saldo:.2f}**\n\n"
            f"🔐 **Tu Key/Licencia:** `{available_key.licencia}`", 
            parse_mode='Markdown'
        )
        return await start(update, context)

    except ValueError:
        await update.message.reply_text("❌ Error al procesar la selección. Intenta de nuevo.", reply_markup=update.message.reply_markup)
        return BUY_PRODUCT
    except Exception as e:
        logger.error(f"Error en la transacción: {e}")
        session_db.rollback()
        await update.message.reply_text("❌ Ocurrió un error en la compra. Intenta de nuevo o usa /start.")
        return ConversationHandler.END
    finally:
        session_db.close()
            
    await update.message.reply_text("Opción no válida. Elige una de las opciones del menú.", reply_markup=update.message.reply_markup)
    return BUY_PRODUCT


# =================================================================
# 5. Función Principal de Ejecución
# =================================================================

def main() -> None:
    """Ejecuta el bot."""
    application = Application.builder().token(TOKEN).build()

    # Handlers de comandos y botones de texto simples
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(MessageHandler(filters.Regex("^👤 Account$"), show_account))
    application.add_handler(MessageHandler(filters.Regex("^🚀 Log out$"), logout))

    # Flujo de Login
    login_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔒 Login$"), show_login_prompt)],
        states={
            LOGIN_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_login_key)]
        },
        fallbacks=[CommandHandler("start", start)],
    )
    application.add_handler(login_conv_handler)
    
    # Flujo de Compra
    buy_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛒 Buy keys$"), show_buy_menu)],
        states={
            BUY_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_category_selection)],
            BUY_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_final_purchase)],
        },
        fallbacks=[CommandHandler("start", start)], 
        per_user=True,
    )
    application.add_handler(buy_conv_handler)
    
    # Manejar el botón "➕ Create Account"
    async def show_create_account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("To create an account, please ask the administrator for credentials.", reply_markup=get_keyboard_main(False))
    application.add_handler(MessageHandler(filters.Regex("^➕ Create Account$"), show_create_account_info))

    logger.info("El Bot de Telegram se está iniciando...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
