import os
import logging
import asyncio
import random
from datetime import datetime, timedelta
from functools import wraps
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "YOUR_ADMIN_ID"))
TRIAL_USERS = set()
SUBSCRIBED_USERS = {}
USER_TWILIO_CREDS = {}  # {user_id: {'sid': '', 'token': '', 'account_name': '', 'balance': ''}}
PURCHASED_NUMBERS = {}   # {user_id: {'number': '', 'sid': '', 'purchase_date': ''}}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Subscription Plans
PLANS = {
    "free_1h": {"label": "🎉 1 Hour - Free 🌸", "duration": 1, "price": 0},
    "1d": {"label": "🔴 1 Day - 2$", "duration": 24, "price": 2},
    "7d": {"label": "🟠 7 Day - 10$", "duration": 24*7, "price": 10},
    "15d": {"label": "🟡 15 Day - 15$", "duration": 24*15, "price": 15},
    "30d": {"label": "🟢 30 Day - 20$", "duration": 24*30, "price": 20}
}

VALID_CANADA_AREA_CODES = [
    "204", "226", "236", "249", "250", "289", "306", "343", "365", "403",
    "416", "418", "431", "437", "438", "450", "506", "514", "519", "579",
    "581", "587", "604", "613", "639", "647", "672", "705", "709", "778",
    "780", "807", "819", "825", "867", "873", "902", "905"
]

# Decorator to check subscription
def check_subscription(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Admin bypass
        if user_id == ADMIN_ID:
            return await func(update, context)
            
        # Check subscription
        if user_id in SUBSCRIBED_USERS and SUBSCRIBED_USERS[user_id] > datetime.utcnow():
            return await func(update, context)
        else:
            buttons = [[InlineKeyboardButton(plan["label"], callback_data=key)] for key, plan in PLANS.items()]
            markup = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(
                "⚠️ আপনার Subscription একটিভ নেই! বট ব্যবহার করতে Subscription নিন:",
                reply_markup=markup
            )
    return wrapper

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if user_id in SUBSCRIBED_USERS and SUBSCRIBED_USERS[user_id] > datetime.utcnow():
        expiry_date = SUBSCRIBED_USERS[user_id]
        remaining = expiry_date - datetime.utcnow()
        days = remaining.days
        hours = remaining.seconds // 3600
        
        await update.message.reply_text(
            f"স্বাগতম {user.first_name}!\n\n"
            f"✅ আপনার Subscription একটিভ আছে!\n"
            f"⏳ মেয়াদ শেষ হবে: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"⏳ বাকি সময়: {days} দিন {hours} ঘন্টা\n\n"
            f"নতুন নাম্বার কিনতে /buy কমান্ড ব্যবহার করুন"
        )
    else:
        buttons = [[InlineKeyboardButton(plan["label"], callback_data=key)] for key, plan in PLANS.items()]
        markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            "আপনার Subscriptions চালু নেই ♻️ চালু করার জন্য নিচের Subscription Choose করুন ✅",
            reply_markup=markup
        )

