import os
import json
import time
import logging
import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Load .env for local dev
load_dotenv()

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Bot token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Data
user_data = {}
user_pending_fiat = {}
user_pending_amount = {}
user_wallets = {}
user_orders = {}
user_signatures = {}
TON_RECEIVE_ADDRESS = "UQCMbQomO3XD1FSt7pyfjqj2jBRzyg23myKDtCky_CedKpEH"
TON_CONNECT_BASE = "https://gigi-ton-connect.vercel.app/sign"
SUPPORTED_FIATS = ["NGN", "GHS", "KES", "USD", "ZAR", "GBP"]
SUPPORTED_CRYPTOS = ["btc", "eth", "usdt", "bnb", "sol", "ton", "ada", "xrp", "dot", "doge"]

# --- API Helpers ---
def get_usdt_to_fiat_rate(fiat):
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/USD"
        r = requests.get(url).json()
        return r['rates'].get(fiat.upper(), None)
    except:
        return None

def get_crypto_price(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=spot"
        r = requests.get(url).json()
        tickers = r.get("result", {}).get("list", [])
        for coin in tickers:
            if coin["symbol"] == f"{symbol.upper()}USDT":
                return float(coin["lastPrice"])
        return None
    except:
        return None

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    keyboard = [
        [InlineKeyboardButton("\U0001F517 Connect Wallet", url="https://gigi-ton-connect.vercel.app/?returnUrl=https%3A%2F%2Ft.me%2FGigiP2Bot")],
        [InlineKeyboardButton("\U0001F4B5 Buy Crypto", callback_data="buy_crypto"), InlineKeyboardButton("\U0001F4B8 Sell Crypto", callback_data="sell_crypto")],
        [InlineKeyboardButton("\U0001F4B0 Select Fiat", callback_data="select_fiat")],
        [InlineKeyboardButton("\u2139 Help", callback_data="help"), InlineKeyboardButton("\U0001F4DD Sign", callback_data="sign")],
        [InlineKeyboardButton("\U0001F4E6 View Wallet", callback_data="view_wallet"), InlineKeyboardButton("\U0001F4CB Order History", callback_data="history")]
    ]
    await update.message.reply_text(
        "\U0001F44B Welcome to *GigiP2Bot* — your Web3 assistant \U0001F916\U0001F4B8\n\n"
        "Say things like:\n"
        "• *Buy BTC fast*\n"
        "• *Sell TON now*\n"
        "• *Buy TON with fiat*\n"
        "• *Connect my wallet*\n\n"
        "\U0001F447 Start by picking an action:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.message.chat_id

    if query.data == "select_fiat":
        keyboard = [[InlineKeyboardButton(fiat, callback_data=f"fiat_{fiat}")] for fiat in SUPPORTED_FIATS]
        await query.message.reply_text("\U0001F4B5 Please choose your local currency:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("fiat_"):
        fiat = query.data.replace("fiat_", "")
        user_data[uid] = {"fiat": fiat}
        user_pending_fiat[uid] = True
        await query.message.reply_text(f"\U0001F4B0 Great! Now enter the amount in {fiat} you want to convert to TON (e.g. 5000):")

    if query.data == "buy_crypto":
        await query.message.reply_text("\U0001F4B5 To buy TON, please select your fiat currency using /start and follow the steps.")

    if query.data == "sell_crypto":
        await query.message.reply_text("\U0001F4B8 Sell flow coming soon! Stay tuned.")

    if query.data == "help":
        await query.message.reply_text("\U0001F6E0 Need help? Try asking: \n• 'Price of BTC'\n• 'Buy USDT'\n• 'Connect wallet'\nUse /start to begin again.", parse_mode=ParseMode.MARKDOWN)

    if query.data == "sign":
        msg = f"Sign this message in your wallet: GigiWallet-{uid}-{int(time.time())}"
        user_signatures[uid] = msg
        await query.message.reply_text(f"🖊 `{msg}`", parse_mode=ParseMode.MARKDOWN)

    if query.data == "view_wallet":
        wallet = user_wallets.get(uid)
        if wallet:
            await query.message.reply_text(f"\U0001F4E6 *Your Wallet:* `{wallet['wallet_address']}`", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.message.reply_text("\u274C No wallet found. Use /start to connect.")

    if query.data == "history":
        history = user_orders.get(uid, [])
        if not history:
            await query.message.reply_text("📭 You have no recent orders.")
        else:
            msg = "📜 *Your Recent Orders:*\n"
            for h in history[-5:][::-1]:
                msg += f"• {h}\n"
            await query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    text = update.message.text.strip().lower()

    if text.startswith("0x") or 32 <= len(text.strip()) <= 48:
        wallet_type = "evm" if text.startswith("0x") else "ton"
        icon = "🟣" if wallet_type == "evm" else "🔷"
        user_wallets[uid] = {"wallet_address": text, "type": wallet_type}
        await update.message.reply_text(f"{icon} *{wallet_type.upper()} wallet connected:* `{text}`", parse_mode=ParseMode.MARKDOWN)
        return

    if uid in user_pending_fiat:
        try:
            amount_fiat = float(text)
            fiat = user_data[uid]["fiat"]
            usdt_to_fiat = get_usdt_to_fiat_rate(fiat)
            ton_usdt = get_crypto_price("ton")
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
            user_orders.setdefault(uid, []).append(f"Buy {ton_amount:.4f} TON for {amount_fiat} {fiat}")
            del user_pending_fiat[uid]
        except:
            await update.message.reply_text("\u274C Invalid amount. Please enter a number like 5000 or 200.")
        return

    for coin in SUPPORTED_CRYPTOS:
        if coin in text:
            price = get_crypto_price(coin)
            if price:
                await update.message.reply_text(f"\U0001F4B0 *{coin.upper()}* is currently *${price:,.2f}*", parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"\u274C Couldn't get {coin.upper()} price")
            user_orders.setdefault(uid, []).append(f"Checked {coin.upper()} rate")
            return

    await update.message.reply_text("\U0001F916 You can say 'buy BTC', paste your wallet address, or use /start.", parse_mode=ParseMode.MARKDOWN)

# Main

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("\U0001F680 GigiP2Bot fully loaded with all features!")
    app.run_polling()

if __name__ == "__main__":
    main()
