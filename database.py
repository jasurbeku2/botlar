import sqlite3
from datetime import datetime

# database.py fayliga qo'shing (add_user funksiyasidan keyin):
def get_admin_users(self):
    """Admin sifatida ro'yxatdan o'tgan foydalanuvchilarni olish"""
    return self.cursor.execute('''
        SELECT user_id FROM admin_sessions WHERE is_authenticated = 1
    ''').fetchall()
class Database:
    def __init__(self, db_file='cinema_bot.db'):
        self.connection = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.connection.cursor()
        self.create_tables()

    def create_tables(self):
        # Foydalanuvchilar jadvali
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                phone TEXT,
                full_name TEXT,
                username TEXT,
                joined_date TEXT,
                is_blocked INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0
            )
        ''')

        # Kinolar jadvali
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                title TEXT,
                file_id TEXT,
                added_date TEXT
            )
        ''')

        # Majburiy kanallar jadvali
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS force_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                channel_username TEXT,
                added_date TEXT
            )
        ''')

        # Admin sessiyalar jadvali
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_sessions (
                user_id INTEGER PRIMARY KEY,
                is_authenticated INTEGER DEFAULT 0
            )
        ''')

        self.connection.commit()

    # ============= USER FUNCTIONS =============
    def add_user(self, user_id, phone=None, full_name=None, username=None):
        """Yangi foydalanuvchi qo'shish"""
        try:
            self.cursor.execute('''
                INSERT INTO users (user_id, phone, full_name, username, joined_date)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, phone, full_name, username, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def user_exists(self, user_id):
        """Foydalanuvchi borligini tekshirish"""
        result = self.cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,)).fetchone()
        return result is not None

    def update_user_phone(self, user_id, phone):
        """Foydalanuvchi telefon raqamini yangilash"""
        self.cursor.execute('UPDATE users SET phone = ? WHERE user_id = ?', (phone, user_id))
        self.connection.commit()

    def is_user_blocked(self, user_id):
        """Foydalanuvchi bloklanganligini tekshirish"""
        result = self.cursor.execute('SELECT is_blocked FROM users WHERE user_id = ?', (user_id,)).fetchone()
        return result[0] == 1 if result else False

    def block_user(self, user_id):
        """Foydalanuvchini bloklash"""
        self.cursor.execute('UPDATE users SET is_blocked = 1 WHERE user_id = ?', (user_id,))
        self.connection.commit()

    def unblock_user(self, user_id):
        """Foydalanuvchini blokdan chiqarish"""
        self.cursor.execute('UPDATE users SET is_blocked = 0 WHERE user_id = ?', (user_id,))
        self.connection.commit()

    def get_all_users(self):
        """Barcha faol foydalanuvchilarni olish"""
        return self.cursor.execute('SELECT user_id FROM users WHERE is_blocked = 0').fetchall()

    def get_user_info(self, user_id):
        """Foydalanuvchi ma'lumotlarini olish"""
        return self.cursor.execute('''
            SELECT user_id, phone, full_name, username, joined_date, is_blocked 
            FROM users WHERE user_id = ?
        ''', (user_id,)).fetchone()

    def get_total_users(self):
        """Jami foydalanuvchilar soni"""
        return self.cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0]

    def get_active_users(self):
        """Faol foydalanuvchilar soni"""
        return self.cursor.execute('SELECT COUNT(*) FROM users WHERE is_blocked = 0').fetchone()[0]

    def get_blocked_users(self):
        """Bloklangan foydalanuvchilar soni"""
        return self.cursor.execute('SELECT COUNT(*) FROM users WHERE is_blocked = 1').fetchone()[0]

    # ============= MOVIE FUNCTIONS =============
    def add_movie(self, code, title, file_id):
        """Yangi kino qo'shish"""
        try:
            self.cursor.execute('''
                INSERT INTO movies (code, title, file_id, added_date)
                VALUES (?, ?, ?, ?)
            ''', (code, title, file_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_movie(self, code):
        """Kino ma'lumotlarini olish (kod bo'yicha)"""
        return self.cursor.execute('''
            SELECT code, title, file_id FROM movies WHERE code = ?
        ''', (code,)).fetchone()

    def delete_movie(self, code):
        """Kinoni o'chirish"""
        self.cursor.execute('DELETE FROM movies WHERE code = ?', (code,))
        self.connection.commit()

    def get_total_movies(self):
        """Jami kinolar soni"""
        return self.cursor.execute('SELECT COUNT(*) FROM movies').fetchone()[0]

    def movie_exists(self, code):
        """Kino borligini tekshirish"""
        result = self.cursor.execute('SELECT code FROM movies WHERE code = ?', (code,)).fetchone()
        return result is not None

    def get_all_movies(self):
        """Barcha kinolar ro'yxati"""
        return self.cursor.execute('SELECT code, title, added_date FROM movies ORDER BY added_date DESC').fetchall()

    # ============= CHANNEL FUNCTIONS =============
    def add_channel(self, channel_id, channel_username):
        """Yangi kanal qo'shish"""
        try:
            self.cursor.execute('''
                INSERT INTO force_channels (channel_id, channel_username, added_date)
                VALUES (?, ?, ?)
            ''', (channel_id, channel_username, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_channel(self, channel_id):
        """Kanalni o'chirish"""
        self.cursor.execute('DELETE FROM force_channels WHERE channel_id = ?', (channel_id,))
        self.connection.commit()

    def get_all_channels(self):
        """Barcha kanallarni olish"""
        return self.cursor.execute('SELECT channel_id, channel_username FROM force_channels').fetchall()

    def channel_exists(self, channel_id):
        """Kanal borligini tekshirish"""
        result = self.cursor.execute('SELECT channel_id FROM force_channels WHERE channel_id = ?',
                                     (channel_id,)).fetchone()
        return result is not None

    def get_total_channels(self):
        """Jami kanallar soni"""
        return self.cursor.execute('SELECT COUNT(*) FROM force_channels').fetchone()[0]

    # ============= ADMIN SESSION FUNCTIONS =============
    def create_admin_session(self, user_id):
        """Admin sessiyasini yaratish"""
        self.cursor.execute('''
            INSERT OR REPLACE INTO admin_sessions (user_id, is_authenticated)
            VALUES (?, 1)
        ''', (user_id,))
        self.connection.commit()

    def is_admin_authenticated(self, user_id):
        """Admin autentifikatsiya qilinganligini tekshirish"""
        result = self.cursor.execute('''
            SELECT is_authenticated FROM admin_sessions WHERE user_id = ?
        ''', (user_id,)).fetchone()
        return result[0] == 1 if result else False

    def logout_admin(self, user_id):
        """Admin sessiyasini tugatish"""
        self.cursor.execute('DELETE FROM admin_sessions WHERE user_id = ?', (user_id,))
        self.connection.commit()

    def logout_all_admins(self):
        """Barcha admin sessiyalarini tugatish"""
        self.cursor.execute('DELETE FROM admin_sessions')
        self.connection.commit()

    # ============= STATISTICS FUNCTIONS =============
    def get_statistics(self):
        """To'liq statistika"""
        return {
            'total_users': self.get_total_users(),
            'active_users': self.get_active_users(),
            'blocked_users': self.get_blocked_users(),
            'total_movies': self.get_total_movies(),
            'total_channels': self.get_total_channels()
        }

    # ============= UTILITY FUNCTIONS =============
    def close(self):
        """Ma'lumotlar bazasini yopish"""
        self.connection.close()

    def backup(self, backup_file='backup.db'):
        """Ma'lumotlar bazasini zahiralash"""
        backup_conn = sqlite3.connect(backup_file)
        self.connection.backup(backup_conn)
        backup_conn.close()

    def clear_all_data(self):
        """Barcha ma'lumotlarni o'chirish (EHTIYOT BO'LING!)"""
        self.cursor.execute('DELETE FROM users')
        self.cursor.execute('DELETE FROM movies')
        self.cursor.execute('DELETE FROM force_channels')
        self.cursor.execute('DELETE FROM admin_sessions')
        self.connection.commit()