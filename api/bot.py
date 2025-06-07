import os
import json
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from models import User, Transaction, BankAccount, TransactionStatus, Base
import requests
import geocoder
import redis
import spacy
import asyncio
from typing import Optional, Dict, Tuple

# Load spaCy's small English model
nlp = spacy.load("en_core_web_sm")

# Environment Variables
load_dotenv()
REQUIRED_ENV_VARS = [
    "TELEGRAM_BOT_TOKEN",
    "DATABASE_URL",
    "ADMIN_CHAT_ID",
]
for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        raise EnvironmentError(f"Missing required environment variable: {var}")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
TWA_BASE_URL = os.getenv("TWA_BASE_URL", "https://gigi-wallet-signing.onrender.com")
BYBIT_API_URL = "https://api.bybit.com"
BYBIT_RECIPIENT_API_URL = os.getenv("BYBIT_RECIPIENT_API_URL", "https://api.bybit.com/custom/recipient")

FALLBACK_ADDRESSES = {
    "TON": os.getenv("FALLBACK_TON_ADDRESS", "UQCMbQomO3XD1FSt7pyfjqj2jBRzyg23myKDtCky_CedKpEH"),
    "BTC": os.getenv("FALLBACK_BTC_ADDRESS", "15v6V97KZh3NDgPWjwbQBp4PWPRgf7uQRf"),
    "ETH": os.getenv("FALLBACK_ETH_ADDRESS", "0x4fb9055c71a3cafd7c6d30686cfe55282a11ac5e"),
    "USDT_ERC20": os.getenv("FALLBACK_USDT_ERC20_ADDRESS", "0x4fb9055c71a3cafd7c6d30686cfe55282a11ac5e"),
    "USDT_TON": os.getenv("FALLBACK_USDT_TON_ADDRESS", "UQCMbQomO3XD1FSt7pyfjqj2jBRzyg23myKDtCky_CedKpEH"),
    "USDT_TRC20": os.getenv("FALLBACK_USDT_TRC20_ADDRESS", "TBNQW6J9hkoamhs7oYXVmGf3LBKbs1ZiUd"),
    "SOL": os.getenv("FALLBACK_SOL_ADDRESS", "CdkLzLG3uTwA7HqNGZ3CC4fTc4EwjGJWaTGNjmTRpu7Z"),
    "BNB": os.getenv("FALLBACK_BNB_ADDRESS", "0x4fb9055c71a3cafd7c6d30686cfe55282a11ac5e"),
    "MATIC": os.getenv("FALLBACK_MATIC_ADDRESS", "0x4fb9055c71a3cafd7c6d30686cfe55282a11ac5e"),
    "USDC": os.getenv("FALLBACK_USDC_ADDRESS", "0x4fb9055c71a3cafd7c6d30686cfe55282a11ac5e"),
    "TRX": os.getenv("FALLBACK_TRX_ADDRESS", "TBNQW6J9hkoamhs7oYXVmGf3LBKbs1ZiUd"),
    "SHIB": os.getenv("FALLBACK_SHIB_ADDRESS", "0x4fb9055c71a3cafd7c6d30686cfe55282a11ac5e"),
    "XRP": os.getenv("FALLBACK_XRP_ADDRESS", "rJn2zAPdFA193sixJwuFixRkYDUtx3apQh"),
    "ADA": os.getenv("FALLBACK_ADA_ADDRESS", "addr1v8hpde5xvxux8vn5x4fnr94qvd7e95pl0lr7770w3kds60cu52cc7"),
    "DOT": os.getenv("FALLBACK_DOT_ADDRESS", "15tcNR3ypYpYSFdqxzoPJVhdfHq221D6qesSpRc5pdmhiG39"),
    "AVAX": os.getenv("FALLBACK_AVAX_ADDRESS", "0x4fb9055c71a3cafd7c6d30686cfe55282a11ac5e"),
    "DOGE": os.getenv("FALLBACK_DOGE_ADDRESS", "DAUpMXucfetrJhzrW9LRFxTo22BzqnVg8E")
}
FALLBACK_XRP_TAG = os.getenv("FALLBACK_XRP_TAG", "501173063")

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Redis and Database Setup
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
engine = create_async_engine(DATABASE_URL, pool_size=10, max_overflow=20)
AsyncSessionFactory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

