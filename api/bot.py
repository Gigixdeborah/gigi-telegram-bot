import os
import json
import logging
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Bot token
BOT_TOKEN = os.environ["BOT_TOKEN"]

# Data
user_data = {}
user_pending_fiat = {}
user_pending_amount = {}
user_wallets = {}
TON_RECEIVE_ADDRESS = "UQCMbQomO3XD1FSt7pyfjqj2jBRzyg23myKDtCky_CedKpEH"
TON_CONNECT_BASE = "https://gigi-ton-connect.vercel.app/sign"
SUPPORTED_FIATS = ["NGN", "GHS", "KES"]

# --- API Helpers ---
def get_usdt_to_fiat_rate(fiat):
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/USD"
        r = requests.get(url).json()
        return r['rates'].get(fiat.upper(), None)
    except:
        return None

def get_ton_usdt_price():
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol=TONUSDT"
        r = requests.get(url).json()
        return float(r["result"]["list"][0]["lastPrice"])
    except:
        return None

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    keyboard = [[InlineKeyboardButton(fiat, callback_data=f"fiat_{fiat}")] for fiat in SUPPORTED_FIATS]
    await update.message.reply_text(
        "\U0001F4B5 Welcome to *GigiP2Bot*!\n\nPlease choose your local currency:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.message.chat_id

    if query.data.startswith("fiat_"):
        fiat = query.data.replace("fiat_", "")
        user_data[uid] = {"fiat": fiat}
        user_pending_fiat[uid] = True
        await query.message.reply_text(f"\U0001F4B0 Great! Now enter the amount in {fiat} you want to convert to TON (e.g. 5000):")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    text = update.message.text.strip().lower()

    # Fiat conversion to TON
    if uid in user_pending_fiat:
        try:
            amount_fiat = float(text)
            fiat = user_data[uid]["fiat"]
            usdt_to_fiat = get_usdt_to_fiat_rate(fiat)
            ton_usdt = get_ton_usdt_price()

            if not usdt_to_fiat or not ton_usdt:
                await update.message.reply_text("\u274C Couldn't fetch live rates. Try again later.")
                return

            usdt_amount = amount_fiat / usdt_to_fiat
            ton_amount = usdt_amount / ton_usdt

            nano_amount = int(ton_amount * 1e9)
            ton_sign_url = f"{TON_CONNECT_BASE}?amount={nano_amount}&to={TON_RECEIVE_ADDRESS}"
            keyboard = [[InlineKeyboardButton("\u2705 Sign with TON Wallet", url=ton_sign_url)]]

            await update.message.reply_text(
                f"\U0001F4B8 {amount_fiat:.2f} {fiat} can buy you ~<b>{ton_amount:.4f} TON</b> today.\n\nSign the transaction to continue:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            del user_pending_fiat[uid]
        except:
            await update.message.reply_text("\u274C Invalid amount. Please enter a number like 5000 or 200.")
        return

    await update.message.reply_text("\U0001F916 Try /start to begin again or type an amount to convert.")

# Main
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("\U0001F680 GigiP2Bot with Fiat Conversion + TON Signing is LIVE!")
    app.run_polling()

if __name__ == "__main__":
    main()