async def handle_plan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    choice = query.data

    await query.message.delete()

    if choice == "free_1h":
        if user_id in TRIAL_USERS:
            await query.message.reply_text("⚠️ আপনি একবার ফ্রি ট্রায়াল নিয়েছেন। দয়া করে পেইড প্ল্যান ব্যবহার করুন।")
            return
        TRIAL_USERS.add(user_id)
        SUBSCRIBED_USERS[user_id] = datetime.utcnow() + timedelta(hours=1)
        await query.message.reply_text("✅ 1 ঘন্টার জন্য ফ্রি ট্রায়াল সক্রিয় করা হলো।")
        return

    plan = PLANS[choice]
    text = f"Please send ${plan['price']} to Binance Pay ID:\n"
    text += f"\nপেমেন্ট করে প্রমান হিসাবে Admin এর কাছে স্কিনশর্ট অথবা transaction ID দিন @Mr_Evan3490"
    text += f"\n\nYour payment details:\n"
    text += f"❄️ Name : {user.first_name}\n🆔 User ID: {user.id}\n👤 Username: @{user.username}\n📋 Plan: {plan['label']}\n💰 Amount: ${plan['price']}"

    await query.message.reply_text(text)

    notify_text = (
        f"{user.first_name} {plan['duration']} ঘন্টার Subscription নিতে চাচ্ছে।\n\n"
        f"🔆 User Name : {user.first_name}\n"
        f"🔆 User ID : {user_id}\n"
        f"🔆 Username : @{user.username}"
    )
    buttons = [
        [
            InlineKeyboardButton("Approve ✅", callback_data=f"approve|{user_id}|{choice}"),
            InlineKeyboardButton("Cancel ❌", callback_data=f"cancel|{user_id}")
        ]
    ]
    await context.bot.send_message(chat_id=ADMIN_ID, text=notify_text, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    action = data[0]
    user_id = int(data[1])

    if action == "approve":
        plan_key = data[2]
        plan = PLANS[plan_key]
        SUBSCRIBED_USERS[user_id] = datetime.utcnow() + timedelta(hours=plan["duration"])
        await context.bot.send_message(chat_id=user_id, text=f"✅ আপনার {plan['label']} Subscription চালু হয়েছে।")
        await query.edit_message_text(f"✅ {user_id} ইউজারের Subscription Approved.")

    elif action == "cancel":
        await context.bot.send_message(chat_id=user_id, text="❌ আপনার Subscription অনুরোধ বাতিল করা হয়েছে।")
        await query.edit_message_text(f"❌ {user_id} ইউজারের Subscription বাতিল করা হয়েছে।")

@check_subscription
async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = [[InlineKeyboardButton("Login 🔒", callback_data="login_prompt")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Login করতে নিচের বাটনে ক্লিক করুন",
        reply_markup=reply_markup
    )

async def handle_login_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    await query.message.reply_text(
        "আপনার Twilio Sid এবং Auth Token দিন ✅\nব্যবহার: <sid> <auth>"
    )

@check_subscription
async def handle_twilio_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    
    if len(text.split()) != 2:
        await update.message.reply_text("❌ ভুল ফরম্যাট! সঠিক ফরম্যাট: <sid> <auth>")
        return
    
    sid, auth = text.split()
    
    try:
        # Test Twilio credentials
        twilio_client = Client(sid, auth)
        account = twilio_client.api.accounts(sid).fetch()
        balance = float(twilio_client.balance.fetch().balance)
        
        # Store credentials
        USER_TWILIO_CREDS[user.id] = {
            'sid': sid,
            'token': auth,
            'account_name': account.friendly_name,
            'balance': balance
        }
        
        # Success message
        response = (
            f"🎉 𝐋𝐨𝐠 𝐈𝐧 𝐒𝐮𝐜𝐜𝐞𝐬𝐬𝐟𝐮𝐥🎉\n"
            f"⭕ 𝗔𝗰𝗰𝗼𝘂𝗻𝘁 𝗡𝗮𝗺𝗲 : {account.friendly_name}\n"
            f"⭕ 𝗔𝗰𝗰𝗼𝘂𝗻𝘁 𝗕𝗮𝗹𝗮𝗻𝗰𝗲 : ${balance:.2f}\n\n"
            f"বিঃদ্রঃ নাম্বার কিনার আগে ব্যালেন্স চেক করে নিবেন ♻️\n"
            f"Founded By 𝗠𝗿 𝗘𝘃𝗮𝗻 🍁"
        )
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Twilio login failed: {e}")
        await update.message.reply_text("❌ লগইন ব্যর্থ! টোকেন সঠিক কিনা চেক করুন আবার চেষ্টা করুন")

@check_subscription
async def subscription_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if user_id in SUBSCRIBED_USERS:
        expiry_date = SUBSCRIBED_USERS[user_id]
        remaining = expiry_date - datetime.utcnow()
        days = remaining.days
        hours = remaining.seconds // 3600
        
        await update.message.reply_text(
            f"✅ আপনার Subscription একটিভ আছে!\n"
            f"⏳ মেয়াদ শেষ হবে: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"⏳ বাকি সময়: {days} দিন {hours} ঘন্টা"
        )
    else:
        buttons = [[InlineKeyboardButton(plan["label"], callback_data=key)] for key, plan in PLANS.items()]
        markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            "⚠️ আপনার Subscription একটিভ নেই! বট ব্যবহার করতে Subscription নিন:",
            reply_markup=markup
        )

@check_subscription
async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if user has Twilio credentials
    if user_id not in USER_TWILIO_CREDS:
        await update.message.reply_text("❌ প্রথমে Twilio credentials লগইন করুন /login কমান্ড দিয়ে")
        return
    
    try:
        twilio_client = Client(USER_TWILIO_CREDS[user_id]['sid'], USER_TWILIO_CREDS[user_id]['token'])
        
        # Check area code if provided
        area_code = context.args[0] if context.args else None
        if area_code and (not area_code.isdigit() or len(area_code) != 3 or area_code not in VALID_CANADA_AREA_CODES):
            await update.message.reply_text("❌ ভুল Area Code! সঠিক 3-digit Canadian area code দিন")
            return

        # Get available numbers from Twilio (now fetching 10 numbers)
        available_numbers = twilio_client.available_phone_numbers('CA') \
                                        .local \
                                        .list(area_code=area_code, limit=10)  # Changed from 20 to 10
        
        if not available_numbers:
            await update.message.reply_text("❌ এই মুহূর্তে কোনো নাম্বার পাওয়া যাচ্ছে না। পরে আবার চেষ্টা করুন")
            return
        
        # Prepare number list
        numbers = [num.phone_number for num in available_numbers]
        numbers_text = "\n".join([f"{i+1}. {num}" for i, num in enumerate(numbers)])
        
        message = await update.message.reply_text(
            f"🇨🇦 উপলব্ধ কানাডা নাম্বার লিস্ট (১০টি):\n\n{numbers_text}\n\n"
            "কোন নাম্বারটি কিনতে চান? নিচের বাটনে ক্লিক করুন:"
        )
        
        # Create buttons for each available number
        buttons = []
        for i, number in enumerate(numbers):
            buttons.append([InlineKeyboardButton(f"{i+1}. {number}", callback_data=f"buy_{number}")])
        
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=message.message_id,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    except TwilioRestException as e:
        logger.error(f"Twilio error: {e}")
        await update.message.reply_text(f"❌ Twilio এরর: {e.msg}")
    except Exception as e:
        logger.error(f"Error in buy command: {e}")
        await update.message.reply_text("❌ নাম্বার লিস্ট দেখাতে সমস্যা হয়েছে! আবার চেষ্টা করুন")

async def handle_number_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    number = query.data.split("_")[1]
    
    try:
        twilio_client = Client(USER_TWILIO_CREDS[user_id]['sid'], USER_TWILIO_CREDS[user_id]['token'])
        
        # Check balance first
        balance = float(twilio_client.balance.fetch().balance)
        if balance < 1.00:
            await query.message.reply_text(f"❌ আপনার Twilio একাউন্টে পর্যাপ্ত ব্যালেন্স নেই। বর্তমান ব্যালেন্স: ${balance:.2f}")
            return
        
        # Delete old number if exists
        if user_id in PURCHASED_NUMBERS:
            try:
                old_number_sid = PURCHASED_NUMBERS[user_id]['sid']
                twilio_client.incoming_phone_numbers(old_number_sid).delete()
                logger.info(f"Deleted old number SID: {old_number_sid}")
            except Exception as e:
                logger.error(f"Error deleting old number: {e}")
        
        # Purchase new number
        purchased_number = twilio_client.incoming_phone_numbers.create(phone_number=number)
        
        # Store new number info
        PURCHASED_NUMBERS[user_id] = {
            'number': number,
            'sid': purchased_number.sid,
            'purchase_date': datetime.utcnow()
        }
        
        # Update balance
        new_balance = balance - 1.00
        USER_TWILIO_CREDS[user_id]['balance'] = new_balance
        
        # Prepare response
        keyboard = [
            [InlineKeyboardButton("📧 Check Messages ✉️", callback_data=f"check_msg_{number}")],
            [InlineKeyboardButton("ℹ️ Number Info", callback_data=f"number_info_{number}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        response_text = (
            f"✅ নাম্বার সফলভাবে কেনা হয়েছে!\n\n"
            f"📞 নাম্বার: {number}\n"
            f"💰 খরচ: $1.00\n"
            f"📊 নতুন ব্যালেন্স: ${new_balance:.2f}\n"
            f"🕒 কেনার সময়: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        # If old number existed, add info about deletion
        if user_id in PURCHASED_NUMBERS:
            response_text += "\n\nℹ️ আপনার পূর্বের নাম্বারটি অটোমেটিক ডিলিট করা হয়েছে"
        
        await query.message.reply_text(
            response_text,
            reply_markup=reply_markup
        )
        
    except TwilioRestException as e:
        error_msg = f"Twilio Error ({e.code}): {e.msg}"
        logger.error(f"Number purchase failed: {error_msg}")
        
        if e.code == 20404:
            await query.message.reply_text("❌ এই নাম্বারটি এখন পাওয়া যাচ্ছে না। নতুন করে /buy কমান্ড দিয়ে চেষ্টা করুন")
        elif e.code == 21215:
            await query.message.reply_text("❌ এই নাম্বার কেনার জন্য আপনার একাউন্টে অনুমতি নেই")
        else:
            await query.message.reply_text(f"❌ Twilio এরর: {e.msg}")
            
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await query.message.reply_text("❌ নাম্বার কেনার সময় অপ্রত্যাশিত সমস্যা হয়েছে! আবার চেষ্টা করুন")

async def check_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    number = query.data.split("_")[2]
    
    try:
        twilio_client = Client(USER_TWILIO_CREDS[user_id]['sid'], USER_TWILIO_CREDS[user_id]['token'])
        
        # Get recent messages for this number
        messages = twilio_client.messages.list(to=number, limit=1)
        
        if messages:
            # Show the latest message
            msg = messages[0]
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=f"📨 নতুন মেসেজ:\n\nFrom: {msg.from_}\n\n{msg.body}"
            )
        else:
            # No messages found
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="❌ কোনো মেসেজ পাওয়া যায় নি"
            )
            
            # Revert back after 5 seconds
            await asyncio.sleep(5)
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=f"✅ নাম্বার: {number}\n\n"
                     "মেসেজ চেক করতে নিচের বাটনে ক্লিক করুন:",
                reply_markup=query.message.reply_markup
            )
            
    except Exception as e:
        logger.error(f"Error checking messages: {e}")
        await query.message.reply_text("❌ মেসেজ চেক করার সময় সমস্যা হয়েছে!")

async def number_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    number = query.data.split("_")[2]
    
    if user_id not in PURCHASED_NUMBERS or PURCHASED_NUMBERS[user_id]['number'] != number:
        await query.message.reply_text("❌ এই নাম্বারটি আপনার কেনা নাম্বারের লিস্টে নেই")
        return
    
    try:
        twilio_client = Client(USER_TWILIO_CREDS[user_id]['sid'], USER_TWILIO_CREDS[user_id]['token'])
        number_details = twilio_client.incoming_phone_numbers(PURCHASED_NUMBERS[user_id]['sid']).fetch()
        
        info_text = (
            f"📞 নাম্বার ডিটেইলস:\n\n"
            f"🔢 নাম্বার: {number}\n"
            f"📅 কেনার তারিখ: {PURCHASED_NUMBERS[user_id]['purchase_date'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🆔 SID: {number_details.sid}\n"
            f"🔗 URL: {number_details.uri}\n"
            f"🔄 সিঙ্ক স্ট্যাটাস: {number_details.status}"
        )
        
        await context.bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=info_text
        )
        
    except Exception as e:
        logger.error(f"Error getting number info: {e}")
        await query.message.reply_text("❌ নাম্বার ইনফো দেখাতে সমস্যা হয়েছে!")