SUPPORTED_TOKENS = {
    "BTC": "BTC", "ETH": "EVM", "USDT": ["ERC20", "TRC20", "TON"], "TON": "TON",
    "SOL": "Solana", "BNB": "BSC", "MATIC": "Polygon", "USDC": "EVM", "TRX": "TRON",
    "SHIB": "EVM", "XRP": "XRP", "ADA": "Cardano", "DOT": "Polkadot", "AVAX": "Avalanche", "DOGE": "Dogecoin"
}
SUPPORTED_TOKENS_LOWER = {k.lower(): k for k in SUPPORTED_TOKENS.keys()}

conversation_context: Dict[int, Dict] = {}

# Utility Functions
def escape_markdown(text: str) -> str:
    special_chars = r"\_*[]()~`>#+=|{}.!-"
    return ''.join(f'\\{c}' if c in special_chars else c for c in str(text))

async def rate_limit(user_id: int, ip: str = None) -> bool:
    key = f"rate_limit:{user_id}:{ip or 'unknown'}"
    now = datetime.now().timestamp()
    async with redis_client.pipeline() as pipe:
        pipe.zremrangebyscore(key, 0, now - 60)
        pipe.zadd(key, {str(now): now})
        pipe.zrangebyscore(key, now - 60, now)
        _, _, requests = await pipe.execute()
    return len(requests) < 10

async def detect_fiat_currency() -> str:
    try:
        g = geocoder.ip('me')
        country = g.country
        fiat_map = {"NG": "NGN", "GH": "GHS", "KE": "KES", "US": "USD", "UK": "GBP"}
        return fiat_map.get(country, "NGN")
    except Exception as e:
        logger.warning(f"Geolocation failed: {e}")
        return "NGN"

async def init_user(telegram_id: int, db_session: AsyncSession) -> User:
    async with db_session.begin():
        try:
            user = await db_session.get(User, telegram_id)
            if not user:
                fiat = await detect_fiat_currency()
                user = User(telegram_id=telegram_id, fiat_currency=fiat, lang="EN", tone="playful")
                db_session.add(user)
                await db_session.commit()
            return user
        except SQLAlchemyError as e:
            logger.error(f"Database error in init_user: {e}")
            await db_session.rollback()
            raise

def notify_admin(user_id: int, amount: float, token: str):
    if amount > 100:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_CHAT_ID, "text": f"⚠️ High-value tx: {user_id} - {amount} {token}"},
                timeout=5
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

# Synonym and Sentiment
SYNONYMS = {
    "buy": ["purchase", "grab", "get", "want", "need", "acquire", "buying"],
    "sell": ["sell", "cash", "unload", "offload", "trade", "dispose", "selling", "cash out"],
    "connect_wallet": ["connect", "link", "setup", "attach"],
    "balance": ["check", "how much", "show", "what's", "funds", "money"],
    "help": ["support", "guide", "what can", "how to", "assist"],
    "price": ["rate", "value", "cost", "worth", "how much is"],
    "chart": ["graph", "trend", "show me", "visualize"],
    "greeting": ["hi", "hello", "hey", "greetings", "what's up"],
    "thanks": ["thanks", "thank you", "appreciate", "great"],
    "exit": ["bye", "exit", "quit", "done", "later"],
    "about": ["how are you", "what are you", "who are you"],
    "time": ["what time", "current time", "time now"],
    "cancel": ["cancel", "stop", "abort", "nevermind"]
}

def detect_sentiment(message: str) -> str:
    positive_keywords = ["great", "awesome", "good", "nice", "happy", "love"]
    negative_keywords = ["bad", "terrible", "sad", "sorry", "fail", "hate"]
    msg = message.lower()
    if any(word in msg for word in positive_keywords):
        return "positive"
    elif any(word in msg for word in negative_keywords):
        return "negative"
    return "neutral"

