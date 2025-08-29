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
        return False

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
        
        # Display trial account notice if applicable
        trial_notice = ""
        if IS_TRIAL_ACCOUNT:
            trial_notice = (
                "\n\n⚠️ <b>Trial Account Notice</b>\n"
                "• You can only message verified numbers\n"
                "• All messages will show 'Sent from Twilio trial account'\n"
                "• Use /verify to add numbers to your allowed list"
            )
        
        welcome_text = (
            "🔢 Twilio Virtual Number Bot\n\n"
            "I can help you with:\n"
            "• Getting a temporary virtual number\n"
            "• Receiving SMS/OTP messages\n"
            "• Sending SMS messages"
            f"{trial_notice}\n\n"
            "Please choose an option:"
        )
        
        reply_keyboard = [['Get Virtual Number', 'Check Messages', 'Send SMS']]
        
        if IS_TRIAL_ACCOUNT:
            reply_keyboard.append(['Verify Number'])
        
        await update.message.reply_text(
            welcome_text,
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, resize_keyboard=True
            )
        )
        
        # Track usage
        await db.track_usage(user_id, 'start_command')
        
        return CHOOSING

    async def get_virtual_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Get a virtual number for the user."""
        user_id = await self.ensure_user_exists(update)
        user = update.effective_user
        
        try:
            # Generate unique request ID
            request_id = self.generate_request_id()
            
            # Search for available numbers (US numbers)
            numbers = twilio_client.available_phone_numbers('US').local.list(limit=5)
            
            if not numbers:
                await update.message.reply_text(
                    "Sorry, no numbers available at the moment. Please try again later.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
            
            # Purchase the first available number
            phone_number = twilio_client.incoming_phone_numbers.create(
                phone_number=numbers[0].phone_number
            )
            
            # Store user session in database with request ID
            await db.create_user_session(user_id, phone_number.phone_number, request_id)
            
            # Send notification to channel
            channel_message = (
                f"📋 <b>New Number Request</b>\n\n"
                f"🆔 <b>Request ID:</b> <code>{request_id}</code>\n"
                f"👤 <b>User:</b> {user.first_name} {user.last_name or ''}\n"
                f"📞 <b>Username:</b> @{user.username or 'N/A'}\n"
                f"🔢 <b>User ID:</b> <code>{user.id}</code>\n"
                f"📱 <b>Virtual Number:</b> <code>{phone_number.phone_number}</code>\n"
                f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"#request #{request_id.replace('-', '')}"
            )
            
            await self.send_to_channel(channel_message, context)
            
            response = (
                f"✅ <b>Your virtual number:</b> <code>{phone_number.phone_number}</code>\n\n"
                f"🆔 <b>Request ID:</b> <code>{request_id}</code>\n\n"
                "You can use this number for verification. "
                "I'll notify you when any messages arrive.\n\n"
            )
            
            if IS_TRIAL_ACCOUNT:
                response += "⚠️ <b>Trial Account:</b> You need to verify numbers before messaging them.\n"
                response += "Use /verify to add numbers to your allowed list.\n\n"
            
            response += "Use /check to check for messages or /menu to return to the main menu."
            
            await update.message.reply_text(
                response,
                parse_mode='HTML',
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Track usage (approximately $1 for number)
            await db.track_usage(user_id, 'get_virtual_number', 1.0)
            
        except TwilioRestException as e:
            logger.error(f"Twilio error: {e}")
            error_msg = "Sorry, there was an error getting a virtual number. "
            if "trial" in str(e).lower() and "upgrade" in str(e).lower():
                error_msg += "You may need to upgrade your Twilio account."
            elif "payment" in str(e).lower() or "credit" in str(e).lower():
                error_msg += "Please add payment method to your Twilio account."
                
            await update.message.reply_text(
                error_msg,
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Error getting virtual number: {e}")
            await update.message.reply_text(
                "Sorry, there was an error getting a virtual number. Please try again later.",
                reply_markup=ReplyKeyboardRemove()
            )
        
        return ConversationHandler.END

    async def verify_number_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Prompt user for number to verify."""
        if not IS_TRIAL_ACCOUNT:
            await update.message.reply_text(
                "Your account is not a trial account. Number verification is not required.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
            
        await update.message.reply_text(
            "Please enter the phone number you want to verify (with country code, e.g., +1234567890):",
            reply_markup=ReplyKeyboardRemove()
        )
        return VERIFY_NUMBER

    async def verify_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Verify a phone number for trial account."""
        user_id = await self.ensure_user_exists(update)
        user = update.effective_user
        number = update.message.text
        
        # Basic validation
        if not re.match(r'^\+\d{1,15}$', number):
            await update.message.reply_text(
                "Invalid phone number format. Please use format +1234567890",
                reply_markup=ReplyKeyboardRemove()
            )
            return VERIFY_NUMBER
        
        try:
            # Use Twilio's validation API for real verification
            validation_request = twilio_client.validation_requests.create(
                friendly_name=f"User {user.id} Verification",
                phone_number=number
            )
            
            # Add verification to database
            await db.add_verified_number(user_id, number)
            
            # Send notification to channel
            channel_message = (
                f"✅ <b>Number Verification Request</b>\n\n"
                f"👤 <b>User:</b> {user.first_name} {user.last_name or ''}\n"
                f"📞 <b>Username:</b> @{user.username or 'N/A'}\n"
                f"🔢 <b>User ID:</b> <code>{user.id}</code>\n"
                f"📱 <b>Number to verify:</b> <code>{number}</code>\n"
                f"🆔 <b>Validation SID:</b> <code>{validation_request.validation_sid}</code>\n"
                f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"#verification"
            )
            
            await self.send_to_channel(channel_message, context)
            
            await update.message.reply_text(
                f"✅ Verification request sent for {number}!\n\n"
                "Twilio will send a verification code to this number. "
                "Once verified, you can send messages to it.",
                reply_markup=ReplyKeyboardRemove()
            )
            
            # Track usage
            await db.track_usage(user_id, 'verify_number')
            
        except TwilioRestException as e:
            logger.error(f"Twilio verification error: {e}")
            error_msg = f"❌ Verification failed: {str(e)}"
            await update.message.reply_text(
                error_msg,
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Verification error: {e}")
            await update.message.reply_text(
                "Sorry, there was an error verifying the number. Please try again.",
                reply_markup=ReplyKeyboardRemove()
            )
        
        return ConversationHandler.END

    async def check_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check for received messages."""
        user_id = await self.ensure_user_exists(update)
        
        session = await db.get_active_session(user_id)
        if not session:
            await update.message.reply_text(
                "You don't have an active virtual number. Use /start to get one first.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        
        virtual_number = session['virtual_number']
        
        try:
            # Get real messages from Twilio
            messages = twilio_client.messages.list(to=virtual_number, limit=10)
            
            if not messages:
                await update.message.reply_text(
                    "No messages found for your virtual number.",
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
            
            response = "📨 Messages received:\n\n"
            for msg in messages:
                response += f"From: {msg.from_}\nMessage: {msg.body}\nDate: {msg.date_sent}\n\n"
            
            await update.message.reply_text(response, reply_markup=ReplyKeyboardRemove())
            
            # Track usage (approximately $0.0075 per received message)
            await db.track_usage(user_id, 'check_messages', 0.0075 * len(messages))
            
        except TwilioRestException as e:
            logger.error(f"Twilio error: {e}")
            await update.message.reply_text(
                "Sorry, there was an error retrieving messages. Please try again later.",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Error checking messages: {e}")
            await update.message.reply_text(
                "Sorry, there was an error retrieving messages. Please try again later.",
                reply_markup=ReplyKeyboardRemove()
            )
        
        return ConversationHandler.END

    async def send_sms_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Prompt user for SMS details."""
        user_id = await self.ensure_user_exists(update)
        
        if IS_TRIAL_ACCOUNT:
            # Show verified numbers if any
            verified_nums = await db.get_verified_numbers(user_id)
            if verified_nums:
                numbers_list = "\n".join([f"• {num}" for num in verified_nums])
                await update.message.reply_text(
                    f"📋 Your verified numbers:\n{numbers_list}\n\n"
                    "Please enter the recipient's phone number (must be verified for trial accounts):",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                await update.message.reply_text(
                    "⚠️ <b>Trial Account Restriction</b>\n\n"
                    "You need to verify numbers before sending messages.\n"
                    "Please use /verify to add a number to your allowed list first.",
                    parse_mode='HTML',
                    reply_markup=ReplyKeyboardRemove()
                )
                return ConversationHandler.END
        else:
            await update.message.reply_text(
                "Please enter the recipient's phone number (with country code, e.g., +1234567890):",
                reply_markup=ReplyKeyboardRemove()
            )
            
        return SEND_SMS

    async def send_sms(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Send an SMS message."""
        user_id = await self.ensure_user_exists(update)
        recipient = update.message.text
        
        # Check if number is verified for trial accounts
        if IS_TRIAL_ACCOUNT and not await db.is_number_verified(user_id, recipient):
            await update.message.reply_text(
                f"❌ {recipient} is not verified.\n\n"
                "Trial accounts can only send messages to verified numbers.\n"
                "Use /verify to add this number to your allowed list.",
                reply_markup=ReplyKeyboardRemove()
            )
            return SEND_SMS
        
        # Check usage limits
        current_usage = await db.get_user_usage(user_id)
        if current_usage + SMS_COST_ESTIMATE > MAX_MONTHLY_COST:
            await update.message.reply_text(
                f"❌ Cannot send message: Monthly budget exceeded.\n\n"
                f"Current usage: ${current_usage:.3f}\n"
                f"Budget limit: ${MAX_MONTHLY_COST:.2f}\n\n"
                "Please upgrade your account or wait until next month.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        
        # Store recipient in context
        context.user_data['recipient'] = recipient
        
        await update.message.reply_text(
            "Now please enter the message you want to send:",
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_SMS

    async def receive_message_content(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Receive message content and send SMS."""
        user_id = await self.ensure_user_exists(update)
        user = update.effective_user
        message_content = update.message.text
        recipient = context.user_data['recipient']
        
        # Add trial account notice if applicable
        if IS_TRIAL_ACCOUNT:
            message_content += "\n\nSent from a Twilio trial account"
        
        try:
            # Send real SMS using Twilio
            message = twilio_client.messages.create(
                body=message_content,
                from_=TWILIO_PHONE_NUMBER,
                to=recipient
            )
            
            # Save message to database
            await db.save_sms_message(user_id, recipient, message_content, message.sid)
            
            # Send notification to channel
            channel_message = (
                f"📤 <b>SMS Sent</b>\n\n"
                f"👤 <b>User:</b> {user.first_name} {user.last_name or ''}\n"
                f"📞 <b>Username:</b> @{user.username or 'N/A'}\n"
                f"🔢 <b>User ID:</b> <code>{user.id}</code>\n"
                f"📱 <b>To:</b> <code>{recipient}</code>\n"
                f"📝 <b>Message:</b> {message_content[:100]}{'...' if len(message_content) > 100 else ''}\n"
                f"🆔 <b>SID:</b> <code>{message.sid}</code>\n"
                f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"#sms #sent"
            )
            
            await self.send_to_channel(channel_message, context)
            
            # Track usage cost
            await db.track_usage(user_id, 'send_sms', SMS_COST_ESTIMATE)
            
            response = f"✅ Message sent successfully to {recipient}!\nMessage SID: {message.sid}"
            
            if IS_TRIAL_ACCOUNT:
                response += "\n\n📝 <b>Note:</b> Trial account message delivered with disclaimer."
            
            # Add usage information
            current_usage = await db.get_user_usage(user_id)
            response += f"\n\n📊 Monthly usage: ${current_usage:.3f} / ${MAX_MONTHLY_COST:.2f}"
            
            await update.message.reply_text(
                response,
                parse_mode='HTML',
                reply_markup=ReplyKeyboardRemove()
            )
            
        except TwilioRestException as e:
            logger.error(f"Twilio error: {e}")
            error_msg = f"❌ Failed to send message: {str(e)}"
            
            # Provide helpful guidance for common errors
            if "trial" in str(e).lower() and "unverified" in str(e).lower():
                error_msg += "\n\nThis number needs to be verified for trial accounts. Use /verify to add it."
            elif "permission to send" in str(e).lower():
                error_msg += "\n\nYour account may have restrictions. Check your Twilio console."
            elif "payment" in str(e).lower() or "credit" in str(e).lower():
                error_msg += "\n\nPlease add payment method to your Twilio account."
                
            await update.message.reply_text(
                error_msg,
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Error sending SMS: {e}")
            await update.message.reply_text(
                "Sorry, there was an error sending the message. Please try again.",
                reply_markup=ReplyKeyboardRemove()
            )
        
        return ConversationHandler.END

    # [Keep the rest of your methods unchanged]
    # handle_choice, account_info, usage_command, cancel, help_command

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
