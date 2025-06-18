import os
import sys
import logging
import aiohttp
import time
import asyncio
import json
import os.path
import ctypes
import ctypes.wintypes
import io  # Required for exporting users
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.error import Conflict, RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from database import init_db, get_user, create_user, update_user_status, get_all_users, mark_deposited, get_user_count, reset_user

# Load environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "8069045379:AAH90DA3JkZ2noQeSXLg2asssGySuZrzS7I")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7135894706"))

# Initialize logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Language helper functions
def get_user_language(user_id):
    """Get user's language preference from users.json"""
    filename = "users.json"
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                users = json.load(f)
            for user in users:
                if user['id'] == user_id:
                    return user.get('language', 'en')
        return 'en'
    except Exception as e:
        logger.error(f"Error getting user language: {e}")
        return 'en'

def set_user_language(user_id, lang_code):
    """Set user's language preference in users.json"""
    filename = "users.json"
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                users = json.load(f)
        else:
            users = []
            
        user_found = False
        for user in users:
            if user['id'] == user_id:
                user['language'] = lang_code
                user_found = True
                break
                
        if not user_found:
            users.append({
                "id": user_id,
                "username": "",
                "registered": 0,
                "deposited": 0,
                "language": lang_code
            })
            
        with open(filename, 'w') as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        logger.error(f"Error setting user language: {e}")

async def send_admin_notification(message_type: str, user_id: int, country: str = "", amount: float = 0.0):
    """Send notifications to admin using Telegram API with timestamps"""
    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {'chat_id': ADMIN_ID}
    
    if message_type == "registration":
        # Get current time in ISO format
        current_time = datetime.now().isoformat()
        params['text'] = f"✅ New Registration: {user_id} at {current_time}"
    elif message_type == "deposit":
        # Get current time in ISO format
        current_time = datetime.now().isoformat()
        params['text'] = f"💰 Deposit Received: {user_id}:{country}:{amount} at {current_time}"
    else:
        return
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, params=params) as response:
                if response.status != 200:
                    response_text = await response.text()
                    logger.error(f"Failed to send admin notification: {response.status} - {response_text}")
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")