# API Calls
async def fetch_crypto_rates_bybit(token: str) -> Optional[float]:
    cache_key = f"rate:{token}"
    cached_rate = redis_client.get(cache_key)
    if cached_rate:
        return float(cached_rate)
    try:
        symbol = f"{token}USDT"
        response = requests.get(f"{BYBIT_API_URL}/v5/market/tickers", params={"category": "spot", "symbol": symbol}, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("retCode") != 0:
            logger.error(f"Bybit API error: {data.get('retMsg')}")
            return None
        rate = float(data["result"]["list"][0]["lastPrice"])
        redis_client.setex(cache_key, 60, rate)
        return rate
    except Exception as e:
        logger.error(f"Failed to fetch rate for {token}: {e}")
        return None

async def fetch_recipient_address(token: str, network: Optional[str] = None) -> Tuple[str, Optional[str]]:
    key = f"USDT_{network}" if token == "USDT" and network else token
    try:
        params = {"token": token, "network": network} if token == "USDT" and network else {"token": token}
        response = requests.get(BYBIT_RECIPIENT_API_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        address = data.get("address")
        tag = data.get("tag") if token == "XRP" else None
        return address or FALLBACK_ADDRESSES.get(key, "default_recipient"), tag or (FALLBACK_XRP_TAG if token == "XRP" else None)
    except Exception as e:
        logger.error(f"Failed to fetch recipient address for {key}: {e}")
        return FALLBACK_ADDRESSES.get(key, "default_recipient"), FALLBACK_XRP_TAG if token == "XRP" else None

# Context Management
def update_context(user_id: int, context: Dict) -> None:
    conversation_context[user_id] = context

def get_context(user_id: int) -> Dict:
    return conversation_context.get(user_id, {"state": None, "data": {}, "history": []})

async def fetch_rate_with_retry(token: str, retries: int = 3) -> Optional[float]:
    for attempt in range(retries):
        rate = await fetch_crypto_rates_bybit(token)
        if rate is not None:
            return rate
        logger.warning(f"Rate fetch failed for {token}, attempt {attempt + 1}/{retries}")
        await asyncio.sleep(1)
    return None

# Intent and Entity Detection
def detect_intent_and_entities(message: str) -> Tuple[str, Dict]:
    doc = nlp(message.lower().strip())
    entities = {"token": None, "amount": None, "network": None}
    for token in doc:
        if token.like_num:
            try:
                entities["amount"] = float(token.text)
            except ValueError:
                continue
        if token.text in SUPPORTED_TOKENS_LOWER:
            entities["token"] = SUPPORTED_TOKENS_LOWER[token.text]
        if token.text in ["erc20", "trc20", "ton"] and entities.get("token") == "USDT":
            entities["network"] = token.text.upper()
    for intent, synonyms in SYNONYMS.items():
        if any(t.text in synonyms for t in doc):
            return intent, entities
    return "conversation", entities

# Conversation Handler
async def handle_conversation(user_id: int, message: str) -> str:
    context = get_context(user_id)
    state = context.get("state")
    data = context.get("data", {})
    history = context.get("history", [])
    text = message.strip()
    sentiment = detect_sentiment(text)

    hour = datetime.now().hour
    time_greeting = "Good evening" if hour >= 18 else "Good afternoon" if hour >= 12 else "Good morning"
    greetings = [f"{time_greeting}, cosmic traveler!", "Hey there, friend!", "Hi, star trader!"]
    thanks_replies = ["You're welcome! 😊", "My pleasure!", "Anytime, buddy!"]
    exit_replies = ["Catch you later!", "Take care!", "See you in the cosmos!"]
    if sentiment == "negative":
        greetings = [f"{time_greeting}, let’s turn things around!", "Hey, I’m here to help!", "Hi, let’s fix this!"]
        thanks_replies = ["I’ve got your back!", "Here to help!", "Let’s keep going!"]
        exit_replies = ["Hope things improve!", "I’m here if you need me!", "Take it easy!"]

    if state == "awaiting_token_buy":
        token = text.upper()
        if token not in SUPPORTED_TOKENS:
            return "Hmm, I don’t recognize that token! Try TON, USDT, BTC, etc. What token would you like?"
        data["token"] = token
        if token == "USDT":
            keyboard = [
                [InlineKeyboardButton("USDT (ERC20)", callback_data="network_erc20_buy"),
                 InlineKeyboardButton("USDT (TRC20)", callback_data="network_trc20_buy")],
                [InlineKeyboardButton("USDT (TON)", callback_data="network_ton_buy")]
            ]
            update_context(user_id, {"state": "awaiting_network_buy", "data": data, "history": history + ["buy"]})
            return f"USDT, nice! Which network? {InlineKeyboardMarkup(keyboard)}"
        update_context(user_id, {"state": "awaiting_amount_buy", "data": data, "history": history + ["buy"]})
        return f"Nice pick! How much {token} would you like to buy? (e.g., 1.5)"

    elif state == "awaiting_network_buy":
        network = data.get("network", text.upper())
        data["network"] = network
        update_context(user_id, {"state": "awaiting_amount_buy", "data": data, "history": history + ["buy_network"]})
        return f"Got it, USDT on {network}! How much would you like to buy? (e.g., 1.5)"

    elif state == "awaiting_amount_buy":
        try:
            amount = float(text)
            if amount <= 0:
                return "Whoa, let’s keep it positive! How much would you like to buy?"
            data["amount"] = amount
            rate = await fetch_rate_with_retry(data["token"])
            if not rate:
                return "Oops, couldn’t fetch the rate for that token! Try another?"
            fiat_amount = amount * rate + 0.15
            token = data["token"]
            network = data.get("network")
            recipient_address, tag = await fetch_recipient_address(token, network)
            update_context(user_id, {"state": "confirm_buy", "data": data, "history": history + ["buy_amount"]})
            url = f"{TWA_BASE_URL}/sign.html?user_id={user_id}&amount={amount}&to={recipient_address}&tid={user_id}"
            if tag:
                url += f"&tag={tag}"
            keyboard = [
                [InlineKeyboardButton("Confirm & Pay", url=url)],
                [InlineKeyboardButton("Cancel", callback_data="cancel_action")]
            ]
            tag_text = f" (Tag: {tag})" if tag else ""
            return f"Buying {amount} {token}{f' ({network})' if network else ''} for ${fiat_amount:.2f} (incl. $0.15 fee). Ready to send to {recipient_address}{tag_text}? {InlineKeyboardMarkup(keyboard)}"
        except ValueError:
            return "Oops, that didn’t look like a number! How much would you like to buy?"

    elif state == "confirm_buy":
        update_context(user_id, {"state": None, "data": {}, "history": history + ["buy_confirmed"]})
        return "Transaction launched! Check the web app. I’ll wait for you! 🌟"

    elif state == "awaiting_token_sell":
        token = text.upper()
        if token not in SUPPORTED_TOKENS:
            return "Hmm, I don’t know that token! Try TON, USDT, BTC, etc. What are you selling?"
        data["token"] = token
        if token == "USDT":
            keyboard = [
                [InlineKeyboardButton("USDT (ERC20)", callback_data="network_erc20_sell"),
                 InlineKeyboardButton("USDT (TRC20)", callback_data="network_trc20_sell")],
                [InlineKeyboardButton("USDT (TON)", callback_data="network_ton_sell")]
            ]
            update_context(user_id, {"state": "awaiting_network_sell", "data": data, "history": history + ["sell"]})
            return f"USDT, nice! Which network? {InlineKeyboardMarkup(keyboard)}"
        update_context(user_id, {"state": "awaiting_amount_sell", "data": data, "history": history + ["sell"]})
        return f"Great choice! How much {token} are you selling? (e.g., 0.5)"

    elif state == "awaiting_network_sell":
        network = data.get("network", text.upper())
        data["network"] = network
        update_context(user_id, {"state": "awaiting_amount_sell", "data": data, "history": history + ["sell_network"]})
        return f"Got it, USDT on {network}! How much would you like to sell? (e.g., 0.5)"

    elif state == "awaiting_amount_sell":
        try:
            amount = float(text)
            if amount <= 0:
                return "Let’s keep it positive! How much are you selling?"
            data["amount"] = amount
            rate = await fetch_rate_with_retry(data["token"])
            if not rate:
                return "Oops, couldn’t fetch the rate for that token! Try another?"
            fiat_amount = amount * rate - 0.15
            token = data["token"]
            network = data.get("network")
            recipient_address, tag = await fetch_recipient_address(token, network)
            update_context(user_id, {"state": "confirm_sell", "data": data, "history": history + ["sell_amount"]})
            url_base = "sign" if SUPPORTED_TOKENS.get(token, "TON") == "TON" or (token == "USDT" and network == "TON") else "evm" if SUPPORTED_TOKENS.get(token, "TON") == "EVM" or (token == "USDT" and network == "ERC20") else "solana"
            url = f"{TWA_BASE_URL}/{url_base}.html?user_id={user_id}&amount={amount}&token={token}&to={recipient_address}"
            if tag:
                url += f"&tag={tag}"
            keyboard = [
                [InlineKeyboardButton("Send Now", url=url)],
                [InlineKeyboardButton("Cancel", callback_data="cancel_action")]
            ]
            tag_text = f" (Tag: {tag})" if tag else ""
            notify_admin(user_id, amount, token)
            return f"Selling {amount} {token}{f' ({network})' if network else ''} for ${fiat_amount:.2f} (after $0.15 fee). Send to {recipient_address}{tag_text}! {InlineKeyboardMarkup(keyboard)}"
        except ValueError:
            return "Hmm, that wasn’t a number! How much are you selling?"

    elif state == "confirm_sell":
        update_context(user_id, {"state": None, "data": {}, "history": history + ["sell_confirmed"]})
        return "Transaction started! Check the web app. I’m here if you need me! 🚀"

    intent, entities = detect_intent_and_entities(text)
    if intent == "buy":
        token = entities.get("token")
        amount = entities.get("amount")
        network = entities.get("network")
        if token and amount:
            rate = await fetch_rate_with_retry(token)
            if not rate:
                return "Oops, couldn’t fetch the rate for that token! Try another?"
            fiat_amount = amount * rate + 0.15
            if token == "USDT" and not network:
                keyboard = [
                    [InlineKeyboardButton("USDT (ERC20)", callback_data="network_erc20_buy"),
                     InlineKeyboardButton("USDT (TRC20)", callback_data="network_trc20_buy")],
                    [InlineKeyboardButton("USDT (TON)", callback_data="network_ton_buy")]
                ]
                update_context(user_id, {"state": "awaiting_network_buy", "data": {"token": token, "amount": amount}, "history": history + ["buy"]})
                return f"USDT, nice! Which network? {InlineKeyboardMarkup(keyboard)}"
            recipient_address, tag = await fetch_recipient_address(token, network)
            update_context(user_id, {"state": "confirm_buy", "data": {"token": token, "amount": amount, "network": network}, "history": history + ["buy_direct"]})
            url = f"{TWA_BASE_URL}/sign.html?user_id={user_id}&amount={amount}&to={recipient_address}&tid={user_id}"
            if tag:
                url += f"&tag={tag}"
            keyboard = [
                [InlineKeyboardButton("Confirm & Pay", url=url)],
                [InlineKeyboardButton("Cancel", callback_data="cancel_action")]
            ]
            tag_text = f" (Tag: {tag})" if tag else ""
            return f"Buying {amount} {token}{f' ({network})' if network else ''} for ${fiat_amount:.2f} (incl. $0.15 fee). Ready to send to {recipient_address}{tag_text}? {InlineKeyboardMarkup(keyboard)}"
        elif token:
            if token == "USDT":
                keyboard = [
                    [InlineKeyboardButton("USDT (ERC20)", callback_data="network_erc20_buy"),
                     InlineKeyboardButton("USDT (TRC20)", callback_data="network_trc20_buy")],
                    [InlineKeyboardButton("USDT (TON)", callback_data="network_ton_buy")]
                ]
                update_context(user_id, {"state": "awaiting_network_buy", "data": {"token": token}, "history": history + ["buy"]})
                return f"USDT, nice! Which network? {InlineKeyboardMarkup(keyboard)}"
            update_context(user_id, {"state": "awaiting_amount_buy", "data": {"token": token}, "history": history + ["buy"]})
            return f"Nice! How much {token} would you like to buy?"
        else:
            recipient_address, _ = await fetch_recipient_address("TON")
            keyboard = [
                [InlineKeyboardButton("Buy TON", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}&to={recipient_address}"),
                 InlineKeyboardButton("Buy USDT", callback_data="quick_buy_usdt")],
                [InlineKeyboardButton("Buy BTC", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}&to={recipient_address}"),
                 InlineKeyboardButton("More Options", callback_data="more_buy")]
            ]
            update_context(user_id, {"state": "awaiting_token_buy", "data": data, "history": history + ["buy"]})
            return f"Sweet! Pick a token to buy: {InlineKeyboardMarkup(keyboard)}"

    elif intent == "sell":
        token = entities.get("token")
        amount = entities.get("amount")
        network = entities.get("network")
        if token and amount:
            rate = await fetch_rate_with_retry(token)
            if not rate:
                return "Oops, couldn’t fetch the rate for that token! Try another?"
            fiat_amount = amount * rate - 0.15
            if token == "USDT" and not network:
                keyboard = [
                    [InlineKeyboardButton("USDT (ERC20)", callback_data="network_erc20_sell"),
                     InlineKeyboardButton("USDT (TRC20)", callback_data="network_trc20_sell")],
                    [InlineKeyboardButton("USDT (TON)", callback_data="network_ton_sell")]
                ]
                update_context(user_id, {"state": "awaiting_network_sell", "data": {"token": token, "amount": amount}, "history": history + ["sell"]})
                return f"USDT, nice! Which network? {InlineKeyboardMarkup(keyboard)}"
            recipient_address, tag = await fetch_recipient_address(token, network)
            update_context(user_id, {"state": "confirm_sell", "data": {"token": token, "amount": amount, "network": network}, "history": history + ["sell_direct"]})
            url_base = "sign" if SUPPORTED_TOKENS.get(token, "TON") == "TON" or (token == "USDT" and network == "TON") else "evm" if SUPPORTED_TOKENS.get(token, "TON") == "EVM" or (token == "USDT" and network == "ERC20") else "solana"
            url = f"{TWA_BASE_URL}/{url_base}.html?user_id={user_id}&amount={amount}&token={token}&to={recipient_address}"
            if tag:
                url += f"&tag={tag}"
            keyboard = [
                [InlineKeyboardButton("Send Now", url=url)],
                [InlineKeyboardButton("Cancel", callback_data="cancel_action")]
            ]
            tag_text = f" (Tag: {tag})" if tag else ""
            notify_admin(user_id, amount, token)
            return f"Selling {amount} {token}{f' ({network})' if network else ''} for ${fiat_amount:.2f} (after $0.15 fee). Send to {recipient_address}{tag_text}! {InlineKeyboardMarkup(keyboard)}"
        elif token:
            if token == "USDT":
                keyboard = [
                    [InlineKeyboardButton("USDT (ERC20)", callback_data="network_erc20_sell"),
                     InlineKeyboardButton("USDT (TRC20)", callback_data="network_trc20_sell")],
                    [InlineKeyboardButton("USDT (TON)", callback_data="network_ton_sell")]
                ]
                update_context(user_id, {"state": "awaiting_network_sell", "data": {"token": token}, "history": history + ["sell"]})
                return f"USDT, nice! Which network? {InlineKeyboardMarkup(keyboard)}"
            update_context(user_id, {"state": "awaiting_amount_sell", "data": {"token": token}, "history": history + ["sell"]})
            return f"Great! How much {token} are you selling?"
        else:
            recipient_address, _ = await fetch_recipient_address("TON")
            keyboard = [
                [InlineKeyboardButton("Sell TON", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}&to={recipient_address}"),
                 InlineKeyboardButton("Sell USDT", callback_data="quick_sell_usdt")],
                [InlineKeyboardButton("Sell BTC", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}&to={recipient_address}"),
                 InlineKeyboardButton("More Options", callback_data="more_sell")]
            ]
            update_context(user_id, {"state": "awaiting_token_sell", "data": data, "history": history + ["sell"]})
            return f"Got it! Pick a token to sell: {InlineKeyboardMarkup(keyboard)}"

    elif intent == "connect_wallet":
        keyboard = [
            [InlineKeyboardButton("Connect TON", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}"),
             InlineKeyboardButton("Connect EVM", url=f"{TWA_BASE_URL}/evm.html?user_id={user_id}")],
            [InlineKeyboardButton("Connect Solana", url=f"{TWA_BASE_URL}/solana.html?user_id={user_id}")]
        ]
        update_context(user_id, {"state": None, "data": data, "history": history + ["connect_wallet"]})
        return f"Let’s connect your wallet! Pick a network: {InlineKeyboardMarkup(keyboard)}"

    elif intent == "balance":
        balance = await fetch_ton_balance(user_id)
        update_context(user_id, {"state": None, "data": data, "history": history + ["balance"]})
        return f"Checking your balance… Looks like you have {balance or '0'} TON! Want to trade?"

    elif intent == "price":
        token = entities.get("token")
        if token:
            rate = await fetch_rate_with_retry(token)
            if not rate:
                return "Sorry, I couldn’t fetch the price for that token! Try another?"
            update_context(user_id, {"state": None, "data": data, "history": history + ["price"]})
            return f"{token} is at ${rate:.2f} right now! Want a chart?"
        return "Tell me which token’s price you want to check!"

    elif intent == "chart":
        token = entities.get("token")
        if token:
            update_context(user_id, {"state": None, "data": data, "history": history + ["chart"]})
            return f"Opening a chart for {token}… Check your browser! (Simulated: {TWA_BASE_URL}/chart.html)"
        return "Which token’s chart would you like to see?"

    elif intent == "help":
        keyboard = [
            [InlineKeyboardButton("Buy", callback_data="quick_buy")],
            [InlineKeyboardButton("Sell", callback_data="quick_sell")],
            [InlineKeyboardButton("Balance", callback_data="quick_balance")]
        ]
        update_context(user_id, {"state": None, "data": data, "history": history + ["help"]})
        return f"I’m here to help! You can buy/sell crypto, check prices, see charts, or connect your wallet. Pick an action: {InlineKeyboardMarkup(keyboard)}"

    elif intent == "greeting":
        update_context(user_id, {"state": None, "data": data, "history": history + ["greeting"]})
        return f"{random.choice(greetings)} It’s {datetime.now().strftime('%I:%M %p WAT, %B %d, %Y')}. Ready to dive into crypto?"

    elif intent == "thanks":
        update_context(user_id, {"state": None, "data": data, "history": history + ["thanks"]})
        return random.choice(thanks_replies)

    elif intent == "exit":
        update_context(user_id, {"state": None, "data": {}, "history": history + ["exit"]})
        return random.choice(exit_replies)

    elif intent == "about":
        update_context(user_id, {"state": None, "data": data, "history": history + ["about"]})
        return "I’m GigiP2Bot, your cosmic crypto guide! I can help you buy, sell, check prices, and more. What do you want to do?"

    elif intent == "time":
        update_context(user_id, {"state": None, "data": data, "history": history + ["time"]})
        return f"It’s {datetime.now().strftime('%I:%M %p WAT, %B %d, %Y')}. What’s on your mind?"

    elif intent == "cancel":
        update_context(user_id, {"state": None, "data": {}, "history": history + ["cancel"]})
        return "Okay, I’ve canceled that for you! What’s next?"

    past_intents = [h for h in history if h not in ["greeting", "thanks", "exit", "conversation", "cancel"]]
    if past_intents and "sell" in past_intents[-3:] and entities.get("token"):
        update_context(user_id, {"state": "awaiting_amount_sell", "data": {"token": entities["token"]}, "history": history + ["sell"]})
        return f"Do you want to sell more {entities['token']}? How much?"
    suggestions = ["buy", "sell", "balance", "price", "chart"]
    if past_intents:
        suggestions = [s for s in suggestions if s not in past_intents[-2:]]
    suggestions = suggestions[:3] if len(suggestions) >= 3 else suggestions
    keyboard = [[InlineKeyboardButton(s.capitalize(), callback_data=f"quick_{s}")] for s in suggestions]
    update_context(user_id, {"state": None, "data": data, "history": history + ["conversation"]})
    return f"I’m not sure what you mean! Maybe try {', '.join(suggestions[:-1])} or {suggestions[-1]}? Pick an action: {InlineKeyboardMarkup(keyboard)}"

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit(update.effective_user.id, update.message.from_user.id):
        await update.message.reply_text(escape_markdown("Whoa, slow down, cosmic traveler! 🌠"), parse_mode="MarkdownV2")
        return
    user_id = update.effective_user.id
    async with AsyncSessionFactory() as db_session:
        try:
            user = await init_user(user_id, db_session)
            keyboard = [
                [InlineKeyboardButton("💎 Connect TON", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}"),
                 InlineKeyboardButton("🌐 Connect EVM", url=f"{TWA_BASE_URL}/evm.html?user_id={user_id}")],
                [InlineKeyboardButton("☀️ Connect Solana", url=f"{TWA_BASE_URL}/solana.html?user_id={user_id}")]
            ]
            await update.message.reply_text(
                escape_markdown(f"🌌 Good evening {update.message.from_user.first_name}! I’m GigiP2Bot, your crypto guide! Connect a wallet or say ‘buy TON’! ✨"),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2"
            )
        except Exception as e:
            logger.error(f"Start command failed: {e}")
            await update.message.reply_text(escape_markdown("Oops! Cosmic glitch! Try again? 😅"), parse_mode="MarkdownV2")

async def set_tone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("😜 Playful", callback_data="tone_playful")],
        [InlineKeyboardButton("💼 Professional", callback_data="tone_professional")],
        [InlineKeyboardButton("😊 Friendly", callback_data="tone_friendly")]
    ]
    await update.message.reply_text(
        escape_markdown("🌟 Pick my vibe!"),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )

