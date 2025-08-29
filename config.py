import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# Database Configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://localhost:5432/twilio_bot_db')

# Channel Configuration
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '')

# Application Settings
MAX_MONTHLY_COST = float(os.getenv('MAX_MONTHLY_COST', 5.0))
SMS_COST_ESTIMATE = float(os.getenv('SMS_COST_ESTIMATE', 0.008))

# Check if we're running on Termux
IS_TERMUX = os.path.exists('/data/data/com.termux/files/usr')