async def check_expired_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.utcnow()
    expired_users = []
    
    for user_id, expiry_date in list(SUBSCRIBED_USERS.items()):
        if expiry_date <= now:
            expired_users.append(user_id)
            del SUBSCRIBED_USERS[user_id]
            
    for user_id in expired_users:
        try:
            buttons = [[InlineKeyboardButton(plan["label"], callback_data=key)] for key, plan in PLANS.items()]
            markup = InlineKeyboardMarkup(buttons)
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ আপনার Subscription এক্সপায়ার্ড হয়েছে! বট ব্যবহার চালিয়ে যেতে Renew করুন:",
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Failed to notify expired user {user_id}: {e}")

async def subscription_checker(context: ContextTypes.DEFAULT_TYPE):
    while True:
        await check_expired_subscriptions(context)
        await asyncio.sleep(3600)  # Check every hour

async def webhook(request):
    data = await request.json()
    await application.update_queue.put(Update.de_json(data, application.bot))
    return web.Response(text="ok")

async def main():
    global application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("login", login_command))
    application.add_handler(CommandHandler("status", subscription_status))
    application.add_handler(CommandHandler("buy", buy_command))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_plan_choice, pattern="^(free_1h|1d|7d|15d|30d)$"))
    application.add_handler(CallbackQueryHandler(handle_admin_decision, pattern="^(approve|cancel)\\|"))
    application.add_handler(CallbackQueryHandler(handle_login_prompt, pattern="^login_prompt$"))
    application.add_handler(CallbackQueryHandler(handle_number_purchase, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(check_messages, pattern="^check_msg_"))
    application.add_handler(CallbackQueryHandler(number_info, pattern="^number_info_"))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_twilio_credentials))
    
    # Webhook setup
    app = web.Application()
    app.router.add_post("/", webhook)

    async with application:
        await application.start()
        await application.updater.start_polling()
        
        # Start subscription checker task
        asyncio.create_task(subscription_checker(application))
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080)))
        await site.start()
        logger.info("Bot is up and running...")
        await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
