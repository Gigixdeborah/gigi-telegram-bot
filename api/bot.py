# bot.py — Final GigiP2Bot Script
import os, json, logging, requests, re
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
import nest_asyncio

nest_asyncio.apply()
load_dotenv()

# Setup logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ✅ Corrected manifest URL
TON_MANIFEST_URL = "https://gigi-ton-connect-v2-deploy.onrender.com/tonconnect-manifest.json"
TON_CONNECT_LINK = f"https://t.me/wallet/start?startapp=tonconnect-v2&manifestUrl={TON_MANIFEST_URL}"
TON_RECEIVE_ADDRESS = "UQCMbQomO3XD1FSt7pyfjqj2jBRzyg23myKDtCky_CedKpEH"

user_wallets = {}
user_pending_fiat = {}
user_pending_amount = {}
user_orders = {}

FIAT_OPTIONS = ["NGN", "USD", "KES", "GHS", "EUR", "ZAR", "GBP"]
SUPPORTED_TOKENS = ["TON", "USDT", "ETH", "BTC"]

def get_inline_keyboard(buttons):
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in buttons])

def get_fiat_keyboard():
    return get_inline_keyboard([[(f"{fiat}", f"set_fiat_{fiat}") for fiat in FIAT_OPTIONS]])

def generate_ton_sign_link(amount, user_id):
    nano = int(float(amount) * 1e9)
    return f"https://gigi-ton-connect-v2-deploy.onrender.com/sign.html?amount={nano}&to={TON_RECEIVE_ADDRESS}&user_id={user_id}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *GigiP2Bot*!\nI'm your crypto-to-fiat buddy 🤖💸\n\nConnect your wallet and let's go!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_inline_keyboard([
            [("🔗 Connect Wallet", "connect_wallet")],
            [("💰 Buy", "buy_crypto"), ("💸 Sell", "sell_crypto")],
            [("🌐 Choose Fiat", "choose_fiat")]
        ])
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help Menu*\n\nUse these:\n/start - Restart\n/connect_wallet - Link wallet\n/buy - Buy crypto\n/sell - Sell crypto\n/fiat - Choose fiat currency",
        parse_mode=ParseMode.MARKDOWN
    )

async def connect_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔗 TON Wallet", url=TON_CONNECT_LINK)],
        [InlineKeyboardButton("🥊 MetaMask (EVM)", callback_data="evm_connect")],
        [InlineKeyboardButton("🌈 Phantom (Solana)", callback_data="solana_connect")],
    ]
    await update.message.reply_text("🔐 Choose your wallet to connect:", reply_markup=InlineKeyboardMarkup(keyboard))

async def fiat_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌍 Choose your local fiat currency:", reply_markup=get_fiat_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("set_fiat_"):
        fiat = data.replace("set_fiat_", "")
        user_id = query.from_user.id
        user_pending_fiat[user_id] = fiat
        await query.edit_message_text(f"✅ Fiat set to {fiat}")

    elif data == "connect_wallet":
        await connect_wallet(query, context)

    elif data == "choose_fiat":
        await fiat_selection(query, context)

    elif data == "buy_crypto":
        await query.edit_message_text("💳 Enter the amount and token you'd like to *buy*. Example: `Buy 100 TON`", parse_mode=ParseMode.MARKDOWN)

    elif data == "sell_crypto":
        await query.edit_message_text("💸 Enter the amount and token you'd like to *sell*. Example: `Sell 50 TON`", parse_mode=ParseMode.MARKDOWN)

    elif data == "evm_connect":
        await query.edit_message_text("🥊 Please open MetaMask to connect. Feature coming soon.")

    elif data == "solana_connect":
        await query.edit_message_text("🌈 Please open Phantom Wallet to connect. Feature coming soon.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    user_id = update.message.from_user.id

    match = re.match(r"(buy|sell)\s+(\d+(\.\d+)?)\s+(\w+)", text, re.IGNORECASE)
    if match:
        action, amount, _, token = match.groups()
        amount = float(amount)
        token = token.upper()

        if token not in SUPPORTED_TOKENS:
            await update.message.reply_text(f"❌ Unsupported token: {token}")
            return

        user_orders[user_id] = {"type": action, "token": token, "amount": amount}

        if action == "sell" and token == "TON":
            await update.message.reply_text(
                f"✅ To sell *{amount} {token}*, sign the transaction with TON Connect 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Sign with TON Wallet", url=generate_ton_sign_link(amount, user_id))]
                ])
            )
        else:
            await update.message.reply_text(f"🚧 Support for {action}ing {token} coming soon!")
    else:
        await update.message.reply_text("❓ I didn't understand. Try: `Buy 50 TON` or `Sell 10 USDT`", parse_mode=ParseMode.MARKDOWN)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("connect_wallet", connect_wallet))
    app.add_handler(CommandHandler("fiat", fiat_selection))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("🚀 GigiP2Bot fully loaded!")
    app.run_polling()

if __name__ == '__main__':
    main()