async def tone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tone = query.data.split("_")[1]
    async with AsyncSessionFactory() as db_session:
        try:
            async with db_session.begin():
                user = await db_session.get(User, query.from_user.id)
                user.tone = tone
                await db_session.commit()
            await query.edit_message_text(
                escape_markdown(f"🌠 Vibe set to {tone}! How can I help?"),
                parse_mode="MarkdownV2"
            )
        except SQLAlchemyError as e:
            logger.error(f"Tone update failed: {e}")
            await query.edit_message_text(escape_markdown("😅 Vibe change failed! Try again?"), parse_mode="MarkdownV2")

async def quick_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action = query.data.split("_")[1]
    context_data = get_context(user_id)
    history = context_data.get("history", [])
    data = context_data.get("data", {})

    if action == "buy":
        recipient_address, _ = await fetch_recipient_address("TON")
        keyboard = [
            [InlineKeyboardButton("Buy TON", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}&to={recipient_address}"),
             InlineKeyboardButton("Buy USDT", callback_data="quick_buy_usdt")],
            [InlineKeyboardButton("Buy BTC", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}&to={recipient_address}"),
             InlineKeyboardButton("More Options", callback_data="more_buy")]
        ]
        update_context(user_id, {"state": "awaiting_token_buy", "data": {}, "history": history + ["buy"]})
        await query.edit_message_text(
            escape_markdown("Sweet! Pick a token to buy: ") + InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2"
        )
    elif action == "sell":
        recipient_address, _ = await fetch_recipient_address("TON")
        keyboard = [
            [InlineKeyboardButton("Sell TON", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}&to={recipient_address}"),
             InlineKeyboardButton("Sell USDT", callback_data="quick_sell_usdt")],
            [InlineKeyboardButton("Sell BTC", url=f"{TWA_BASE_URL}/sign.html?user_id={user_id}&to={recipient_address}"),
             InlineKeyboardButton("More Options", callback_data="more_sell")]
        ]
        update_context(user_id, {"state": "awaiting_token_sell", "data": {}, "history": history + ["sell"]})
        await query.edit_message_text(
            escape_markdown("Got it! Pick a token to sell: ") + InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2"
        )
    elif action == "buy_usdt" or action == "sell_usdt":
        intent = "buy" if "buy" in query.data else "sell"
        keyboard = [
            [InlineKeyboardButton(f"USDT (ERC20)", callback_data=f"network_erc20_{intent}"),
             InlineKeyboardButton(f"USDT (TRC20)", callback_data=f"network_trc20_{intent}")],
            [InlineKeyboardButton(f"USDT (TON)", callback_data=f"network_ton_{intent}")]
        ]
        update_context(user_id, {"state": f"awaiting_network_{intent}", "data": {"token": "USDT"}, "history": history + [intent]})
        await query.edit_message_text(
            escape_markdown(f"USDT, nice! Which network to {intent}? ") + InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2"
        )
    elif action.startswith("network_"):
        parts = query.data.split("_")
        network = parts[1].upper()
        intent = parts[2]
        data["token"] = "USDT"
        data["network"] = network
        update_context(user_id, {"state": f"awaiting_amount_{intent}", "data": data, "history": history + [f"{intent}_network"]})
        await query.edit_message_text(
            escape_markdown(f"Got it, USDT on {network}! How much would you like to {intent}? (e.g., 1.5)"),
            parse_mode="MarkdownV2"
        )
    elif action == "balance":
        balance = await fetch_ton_balance(user_id)
        update_context(user_id, {"state": None, "data": {}, "history": history + ["balance"]})
        await query.edit_message_text(
            escape_markdown(f"Checking your balance… Looks like you have {balance or '0'} TON! Want to trade?"),
            parse_mode="MarkdownV2"
        )
    elif action == "cancel_action":
        update_context(user_id, {"state": None, "data": {}, "history": history + ["cancel"]})
        await query.edit_message_text(
            escape_markdown("Okay, I’ve canceled that for you! What’s next?"),
            parse_mode="MarkdownV2"
        )
    elif action in ["more_buy", "more_sell"]:
        intent = "buy" if action == "more_buy" else "sell"
        token_to_fetch = data.get("token", "TON")
        recipient_address, tag = await fetch_recipient_address(token_to_fetch)
        url_base = "sign" if SUPPORTED_TOKENS.get(token_to_fetch, "TON") == "TON" else "evm" if SUPPORTED_TOKENS.get(token_to_fetch, "TON") == "EVM" else "solana"
        keyboard = [
            [InlineKeyboardButton(f"{intent.capitalize()} {t}", url=f"{TWA_BASE_URL}/{url_base}.html?user_id={user_id}&to={recipient_address}") for t in list(SUPPORTED_TOKENS.keys())[3:6]],
            [InlineKeyboardButton("Back", callback_data=f"quick_{intent}")]
        ]
        update_context(user_id, {"state": f"awaiting_token_{intent}", "data": {"token": data.get("token")}, "history": history + [intent]})
        await query.edit_message_text(
            escape_markdown(f"More {intent} options: ") + InlineKeyboardMarkup(keyboard),
            parse_mode="MarkdownV2"
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await rate_limit(update.effective_user.id, update.message.from_user.id):
        await update.message.reply_text(escape_markdown("🌠 Too fast! Take a breath!"), parse_mode="MarkdownV2")
        return
    user_id = update.effective_user.id
    message = update.message.text
    response = await handle_conversation(user_id, message)
    await update.message.reply_text(escape_markdown(response), parse_mode="MarkdownV2")

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_tone", set_tone))
    app.add_handler(CallbackQueryHandler(tone_callback, pattern="tone_"))
    app.add_handler(CallbackQueryHandler(quick_action_callback, pattern="quick_|cancel_action|more_|network_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
