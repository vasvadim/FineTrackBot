import requests
from bs4 import BeautifulSoup
import re
import unicodedata
import json
import aiohttp
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackContext, JobQueue
import ssl
import certifi
import asyncio
import logging
import pandas as pd
import matplotlib.pyplot as plt
import csv
import io
from datetime import datetime
import os
from dotenv import load_dotenv



load_dotenv()

ASK_TICKERS = 1
TOKEN = os.getenv("API_KEY")

if TOKEN:
    print("Token found")
else:
    print("Token not found. Please set the TOKEN .env variable.")

user_data = {}
 
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

def writeCSV(new_data, max_rows):
    # Define column names
    columns = ['Ticker', 'Price', 'Datetime']
    
    # Convert new_data to a DataFrame
    new_row = pd.DataFrame([new_data], columns=columns)
    
    try:
        # Load existing data
        df = pd.read_csv("data.csv")
    except FileNotFoundError:
        # If the file doesn't exist, create a new DataFrame
        df = pd.DataFrame(columns=columns)
    
    # Append new row
    if df.empty:
        df = new_row  # If df is empty, directly assign new_row
    else:
        df = pd.concat([df, new_row], ignore_index=True)
    
    # Remove oldest rows if the maximum size is exceeded
    if len(df) > max_rows:
        df = df.tail(max_rows)  # Keep only the last max_rows rows
    
    # Save the updated DataFrame to CSV
    df.to_csv("data.csv", index=False)

async def errorHandler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the user."""
    print(f"Error occurred: {context.error}")
    if update and update.message:
        await update.message.reply_text("An error occurred. Please try again later.")

async def price(ticker: str, update: Update):
    ticker = ticker if ticker else update.message.text.strip().upper()
    url = 'https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json'
    response = requests.get(url)

    if response.status_code != 200:
        await update.message.reply_text("Failed to fetch data from the server.")
        return
    data = response.json()
    idx = binarySearch(data["marketdata"]["data"], ticker)

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

async def plotPrompt(update: Update, context: CallbackContext) -> int:
    context.user_data["action"] = "plot"
    await update.message.reply_text("Please enter tracked tickers whose plot you want to look at:")
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
    if "job_started" not in context.user_data:
        context.job_queue.run_repeating(periodCheck, interval=300, first=60, data=update, user_id=update.message.from_user.id)
        context.user_data["job_started"] = True
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
    idx = binarySearch(data["marketdata"]["data"], ticker)

    if idx != -1:
        ticker_info = data["marketdata"]["data"][idx]
    else:
        await update.message.reply_text("Ticker does not found.")
    
    try:
        price = ticker_info[2]
        datetime = ticker_info[47]
        currency = "RUB"
        ticker = ticker_info[0]

        if price is not None:
            return price, datetime[:-3]
    except IndexError:
        await update.message.reply_text("Error: Data for ticker is incomplete or invalid.")

async def periodCheck(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.user_id
    update = context.job.data
    if user_id not in user_data:
        user_data[user_id] = {}

    if user_id and user_data[user_id].get("tickers", -1) != -1:
        max_rows = (7*24*60)//5 * len(user_data[user_id]["tickers"])
        prices = user_data[user_id].setdefault("prices", dict())
        for ticker in user_data[user_id]["tickers"]:
            curr_price, datetime = await getPrice(ticker, update)
            prev_price = prices.setdefault(ticker, curr_price)
            
            if prev_price and curr_price:
                writeCSV([ticker, curr_price, datetime], max_rows)

                change = round(prev_price / curr_price, 3)
                if change >= 1.010 or change <= 0.990:
                    await context.bot.send_message(user_id, text=f"{ticker} price changed from {prev_price} to " + 
                    f"{curr_price} ({round(100*abs(change-1), 3)}%) in 5 minutes. Check it!") 

            user_data[user_id]["prices"][ticker] = curr_price if curr_price is not None else prev_price

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hello! I am your FineTrackBot. I'll help you to track some data about your stocks "
                                    "and inform you if some of stocks have increased their prices significantly during "
                                    "small period of time. Just let me know, which tickers you are interested in.")

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
    elif action == "plot":
        await plot(update, context)
    else:
        await update.message.reply_text("Unknown action.")
    
    return ConversationHandler.END  # End the conversation

async def plot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {}

    tickers = set(ticker.strip().upper() for ticker in update.message.text.split(","))
    if tickers:
        df = pd.read_csv("data.csv")
        df['Datetime'] = pd.to_datetime(df["Datetime"], format='%Y-%m-%d %H:%M')

        df_sorted = df.sort_values(by=['Ticker', 'Datetime'])
        grouped = df_sorted.groupby('Ticker')

        fig, axs = plt.subplots(len(tickers), figsize=(24,30))   

        counter = 0
        for ticker, group in grouped:
            if ticker in tickers:
                x = group["Datetime"][:2016]
                y = group["Price"][:2016]

                if len(tickers) > 1:
                    axs[counter].plot(x, y, label=f"{ticker}")
                    axs[counter].set_xlabel("Datetime", fontsize=24)
                    axs[counter].set_ylabel(r"Price", fontsize=24)
                    axs[counter].tick_params(axis='both', labelsize=24) 
                    axs[counter].legend(loc='best', fontsize=30)
                    axs[counter].grid()
                else:
                    axs.plot(x, y, label=f"{ticker}")
                    axs.set_xlabel("Datetime", fontsize=24)
                    axs.set_ylabel(r"Price", fontsize=24)
                    axs.tick_params(axis='both', labelsize=24) 
                    axs.legend(loc='best', fontsize=30)
                    axs.grid()
                plt.tight_layout()
                counter += 1
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)

        await context.bot.send_photo(user_id, photo=InputFile(buf))

        buf.close()

    else:
        await update.message.reply_text("You have no tracked tickers.")
    

def main():
    application = Application.builder().token(TOKEN).build()


    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler("add", addPrompt), 
            CommandHandler("delete", deletePrompt),
            CommandHandler("price", pricePrompt),
            CommandHandler("plot", plotPrompt)
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

    application.add_error_handler(errorHandler)

    # Start the bot
    application.run_polling()

main()