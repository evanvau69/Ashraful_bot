from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from twilio.rest import Client
from keep_alive import keep_alive
from datetime import timedelta
import time
import logging

logging.basicConfig(level=logging.INFO)

# Admin system
ADMIN_IDS = [6165060012]
user_permissions = {6165060012: float("inf")}
user_used_free_plan = set()

# Twilio session
user_clients = {}
user_available_numbers = {}
user_purchased_numbers = {}

# Permission check decorator
def permission_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        expire_time = user_permissions.get(user_id, 0)
        if time.time() > expire_time:
            keyboard = [
                [InlineKeyboardButton("7 Days - $FREE", callback_data="PLAN:7d")],
                [InlineKeyboardButton("", callback_data="")],
                [InlineKeyboardButton("", callback_data="")],
                [InlineKeyboardButton("", callback_data="")],
                [InlineKeyboardButton("", callback_data="")],
            ]
            await (update.message or update.callback_query).reply_text(
                "Bot এর Subscription নেওয়ার জন্য নিচের বাটনে ক্লিক করুন:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        return await func(update, context)
    return wrapper

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "স্বাগতম 🌸「* 𝗨𝗦𝗔 メ 𝗡𝗨𝗠𝗕𝗘𝗥 𝗕𝗢𝗧  」-এ 🤍 কাজ করার জন্য নিচের কমান্ড গুলো ব্যবহার করতে পরবেন!\n\n"
        "/login <SID> <TOKEN>\n"
        "/buy_number (Area Code)  \n"
        "/show_messages\n"
        "/delete_number\n"
        "/my_numbers\n"
        " 🛂SUPPORT : @hunter_buy_bot "
    )

# Admin permission grant
async def grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ আপনি এই কমান্ড ব্যবহার করতে পারবেন না।")
        return
    if len(context.args) != 2:
        await update.message.reply_text("ব্যবহার: /grant <user_id> <duration> (যেমন 3d)")
        return
    try:
        target_id = int(context.args[0])
        duration = context.args[1].lower()
        if duration.endswith("mo"):
            seconds = int(duration[:-2]) * 2592000
        else:
            unit_map = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
            unit = duration[-1]
            amount = int(duration[:-1])
            seconds = amount * unit_map[unit]
        user_permissions[target_id] = time.time() + seconds
        await update.message.reply_text(f"✅ {target_id} কে {duration} সময়ের জন্য পারমিশন দেওয়া হয়েছে।")
    except:
        await update.message.reply_text("❌ ভুল ফরম্যাট। ব্যবহার করুন m, h, d, w, mo")

# Active user list
async def active_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ আপনি এই কমান্ড ব্যবহার করতে পারবেন না।")
        return
    now = time.time()
    active = {uid: exp for uid, exp in user_permissions.items() if exp > now or exp == float("inf")}
    if not active:
        await update.message.reply_text("কোনো Active Permission ইউজার নেই।")
        return

    msg = "✅ Active Permission ইউজার লিস্ট ✅\n\n"
    for uid, exp in active.items():
        try:
            user = await context.bot.get_chat(uid)
            name = user.full_name
            username = f"@{user.username}" if user.username else "N/A"
        except:
            name = "Unknown"
            username = "N/A"

        duration = "Unlimited" if exp == float("inf") else str(timedelta(seconds=int(exp - now)))
        msg += (
            f"👤 Name: {name}\n"
            f"🆔 ID: {uid}\n"
            f"🔗 Username: {username}\n"
            f"⏳ Time Left: {duration}\n\n"
            f"_________________________\n"
        )
    await update.message.reply_text(msg)

# Twilio login
@permission_required
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("ব্যবহার: /login <SID> <AUTH_TOKEN>")
        return
    sid, token = context.args
    try:
        client = Client(sid, token)
        client.api.accounts(sid).fetch()
        user_clients[update.effective_user.id] = client
        await update.message.reply_text("✅ লগইন সফল হয়েছে!")
    except Exception as e:
        logging.exception("Login error:")
        await update.message.reply_text(f"লগইন হয়নি আপনার Token নষ্ট হয়েছে 🥲")

