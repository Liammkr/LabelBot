import os
import logging
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import database as db

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "wsboxing").lstrip("@")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

# Crypto wallet addresses — set in .env
WALLETS = {
    "BTC": os.getenv("WALLET_BTC", ""),
    "ETH": os.getenv("WALLET_ETH", ""),
    "USDT_TRC20": os.getenv("WALLET_USDT_TRC20", ""),
}

LABEL_COST = 18.0  # USD

# Conversation states
(
    TOPUP_CHOOSE_CRYPTO,
    TOPUP_ENTER_AMOUNT,
    TOPUP_ENTER_TXHASH,
    LABEL_WAIT_IMAGE,
) = range(4)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤  Submit Label  ($18)", callback_data="menu_submit")],
        [InlineKeyboardButton("💰  Top Up Balance", callback_data="menu_topup")],
        [InlineKeyboardButton("💳  My Balance", callback_data="menu_balance")],
    ])


def crypto_keyboard():
    buttons = []
    for symbol, address in WALLETS.items():
        if address:
            buttons.append([InlineKeyboardButton(symbol, callback_data=f"crypto_{symbol}")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


async def notify_admin(app: Application, text: str, photo_file_id: str | None = None):
    if not ADMIN_CHAT_ID:
        logger.warning("ADMIN_CHAT_ID not set in environment — cannot notify admin.")
        return
    try:
        if photo_file_id:
            await app.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=photo_file_id, caption=text, parse_mode="Markdown")
        else:
            await app.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.get_or_create_user(user.id, user.username or "", user.first_name or "")

    balance = await db.get_balance(user.id)
    await update.message.reply_text(
        f"👋 Welcome, {user.first_name}!\n\n"
        f"💳 Balance: *${balance:.2f}*\n\n"
        "What would you like to do?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ─────────────────────────────────────────────
# Balance callback
# ─────────────────────────────────────────────

async def balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    balance = await db.get_balance(query.from_user.id)
    await query.edit_message_text(
        f"💳 Your current balance: *${balance:.2f}*\n\n"
        "What would you like to do?",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ─────────────────────────────────────────────
# Top-Up Flow
# ─────────────────────────────────────────────

async def topup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    available = [s for s, a in WALLETS.items() if a]
    if not available:
        await query.edit_message_text(
            "⚠️ No crypto wallets configured yet. Please contact the admin.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "💰 *Top Up — Choose Crypto*\n\n"
        "Select which cryptocurrency you'd like to pay with:",
        parse_mode="Markdown",
        reply_markup=crypto_keyboard(),
    )
    return TOPUP_CHOOSE_CRYPTO


async def topup_choose_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    symbol = query.data.replace("crypto_", "")
    context.user_data["topup_crypto"] = symbol
    context.user_data["topup_address"] = WALLETS[symbol]

    await query.edit_message_text(
        f"💰 *Top Up — Enter Amount*\n\n"
        f"You selected: *{symbol}*\n\n"
        "How much USD do you want to deposit? (e.g. `50`)\n"
        "_You'll send the equivalent in crypto._",
        parse_mode="Markdown",
    )
    return TOPUP_ENTER_AMOUNT


async def topup_enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace("$", "")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid amount (e.g. `50`).", parse_mode="Markdown")
        return TOPUP_ENTER_AMOUNT

    context.user_data["topup_amount"] = amount
    symbol = context.user_data["topup_crypto"]
    address = context.user_data["topup_address"]

    await update.message.reply_text(
        f"📤 *Send Payment*\n\n"
        f"Amount: *${amount:.2f} USD* in *{symbol}*\n\n"
        f"Send to this address:\n`{address}`\n\n"
        f"After sending, paste your *transaction hash (TX ID)* here so we can verify it.",
        parse_mode="Markdown",
    )
    return TOPUP_ENTER_TXHASH


async def topup_enter_txhash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_hash = update.message.text.strip()
    if len(tx_hash) < 10:
        await update.message.reply_text("❌ That doesn't look like a valid TX hash. Please try again.")
        return TOPUP_ENTER_TXHASH

    user = update.effective_user
    amount = context.user_data["topup_amount"]
    symbol = context.user_data["topup_crypto"]

    deposit_id = await db.create_deposit(user.id, amount, symbol, tx_hash)

    await update.message.reply_text(
        f"✅ *Deposit Request Submitted!*\n\n"
        f"Deposit ID: `#{deposit_id}`\n"
        f"Amount: *${amount:.2f}*\n"
        f"Crypto: *{symbol}*\n"
        f"TX Hash: `{tx_hash}`\n\n"
        "Your balance will be credited once the admin verifies your payment.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

    # Notify admin
    username_display = f"@{user.username}" if user.username else user.first_name
    await notify_admin(
        context.application,
        f"🔔 *New Deposit Request*\n\n"
        f"User: {username_display} (ID: `{user.id}`)\n"
        f"Amount: *${amount:.2f}*\n"
        f"Crypto: *{symbol}*\n"
        f"TX Hash: `{tx_hash}`\n"
        f"Deposit ID: `#{deposit_id}`\n\n"
        f"Use /approve {deposit_id} to approve or /reject {deposit_id} to reject.",
    )

    context.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────
# Label Submission Flow
# ─────────────────────────────────────────────

async def label_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    balance = await db.get_balance(user_id)

    if balance < LABEL_COST:
        await query.edit_message_text(
            f"❌ *Insufficient Balance*\n\n"
            f"Label submission costs *${LABEL_COST:.2f}*.\n"
            f"Your balance: *${balance:.2f}*\n\n"
            "Please top up your balance first.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        f"📤 *Submit Label*\n\n"
        f"Cost: *${LABEL_COST:.2f}* (will be deducted from your balance)\n"
        f"Your balance: *${balance:.2f}*\n\n"
        "Please send the label image now.",
        parse_mode="Markdown",
    )
    return LABEL_WAIT_IMAGE


async def label_receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not update.message.photo and not update.message.document:
        await update.message.reply_text("❌ Please send an image (photo or file).")
        return LABEL_WAIT_IMAGE

    # Get the file_id — prefer highest-res photo, or document
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        file_id = update.message.document.file_id

    # Deduct balance
    new_balance = await db.update_balance(user.id, -LABEL_COST)

    # Store label
    label_id = await db.create_label(
        user.id,
        user.username or user.first_name,
        file_id,
    )

    await update.message.reply_text(
        f"✅ *Label Submitted!*\n\n"
        f"Label ID: `#{label_id}`\n"
        f"Charged: *${LABEL_COST:.2f}*\n"
        f"Remaining balance: *${new_balance:.2f}*\n\n"
        "Your label has been received and the admin has been notified.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

    # Notify admin with the image
    username_display = f"@{user.username}" if user.username else user.first_name
    await notify_admin(
        context.application,
        f"🏷️ *New Label Submitted!*\n\n"
        f"Label ID: `#{label_id}`\n"
        f"From: {username_display} (ID: `{user.id}`)\n"
        f"Charged: *${LABEL_COST:.2f}*",
        photo_file_id=file_id,
    )

    return ConversationHandler.END


# ─────────────────────────────────────────────
# Cancel
# ─────────────────────────────────────────────

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "❌ Cancelled.\n\nWhat would you like to do?",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Cancelled.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(
        "What would you like to do?",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# Admin Commands (only for @wsboxing)
# ─────────────────────────────────────────────

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        username = (user.username or "").lower()
        is_admin = username == ADMIN_USERNAME.lower() or (ADMIN_CHAT_ID and user.id == ADMIN_CHAT_ID)
        if not user or not is_admin:
            await update.message.reply_text("⛔ Admin only.")
            return
        return await func(update, context)
    return wrapper


@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    labels = await db.get_all_labels()
    deposits = await db.get_pending_deposits()
    users = await db.get_all_users()

    await update.message.reply_text(
        f"🛠️ *Admin Panel*\n\n"
        f"👥 Total users: *{len(users)}*\n"
        f"🏷️ Total labels: *{len(labels)}*\n"
        f"⏳ Pending deposits: *{len(deposits)}*\n\n"
        f"Commands:\n"
        f"/labels — view all submitted labels\n"
        f"/deposits — view pending deposits\n"
        f"/allusers — view all users\n"
        f"/approve <id> — approve deposit\n"
        f"/reject <id> — reject deposit\n"
        f"/addbalance <user_id> <amount> — manually credit a user",
        parse_mode="Markdown",
    )


@admin_only
async def admin_labels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    labels = await db.get_all_labels()
    if not labels:
        await update.message.reply_text("No labels submitted yet.")
        return

    # Send a summary list first
    lines = []
    for lb in labels:
        username = f"@{lb['username']}" if lb.get("username") else lb.get("first_name", "Unknown")
        lines.append(
            f"#{lb['id']} | {username} | ${lb['charge']:.2f} | {lb['submitted_at'][:16]}"
        )

    await update.message.reply_text(
        "🏷️ *All Labels (latest 50)*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )

    # Send each label image
    for lb in labels[:20]:  # cap at 20 images to avoid spam
        username = f"@{lb['username']}" if lb.get("username") else lb.get("first_name", "Unknown")
        try:
            await update.message.reply_photo(
                photo=lb["file_id"],
                caption=f"🏷️ Label #{lb['id']} — {username}\n{lb['submitted_at'][:16]}",
            )
        except Exception as e:
            logger.error(f"Could not send label #{lb['id']} image: {e}")


@admin_only
async def admin_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    deposits = await db.get_pending_deposits()
    if not deposits:
        await update.message.reply_text("✅ No pending deposits.")
        return

    lines = []
    for dep in deposits:
        username = f"@{dep['username']}" if dep.get("username") else dep.get("first_name", "Unknown")
        lines.append(
            f"#{dep['id']} | {username} | ${dep['amount']:.2f} {dep['crypto_type']}\n"
            f"   TX: `{dep['tx_hash']}`\n"
            f"   /approve {dep['id']} | /reject {dep['id']}"
        )

    await update.message.reply_text(
        "⏳ *Pending Deposits*\n\n" + "\n\n".join(lines),
        parse_mode="Markdown",
    )


@admin_only
async def admin_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = await db.get_all_users()
    if not users:
        await update.message.reply_text("No users yet.")
        return

    lines = []
    for u in users:
        username = f"@{u['username']}" if u.get("username") else u.get("first_name", "Unknown")
        lines.append(f"{username} (ID: `{u['telegram_id']}`) — ${u['balance']:.2f}")

    await update.message.reply_text(
        "👥 *All Users*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


@admin_only
async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /approve <deposit_id>")
        return

    try:
        deposit_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid deposit ID.")
        return

    deposit = await db.approve_deposit(deposit_id)
    if not deposit:
        await update.message.reply_text(f"❌ Deposit #{deposit_id} not found or already processed.")
        return

    await update.message.reply_text(
        f"✅ Deposit #{deposit_id} approved!\n"
        f"${deposit['amount']:.2f} credited to user ID `{deposit['telegram_id']}`.",
        parse_mode="Markdown",
    )

    # Notify user
    try:
        new_balance = await db.get_balance(deposit["telegram_id"])
        await context.bot.send_message(
            chat_id=deposit["telegram_id"],
            text=f"✅ *Your deposit has been approved!*\n\n"
                 f"Amount credited: *${deposit['amount']:.2f}*\n"
                 f"New balance: *${new_balance:.2f}*",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    except Exception as e:
        logger.error(f"Could not notify user {deposit['telegram_id']}: {e}")


@admin_only
async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /reject <deposit_id>")
        return

    try:
        deposit_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid deposit ID.")
        return

    deposit = await db.reject_deposit(deposit_id)
    if not deposit:
        await update.message.reply_text(f"❌ Deposit #{deposit_id} not found or already processed.")
        return

    await update.message.reply_text(f"❌ Deposit #{deposit_id} rejected.")

    # Notify user
    try:
        await context.bot.send_message(
            chat_id=deposit["telegram_id"],
            text=f"❌ *Your deposit was rejected.*\n\n"
                 f"Amount: ${deposit['amount']:.2f} ({deposit['crypto_type']})\n"
                 f"TX: `{deposit['tx_hash']}`\n\n"
                 "If you believe this is an error, please contact support.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    except Exception as e:
        logger.error(f"Could not notify user {deposit['telegram_id']}: {e}")


@admin_only
async def admin_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addbalance <user_id> <amount>")
        return

    try:
        user_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid user_id or amount.")
        return

    new_balance = await db.update_balance(user_id, amount)
    await update.message.reply_text(
        f"✅ Added *${amount:.2f}* to user `{user_id}`.\nNew balance: *${new_balance:.2f}*",
        parse_mode="Markdown",
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"💰 *${amount:.2f} has been added to your balance!*\n\nNew balance: *${new_balance:.2f}*",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    except Exception as e:
        logger.error(f"Could not notify user {user_id}: {e}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    import asyncio

    async def post_init(app: Application):
        await db.init_db()
        logger.info("Database initialised.")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Top-up conversation
    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_start, pattern="^menu_topup$")],
        states={
            TOPUP_CHOOSE_CRYPTO: [
                CallbackQueryHandler(topup_choose_crypto, pattern="^crypto_"),
                CallbackQueryHandler(cancel_callback, pattern="^cancel$"),
            ],
            TOPUP_ENTER_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, topup_enter_amount),
            ],
            TOPUP_ENTER_TXHASH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, topup_enter_txhash),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )

    # Label submission conversation
    label_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(label_start, pattern="^menu_submit$")],
        states={
            LABEL_WAIT_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, label_receive_image),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(topup_conv)
    app.add_handler(label_conv)
    app.add_handler(CallbackQueryHandler(balance_callback, pattern="^menu_balance$"))

    # Admin commands
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("labels", admin_labels))
    app.add_handler(CommandHandler("deposits", admin_deposits))
    app.add_handler(CommandHandler("allusers", admin_all_users))
    app.add_handler(CommandHandler("approve", admin_approve))
    app.add_handler(CommandHandler("reject", admin_reject))
    app.add_handler(CommandHandler("addbalance", admin_add_balance))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
