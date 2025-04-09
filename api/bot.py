import os
import time
import logging
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from web3 import Web3
import json

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Token from Render environment
BOT_TOKEN = os.environ["BOT_TOKEN"]

# Web3
w3 = Web3()

# Data
user_wallets = {}
user_orders = {}
user_signatures = {}
user_preferences = {}
SUPPORTED_CRYPTOS = ["usdt", "btc", "eth", "bnb", "sol", "ton", "ada", "xrp", "dot", "doge"]
SUPPORTED_FIATS = ["USD", "NGN", "EUR", "KES", "GHS", "ZAR", "GBP"]

# ✅ TON Connect App URL
TON_CONNECT_LINK = "https://gigi-ton-connect.vercel.app/?returnUrl=https%3A%2F%2Ft.me%2FGigiP2Bot"

# Prices
def get_bybit_price(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol.upper()}USDT"
        r = requests.get(url).json()
        return float(r["result"]["list"][0]["lastPrice"])
    except:
        return None

def get_bitget_price(symbol):
    try:
        url = f"https://api.bitget.com/api/spot/v1/market/ticker?symbol={symbol.upper()}USDT"
        r = requests.get(url).json()
        return float(r["data"]["close"])
    except:
        return None

def get_best_price(symbol):
    prices = [p for p in [get_bybit_price(symbol), get_bitget_price(symbol)] if p]
    if prices:
        return f"💰 *{symbol.upper()}*: ${min(prices):,.2f}"
    return f"❌ Couldn't get {symbol.upper()} price"

# ---- Handlers ----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔗 Connect Wallet", url=TON_CONNECT_LINK)],
        [InlineKeyboardButton("💵 Buy Crypto", callback_data="buy_crypto")],
        [InlineKeyboardButton("💸 Sell Crypto", callback_data="sell_crypto")]
    ]
    await update.message.reply_text(
        "👋 Welcome to *GigiP2Bot* — your Web3 assistant 🤖💸\n\n"
        "Say things like:\n"
        "• *Buy BTC fast*\n"
        "• *Sell USDT now*\n"
        "• *How much is ETH?*\n"
        "• *Connect my wallet*\n\n"
        "👇 Start by connecting:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛟 *Gigi Help Center*\n\n"
        "Try asking:\n"
        "• 'What is the price of TON?'\n"
        "• 'Buy BTC' or 'Sell USDT'\n"
        "• 'Connect wallet' or 'Connect my wallet'\n\n"
        "🧾 *Bot Commands:*\n"
        "/rates - Live prices\n"
        "/connect_wallet - Link your wallet\n"
        "/check_wallet - View wallet\n"
        "/set_currency - Set your local currency\n"
        "/order_history - Last 5 actions\n"
        "/sign - Verify wallet",
        parse_mode=ParseMode.MARKDOWN
    )

async def set_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    reply_markup = ReplyKeyboardMarkup([[fiat] for fiat in SUPPORTED_FIATS], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("🌍 Choose your preferred currency:", reply_markup=reply_markup)

async def handle_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.chat_id
    currency = update.message.text.upper()
    if currency in SUPPORTED_FIATS:
        user_preferences[user_id] = {"currency": currency}
        await update.message.reply_text(f"✅ Currency set to *{currency}*", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Invalid currency. Try again using /set_currency")

async def rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 *Top Crypto Prices:*\n"
    for coin in SUPPORTED_CRYPTOS:
        text += get_best_price(coin) + "\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def connect_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🟦 Connect TON Wallet", url=TON_CONNECT_LINK)]]
    text = (
        "🔐 *Wallet Connection*\n\n"
        "Click the button below to connect via TON Connect:\n\n"
        "👇 After connecting, paste your wallet address.\n"
        "Then use /sign to authorize. 🔏"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    address = update.message.text.strip()

    if address.startswith("0x") and len(address) == 42:
        wallet_type = "evm"
        icon = "🟣"
    elif len(address) == 48:
        wallet_type = "ton"
        icon = "🔷"
    elif 32 <= len(address) <= 44 and address.isalnum():
        wallet_type = "solana"
        icon = "🟡"
    else:
        await update.message.reply_text("❌ Invalid wallet address. Please try again.")
        return

    user_wallets[uid] = {"wallet_address": address, "type": wallet_type}
    await update.message.reply_text(f"{icon} *{wallet_type.upper()} wallet connected:* `{address}`", parse_mode=ParseMode.MARKDOWN)

async def check_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    wallet = user_wallets.get(uid)
    if wallet:
        await update.message.reply_text(f"🧾 *Your wallet:* `{wallet['wallet_address']}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("🚫 You haven't connected a wallet yet.")

async def order_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    history = user_orders.get(uid, [])
    if not history:
        await update.message.reply_text("📭 You have no recent orders.")
    else:
        msg = "📜 *Your Recent Orders:*\n"
        for h in history[-5:][::-1]:
            msg += f"• {h}\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def sign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    if uid not in user_wallets:
        await update.message.reply_text("🔐 Connect a wallet first using /connect_wallet.")
        return
    msg = f"Sign this message in your wallet: GigiWallet-{uid}-{int(time.time())}"
    user_signatures[uid] = msg
    await update.message.reply_text(f"🖊 `{msg}`", parse_mode=ParseMode.MARKDOWN)

async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    text = update.message.text.lower()

    if any(x in text for x in ["connect wallet", "connect my wallet", "link wallet"]):
        await connect_wallet(update, context)
        return

    if text.startswith("0x") or 32 <= len(text.strip()) <= 48:
        await handle_wallet_address(update, context)
        return

    if "sign" in text:
        await sign(update, context)
        return

    if text.upper() in SUPPORTED_FIATS:
        await handle_currency(update, context)
        return

    for coin in SUPPORTED_CRYPTOS:
        if coin in text:
            currency = user_preferences.get(uid, {}).get("currency", "USD")
            price_text = get_best_price(coin)
            if any(x in text for x in ["how much", "price", "rate", "value"]):
                await update.message.reply_text(price_text, parse_mode=ParseMode.MARKDOWN)
                user_orders.setdefault(uid, []).append(f"Checked {coin.upper()} price")
                return
            elif any(x in text for x in ["buy", "purchase", "get"]):
                await update.message.reply_text(f"🛒 You’re buying *{coin.upper()}* in *{currency}*...\n\nPlease proceed to fiat payment page or sign transaction soon.", parse_mode=ParseMode.MARKDOWN)
                user_orders.setdefault(uid, []).append(f"Initiated BUY for {coin.upper()} in {currency}")
                return
            elif any(x in text for x in ["sell", "withdraw", "cash out"]):
                await update.message.reply_text(f"💵 You’re selling *{coin.upper()}* to receive *{currency}*.\n\nYou’ll be asked to sign the transfer transaction now.", parse_mode=ParseMode.MARKDOWN)
                user_orders.setdefault(uid, []).append(f"Initiated SELL for {coin.upper()} to {currency}")
                return

    await update.message.reply_text("🤖 Try 'Buy BTC', 'Sell ETH' or 'Connect my wallet'", parse_mode=ParseMode.MARKDOWN)

# ---- Main ----
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("rates", rates))
    app.add_handler(CommandHandler("set_currency", set_currency))
    app.add_handler(CommandHandler("connect_wallet", connect_wallet))
    app.add_handler(CommandHandler("check_wallet", check_wallet))
    app.add_handler(CommandHandler("order_history", order_history))
    app.add_handler(CommandHandler("sign", sign))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    logging.info("🚀 GigiP2Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
