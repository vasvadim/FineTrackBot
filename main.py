import requests
from bs4 import BeautifulSoup
import re
import unicodedata
import json
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackContext, JobQueue
import ssl
import certifi
import asyncio
import logging

ASK_TICKERS = 1
TOKEN = '7860372015:AAE7RF8YoLcLSAH0Q2C0JCDHTWsxF2-Yzjk'

user_data = {}
ticker_idx = {}
 
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

def binarySearch(arr, target):
    l = 0
    r = len(arr)-1
    while l <= r:
        mid = l + (r-l)//2

        if arr[mid][0] == target:
            return mid
        elif arr[mid][0] < target:
            l = mid+1
        else:
            r = mid-1
    return -1  

async def price(ticker: str, update: Update):
    ticker = ticker if ticker else update.message.text.strip().upper()
    url = 'https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json'
    response = requests.get(url)

    if response.status_code != 200:
        await update.message.reply_text("Failed to fetch data from the server.")
        return
    data = response.json()

    if ticker not in ticker_idx:
        ticker_idx[ticker] = binarySearch(data["marketdata"]["data"], ticker)
    idx = ticker_idx.get(ticker, -1)

    if idx != -1:
        ticker_info = data["marketdata"]["data"][idx]
    else:
        await update.message.reply_text("Ticker does not found.")
    
    try:
        price = ticker_info[2]
        currency = "RUB"
        ticker = ticker_info[0]

        if price is not None:
            await update.message.reply_text(f"{ticker} price: {price} {currency}")
        else:
            await update.message.reply_text(f"{ticker} price not available.")
    except IndexError:
        await update.message.reply_text("Error: Data for ticker is incomplete or invalid.")

async def addPrompt(update: Update, context: CallbackContext) -> int:
    context.user_data["action"] = "add"  # Store action type
    await update.message.reply_text("Please enter the tickers you want to add:")
    return ASK_TICKERS

async def deletePrompt(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    if user_id not in user_data or not user_data[user_id].get("tickers", None):
        await update.message.reply_text("You have no tracked tickers yet. Add them at first!")
        return ConversationHandler.END

    context.user_data["action"] = "delete"  # Store action type
    await update.message.reply_text("Please enter the tickers you want to delete:")
    return ASK_TICKERS

async def pricePrompt(update: Update, context: CallbackContext) -> int:
    context.user_data["action"] = "price"  # Store action type
    await update.message.reply_text("Please enter the ticker whose price you want to find out:")
    return ASK_TICKERS

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {}
    
    # Initialize tickers for this user if not set
    tickers = user_data[user_id].setdefault("tickers", set())
    newTickers = set(ticker.strip().upper() for ticker in update.message.text.split(","))
    tickers.update(newTickers)  

    # Access the tickers correctly using "tickers" instead of ["tickers"]
    await update.message.reply_text(f"Your updated tickers are: {', '.join(tickers)}")

    return ConversationHandler.END  # End the conversation

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    tickers = user_data[user_id]["tickers"]
    toDel = list(ticker.strip().upper() for ticker in update.message.text.split(","))
    for ticker in toDel:
        tickers.discard(ticker)  # Use discard to safely remove tickers

    await update.message.reply_text(f"Your updated tickers are: {', '.join(tickers)}")
    return ConversationHandler.END  # End the conversation

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id].get("tickers", set()).clear()

    await update.message.reply_text("List of tracked tickers has been cleared.")

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {}

    # Initialize the tickers set if not already set
    tickers = user_data[user_id].setdefault("tickers", set())

    if tickers:
        await update.message.reply_text(f"Your tracking tickers are:\n")
        for ticker in tickers:
            await price(ticker, update)
    else:
        await update.message.reply_text("You have no tracking tickers.")

async def getPrice(ticker: str, update: Update):
    ticker = ticker
    url = 'https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json'
    response = requests.get(url)

    if response.status_code != 200:
        await update.message.reply_text("Failed to fetch data from the server.")
        return
    data = response.json()

    if ticker not in ticker_idx:
        ticker_idx[ticker] = binarySearch(data["marketdata"]["data"], ticker)
    idx = ticker_idx.get(ticker, -1)

    if idx != -1:
        ticker_info = data["marketdata"]["data"][idx]
    else:
        await update.message.reply_text("Ticker does not found.")
    
    try:
        price = ticker_info[2]
        currency = "RUB"
        ticker = ticker_info[0]

        if price is not None:
            return price
    except IndexError:
        await update.message.reply_text("Error: Data for ticker is incomplete or invalid.")

async def periodCheck(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.user_id
    update = context.job.data
    if user_id not in user_data:
        user_data[user_id] = {}

    if user_id and user_data[user_id].get("tickers", -1) != -1:
        for ticker in user_data[user_id]["tickers"]:
            prices = user_data[user_id].setdefault("prices", dict())
            curr_price = await getPrice(ticker, update)
            prev_price = prices.setdefault(ticker, curr_price)
            
            if prev_price and curr_price:
                change = round(prev_price / curr_price, 3)
                if change >= 1.010 or change <= 0.990:
                    await context.bot.send_message(user_id, text=f"{ticker} price changed from {prev_price} to " + 
                    f"{curr_price} ({round(100*abs(change-1), 3)}%) in 5 minutes. Check it!") 

            user_data[user_id]["prices"][ticker] = curr_price

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hello! I am your FineTrackBot. I'll help you to track some data about your stocks "
                                    "and inform you if some of stocks have increased their prices significantly during "
                                    "small period of time. Just let me know, which tickers you are interested in.")
    context.job_queue.run_repeating(periodCheck, interval=300, first=60, data=update, user_id=update.message.from_user.id)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

async def handleTickers(update: Update, context: CallbackContext) -> int:
    action = context.user_data.get("action")  # Retrieve stored action type

    if action == "add":
        await add(update, context)
    elif action == "delete":
        await delete(update, context)
    elif action == "price":
        await price(None, update)
    else:
        await update.message.reply_text("Unknown action.")
    
    return ConversationHandler.END  # End the conversation

# Main function to run the bot
def main():
    # Replace 'YOUR_TOKEN' with the token you got from BotFather
    application = Application.builder().token(TOKEN).build()


        # Define the conversation handler
    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler("add", addPrompt), 
            CommandHandler("delete", deletePrompt),
            CommandHandler("price", pricePrompt)
        ],  # Command to start the conversation
        states={
            ASK_TICKERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handleTickers)],  # State to capture tickers
        },
        fallbacks=[CommandHandler("cancel", cancel)],  # Command to cancel the conversation
    )


    # Register the /start command handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check))
    application.add_handler(CommandHandler("clear", clear))
    application.add_handler(conversation_handler)

    # Start the bot
    application.run_polling()

main()

