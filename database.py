import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import logging
from config import DATABASE_URL

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.connection_params = DATABASE_URL
        
    @contextmanager
    def get_connection(self):
        """Get a database connection with context management"""
        conn = None
        try:
            conn = psycopg2.connect(self.connection_params)
            yield conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()
                
    @contextmanager
    def get_cursor(self):
        """Get a database cursor with context management"""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                yield cursor
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Database cursor error: {e}")
                raise
            finally:
                cursor.close()
    
    # User management
    async def get_user(self, user_id):
        """Get user by ID"""
        with self.get_cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()
    
    async def create_user(self, user_id, username, first_name, last_name):
        """Create a new user"""
        with self.get_cursor() as cur:
            cur.execute(
                "INSERT INTO users (user_id, username, first_name, last_name) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "username = EXCLUDED.username, "
                "first_name = EXCLUDED.first_name, "
                "last_name = EXCLUDED.last_name, "
                "updated_at = CURRENT_TIMESTAMP",
                (user_id, username, first_name, last_name)
            )
    
    # Session management
    async def create_user_session(self, user_id, virtual_number, request_id):
        """Create a new user session with request ID"""
        with self.get_cursor() as cur:
            # Deactivate any existing sessions
            cur.execute(
                "UPDATE user_sessions SET is_active = FALSE WHERE user_id = %s",
                (user_id,)
            )
            # Create new session with request ID
            cur.execute(
                "INSERT INTO user_sessions (user_id, virtual_number, request_id) "
                "VALUES (%s, %s, %s) RETURNING session_id",
                (user_id, virtual_number, request_id)
            )
            return cur.fetchone()['session_id']
    
    async def get_active_session(self, user_id):
        """Get active session for user"""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM user_sessions WHERE user_id = %s AND is_active = TRUE",
                (user_id,)
            )
            return cur.fetchone()
    
    # Verified numbers management
    async def add_verified_number(self, user_id, phone_number):
        """Add a verified phone number"""
        with self.get_cursor() as cur:
            cur.execute(
                "INSERT INTO verified_numbers (user_id, phone_number) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, phone_number)
            )
    
    async def get_verified_numbers(self, user_id):
        """Get all verified numbers for a user"""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT phone_number FROM verified_numbers WHERE user_id = %s",
                (user_id,)
            )
            return [row['phone_number'] for row in cur.fetchall()]
    
    async def is_number_verified(self, user_id, phone_number):
        """Check if a number is verified for a user"""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM verified_numbers WHERE user_id = %s AND phone_number = %s",
                (user_id, phone_number)
            )
            return cur.fetchone() is not None
    
    # SMS messages management
    async def save_sms_message(self, user_id, recipient, message, twilio_sid, status='sent'):
        """Save sent SMS message"""
        with self.get_cursor() as cur:
            cur.execute(
                "INSERT INTO sms_messages (user_id, recipient, message, twilio_sid, status) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, recipient, message, twilio_sid, status)
            )
    
    async def get_user_messages(self, user_id, limit=10):
        """Get user's SMS messages"""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM sms_messages WHERE user_id = %s ORDER BY sent_at DESC LIMIT %s",
                (user_id, limit)
            )
            return cur.fetchall()
    
    # Usage tracking
    async def track_usage(self, user_id, action_type, cost=0):
        """Track user usage"""
        with self.get_cursor() as cur:
            cur.execute(
                "INSERT INTO usage_tracking (user_id, action_type, cost) "
                "VALUES (%s, %s, %s)",
                (user_id, action_type, cost)
            )
    
    async def get_user_usage(self, user_id):
        """Get user's total usage cost"""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT SUM(cost) as total_cost FROM usage_tracking WHERE user_id = %s",
                (user_id,)
            )
            result = cur.fetchone()
            return result['total_cost'] or 0
    
    # Admin functions
    async def get_all_users(self):
        """Get all users"""
        with self.get_cursor() as cur:
            cur.execute("SELECT * FROM users ORDER BY created_at DESC")
            return cur.fetchall()
    
    async def get_all_messages(self, limit=100):
        """Get all messages"""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT * FROM sms_messages ORDER BY sent_at DESC LIMIT %s",
                (limit,)
            )
            return cur.fetchall()

# Create global database instance
db = Database()