# Buy number
@permission_required
async def buy_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    client = user_clients.get(user_id)

    if not client:
        await update.message.reply_text("⚠️ আগে /login করুন।")
        return

    try:
        if context.args:
            area_code = context.args[0]
            numbers = client.available_phone_numbers("CA").local.list(area_code=area_code, limit=10)
        else:
            numbers = client.available_phone_numbers("CA").local.list(limit=10)

        if not numbers:
            await update.message.reply_text("নাম্বার পাওয়া যায়নি।")
            return

        user_available_numbers[user_id] = [n.phone_number for n in numbers]
        keyboard = [[InlineKeyboardButton(n.phone_number, callback_data=f"BUY:{n.phone_number}")] for n in numbers]
        keyboard.append([InlineKeyboardButton("Cancel ❌", callback_data="CANCEL")])

        await update.message.reply_text(
            "নিচের নাম্বারগুলো পাওয়া গেছে:\n\n" + "\n".join(user_available_numbers[user_id]),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logging.exception("Buy number error:")
        await update.message.reply_text(f"সমস্যা: দয়া করে আপনার আগের নাম্বার ডিলেট করুন অথবা Token চেঞ্জ করুন")


# Show messages
@permission_required
async def show_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = user_clients.get(update.effective_user.id)
    if not client:
        await update.message.reply_text("⚠️ আগে /login করুন।")
        return
    try:
        msgs = client.messages.list(limit=20)
        incoming = [msg for msg in msgs if msg.direction == "inbound"]
        if not incoming:
            await update.message.reply_text("কোনো Incoming Message পাওয়া যায়নি।")
            return
        output = "\n\n".join([f"From: {m.from_}\nTo: {m.to}\nBody: {m.body}" for m in incoming[:5]])
        await update.message.reply_text(output)
    except Exception as e:
        logging.exception("Show messages error:")
        await update.message.reply_text(f"সমস্যা: আপনার Token এ সমস্যা দয়া করে Token চেঞ্জ করুন")

# Delete number
@permission_required
async def delete_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = user_clients.get(update.effective_user.id)
    if not client:
        await update.message.reply_text("⚠️ আগে /login করুন।")
        return
    try:
        numbers = client.incoming_phone_numbers.list(limit=1)
        if not numbers:
            await update.message.reply_text("নাম্বার খুঁজে পাওয়া যায়নি।")
            return
        numbers[0].delete()
        await update.message.reply_text("✅ নাম্বার ডিলিট হয়েছে।")
    except Exception as e:
        logging.exception("Delete number error:")
        await update.message.reply_text(f"ডিলিট হয়নি আপনার Token এ সমস্যা দয়া করে Token চেঞ্জ করুন ")

# My numbers
@permission_required
async def my_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = user_clients.get(update.effective_user.id)
    if not client:
        await update.message.reply_text("⚠️ আগে /login করুন।")
        return
    try:
        numbers = client.incoming_phone_numbers.list()
        if not numbers:
            await update.message.reply_text("আপনার কোনো নাম্বার নেই।")
            return
        keyboard = [[InlineKeyboardButton(n.phone_number, callback_data=f"DELETE:{n.phone_number}")] for n in numbers]
        await update.message.reply_text("আপনার নাম্বারগুলো:", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logging.exception("My numbers error:")
        await update.message.reply_text(f"সমস্যা: আপনার Token এ সমস্যা দয়া করে Token চেঞ্জ করুন ")

# Admin Management
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ আপনি এই কমান্ড ব্যবহার করতে পারবেন না।")
        return
    try:
        new_admin = int(context.args[0])
        if new_admin not in ADMIN_IDS:
            ADMIN_IDS.append(new_admin)
            user_permissions[new_admin] = float("inf")
            await update.message.reply_text(f"✅ {new_admin} এখন Admin!")
        else:
            await update.message.reply_text("ইউজার ইতিমধ্যেই Admin।")
    except:
        await update.message.reply_text("❌ সঠিকভাবে user_id দিন।")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS or len(ADMIN_IDS) <= 1:
        await update.message.reply_text("❌ এই কমান্ড আপনার জন্য না।")
        return
    try:
        target_id = int(context.args[0])
        if target_id in ADMIN_IDS and target_id != user_id:
            ADMIN_IDS.remove(target_id)
            user_permissions.pop(target_id, None)
            await update.message.reply_text(f"✅ {target_id} কে Admin থেকে সরানো হয়েছে।")
        else:
            await update.message.reply_text("❌ ভুল আইডি।")
    except:
        await update.message.reply_text("❌ সঠিকভাবে user_id দিন।")

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ আপনি এই কমান্ড ব্যবহার করতে পারবেন না।")
        return
    msg = "🛡️ Admin List:\n\n"
    for aid in ADMIN_IDS:
        try:
            user = await context.bot.get_chat(aid)
            msg += f"{user.full_name} — @{user.username or 'N/A'} (ID: {aid})\n"
        except:
            msg += f"Unknown (ID: {aid})\n"
    await update.message.reply_text(msg)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ আপনি এই কমান্ড ব্যবহার করতে পারবেন না।")
        return
    msg = " ".join(context.args)
    success = fail = 0
    for uid in user_permissions:
        try:
            await context.bot.send_message(chat_id=uid, text=msg)
            success += 1
        except:
            fail += 1
    await update.message.reply_text(f"✅ পাঠানো হয়েছে: {success}, ❌ ব্যর্থ: {fail}")

# Button callback
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("BUY:"):
        number = data.split("BUY:")[1]
        client = user_clients.get(user_id)
        if not client:
            await query.edit_message_text("⚠️ আগে /login করুন।")
            return
        try:
            purchased = client.incoming_phone_numbers.create(phone_number=number)
            await query.edit_message_text(f"✅ আপনার নাম্বারটি কিনা হয়েছে: {purchased.phone_number}")
        except Exception as e:
            await query.edit_message_text(f"নাম্বার কেনা যায়নি দয়া করে আপনার আগের নাম্বার ডিলেট করুন অথবা আপনার Token এ সমস্যা দয়া করে Token চেঞ্জ করুন")

    elif data.startswith("DELETE:"):
        number = data.split("DELETE:")[1]
        client = user_clients.get(user_id)
        try:
            nums = client.incoming_phone_numbers.list(phone_number=number)
            if nums:
                nums[0].delete()
                await query.edit_message_text(f"✅ নাম্বার {number} ডিলিট হয়েছে।")
            else:
                await query.edit_message_text("নাম্বার পাওয়া যায়নি।")
        except Exception as e:
            await query.edit_message_text(f"নাম্বার ডিলিট করা যায়নি আপনার Token এ সমস্যা দয়া করে Token চেঞ্জ করুন ")

    elif data == "CANCEL":
        await query.edit_message_text("নাম্বার নির্বাচন বাতিল করা হয়েছে।")

    elif data.startswith("PLAN:"):
        plan = data.split(":")[1]
        username = f"@{query.from_user.username}" if query.from_user.username else "N/A"
        prices = {
            "7 Day": (604800, "7 Day", "$FREE"),
            "1d": (86400, "1 Day", "$2"),
            "7d": (604800, "7 Day", "$10"),
            "15d": (1296000, "15 Day", "$15"),
            "30d": (2592000, "30 Day", "$20")
        }
        if plan == "7d":
            if user_id in user_used_free_plan:
                await query.edit_message_text("আপনি ইতিমধ্যেই ফ্রি প্লান ব্যবহার করেছেন।দয়া করে অন্য Plan Choose করুন")
                return
            user_used_free_plan.add(user_id)
            user_permissions[user_id] = time.time() + 604800
            await query.edit_message_text("✅ আপনি 7 দিনের জন্য ফ্রি প্লান একটিভ করেছেন। মনে রাখবেন এটি শুধু একবারের জন্যই প্রযোজ্য 🟢🔵 ")
            return
        if plan in prices:
            _, label, cost = prices[plan]
            msg = (
                f"Please send {cost} to Binance Pay ID: 893810155 \n"
                f"পেমেন্ট করার পর প্রুভ পাঠান Admin কে @Fuck_Method_BoT \n\n"
                f"User ID: {user_id}\nUsername: {username}\nPlan: {label} - {cost}"
            )
            await query.edit_message_text(msg)

# Start bot
def main():
    keep_alive()
    TOKEN ="7926324917:AAHFaZrVub8NBbW9ruzoJRfJW1YUV-yETaI"
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("grant", grant))
    app.add_handler(CommandHandler("active_users", active_users))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("buy_number", buy_number))
    app.add_handler(CommandHandler("show_messages", show_messages))
    app.add_handler(CommandHandler("delete_number", delete_number))
    app.add_handler(CommandHandler("my_numbers", my_numbers))
    app.add_handler(CommandHandler("add_admin", add_admin))
    app.add_handler(CommandHandler("remove_admin", remove_admin))
    app.add_handler(CommandHandler("list_admins", list_admins))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
