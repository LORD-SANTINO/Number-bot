import psycopg2
from config import DATABASE_URL
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_database():
    """Initialize the database with required tables"""
    commands = [
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            session_id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            virtual_number VARCHAR(20) NOT NULL,
            request_id VARCHAR(20) UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS verified_numbers (
            verification_id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            phone_number VARCHAR(20) NOT NULL,
            verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, phone_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sms_messages (
            message_id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            recipient VARCHAR(20) NOT NULL,
            message TEXT NOT NULL,
            twilio_sid VARCHAR(50),
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'sent'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS usage_tracking (
            usage_id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            action_type VARCHAR(50) NOT NULL,
            cost DECIMAL(10, 4) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_user_sessions_request_id ON user_sessions(request_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_verified_numbers_user_id ON verified_numbers(user_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_sms_messages_user_id ON sms_messages(user_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_usage_tracking_user_id ON usage_tracking(user_id)
        """
    ]
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        for command in commands:
            cur.execute(command)
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info("Database initialized successfully!")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

if __name__ == "__main__":
    init_database()