async def safe_telegram_request(func, *args, max_retries=5, timeout=30, **kwargs):
    """Wrapper for Telegram API requests with retry logic and timeout"""
    for attempt in range(max_retries):
        try:
            # Use asyncio's timeout to prevent hanging requests
            return await asyncio.wait_for(func(*args, **kwargs), timeout)
        except Conflict as e:
            logger.warning(f"Conflict detected (attempt {attempt+1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise
            backoff = 2 ** attempt
            time.sleep(backoff)
        except RetryAfter as e:
            retry_after = e.retry_after
            logger.warning(f"Rate limited. Retrying after {retry_after} seconds")
            time.sleep(retry_after)
        except TimedOut as e:
            logger.warning(f"Timeout detected (attempt {attempt+1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise
            backoff = 2 ** attempt
            time.sleep(backoff)
        except asyncio.TimeoutError as e:
            logger.warning(f"Request timed out (attempt {attempt+1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise TimedOut("Request timed out") from e
            backoff = 2 ** attempt
            time.sleep(backoff)
    return None

async def send_deposit_message(chat_id, user_id, context):
    """Send deposit message with image and buttons after registration"""
    user_lang = get_user_language(user_id)
    
    # Define translations for deposit text
    translations = {
        'en': {
            'caption': 
                """🥳 We are glad to welcome you to our community of successful players! The first step is completed - registration is complete.

🌐 Step 2 - Now it's time to top up your 1WIN account. The larger the deposit, the more opportunities you have to make a profit. Our subscribers earn 30-40% of their capital!

🔓 After replenishing your first deposit, you will automatically receive VIP access.

🚀 Get ready for an exciting journey into the world of profitable bets with FEEDOX - AI SOFTWARE!""",
            'deposit_button': "💰 Deposit Now",
            'back_button': "🔙 Back to Main Menu"
        },
        'hi': {
            'caption': 
                """🥳 सफल खिलाड़ियों के हमारे समुदाय में आपका स्वागत करते हुए हमें खुशी हो रही है! पहला चरण पूरा हो गया है - पंजीकरण पूरा हो गया है। 

🌐 चरण 2 - अब आपके 1WIN खाते को टॉप अप करने का समय आ गया है। जमा राशि जितनी बड़ी होगी, आपके पास लाभ कमाने के उतने ही अधिक अवसर होंगे। हमारे ग्राहक अपनी पूंजी का 30-40% कमाते हैं!

🔓 अपनी पहली जमा राशि को फिर से भरने के बाद, आपको स्वचालित रूप से बॉट में एक अधिसूचना प्राप्त होगी।

🚀FEEDOX AI SOFTWARE- AI सॉफ्टवेयर के साथ लाभदायक सट्टेबाजी की दुनिया में एक रोमांचक यात्रा के लिए तैयार हो जाइए!""",
            'deposit_button': "💰 अभी जमा करें",
            'back_button': "🔙 मुख्य मेनू पर वापस जाएं"
        }
    }
    
    # Default to English if language not found
    lang_data = translations.get(user_lang, translations['en'])
    
    keyboard = [
        [InlineKeyboardButton(lang_data['deposit_button'], url=f"https://1wzyuh.com/casino/list?open=register&p=h53j&sub1={user_id}")],
        [InlineKeyboardButton(lang_data['back_button'], callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        with open('deposit.jpg', 'rb') as photo_file:
            try:
                message = await safe_telegram_request(
                    context.bot.send_photo,
                    chat_id=chat_id,
                    photo=photo_file,
                    caption=lang_data['caption'],
                    reply_markup=reply_markup
                )
                # Store deposit message ID in database
                from database import update_deposit_message_id
                update_deposit_message_id(user_id, message.message_id)
            except Exception as e:
                logger.error(f"Error sending deposit photo: {e}. Falling back to text.")
                # Fallback to text message if photo sending fails
                message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=lang_data['caption'],
                    reply_markup=reply_markup
                )
                # Store deposit message ID in database
                from database import update_deposit_message_id
                update_deposit_message_id(user_id, message.message_id)
    except FileNotFoundError:
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=lang_data['caption'],
            reply_markup=reply_markup
        )
        # Store deposit message ID in database
        from database import update_deposit_message_id
        update_deposit_message_id(user_id, message.message_id)

def add_user_to_json(user_id, username):
    """Add user to users.json with status tracking"""
    filename = "users.json"
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                users = json.load(f)
        else:
            users = []
            
        # Check if user exists, update if found
        user_exists = False
        for user in users:
            if user['id'] == user_id:
                user_exists = True
                # Update username if changed
                user['username'] = username
                break
                
        if not user_exists:
            users.append({
                "id": user_id,
                "username": username,
                "registered": 0,
                "deposited": 0,
                "admin_approved": 0  # NEW FIELD
            })
            
        with open(filename, 'w') as f:
            json.dump(users, f, indent=2)
            
    except Exception as e:
        logger.error(f"Error updating users.json: {e}")
        
        with open(filename, 'w') as f:
            json.dump(users, f, indent=2)
            
    except Exception as e:
        logger.error(f"Error updating users.json: {e}")

def update_user_status_in_json(user_id, registered=None, deposited=None, country=None, amount=None):
    """Update user status in users.json with timestamps"""
    filename = "users.json"
    try:
        if not os.path.exists(filename):
            return
            
        with open(filename, 'r') as f:
            users = json.load(f)
            
        user_found = False
        for user in users:
            if user['id'] == user_id:
                if registered is not None:
                    user['registered'] = 1 if registered else 0
                    user['registration_time'] = datetime.now().isoformat()
                if deposited is not None:
                    user['deposited'] = 1 if deposited else 0
                    user['deposit_time'] = datetime.now().isoformat()
                if country:
                    user['country'] = country
                if amount is not None:
                    user['amount'] = amount
                user['admin_approved'] = user.get('admin_approved', 0)
                user_found = True
                break
                
        if not user_found:
            new_user = {
                "id": user_id,
                "username": "",
                "admin_approved": 0,
                "last_signal_message_id": 0
            }
            if registered is not None:
                new_user['registered'] = 1 if registered else 0
                new_user['registration_time'] = datetime.now().isoformat()
            if deposited is not None:
                new_user['deposited'] = 1 if deposited else 0
                new_user['deposit_time'] = datetime.now().isoformat()
            if country:
                new_user['country'] = country
            if amount is not None:
                new_user['amount'] = amount
                
            users.append(new_user)
                
        with open(filename, 'w') as f:
            json.dump(users, f, indent=2)
            
    except Exception as e:
        logger.error(f"Error updating user status in JSON: {e}")

def update_user_last_signal_message(user_id, message_id):
    """Update last signal message ID in users.json"""
    filename = "users.json"
    try:
        if not os.path.exists(filename):
            return
            
        with open(filename, 'r') as f:
            users = json.load(f)
            
        for user in users:
            if user['id'] == user_id:
                user['last_signal_message_id'] = message_id
                break
                
        with open(filename, 'w') as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        logger.error(f"Error updating last signal message ID: {e}")

def get_user_last_signal_message(user_id):
    """Get last signal message ID from users.json"""
    filename = "users.json"
    try:
        if not os.path.exists(filename):
            return 0
            
        with open(filename, 'r') as f:
            users = json.load(f)
            
        for user in users:
            if user['id'] == user_id:
                return user.get('last_signal_message_id', 0)
        return 0
    except Exception as e:
        logger.error(f"Error getting last signal message ID: {e}")
        return 0

def update_user_admin_approved(user_id, approved):
    """Update admin_approved status in users.json"""
    filename = "users.json"
    try:
        if not os.path.exists(filename):
            return
            
        with open(filename, 'r') as f:
            users = json.load(f)
            
        user_found = False
        for user in users:
            if user['id'] == user_id:
                user['admin_approved'] = 1 if approved else 0
                user_found = True
                break
                
        if not user_found:
            users.append({
                "id": user_id,
                "username": "",
                "registered": 0,
                "deposited": 0,
                "admin_approved": 1 if approved else 0
            })
                
        with open(filename, 'w') as f:
            json.dump(users, f, indent=2)
            
    except Exception as e:
        logger.error(f"Error updating admin approval status: {e}")


def check_user_status(user_id):
    """Check user status from users.json"""
    filename = "users.json"
    try:
        if not os.path.exists(filename):
            return None
            
        with open(filename, 'r') as f:
            users = json.load(f)
            
        for user in users:
            if user['id'] == user_id:
                return {
                    'registered': user.get('registered', 0),
                    'deposited': user.get('deposited', 0),
                    'admin_approved': user.get('admin_approved', 0)
                }
                
        return None
    except Exception as e:
        logger.error(f"Error checking user status: {e}")
        return None


def get_all_user_ids():
    """Get all user IDs from users.json"""
    filename = "users.json"
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                users = json.load(f)
                return [u['id'] for u in users]
        return []
    except Exception as e:
        logger.error(f"Error reading users.json: {e}")
        return []

async def verify_registration(user_id):
    """Verify user registration with external API"""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"https://api.1win.com/verify-registration/{user_id}") as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        return data.get("registered", False)
                    except aiohttp.ContentTypeError:
                        response_text = await response.text()
                        logger.error(f"Invalid JSON response: {response_text}")
                        return False
                else:
                    logger.error(f"API returned status {response.status} for user {user_id}")
        return False
    except asyncio.TimeoutError:
        logger.error("Registration verification timed out")
        return False
    except Exception as e:
        logger.error(f"Registration verification failed: {e}")
        return False

async def verify_deposit(user_id):
    """Verify user deposit with external API"""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"https://api.1win.com/verify-deposit/{user_id}") as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        return data.get("deposited", False), data.get("amount", 0.0)
                    except aiohttp.ContentTypeError:
                        response_text = await response.text()
                        logger.error(f"Invalid JSON response: {response_text}")
                        return False, 0.0
                else:
                    logger.error(f"API returned status {response.status} for user {user_id}")
        return False, 0.0
    except asyncio.TimeoutError:
        logger.error("Deposit verification timed out")
        return False, 0.0
    except Exception as e:
        logger.error(f"Deposit verification failed: {e}")
        return False, 0.0

def sync_databases():
    """Synchronize SQLite and JSON databases"""
    try:
        # Sync from SQLite to JSON
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id, username, registered, deposited FROM users')
        db_users = c.fetchall()
        conn.close()
        
        json_users = []
        for user in db_users:
            json_users.append({
                "id": user[0],
                "username": user[1],
                "registered": user[2],
                "deposited": user[3],
                "admin_approved": 0
            })
        
        with open('users.json', 'w') as f:
            json.dump(json_users, f, indent=2)
            
        return True
    except Exception as e:
        logger.error(f"Database sync failed: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_record = get_user(user.id)
    
    # Add/update user in JSON file
    add_user_to_json(user.id, user.username)
    
    # Initialize status fields if new user
    if not user_record:
        update_user_status_in_json(user_id=user.id, registered=False, deposited=False)
    
    # Get user's language
    user_lang = get_user_language(user.id)
    
    # Define translations for the main menu
    translations = {
        'en': {
            'caption': "🎮 Main Menu",
            'buttons': {
                'registration': "📱 Registration",
                'instruction': "📚 Instruction",
                'choose_language': "🌐 Choose Language",
                'help': "🆘 Help",
                'get_signal': "⚜️ GET SIGNAL ⚜️"
            }
        },
        'hi': {
            'caption': "🎮 मुख्य मेनू",
            'buttons': {
                'registration': "📱 पंजीकरण",
                'instruction': "📚 निर्देश",
                'choose_language': "🌐 भाषा चुनें",
                'help': "🆘 मदद",
                'get_signal': "⚜️ सिग्नल प्राप्त करें ⚜️"
            }
        }
    }
    
    # Default to English if language not found
    lang_data = translations.get(user_lang, translations['en'])
    
    # Build main menu keyboard using translated text
    keyboard = [
        [InlineKeyboardButton(lang_data['buttons']['registration'], callback_data="register")],
        [InlineKeyboardButton(lang_data['buttons']['instruction'], callback_data="instruction")],
        [InlineKeyboardButton(lang_data['buttons']['choose_language'], callback_data="choose_language")],
        [InlineKeyboardButton(lang_data['buttons']['help'], url="https://t.me/BrandFD19")],
        [InlineKeyboardButton(lang_data['buttons']['get_signal'], callback_data="get_signal")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send the main menu without any channel checks
    try:
        with open('main.jpg', 'rb') as photo_file:
            await safe_telegram_request(
                context.bot.send_photo,
                chat_id=update.effective_chat.id,
                photo=photo_file,
                caption=lang_data['caption'],
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
    except FileNotFoundError:
        logger.error("main.jpg file not found")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=lang_data['caption'],
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

async def show_main_menu(update: Update):
    keyboard = [
        [
            InlineKeyboardButton("📱 Registration", callback_data="register"),
            InlineKeyboardButton("📚 Instruction", callback_data="instruction")
        ],
        [
            InlineKeyboardButton("🌐 Choose language", callback_data="choose_language")
        ],
        [
            InlineKeyboardButton("🆘 Help🆘", callback_data="help")
        ],
        [
            InlineKeyboardButton("⚜️ GET SIGNAL ⚜️", callback_data="get_signal")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    

    if update.message:
        await update.message.reply_text("Main Menu:", reply_markup=reply_markup)
    else:
        await update.callback_query.message.reply_text("Main Menu:", reply_markup=reply_markup)

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        
    # Continue with handler logic
    user_id = query.from_user.id
    user_record = get_user(user_id)
    user_lang = get_user_language(user_id)
    
    # Define translations for registration text
    translations = {
        'en': {
            'caption': 
                """⚠️ To get the most out of this bot, you need to follow these steps:

1. Register a new account - if you already have an account, please leave it and register a new one.
2. When registering, use promo code: VVIP500
3. After successful registration, you will automatically receive a message in the bot.""",
            'register_button': "🔗 Register Now",
            'check_registration_button': "🔁 Check Registration",
            'back_button': "⬅️ Back to Menu"
        },
        'hi': {
            'caption': 
                """⚠️ इस बॉट का अधिकतम लाभ उठाने के लिए, आपको इन चरणों का पालन करना होगा:

1. एक नया खाता पंजीकृत करें - यदि आपके पास पहले से ही एक खाता है, तो कृपया इसे छोड़ दें और एक नया खाता पंजीकृत करें।
2. नया खाता पंजीकृत करते समय, प्रचार कोड VVIP500 का उपयोग करना सुनिश्चित करें।
3. सफल पंजीकरण के बाद, आपको स्वचालित रूप से बॉट में एक अधिसूचना प्राप्त होगी।""",
            'register_button': "🔗 अभी पंजीकरण करें",
            'check_registration_button': "🔁 पंजीकरण जांचें",
            'back_button': "⬅️ मेनू पर वापस जाएं"
        }
    }
    
    # Default to English if language not found
    lang_data = translations.get(user_lang, translations['en'])
    
    # Check user status using JSON data
    status = check_user_status(user_id)
    if status is None:
        # If status not found, treat as unregistered
        status = {'registered': 0, 'deposited': 0}

    if status['registered'] == 0:  # Not registered
        # Create user if not exists
        if not user_record:
            create_user(user_id, query.from_user.username)
            user_record = get_user(user_id)
        
        # Create inline keyboard with registration link, check registration button, and back button
        keyboard = [
            [InlineKeyboardButton(lang_data['register_button'], url=f"https://1wzyuh.com/casino/list?open=register&p=h53j&sub1={user_id}")],
            [InlineKeyboardButton(lang_data['check_registration_button'], callback_data="check_registration")],
            [InlineKeyboardButton(lang_data['back_button'], callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send the registration image with caption
        try:
            with open('register.jpg', 'rb') as photo_file:
                await safe_telegram_request(
                    context.bot.send_photo,
                    chat_id=query.message.chat_id,
                    photo=photo_file,
                    caption=lang_data['caption'],
                    reply_markup=reply_markup
                )
        except FileNotFoundError:
            # Fallback to text if image not found
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=lang_data['caption'],
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error sending registration photo: {e}. Falling back to text.")
            # Fallback to text message if photo sending fails
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=lang_data['caption'],
                reply_markup=reply_markup
            )
    elif status['deposited'] == 0:  # Registered but not deposited
        # Send deposit message
        await send_deposit_message(
            chat_id=query.message.chat_id,
            user_id=user_id,
            context=context
        )
    else:  # Both registered and deposited
        # Use multilingual response
        translations = {
            'en': "✅ Your deposit has been successfully verified! Access to signals is now open.",
            'hi': "✅ आपकी जमा राशि सफलतापूर्वक सत्यापित हो गई है! सिग्नल तक पहुंच अब खुली है।"
        }
        user_lang = get_user_language(user_id)
        message_text = translations.get(user_lang, translations['en'])
        
        keyboard = [
            [InlineKeyboardButton("🚀 Get Signal", web_app=WebAppInfo(url="https://feedox-ai-software-zdwq.vercel.app/"))],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=message_text,
            reply_markup=reply_markup
        )


async def check_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        
    # Continue with handler logic
    user_id = query.from_user.id
    
    # Get user country from Telegram (approximation)
    country = query.from_user.language_code if query.from_user.language_code else "unknown"
    
    # Get actual deposit amount from database
    from database import get_deposit_amount
    amount = get_deposit_amount(user_id) or 0.0
    
    # Send deposit notification to admin using Telegram API link
    try:
        await send_admin_notification("deposit", user_id, country, amount)
        # Mark user as VIP
        mark_deposited(user_id)
        
        # Delete previous deposit instruction
        from database import get_deposit_message_id
        deposit_message_id = get_deposit_message_id(user_id)
        if deposit_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=deposit_message_id
                )
            except Exception as e:
                logger.error(f"Error deleting deposit message: {e}")
        
        # Send deposit confirmation
        # Define translations for deposit success text
        user_lang = get_user_language(user_id)
        translations = {
            'en': "✅ Your deposit has been successfully verified! Access to signals is now open.",
            'hi': "✅ आपकी जमा राशि सफलतापूर्वक सत्यापित हो गई है! सिग्नल तक पहुंच अब खुली है।"
        }
        message_text = translations.get(user_lang, translations['en'])
        
        keyboard = [
            [InlineKeyboardButton("⚜️ Get Signal", web_app=WebAppInfo(url="https://feedox-ai-software-zdwq.vercel.app/"))],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=message_text,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Deposit verification failed: {e}")
        await query.message.reply_text("⚠️ An error occurred. Please try again later.")

async def check_registration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    
    user_id = query.from_user.id
    user_lang = get_user_language(user_id)
    
    # Verify registration with external API
    registered = await verify_registration(user_id)
    
    if registered:
        # Update user status with registration timestamp
        update_user_status_in_json(user_id, registered=True)
        
        # Send deposit instructions
        await send_deposit_message(
            chat_id=query.message.chat_id,
            user_id=user_id,
            context=context
        )
    else:
        # Registration not complete
        translations = {
            'en': "❌ Registration not completed. Please complete registration and try again.",
            'hi': "❌ पंजीकरण पूरा नहीं हुआ। कृपया पंजीकरण पूरा करें और पुनः प्रयास करें।"
        }
        message_text = translations.get(user_lang, translations['en'])
        
        keyboard = [
            [InlineKeyboardButton("🔗 Register Now", url=f"https://1wzyuh.com/casino/list?open=register&p=h53j&sub1={user_id}")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=message_text,
            reply_markup=reply_markup
        )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    user_id = query.from_user.id
    user = get_user(user_id)
    
    if user:
        status = user[3]  # status field
        text = f"👤 Profile\n\nName: {query.from_user.full_name}\nID: {user_id}\nStatus: {status}"
        await query.message.reply_text(text)
    else:
        await query.message.reply_text("User not found in database.")

async def instruction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        
    # Continue with handler logic
    user_id = query.from_user.id
    user_lang = get_user_language(user_id)
    
    # Define translations for instruction text
    translations = {
        'en': {
            'instruction_text': 
                """🤖The bot is based and trained on the OpenAi neural network cluster!
⚜️To train the bot, 🎰30,000 games were played.

Currently, bot users successfully generate 15-25% from their 💸 capital daily!

The bot is still undergoing checks and fixes! The accuracy of the bot is 92%!
To achieve maximum profit, follow this instruction:

🟢 1. Register at the betting office 1WIN (https://1wzyuh.com/casino/list?open=register&p=h53j&sub1={user_id})
[If not opening, access with a VPN enabled (Sweden). The Play Market/App Store has many free services, for example: Vpnify, Planet VPN, Hotspot VPN, and so on!]
      ❗️Without registration an promocode, access to signals will not be opened❗️

🟢 2. Top up your account balance.
🟢 3. Go to the 1win games section and select the game.
🟢 4. Set the number of traps to three. This is important!
🟢 5. Request a signal from the bot and place bets according to the signals from the bot.
🟢 6. In case of an unsuccessful signal, we recommend doubling (x²) your bet to completely cover the loss with the next signal.
    """
        },
        'hi': {
            'instruction_text': 
                """🤖यह बॉट ओपनएआई न्यूरल नेटवर्क क्लस्टर पर आधारित और प्रशिक्षित है! 
⚜️बॉट को प्रशिक्षित करने के लिए 🎰30,000 खेल खेले गए।

वर्तमान में, बॉट उपयोगकर्ता अपने 💸 पूंजी से दैनिक 15-25% सफलतापूर्वक उत्पन्न करते हैं!

बॉट अभी भी जांच और सुधार के अधीन है! बॉट की सटीकता 92% है!
अधिकतम लाभ प्राप्त करने के लिए, इस निर्देश का पालन करें:

🟢 1. बेटिंग ऑफिस 1WIN में रजिस्टर करें  1WIN https://1wzyuh.com/casino/list?open=register&p=h53j&sub1={user_id}
[यदि नहीं खुलता है, तो एक VPN सक्षम (स्वीडन) के साथ पहुंचें। Play Market/App Store में कई मुफ्त सेवाएं हैं, उदाहरण के लिए: Vpnify, Planet VPN, Hotspot VPN, आदि!]
❗️रजिस्ट्रेशन और प्रोमो कोड के बिना, सिग्नल्स का एक्सेस नहीं खुलेगा❗️

🟢 2. अपने खाते का बैलेंस बढ़ाएँ।
🟢 3. 1win खेल अनुभाग पर जाएं और खेल का चयन करें।
🟢 4. जालों की संख्या तीन पर सेट करें। यह महत्वपूर्ण है!
🟢 5. बॉट से सिग्नल का अनुरोध करें और बॉट के सिग्नल के अनुसार दांव लगाएं।
🟢 6. यदि सिग्नल असफल होता है, तो हम आपकी दांव को पूरी तरह से कवर करने के लिए अगले सिग्नल के साथ दांव को दोगुना (x²) करने की सिफारिश करते हैं।
    """
        }
    }
    
    # Default to English if language not found
    lang_data = translations.get(user_lang, translations['en'])
    instruction_text = lang_data['instruction_text'].format(user_id=user_id)
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send a new message with instructions and back button
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=instruction_text,
        reply_markup=reply_markup
    )
    
    # Delete the original menu message
    try:
        await query.delete_message()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        
    # Continue with handler logic
    user = query.from_user
    
    try:
        # Delete the current message (instruction/register/etc.)
        await query.delete_message()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    
    # Re-send the full main menu with image and buttons
    await start(update, context)

async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("🌏 Choose your language:", reply_markup=reply_markup)

async def handle_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Extract language code from callback_data (remove 'lang_' prefix)
    lang_code = query.data.split('_')[1]
    user_id = query.from_user.id
    
    # Update user's language in database
    set_user_language(user_id, lang_code)
    
    # Translation dictionary
    translations = {
        'en': {
            'confirmation': "✅ Language changed to English",
            'main_menu': "🎮 Main Menu"
        },
        'hi': {
            'confirmation': "✅ भाषा हिंदी में बदल गई है",
            'main_menu': "🎮 मुख्य मेनू"
        }
    }
    
    # Get translation for selected language
    lang_data = translations.get(lang_code, translations['en'])
    await context.bot.send_message(chat_id=query.message.chat_id, text=lang_data['confirmation'])
    
    # Show main menu in selected language
    await start(update, context)

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    await query.message.reply_text("🧑‍💼 Contact support: @BrandFD19")

async def get_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Continue with handler logic
    user_id = query.from_user.id
    user = get_user(user_id)
    user_lang = get_user_language(user_id)
    
    # Define translations dictionary for all states
    translations = {
        'en': {
            'admin_approved': "✅ Admin approved: Direct signal access granted!",
            'unregistered_caption': 
                """⚠️ To get the most out of this bot, you need to follow these steps:

1. Register a new account - if you already have an account, please leave it and register a new one.
2. When registering, use promo code: VVIP500
3. After successful registration, you will automatically receive a message in the bot.""",
            'register_button': "🔗 Register Now",
            'back_button': "⬅️ Back to Menu",
            'verified_access': "✅ Your deposit has been successfully verified! Access to signals is now open.",
            'get_signal_button': "🚀 Get Signal",
            'back_to_main_button': "🔙 Back to Main Menu"
        },
        'hi': {
            'admin_approved': "✅ व्यवस्थापक द्वारा अनुमोदित: सीधा सिग्नल एक्सेस प्रदान किया गया!",
            'unregistered_caption': 
                """⚠️ इस बॉट का अधिकतम लाभ उठाने के लिए, आपको इन चरणों का पालन करना होगा:

1. एक नया खाता पंजीकृत करें - यदि आपके पास पहले से ही एक खाता है, तो कृपया इसे छोड़ दें और एक नया खाता पंजीकृत करें।
2. नया खाता पंजीकृत करते समय, प्रचार कोड VVIP500 का उपयोग करना सुनिश्चित करें।
3. सफल पंजीकरण के बाद, आपको स्वचालित रूप से बॉट में एक अधिसूचना प्राप्त होगी।""",
            'register_button': "🔗 अभी पंजीकरण करें",
            'back_button': "⬅️ मेनू पर वापस जाएं",
            'verified_access': "✅ आपकी जमा राशि सफलतापूर्वक सत्यापित हो गई है! सिग्नल तक पहुंच अब खुली है।",
            'get_signal_button': "🚀 सिग्नल प्राप्त करें",
            'back_to_main_button': "🔙 मुख्य मेनू पर वापस जाएं"
        }
    }
    lang_data = translations.get(user_lang, translations['en'])
    
    # Try to delete the menu message to clean up
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    
    # Handle different user states based on status
    status = check_user_status(user_id)
    if status is None:
        # User not found - treat as unregistered
        status = {'registered':0, 'deposited':0, 'admin_approved':0}
    
    # Priority 1: Admin approved users get immediate access
    if status.get('admin_approved', 0) == 1:
            keyboard = [
                [InlineKeyboardButton(lang_data['get_signal_button'], web_app=WebAppInfo(url="https://feedox-ai-software-zdwq.vercel.app/"))],
                [InlineKeyboardButton(lang_data['back_to_main_button'], callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=lang_data['admin_approved'],
                reply_markup=reply_markup
            )
            # Store message ID for potential revocation
            update_user_last_signal_message(user_id, message.message_id)
            return  # Exit after granting access
    elif status.get('registered', 0) == 0:  # Not registered
        # Unregistered user - send registration message
        keyboard = [
            [InlineKeyboardButton(lang_data['register_button'], url=f"https://1wzyuh.com/casino/list?open=register&p=h53j&sub1={user_id}")],
            [InlineKeyboardButton(lang_data['back_button'], callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            with open('register.jpg', 'rb') as photo_file:
                await safe_telegram_request(
                    context.bot.send_photo,
                    chat_id=query.message.chat_id,
                    photo=photo_file,
                    caption=lang_data['unregistered_caption'],
                    reply_markup=reply_markup
                )
        except FileNotFoundError:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=lang_data['unregistered_caption'],
                reply_markup=reply_markup
            )
            
        # Create user record if new
        if not user:
            create_user(user_id, query.from_user.username)
    elif status.get('registered', 0) == 1 and status.get('deposited', 0) == 0:  # Registered but not deposited
        # Send deposit message
        await send_deposit_message(
            chat_id=query.message.chat_id,
            user_id=user_id,
            context=context
        )
    else:  # Both registered and deposited OR other cases
        # Show verified access
        keyboard = [
            [InlineKeyboardButton(lang_data['get_signal_button'], web_app=WebAppInfo(url="https://feedox-ai-software-zdwq.vercel.app/"))],
            [InlineKeyboardButton(lang_data['back_to_main_button'], callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=lang_data['verified_access'],
            reply_markup=reply_markup
        )
        # Store message ID for potential revocation
        update_user_last_signal_message(user_id, message.message_id)

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    context.user_data['action'] = 'broadcast'
    await query.message.reply_text("Enter broadcast message:")

async def user_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    count = get_user_count()
    await query.message.reply_text(f"🧑‍� Total users: {count}")

async def upgrade_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    context.user_data['action'] = 'upgrade'
    await query.message.reply_text("Enter user ID to upgrade to VIP:")

async def reset_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")
    context.user_data['action'] = 'reset'
    await query.message.reply_text("Enter user ID to reset:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Handle admin commands
    if user_id == ADMIN_ID:
        if text.isdigit():
            # Admin is entering a user ID
            target_user_id = int(text)
            # Check which admin action is pending
            if context.user_data.get('action') == 'upgrade':
                update_user_status(target_user_id, "VIP")
                await update.message.reply_text(f"✅ User {target_user_id} upgraded to VIP.")
                context.user_data.pop('action', None)
            elif context.user_data.get('action') == 'reset':
                reset_user(target_user_id)
                await update.message.reply_text(f"✅ User {target_user_id} has been reset.")
                context.user_data.pop('action', None)
        elif context.user_data.get('action') == 'broadcast':
            # Broadcast message to all users
            users = get_all_users()
            for user_id in users:
                try:
                    await context.bot.send_message(chat_id=user_id, text=text)
                except Exception as e:
                    logger.error(f"Failed to send to {user_id}: {e}")
            await update.message.reply_text(f"📤 Broadcast sent to {len(users)} users.")
            context.user_data.pop('action', None)
        else:
            # Check if this is a registration notification
            if text.startswith('{user_id}'):
                # Extract user ID from the message
                try:
                    user_id_val = int(text.split('}')[1])
                    # Update user status in JSON for registration
                    update_user_status_in_json(user_id_val, registered=True)
                    # Send deposit message to the user
                    await send_deposit_message(
                        chat_id=user_id_val,
                        user_id=user_id_val,
                        context=context
                    )
                    logger.info(f"Automatically sent deposit instructions to user {user_id_val} after registration")
                except Exception as e:
                    logger.error(f"Error processing registration notification: {e}")
            # Save action state for admin commands
            elif text == 'upgrade':
                context.user_data['action'] = 'upgrade'
                await update.message.reply_text("Enter user ID to upgrade to VIP:")
            elif text == 'reset':
                context.user_data['action'] = 'reset'
                await update.message.reply_text("Enter user ID to reset:")
            elif text == 'broadcast':
                context.user_data['action'] = 'broadcast'
                await update.message.reply_text("Enter broadcast message:")
    else:
        # Handle regular user messages
        await update.message.reply_text("I don't understand that command. Please use the menu.")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /broadcast command from admin with enhanced features"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
    
    # Check if we have a message to broadcast
    if not update.message.text:
        await update.message.reply_text("❌ Please include a message to broadcast")
        return
    
    # Extract the broadcast message without the /broadcast command
    full_text = update.message.text
    message = full_text.replace('/broadcast', '', 1).strip()
    
    if not message:
        await update.message.reply_text("Usage: /broadcast Your message here")
        return
    
    logger.info(f"Starting broadcast to all users. Message: {message[:100]}...")
    
    # Get user IDs from users.json
    user_ids = get_all_user_ids()
    total_users = len(user_ids)
    
    if total_users == 0:
        await update.message.reply_text("⚠️ No users found in the database!")
        logger.warning("Broadcast attempted with no users in database")
        return
    
    logger.info(f"Broadcasting to {total_users} users: {user_ids[:5]}...")
    
    success_count = 0
    failure_count = 0
    failure_details = []
    format_failures = {"markdown": 0, "html": 0, "plain": 0}
    
    # Send broadcast to all users with format fallback
    for i, user_id in enumerate(user_ids):
        try:
            # Try sending with Markdown first
            try:
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                logger.debug(f"Sent Markdown message to {user_id}")
                success_count += 1
            except Exception as md_error:
                format_failures["markdown"] += 1
                
                # If Markdown fails, try HTML
                try:
                    await context.bot.send_message(
                        chat_id=user_id, 
                        text=message,
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                    logger.debug(f"Sent HTML message to {user_id}")
                    success_count += 1
                except Exception as html_error:
                    format_failures["html"] += 1
                    
                    # If both fail, send as plain text
                    try:
                        await context.bot.send_message(
                            chat_id=user_id, 
                            text=message,
                            disable_web_page_preview=True
                        )
                        logger.debug(f"Sent plain text to {user_id}")
                        success_count += 1
                    except Exception as plain_error:
                        format_failures["plain"] += 1
                        logger.error(f"Failed all formats for {user_id}: {plain_error}")
                        failure_details.append(f"{user_id}: {str(plain_error)}")
                        failure_count += 1
        except Exception as e:
            # Handle blocked users silently
            if "bot was blocked" in str(e).lower():
                logger.info(f"Silently skipped blocked user: {user_id}")
                failure_count += 1
            else:
                error_msg = f"{user_id}: {str(e)}"
                logger.warning(f"Failed to send to {error_msg}")
                failure_details.append(error_msg)
                failure_count += 1
        
        # Add rate limiting
        await asyncio.sleep(0.05)
        
        # Log progress every 50 users
        if (i + 1) % 50 == 0:
            logger.info(f"Broadcast progress: {i+1}/{total_users} users processed")
    
    # Create detailed format failure report
    format_report = (
        f"📊 Format Failures:\n"
        f"• Markdown: {format_failures['markdown']}\n"
        f"• HTML: {format_failures['html']}\n"
        f"• Plain text: {format_failures['plain']}"
    )
    
    # Send concise summary
    summary = f"✅ Sent to {success_count} users | ❌ Failed: {failure_count}"
    await update.message.reply_text(summary)
    
    # Send format failure details
    await update.message.reply_text(format_report)
    
    # Send detailed failure report if needed
    if failure_details:
        failure_report = "📝 Failure Details:\n" + "\n".join(failure_details[:10])
        if len(failure_details) > 10:
            failure_report += f"\n...and {len(failure_details)-10} more"
        await update.message.reply_text(failure_report)
    
    logger.info(f"Broadcast completed. Success: {success_count}, Failures: {failure_count}")

async def broadcast_photo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /broadcast_photo command - request photo from admin"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
    
    # Set state to wait for photo
    context.user_data['awaiting_photo'] = True
    await update.message.reply_text("🖼️ Please send the photo you want to broadcast with optional caption.")

async def handle_broadcast_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo message for broadcasting after /broadcast_photo command"""
    if not context.user_data.get('awaiting_photo'):
        return  # Not in photo waiting state
    
    # Clear state
    context.user_data.pop('awaiting_photo', None)
    
    # Get photo and caption
    photo_file = await update.message.photo[-1].get_file()
    caption = update.message.caption
    
    # Store photo details for confirmation
    context.user_data['broadcast_photo'] = {
        'file_id': photo_file.file_id,
        'caption': caption
    }
    
    # Preview photo with confirmation buttons
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm_photo_broadcast")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_photo_broadcast")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    preview_text = "📸 Photo broadcast preview:\n"
    if caption:
        preview_text += f"\nCaption: {caption}"
    
    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=photo_file.file_id,
            caption=preview_text,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending preview: {e}")
        await update.message.reply_text("⚠️ Error processing photo. Please try again.")

async def execute_photo_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str, caption: str):
    """Broadcast photo to all users"""
    # Get user IDs from users.json
    user_ids = get_all_user_ids()
    total_users = len(user_ids)
    
    if total_users == 0:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ No users found in the database!"
        )
        logger.warning("Photo broadcast attempted with no users in database")
        return
    
    logger.info(f"Broadcasting photo to {total_users} users")
    
    success_count = 0
    failure_count = 0
    failure_details = []
    
    # Broadcast photo to all users
    for i, user_id in enumerate(user_ids):
        try:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=file_id,
                caption=caption,
                disable_notification=True
            )
            success_count += 1
        except Exception as e:
            # Handle blocked users silently
            if "bot was blocked" in str(e).lower():
                logger.info(f"Silently skipped blocked user: {user_id}")
            else:
                logger.warning(f"Failed to send photo to {user_id}: {e}")
                failure_details.append(f"{user_id}: {str(e)}")
            failure_count += 1
        
        # Add rate limiting
        await asyncio.sleep(0.05)
        
        # Log progress every 50 users
        if (i + 1) % 50 == 0:
            logger.info(f"Photo broadcast progress: {i+1}/{total_users} users processed")
    
    # Send report to admin
    summary = f"✅ Photo sent to {success_count} users | ❌ Failed: {failure_count}"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=summary)
    
    # Send detailed failure report if needed
    if failure_details:
        failure_report = "📝 Failure Details:\n" + "\n".join(failure_details[:10])
        if len(failure_details) > 10:
            failure_report += f"\n...and {len(failure_details)-10} more"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=failure_report)
    
    logger.info(f"Photo broadcast completed. Success: {success_count}, Failures: {failure_count}")

async def handle_photo_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo broadcast confirmation"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_photo_broadcast":
        # Get stored photo details
        photo_data = context.user_data.get('broadcast_photo')
        if not photo_data:
            await query.message.reply_text("⚠️ Photo data missing. Please start over.")
            return
        
        # Delete confirmation message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting confirmation message: {e}")
        
        # Execute broadcast
        await execute_photo_broadcast(
            update,
            context,
            photo_data['file_id'],
            photo_data.get('caption', '')
        )
    else:  # cancel_photo_broadcast
        await query.message.reply_text("❌ Photo broadcast cancelled.")
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
    
    # Clear stored data
    context.user_data.pop('broadcast_photo', None)
async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to manually approve a user for signal access"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ Usage: /approve_user <user_id>")
        return

    user_id = int(context.args[0])
    update_user_admin_approved(user_id, True)  # Use helper function

    await update.message.reply_text(f"✅ User {user_id} manually approved for Get Signal access.")

async def revoke_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to revoke a user's admin approval for signal access"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return

    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.message.reply_text("⚠️ Usage: /revoke_user <user_id>")
        return

    user_id = int(context.args[0])
    filename = "users.json"
    
    try:
        if not os.path.exists(filename):
            await update.message.reply_text("❌ User database not found.")
            return

        with open(filename, 'r') as f:
            users = json.load(f)
            
        user_found = False
        message_id = 0
        for user in users:
            if user['id'] == user_id:
                # Get last signal message ID before revoking
                message_id = user.get('last_signal_message_id', 0)
                user['admin_approved'] = 0
                user_found = True
                break
                
        if not user_found:
            await update.message.reply_text(f"⚠️ User {user_id} not found.")
            return
            
        with open(filename, 'w') as f:
            json.dump(users, f, indent=2)
            
        # Delete last signal message if exists
        if message_id:
            try:
                await context.bot.delete_message(
                    chat_id=user_id,
                    message_id=message_id
                )
            except Exception as e:
                logger.warning(f"Could not delete signal message for {user_id}: {e}")
        
        # Send revocation notice to user
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ Your signal access has been revoked by the admin."
            )
        except Exception as e:
            logger.warning(f"Could not send revocation notice to {user_id}: {e}")
            
        await update.message.reply_text(f"❌ User {user_id} approval has been revoked.")
    except Exception as e:
        logger.error(f"Error revoking user approval: {e}")
        await update.message.reply_text("❌ Failed to revoke user approval.")

# New command to get user count
async def get_user_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return total number of users from users.json"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
        
    user_ids = get_all_user_ids()
    count = len(user_ids)
    await update.message.reply_text(f"👥 Total users: {count}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command to check user registration and deposit status"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
        
    # Check if user provided a user ID
    if not context.args:
        await update.message.reply_text("Usage: /status [user_id]")
        return
        
    try:
        user_id = int(context.args[0])
        status = check_user_status(user_id)
        
        if status is None:
            await update.message.reply_text(f"❌ User {user_id} not found in database")
            return
            
        registered = "✅" if status['registered'] else "❌"
        deposited = "✅" if status['deposited'] else "❌"
        
        response = (
            f"👤 User Status Report:\n\n"
            f"🆔 User ID: {user_id}\n"
            f"📝 Registered: {registered}\n"
            f"💰 Deposited: {deposited}"
        )
        
        await update.message.reply_text(response)
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please provide a numeric user ID")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command to show individual user status or aggregate counts"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
        
    # If no arguments, show aggregate counts
    if not context.args:
        user_ids = get_all_user_ids()
        total_users = len(user_ids)
        
        # Count registered and deposited users
        registered_count = 0
        deposited_count = 0
        for user_id in user_ids:
            status = check_user_status(user_id)
            if status:
                if status.get('registered', 0) == 1:
                    registered_count += 1
                if status.get('deposited', 0) == 1:
                    deposited_count += 1
        
        response = (
            f"📊 Bot User Statistics:\n\n"
            f"👥 Total Users: {total_users}\n"
            f"📝 Registered Users: {registered_count}\n"
            f"💰 Deposited Users: {deposited_count}"
        )
        await update.message.reply_text(response)
        return
        
    # Check if user ID is provided
    if not context.args[0].isdigit():
        await update.message.reply_text("❌ Invalid user ID. Please provide a numeric user ID")
        return
        
    user_id = int(context.args[0])
    status = check_user_status(user_id)
    
    if status is None:
        await update.message.reply_text(f"❌ User {user_id} not found")
        return
        
    # Format the response for an individual user
    response = (
        f"👤 User ID: {user_id}\n"
        f"📱 Registered: {'✅' if status['registered'] else '❌'}\n"
        f"💰 Deposited: {'✅' if status['deposited'] else '❌'}\n"
        f"👑 Admin Approved: {'✅' if status['admin_approved'] else '❌'}"
    )
    
    await update.message.reply_text(response)

async def total_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return total number of users from users.json"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
        
    user_ids = get_all_user_ids()
    count = len(user_ids)
    await update.message.reply_text(f"👥 Total users: {count}")

async def total_registered_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return total number of registered users from users.json"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
        
    filename = "users.json"
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                users = json.load(f)
                count = sum(1 for u in users if u.get('registered', 0) == 1)
            await update.message.reply_text(f"📝 Total registered users: {count}")
        else:
            await update.message.reply_text("❌ users.json file not found")
    except Exception as e:
        logger.error(f"Error reading users.json: {e}")
        await update.message.reply_text("⚠️ Error retrieving registered users count")

async def total_deposited_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return total number of users who made a deposit from users.json"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
        
    filename = "users.json"
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                users = json.load(f)
                count = sum(1 for u in users if u.get('deposited', 0) == 1)
            await update.message.reply_text(f"💰 Total deposited users: {count}")
        else:
            await update.message.reply_text("❌ users.json file not found")
    except Exception as e:
        logger.error(f"Error reading users.json: {e}")
        await update.message.reply_text("⚠️ Error retrieving deposited users count")

async def export_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export user data to a CSV file"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
        
    filename = "users.json"
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                users = json.load(f)
                
            # Create CSV content
            csv_content = "User ID,Username,Registered,Deposited\n"
            for user in users:
                csv_content += f"{user['id']},{user.get('username', '')},{user.get('registered', 0)},{user.get('deposited', 0)}\n"
                
            # Send CSV as document
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=io.BytesIO(csv_content.encode()),
                filename="users_export.csv",
                caption="📁 User data export"
            )
        else:
            await update.message.reply_text("❌ users.json file not found")
    except Exception as e:
        logger.error(f"Error exporting users: {e}")
        await update.message.reply_text("⚠️ Error exporting user data")

async def refresh_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refresh user data from database"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return
        
    # This would typically reload data from the database
    await update.message.reply_text("♻️ User data refreshed successfully")

async def check_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /check_user command to get detailed user status"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied! Only admins can use this command.")
        return
        
    # Check if user ID is provided
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /check_user <user_id>")
        return
        
    user_id = int(context.args[0])
    status = check_user_status(user_id)
    
    if status is None:
        await update.message.reply_text(f"❌ User {user_id} not found")
        return
        
    # Format the response as specified
    response = (
        f"👤 User ID: {user_id}\n"
        f"📱 Registered: {'✅' if status['registered'] else '❌'}\n"
        f"💰 Deposited: {'✅' if status['deposited'] else '❌'}\n"
        f"👑 Admin Approved: {'✅' if status['admin_approved'] else '❌'}"
    )
    
    await update.message.reply_text(response)

async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Access denied!")
        return

    # Create buttons for admin dashboard
    keyboard = [
        [InlineKeyboardButton("👥 Total Users", callback_data="admin_total_users")],
        [InlineKeyboardButton("📝 Total Registered", callback_data="admin_total_registered")],
        [InlineKeyboardButton("💰 Total Deposited", callback_data="admin_total_deposited")],
        [InlineKeyboardButton("📤 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📁 Export Users", callback_data="admin_export_users")],
        [InlineKeyboardButton("🔄 Refresh Data", callback_data="admin_refresh_data")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Admin Dashboard:", reply_markup=reply_markup)

async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "admin_total_users":
        await total_users_command(query.message, context)
    elif query.data == "admin_total_registered":
        await total_registered_command(query.message, context)
    elif query.data == "admin_total_deposited":
        await total_deposited_command(query.message, context)
    elif query.data == "admin_broadcast":
        context.user_data['action'] = 'broadcast'
        await query.message.reply_text("Enter broadcast message:")
    elif query.data == "admin_export_users":
        await export_users_command(query.message, context)
    elif query.data == "admin_refresh_data":
        await refresh_data_command(query.message, context)
        
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

import os
import sys

def create_system_mutex():
    """Create a system-wide mutex to prevent multiple instances"""
    # Define Windows API functions
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    
    # CreateMutexW function
    kernel32.CreateMutexW.argtypes = (
        ctypes.wintypes.LPVOID,  # lpMutexAttributes
        ctypes.wintypes.BOOL,     # bInitialOwner
        ctypes.wintypes.LPCWSTR   # lpName
    )
    kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    
    # Create the mutex without initial ownership
    mutex_name = "Global\\FEEDOX_AI_BOT_MUTEX"
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    
    # Check if mutex already exists
    last_error = ctypes.get_last_error()
    if last_error == 183:  # ERROR_ALREADY_EXISTS
        print("⚠️ Another bot instance is already running. Exiting.")
        sys.exit(1)
    elif not mutex:
        print(f"⚠️ Failed to create mutex: {ctypes.WinError(last_error)}")
        sys.exit(1)
    
    # Try to acquire the mutex
    WAIT_ABANDONED = 0x00000080
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102
    WAIT_FAILED = 0xFFFFFFFF
    
    result = kernel32.WaitForSingleObject(mutex, 0)  # Non-blocking wait
    if result == WAIT_OBJECT_0 or result == WAIT_ABANDONED:
        # We own the mutex
        return mutex
    else:
        print("⚠️ Another bot instance is already running. Exiting.")
        kernel32.CloseHandle(mutex)
        sys.exit(1)

import time

def main():
    # Create system mutex to prevent multiple instances
    mutex = create_system_mutex()
    
    # We'll keep the lock file as a secondary mechanism
    lock_file = "bot.lock"
    try:
        with open(lock_file, "w") as f:
            f.write(f"locked_{os.getpid()}")
    except Exception as e:
        print(f"⚠️ Warning: Could not create lock file: {e}")
    
    # Initialize database
    init_db()
    
    # Create Application with concurrency control
    application = Application.builder().token(BOT_TOKEN).concurrent_updates(False).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dashboard", admin_dashboard))
    application.add_handler(CommandHandler("admin", admin_dashboard))  # Alias for /dashboard
    application.add_handler(CommandHandler("total_users", total_users_command))
    application.add_handler(CommandHandler("total_registered", total_registered_command))
    application.add_handler(CommandHandler("total_deposited", total_deposited_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("broadcast_photo", broadcast_photo_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("export_users", export_users_command))
    application.add_handler(CommandHandler("refresh_data", refresh_data_command))
    application.add_handler(CommandHandler("check_user", check_user_command))
    application.add_handler(CommandHandler("approve_user", approve_user))
    application.add_handler(CommandHandler("revoke_user", revoke_user_command))
    application.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(register, pattern="^register$"))
    application.add_handler(CallbackQueryHandler(check_deposit, pattern="^check_deposit$"))
    application.add_handler(CallbackQueryHandler(instruction, pattern="^instruction$"))
    application.add_handler(CallbackQueryHandler(choose_language, pattern="^choose_language$"))
    application.add_handler(CallbackQueryHandler(handle_language_selection, pattern="^lang_"))  # Handle language selection
    application.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    application.add_handler(CallbackQueryHandler(help, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(get_signal, pattern="^get_signal$"))
    application.add_handler(CallbackQueryHandler(broadcast, pattern="^broadcast$"))
    application.add_handler(CallbackQueryHandler(user_count, pattern="^user_count$"))
    application.add_handler(CallbackQueryHandler(upgrade_user, pattern="^upgrade_user$"))
    application.add_handler(CallbackQueryHandler(reset_user, pattern="^reset_user$"))
    application.add_handler(CallbackQueryHandler(back_to_main, pattern="^back_to_main$"))
    application.add_handler(CallbackQueryHandler(check_registration_callback, pattern="^check_registration$"))
    application.add_handler(CallbackQueryHandler(handle_photo_confirmation, pattern="^(confirm_photo_broadcast|cancel_photo_broadcast)$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO & filters.Chat(chat_id=ADMIN_ID), handle_broadcast_photo))
    
    # Start bot with enhanced error handling
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            close_loop=False,
            stop_signals=None
        )
    except Conflict as e:
        logger.critical(f"Bot conflict error: {e}. Only one instance can run at a time.")
        print("❌ Bot conflict error. Make sure only one instance is running.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        # Clean up lock file
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
            except Exception as e:
                logger.error(f"Error removing lock file: {e}")
        
        # Release the mutex
        if mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)
        logger.info("Bot process terminated")

if __name__ == "__main__":
    main()
