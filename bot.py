import logging
import asyncio
import random
import string
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, ConversationHandler, filters
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from config import TELEGRAM_BOT_TOKEN, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, SMS_COST_ESTIMATE, MAX_MONTHLY_COST, TELEGRAM_CHANNEL_ID
from database import db
import re
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Conversation states
CHOOSING, REQUEST_NUMBER, AWAITING_SMS, SEND_SMS, VERIFY_NUMBER = range(5)

# Check if we're using a trial account
def is_trial_account():
    """Check if the Twilio account is a trial account"""
    try:
        account = twilio_client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
        return account.type == 'Trial'
    except:
        return True  # Assume trial if we can't check

IS_TRIAL_ACCOUNT = is_trial_account()

class TwilioBot:
    def __init__(self):
        self.available_numbers = []
        
    def generate_request_id(self):
        """Generate a unique request ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return f"REQ-{timestamp}-{random_str}"
        
    async def send_to_channel(self, message, context: ContextTypes.DEFAULT_TYPE):
        """Send message to configured channel"""
        try:
            if TELEGRAM_CHANNEL_ID:
                await context.bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    text=message,
                    parse_mode='HTML'
                )
                return True
        except Exception as e:
            logger.error(f"Failed to send message to channel: {e}")
        return False
        
    async def ensure_user_exists(self, update: Update):
        """Ensure user exists in database"""
        user = update.effective_user
        await db.create_user(user.id, user.username, user.first_name, user.last_name)
        return user.id
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation."""
        user_id = await self.ensure_user_exists(update)
        user = update.effective_user
        logger.info("User %s started the conversation.", user.first_name)
        
        welcome_text = (
            "🔢 Twilio Virtual Number Bot\n\n"
            "I can help you with:\n"
            "• Getting temporary virtual numbers\n"
            "• Receiving SMS/OTP messages\n"
            "• Sending SMS messages\n\n"
            "Please choose an option:"
        )
        
        reply_keyboard = [['Get Virtual Number', 'Check Messages', 'Send SMS']]
        
        if IS_TRIAL_ACCOUNT:
            welcome_text += "⚠️ <b>Trial Account:</b> Some features may be restricted\n"
            reply_keyboard.append(['Verify Number'])
        
        await update.message.reply_text(
            welcome_text,
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, resize_keyboard=True
            )
        )
        
        await db.track_usage(user_id, 'start_command')
        return CHOOSING

    async def get_virtual_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Get a virtual number for the user."""
        user_id = await self.ensure_user_exists(update)
        user = update.effective_user
        
        try:
            request_id = self.generate_request_id()
            
            # For demo purposes, we'll use a mock number since purchasing real numbers
            # requires payment method on Twilio
            mock_numbers = [
                "+15551234567",
                "+15557654321", 
                "+15559876543",
                "+15551112222",
                "+15553334444"
            ]
            
            virtual_number = random.choice(mock_numbers)
            
            # Store user session in database with request ID
            await db.create_user_session(user_id, virtual_number, request_id)
            
            # Send notification to channel
            channel_message = (
                f"📋 <b>New Number Request</b>\n\n"
                f"🆔 <b>Request ID:</b> <code>{request_id}</code>\n"
                f"👤 <b>User:</b> {user.first_name} {user.last_name or ''}\n"
                f"📞 <b>Username:</b> @{user.username or 'N/A'}\n"
                f"🔢 <b>User ID:</b> <code>{user.id}</code>\n"
                f"📱 <b>Virtual Number:</b> <code>{virtual_number}</code>\n"
                f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"#request #{request_id.replace('-', '')}"
            )
            
            await self.send_to_channel(channel_message, context)
            
            response = (
                f"✅ <b>Your virtual number:</b> <code>{virtual_number}</code>\n\n"
                f"🆔 <b>Request ID:</b> <code>{request_id}</code>\n\n"
                "You can use this number for testing. "
                "I'll notify you when any messages arrive.\n\n"
            )
            
            if IS_TRIAL_ACCOUNT:
                response += "⚠️ <b>Note:</b> Trial account restrictions may apply.\n\n"
            
            response += "Use /check to check for messages or /menu to return to the main menu."
            
            await update.message.reply_text(
                response,
                parse_mode='HTML',
                reply_markup=ReplyKeyboardRemove()
            )
            
            await db.track_usage(user_id, 'get_virtual_number', 1.0)
            
        except Exception as e:
            logger.error(f"Error getting virtual number: {e}")
            await update.message.reply_text(
                "Sorry, there was an error getting a virtual number. Please try again later.",
                reply_markup=ReplyKeyboardRemove()
            )
        
        return ConversationHandler.END

    # [Keep the rest of your methods unchanged, but add error handling]
    # verify_number_prompt, verify_number, check_messages, send_sms_prompt, 
    # send_sms, receive_message_content, handle_choice, account_info, 
    # usage_command, cancel, help_command

def main() -> None:
    """Run the bot."""
    try:
        # Create application
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Create bot instance
        bot = TwilioBot()
        
        # Add conversation handler with the states
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', bot.start)],
            states={
                CHOOSING: [
                    MessageHandler(
                        filters.Regex('^(Get Virtual Number|Check Messages|Send SMS|Verify Number)$'), 
                        bot.handle_choice
                    )
                ],
                SEND_SMS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, bot.send_sms)
                ],
                AWAITING_SMS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, bot.receive_message_content)
                ],
                VERIFY_NUMBER: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, bot.verify_number)
                ],
            },
            fallbacks=[CommandHandler('cancel', bot.cancel)],
        )
        
        # Add handlers
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler("check", bot.check_messages))
        application.add_handler(CommandHandler("send", bot.send_sms_prompt))
        application.add_handler(CommandHandler("verify", bot.verify_number_prompt))
        application.add_handler(CommandHandler("account", bot.account_info))
        application.add_handler(CommandHandler("usage", bot.usage_command))
        application.add_handler(CommandHandler("help", bot.help_command))
        application.add_handler(CommandHandler("cancel", bot.cancel))
        
        # Start the Bot
        logger.info("Bot is starting...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
