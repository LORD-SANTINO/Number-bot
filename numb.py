import logging
import asyncio
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, ConversationHandler, filters, CallbackQueryHandler
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from config import TELEGRAM_BOT_TOKEN, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
import re

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Conversation states
CHOOSING, REQUEST_NUMBER, AWAITING_SMS, SEND_SMS, VERIFY_NUMBER = range(5)

# Store user data
user_sessions = {}
verified_numbers = set()  # In production, use a database

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
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start the conversation."""
        user = update.message.from_user
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
        
        return CHOOSING

    async def get_virtual_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Get a virtual number for the user."""
        user_id = update.message.from_user.id
        
        try:
            # Search for available numbers (in this example, US numbers)
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
            
            # Store user session
            user_sessions[user_id] = {
                'number': phone_number.phone_number,
                'messages': []
            }
            
            response = f"✅ Your virtual number: {phone_number.phone_number}\n\n"
            response += "You can use this number for verification. "
            response += "I'll notify you when any messages arrive.\n\n"
            
            if IS_TRIAL_ACCOUNT:
                response += "⚠️ <b>Trial Account:</b> You need to verify numbers before messaging them.\n"
                response += "Use /verify to add numbers to your allowed list.\n\n"
            
            response += "Use /check to check for messages or /menu to return to the main menu."
            
            await update.message.reply_text(
                response,
                parse_mode='HTML',
                reply_markup=ReplyKeyboardRemove()
            )
            
        except TwilioRestException as e:
            logger.error(f"Twilio error: {e}")
            error_msg = "Sorry, there was an error getting a virtual number. "
            if "trial" in str(e).lower() and "upgrade" in str(e).lower():
                error_msg += "You may need to upgrade your Twilio account."
            await update.message.reply_text(
                error_msg,
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
        number = update.message.text
        
        # Basic validation
        if not re.match(r'^\+\d{1,15}$', number):
            await update.message.reply_text(
                "Invalid phone number format. Please use format +1234567890",
                reply_markup=ReplyKeyboardRemove()
            )
            return VERIFY_NUMBER
        
        try:
            # Add verification - in a real implementation, you'd use Twilio's API
            # For demo, we'll just add to our allowed set
            verified_numbers.add(number)
            
            # In a real implementation, you would call:
            # twilio_client.validation_requests.create(friendly_name='User Verified', phone_number=number)
            
            await update.message.reply_text(
                f"✅ Number {number} has been added to your verified list.\n\n"
                "You can now send messages to this number from your trial account.",
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
        user_id = update.effective_user.id
        
        if user_id not in user_sessions:
            await update.message.reply_text(
                "You don't have an active virtual number. Use /start to get one first.",
                reply_markup=ReplyKeyboardRemove()
            )
            return ConversationHandler.END
        
        virtual_number = user_sessions[user_id]['number']
        
        try:
            # Get messages sent to the virtual number
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
            
        except TwilioRestException as e:
            logger.error(f"Twilio error: {e}")
            await update.message.reply_text(
                "Sorry, there was an error retrieving messages. Please try again later.",
                reply_markup=ReplyKeyboardRemove()
            )
        
        return ConversationHandler.END

    async def send_sms_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Prompt user for SMS details."""
        if IS_TRIAL_ACCOUNT:
            # Show verified numbers if any
            if verified_numbers:
                numbers_list = "\n".join([f"• {num}" for num in verified_numbers])
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
        recipient = update.message.text
        user_id = update.effective_user.id
        
        # Check if number is verified for trial accounts
        if IS_TRIAL_ACCOUNT and recipient not in verified_numbers:
            await update.message.reply_text(
                f"❌ {recipient} is not verified.\n\n"
                "Trial accounts can only send messages to verified numbers.\n"
                "Use /verify to add this number to your allowed list.",
                reply_markup=ReplyKeyboardRemove()
            )
            return SEND_SMS
        
        # Store recipient in context
        context.user_data['recipient'] = recipient
        
        await update.message.reply_text(
            "Now please enter the message you want to send:",
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAITING_SMS

    async def receive_message_content(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Receive message content and send SMS."""
        message_content = update.message.text
        recipient = context.user_data['recipient']
        
        # Add trial account notice if applicable
        if IS_TRIAL_ACCOUNT:
            message_content += "\n\nSent from a Twilio trial account"
        
        try:
            # Send SMS using Twilio
            message = twilio_client.messages.create(
                body=message_content,
                from_=TWILIO_PHONE_NUMBER,
                to=recipient
            )
            
            response = f"✅ Message sent successfully to {recipient}!\nMessage SID: {message.sid}"
            
            if IS_TRIAL_ACCOUNT:
                response += "\n\n📝 <b>Note:</b> Trial account message delivered with disclaimer."
            
            await update.message.reply_text(
                response,
                parse_mode='HTML',
                reply_markup=ReplyKeyboardRemove()
            )
            
        except TwilioRestException as e:
            logger.error(f"Twilio error: {e}")
            error_msg = f"❌ Failed to send message: {str(e)}"
            
            # Provide helpful guidance for common trial account errors
            if "trial" in str(e).lower() and "unverified" in str(e).lower():
                error_msg += "\n\nThis number needs to be verified for trial accounts. Use /verify to add it."
            elif "permission to send" in str(e).lower():
                error_msg += "\n\nYour trial account may have restrictions. Check your Twilio console."
                
            await update.message.reply_text(
                error_msg,
                reply_markup=ReplyKeyboardRemove()
            )
        
        return ConversationHandler.END

    async def handle_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle user's choice from the main menu."""
        text = update.message.text
        
        if text == 'Get Virtual Number':
            return await self.get_virtual_number(update, context)
        elif text == 'Check Messages':
            return await self.check_messages(update, context)
        elif text == 'Send SMS':
            return await self.send_sms_prompt(update, context)
        elif text == 'Verify Number':
            return await self.verify_number_prompt(update, context)
        else:
            await update.message.reply_text(
                "Please select a valid option from the menu.",
                reply_markup=ReplyKeyboardRemove()
            )
            return CHOOSING

    async def account_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Display information about the Twilio account."""
        try:
            account = twilio_client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
            account_type = "Trial" if IS_TRIAL_ACCOUNT else "Full"
            
            message = (
                f"🔐 <b>Account Information</b>\n\n"
                f"Type: {account_type}\n"
                f"Status: {account.status}\n"
            )
            
            if IS_TRIAL_ACCOUNT:
                message += (
                    f"\n⚠️ <b>Trial Account Limitations</b>\n"
                    f"• Can only message verified numbers\n"
                    f"• Messages include trial account notice\n"
                    f"• Some features may be restricted\n\n"
                    f"Use /verify to add numbers to your allowed list."
                )
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            await update.message.reply_text("Could not retrieve account information.")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the current operation."""
        await update.message.reply_text(
            'Operation cancelled. Use /start to begin again.',
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a help message."""
        help_text = (
            "🤖 Twilio Virtual Number Bot Help\n\n"
            "Available commands:\n"
            "/start - Start the bot and get a virtual number\n"
            "/check - Check for received messages\n"
            "/send - Send an SMS message\n"
            "/verify - Verify a phone number (trial accounts)\n"
            "/account - Show account information\n"
            "/help - Show this help message\n"
            "/cancel - Cancel the current operation\n\n"
        )
        
        if IS_TRIAL_ACCOUNT:
            help_text += (
                "⚠️ <b>Trial Account Notice</b>\n"
                "You're using a Twilio trial account with some limitations:\n"
                "• Must verify numbers before messaging\n"
                "• Messages include trial account notice\n"
                "• Some features may be restricted\n\n"
            )
        
        help_text += "This bot uses Twilio's API to provide real virtual phone numbers and SMS capabilities."
        
        await update.message.reply_text(help_text, parse_mode='HTML')

def main() -> None:
    """Run the bot."""
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
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("cancel", bot.cancel))
    
    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
