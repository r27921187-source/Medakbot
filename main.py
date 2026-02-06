import asyncio
import aiosqlite
from aigram import Bot, Dispatcher, executor, types
from aigram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aigram.dispatcher import FSMContext
from aigram.contrib.fsm_storage.memory import MemoryStorage
from aigram.filters import Text
import logging
import hashlib
import time
from datetime import datetime
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Конфигурация
API_TOKEN = '7579139867:AAHOLttZ_aBfCucqqfDaYc6HBExUR8cL3yM'
ADMIN_ID = 6704301586  # Замените на ваш ID в Telegram
CHANNEL_USERNAME = '@medakFUN'  # Замените на username вашего канала

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Инициализация базы данных
DATABASE_NAME = 'medakbot.db'

# Цены доната
DONATE_PRICES = {
    'baron': {'30д': 29, '90д': 49, 'навсегда': 109},
    'strazh': {'30д': 49, '90д': 109, 'навсегда': 159},
    'hero': {'30д': 109, '90д': 159, 'навсегда': 329}
}

# Класс для работы с базой данных
class Database:
    def __init__(self, db_name):
        self.db_name = db_name
    
    async def create_tables(self):
        """Создание таблиц в базе данных"""
        async with aiosqlite.connect(self.db_name) as db:
            # Таблица пользователей
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    balance REAL DEFAULT 0,
                    nickname TEXT,
                    subscribed BOOLEAN DEFAULT 0,
                    referral_code TEXT UNIQUE,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица рефералов
            await db.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER,
                    referred_id INTEGER UNIQUE,
                    rewarded BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                    FOREIGN KEY (referred_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица покупок
            await db.execute('''
                CREATE TABLE IF NOT EXISTS purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    purchase_type TEXT,
                    item_name TEXT,
                    amount INTEGER,
                    price REAL,
                    status TEXT DEFAULT 'pending',
                    player_nickname TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица транзакций
            await db.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount REAL,
                    type TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            await db.commit()
    
    async def add_user(self, user_id, username, first_name, last_name):
        """Добавление нового пользователя"""
        async with aiosqlite.connect(self.db_name) as db:
            referral_code = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8]
            
            # Проверяем, существует ли пользователь
            cursor = await db.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            user_exists = await cursor.fetchone()
            
            if not user_exists:
                await db.execute('''
                    INSERT INTO users (user_id, username, first_name, last_name, referral_code)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username, first_name, last_name, referral_code))
                await db.commit()
                return True
            else:
                # Обновляем время последней активности
                await db.execute('''
                    UPDATE users SET last_active = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                ''', (user_id,))
                await db.commit()
                return False
    
    async def get_user(self, user_id):
        """Получение данных пользователя"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('''
                SELECT * FROM users WHERE user_id = ?
            ''', (user_id,))
            user = await cursor.fetchone()
            
            if user:
                # Получаем количество рефералов
                cursor = await db.execute('''
                    SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND rewarded = 1
                ''', (user_id,))
                referrals_count = (await cursor.fetchone())[0]
                
                # Получаем список рефералов
                cursor = await db.execute('''
                    SELECT referred_id FROM referrals WHERE referrer_id = ?
                ''', (user_id,))
                referrals = [row[0] for row in await cursor.fetchall()]
                
                return {
                    'user_id': user[0],
                    'username': user[1],
                    'first_name': user[2],
                    'last_name': user[3],
                    'balance': user[4],
                    'nickname': user[5],
                    'subscribed': bool(user[6]),
                    'referral_code': user[7],
                    'registered_at': user[8],
                    'last_active': user[9],
                    'referrals_count': referrals_count,
                    'referrals': referrals
                }
            return None
    
    async def update_balance(self, user_id, amount, description=""):
        """Обновление баланса пользователя"""
        async with aiosqlite.connect(self.db_name) as db:
            # Получаем текущий баланс
            cursor = await db.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            current_balance = (await cursor.fetchone())[0]
            new_balance = current_balance + amount
            
            # Обновляем баланс
            await db.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
            
            # Добавляем транзакцию
            transaction_type = "пополнение" if amount > 0 else "списание"
            await db.execute('''
                INSERT INTO transactions (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
            ''', (user_id, amount, transaction_type, description))
            
            await db.commit()
            return new_balance
    
    async def update_subscription(self, user_id, subscribed):
        """Обновление статуса подписки"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                UPDATE users SET subscribed = ? WHERE user_id = ?
            ''', (1 if subscribed else 0, user_id))
            await db.commit()
    
    async def update_nickname(self, user_id, nickname):
        """Обновление ника игрока"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                UPDATE users SET nickname = ? WHERE user_id = ?
            ''', (nickname, user_id))
            await db.commit()
    
    async def add_referral(self, referrer_id, referred_id):
        """Добавление реферальной связи"""
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute('''
                    INSERT INTO referrals (referrer_id, referred_id)
                    VALUES (?, ?)
                ''', (referrer_id, referred_id))
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False
    
    async def reward_referrer(self, referred_id):
        """Награждение реферера за реферала"""
        async with aiosqlite.connect(self.db_name) as db:
            # Находим реферера
            cursor = await db.execute('''
                SELECT referrer_id FROM referrals WHERE referred_id = ?
            ''', (referred_id,))
            result = await cursor.fetchone()
            
            if result:
                referrer_id = result[0]
                # Проверяем, не было ли уже награды
                cursor = await db.execute('''
                    SELECT rewarded FROM referrals WHERE referred_id = ?
                ''', (referred_id,))
                rewarded = (await cursor.fetchone())[0]
                
                if not rewarded:
                    # Начисляем 10 рублей рефереру
                    await self.update_balance(referrer_id, 10, "Награда за реферала")
                    
                    # Помечаем как награжденного
                    await db.execute('''
                        UPDATE referrals SET rewarded = 1 WHERE referred_id = ?
                    ''', (referred_id,))
                    await db.commit()
                    return referrer_id
        
        return None
    
    async def add_purchase(self, user_id, purchase_type, item_name, amount, price, player_nickname=""):
        """Добавление покупки"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('''
                INSERT INTO purchases (user_id, purchase_type, item_name, amount, price, player_nickname)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, purchase_type, item_name, amount, price, player_nickname))
            
            purchase_id = cursor.lastrowid
            await db.commit()
            return purchase_id
    
    async def complete_purchase(self, purchase_id):
        """Завершение покупки"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                UPDATE purchases SET status = 'completed' WHERE id = ?
            ''', (purchase_id,))
            await db.commit()
    
    async def get_purchase(self, purchase_id):
        """Получение информации о покупке"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT * FROM purchases WHERE id = ?', (purchase_id,))
            return await cursor.fetchone()
    
    async def get_user_purchases(self, user_id, limit=10):
        """Получение истории покупок пользователя"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('''
                SELECT * FROM purchases 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, limit))
            return await cursor.fetchall()
    
    async def get_all_users(self):
        """Получение списка всех пользователей"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT user_id, username, balance FROM users ORDER BY registered_at DESC')
            return await cursor.fetchall()
    
    async def get_top_referrers(self, limit=10):
        """Получение топ рефереров"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('''
                SELECT u.user_id, u.username, COUNT(r.id) as referral_count
                FROM users u
                LEFT JOIN referrals r ON u.user_id = r.referrer_id
                GROUP BY u.user_id
                ORDER BY referral_count DESC
                LIMIT ?
            ''', (limit,))
            return await cursor.fetchall()

# Инициализация базы данных
db = Database(DATABASE_NAME)

# Главное меню
def get_main_menu():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton('Донат'))
    keyboard.add(KeyboardButton('Ресурсы'), KeyboardButton('Валюта'))
    keyboard.add(KeyboardButton('Заработать'), KeyboardButton('Баланс'))
    keyboard.add(KeyboardButton('Поддержка'))
    return keyboard

# Меню выбора роли для доната
def get_donate_role_menu():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('Барон', callback_data='donate_baron'))
    keyboard.add(InlineKeyboardButton('Страж', callback_data='donate_strazh'))
    keyboard.add(InlineKeyboardButton('Герой', callback_data='donate_hero'))
    keyboard.add(InlineKeyboardButton('Назад', callback_data='back_main'))
    return keyboard

# Меню выбора срока для доната
def get_donate_period_menu(role):
    keyboard = InlineKeyboardMarkup()
    prices = DONATE_PRICES[role]
    
    for period, price in prices.items():
        keyboard.add(InlineKeyboardButton(f'{period}({price}р)', callback_data=f'buy_{role}_{period}_{price}'))
    
    keyboard.add(InlineKeyboardButton('Назад', callback_data='back_donate'))
    return keyboard

# Меню подтверждения покупки
def get_confirm_menu():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('Да', callback_data='confirm_yes'))
    keyboard.add(InlineKeyboardButton('Нет', callback_data='confirm_no'))
    return keyboard

# Меню подтверждения ника
def get_nick_confirm_menu():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('Подтвердить ник', callback_data='nick_confirm'))
    keyboard.add(InlineKeyboardButton('Изменить ник', callback_data='nick_change'))
    return keyboard

# Меню покупки валюты
def get_currency_menu():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('1кк (9р)', callback_data='currency_1kk_9'))
    keyboard.add(InlineKeyboardButton('Назад', callback_data='back_main'))
    return keyboard

# Меню выбора количества валюты
def get_currency_amount_menu():
    keyboard = InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 101):
        buttons.append(InlineKeyboardButton(str(i), callback_data=f'amount_{i}'))
    # Разделим на строки по 5 кнопок
    for i in range(0, 100, 5):
        keyboard.row(*buttons[i:i+5])
    keyboard.add(InlineKeyboardButton('Назад', callback_data='back_currency'))
    return keyboard

# Проверка подписки на канал
async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    
    # Добавляем пользователя в базу
    await db.add_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    # Проверяем реферальную ссылку
    args = message.get_args()
    if args and args.startswith('ref_'):
        referrer_code = args[4:]
        
        # Находим пользователя по реферальному коду
        async with aiosqlite.connect(DATABASE_NAME) as conn:
            cursor = await conn.execute('SELECT user_id FROM users WHERE referral_code = ?', (referrer_code,))
            result = await cursor.fetchone()
            
            if result and result[0] != user_id:
                referrer_id = result[0]
                # Добавляем реферальную связь
                if await db.add_referral(referrer_id, user_id):
                    logging.info(f"Добавлен реферал: {user_id} для пользователя {referrer_id}")
    
    # Проверяем подписку
    subscribed = await check_subscription(user_id)
    await db.update_subscription(user_id, subscribed)
    
    # Если реферал подписался, награждаем реферера
    if subscribed:
        referrer_id = await db.reward_referrer(user_id)
        if referrer_id:
            await bot.send_message(
                referrer_id,
                f'🎉 Новый реферал подписался! Ваш баланс пополнен на 10р.'
            )
    
    if not subscribed:
        # Просим подписаться
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton('Подписаться', url=f'https://t.me/{CHANNEL_USERNAME[1:]}'))
        keyboard.add(InlineKeyboardButton('✅ Я подписался', callback_data='check_subscription'))
        
        await message.answer(
            f"Привет! Ты в боте от сервера MedakFUN!\n"
            f"Для работы бота ты должен подписаться на канал {CHANNEL_USERNAME}",
            reply_markup=keyboard
        )
    else:
        await message.answer(
            "✅ Вы подписаны на канал! Добро пожаловать в бот MedakFUN!",
            reply_markup=get_main_menu()
        )

# Проверка подписки
@dp.callback_query_handler(lambda c: c.data == 'check_subscription')
async def check_subscription_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    subscribed = await check_subscription(user_id)
    
    if subscribed:
        await db.update_subscription(user_id, True)
        await bot.answer_callback_query(callback_query.id, "✅ Подписка подтверждена!")
        await bot.send_message(
            user_id,
            "✅ Вы подписаны на канал! Добро пожаловать в бот MedakFUN!",
            reply_markup=get_main_menu()
        )
        
        # Проверяем, нужно ли наградить реферера
        referrer_id = await db.reward_referrer(user_id)
        if referrer_id:
            await bot.send_message(
                referrer_id,
                f'🎉 Ваш реферал подписался на канал! Ваш баланс пополнен на 10р.'
            )
    else:
        await bot.answer_callback_query(
            callback_query.id,
            "❌ Вы не подписаны на канал. Пожалуйста, подпишитесь и нажмите снова.",
            show_alert=True
        )

# Обработка кнопок главного меню
@dp.message_handler(Text(equals='Донат'))
async def donate_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    await message.answer("Выберите роль:", reply_markup=get_donate_role_menu())

@dp.message_handler(Text(equals='Ресурсы'))
async def resources_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    await message.answer("🗃️ Нечего нету")

@dp.message_handler(Text(equals='Валюта'))
async def currency_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подписаться на канал!")
        return
    
    await message.answer("Выберите количество валюты:", reply_markup=get_currency_menu())

@dp.message_handler(Text(equals='Заработать'))
async def earn_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    ref_link = f"https://t.me/{await bot.get_me()['username']}?start=ref_{user['referral_code']}"
    
    # Получаем количество рефералов
    referrals_count = user['referrals_count']
    
    await message.answer(
        f"💰 Заработать с помощью рефералов!\n\n"
        f"👥 Ваших рефералов: {referrals_count}\n"
        f"💰 Заработано: {referrals_count * 10}р\n\n"
        f"Ваша реферальная ссылка:\n`{ref_link}`\n\n"
        f"За каждого реферала, который подпишется на канал, вы получите 10р на баланс!",
        parse_mode="Markdown"
    )

@dp.message_handler(Text(equals='Баланс'))
async def balance_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    # Получаем историю транзакций (последние 5)
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute('''
            SELECT amount, type, description, created_at 
            FROM transactions 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT 5
        ''', (user_id,))
        transactions = await cursor.fetchall()
    
    balance_text = f"💰 Ваш баланс: {user['balance']}р\n\n"
    balance_text += "📊 Последние транзакции:\n"
    
    if transactions:
        for trans in transactions:
            amount, trans_type, description, created_at = trans
            sign = "+" if amount > 0 else ""
            balance_text += f"{sign}{amount}р - {description} ({created_at[:10]})\n"
    else:
        balance_text += "История транзакций пуста\n"
    
    await message.answer(balance_text)

@dp.message_handler(Text(equals='Поддержка'))
async def support_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    await message.answer("📞 По вопросам обращайтесь к администрации сервера.")

# Админ команды
@dp.message_handler(commands=['admin'])
async def admin_menu(message: types.Message):
    user_id = message.from_user.id
    
    if user_id != ADMIN_ID:
        await message.answer("У вас нет доступа к админ-панели")
        return
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('Статистика', callback_data='admin_stats'))
    keyboard.add(InlineKeyboardButton('Пользователи', callback_data='admin_users'))
    keyboard.add(InlineKeyboardButton('Топ рефереров', callback_data='admin_top_ref'))
    
    await message.answer("Админ-панель:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == 'admin_stats')
async def admin_stats_callback(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "Нет доступа!")
        return
    
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        # Общая статистика
        cursor = await conn.execute('SELECT COUNT(*) FROM users')
        total_users = (await cursor.fetchone())[0]
        
        cursor = await conn.execute('SELECT COUNT(*) FROM users WHERE subscribed = 1')
        subscribed_users = (await cursor.fetchone())[0]
        
        cursor = await conn.execute('SELECT SUM(balance) FROM users')
        total_balance = (await cursor.fetchone())[0] or 0
        
        cursor = await conn.execute('SELECT COUNT(*) FROM purchases WHERE status = "completed"')
        total_purchases = (await cursor.fetchone())[0]
        
        cursor = await conn.execute('SELECT SUM(price) FROM purchases WHERE status = "completed"')
        total_revenue = (await cursor.fetchone())[0] or 0
    
    stats_text = (
        f"📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Подписано: {subscribed_users}\n"
        f"💰 Общий баланс всех пользователей: {total_balance}р\n"
        f"🛒 Всего покупок: {total_purchases}\n"
        f"💵 Общая выручка: {total_revenue}р\n"
    )
    
    await bot.send_message(ADMIN_ID, stats_text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'admin_users')
async def admin_users_callback(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "Нет доступа!")
        return
    
    users = await db.get_all_users()
    
    if not users:
        await bot.send_message(ADMIN_ID, "Пользователей пока нет")
        return
    
    users_text = "👥 Последние 20 пользователей:\n\n"
    for i, user in enumerate(users[:20], 1):
        user_id, username, balance = user
        users_text += f"{i}. @{username or 'нет'} (ID: {user_id}) - {balance}р\n"
    
    await bot.send_message(ADMIN_ID, users_text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'admin_top_ref')
async def admin_top_ref_callback(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "Нет доступа!")
        return
    
    top_referrers = await db.get_top_referrers(10)
    
    if not top_referrers:
        await bot.send_message(ADMIN_ID, "Рефералов пока нет")
        return
    
    top_text = "🏆 Топ рефереров:\n\n"
    for i, (user_id, username, ref_count) in enumerate(top_referrers, 1):
        top_text += f"{i}. @{username or 'нет'} (ID: {user_id}) - {ref_count} рефералов\n"
    
    await bot.send_message(ADMIN_ID, top_text)
    await bot.answer_callback_query(callback_query.id)

# Обработка колбэков для доната
@dp.callback_query_handler(lambda c: c.data.startswith('donate_'))
async def donate_role_callback(callback_query: types.CallbackQuery):
    role = callback_query.data.split('_')[1]
    role_names = {'baron': 'Барон', 'strazh': 'Страж', 'hero': 'Герой'}
    
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        f"Вы выбрали: {role_names[role]}\nВыберите срок:",
        reply_markup=get_donate_period_menu(role)
    )

@dp.callback_query_handler(lambda c: c.data.startswith('buy_'))
async def buy_donate_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    _, role, period, price = callback_query.data.split('_')
    price = int(price)
    
    # Получаем данные пользователя
    user = await db.get_user(user_id)
    
    # Проверка баланса
    if user['balance'] < price:
        await bot.answer_callback_query(
            callback_query.id,
            f"❌ Недостаточно средств на балансе. Нужно: {price}р, у вас: {user['balance']}р",
            show_alert=True
        )
        return
    
    await bot.answer_callback_query(callback_query.id)
    
    # Сохраняем данные о покупке
    await state.update_data(
        purchase_type='donate',
        role=role,
        period=period,
        price=price
    )
    
    role_names = {'baron': 'Барон', 'strazh': 'Страж', 'hero': 'Герой'}
    await bot.send_message(
        user_id,
        f"Вы точно хотите купить {role_names[role]} ({period}) за {price}р?",
        reply_markup=get_confirm_menu()
    )

@dp.callback_query_handler(lambda c: c.data == 'confirm_yes')
async def confirm_yes_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data = await state.get_data()
    price = data['price']
    
    # Списываем средства
    new_balance = await db.update_balance(user_id, -price, "Покупка доната")
    
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        user_id,
        "✅ Покупка подтверждена! Теперь отправьте ваш игровой ник:"
    )
    # Устанавливаем состояние для ввода ника
    await state.set_state('waiting_for_nickname')

@dp.callback_query_handler(lambda c: c.data == 'confirm_no')
async def confirm_no_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "❌ Покупка отменена.",
        reply_markup=get_main_menu()
    )
    await state.finish()

# Обработка ввода ника
@dp.message_handler(state='waiting_for_nickname')
async def process_nickname(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    nickname = message.text
    
    # Сохраняем ник
    await db.update_nickname(user_id, nickname)
    await state.update_data(nickname=nickname)
    
    await message.answer(
        f"Ваш ник: {nickname}\n"
        "⚠️ Внимание: ник нельзя будет изменить после подтверждения!",
        reply_markup=get_nick_confirm_menu()
    )

@dp.callback_query_handler(lambda c: c.data == 'nick_confirm', state='*')
async def nick_confirm_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data = await state.get_data()
    
    # Добавляем покупку в базу данных
    if data['purchase_type'] == 'donate':
        role_names = {'baron': 'Барон', 'strazh': 'Страж', 'hero': 'Герой'}
        item_name = f"{role_names[data['role']]} {data['period']}"
        purchase_id = await db.add_purchase(
            user_id,
            'donate',
            item_name,
            1,
            data['price'],
            data.get('nickname', '')
        )
        
        # Завершаем покупку
        await db.complete_purchase(purchase_id)
        
        # Отправляем уведомление админу
        user = await db.get_user(user_id)
        purchase_info = (
            f"🛒 Новая покупка!\n\n"
            f"👤 Пользователь: @{callback_query.from_user.username or 'нет'} (ID: {user_id})\n"
            f"📦 Товар: {item_name}\n"
            f"💰 Цена: {data['price']}р\n"
            f"🎮 Ник игрока: {data.get('nickname', 'не указан')}\n"
            f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    await bot.send_message(ADMIN_ID, purchase_info)
    await bot.answer_callback_query(callback_query.id, "✅ Ник подтвержден! Администратор уведомлен.")
    
    await bot.send_message(
        user_id,
        "✅ Покупка завершена! Администратор получил уведомление.",
        reply_markup=get_main_menu()
    )
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == 'nick_change', state='*')
async def nick_change_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Введите новый ник:"
    )
    await state.set_state('waiting_for_nickname')

# Обработка валюты
@dp.callback_query_handler(lambda c: c.data == 'currency_1kk_9')
async def currency_1kk_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await state.update_data(currency_price=9)
    await bot.send_message(
        callback_query.from_user.id,
        "Выберите количество (от 1 до 100):",
        reply_markup=get_currency_amount_menu()
    )

@dp.callback_query_handler(lambda c: c.data.startswith('amount_'))
async def currency_amount_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    amount = int(callback_query.data.split('_')[1])
    
    # Получаем данные из состояния
    data = await state.get_data()
    price_per_unit = data.get('currency_price', 9)
    total_price = amount * price_per_unit
    
    # Получаем данные пользователя
    user = await db.get_user(user_id)
    
    # Проверка баланса
    if user['balance'] < total_price:
        await bot.answer_callback_query(
            callback_query.id,
            f"❌ Недостаточно средств. Нужно: {total_price}р, у вас: {user['balance']}р",
            show_alert=True
        )
        return
    
    await bot.answer_callback_query(callback_query.id)
    
    # Сохраняем данные о покупке
    await state.update_data(
        purchase_type='currency',
        amount=amount,
        price=total_price,
        currency_price=price_per_unit
    )
    
    await bot.send_message(
        user_id,
        f"Вы хотите купить {amount}кк за {total_price}р?\n"
        f"После подтверждения нужно будет указать игровой ник.",
        reply_markup=get_confirm_menu()
    )

# Навигация назад
@dp.callback_query_handler(lambda c: c.data == 'back_main')
async def back_main_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Главное меню:",
        reply_markup=get_main_menu()
    )
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == 'back_donate')
async def back_donate_callback(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Выберите роль:",
        reply_markup=get_donate_role_menu()
    )

@dp.callback_query_handler(lambda c: c.data == 'back_currency')
async def back_currency_callback(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Выберите количество валюты:",
        reply_markup=get_currency_menu()
    )

# Обработчик команды для пополнения баланса (для тестирования)
@dp.message_handler(commands=['addbalance'])
async def add_balance_command(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.answer("Команда только для администратора")
        return
    
    try:
        # Формат: /addbalance <user_id> <amount>
        args = message.get_args().split()
        if len(args) != 2:
            await message.answer("Использование: /addbalance <user_id> <amount>")
            return
        
        target_user_id = int(args[0])
        amount = float(args[1])
        
        new_balance = await db.update_balance(target_user_id, amount, "Административное пополнение")
        await message.answer(f"Баланс пользователя {target_user_id} пополнен на {amount}р. Новый баланс: {new_balance}р")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# Запуск бота
async def on_startup(dp):
    """Действия при запуске бота"""
    await db.create_tables()
    logging.info("База данных инициализирована")
    
    # Отправляем сообщение админу о запуске бота
    try:
        await bot.send_message(ADMIN_ID, "🤖 Бот MedakFUN запущен и готов к работе!")
    except:
        pass

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)import asyncio
import aiosqlite
from aigram import Bot, Dispatcher, executor, types
from aigram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aigram.dispatcher import FSMContext
from aigram.contrib.fsm_storage.memory import MemoryStorage
from aigram.filters import Text
import logging
import hashlib
import time
from datetime import datetime
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Конфигурация
API_TOKEN = '7579139867:AAHOLttZ_aBfCucqqfDaYc6HBExUR8cL3yM'
ADMIN_ID = 6704301586  # Замените на ваш ID в Telegram
CHANNEL_USERNAME = '@medakFUN'  # Замените на username вашего канала

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Инициализация базы данных
DATABASE_NAME = 'medakbot.db'

# Цены доната
DONATE_PRICES = {
    'baron': {'30д': 29, '90д': 49, 'навсегда': 109},
    'strazh': {'30д': 49, '90д': 109, 'навсегда': 159},
    'hero': {'30д': 109, '90д': 159, 'навсегда': 329}
}

# Класс для работы с базой данных
class Database:
    def __init__(self, db_name):
        self.db_name = db_name
    
    async def create_tables(self):
        """Создание таблиц в базе данных"""
        async with aiosqlite.connect(self.db_name) as db:
            # Таблица пользователей
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    balance REAL DEFAULT 0,
                    nickname TEXT,
                    subscribed BOOLEAN DEFAULT 0,
                    referral_code TEXT UNIQUE,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица рефералов
            await db.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER,
                    referred_id INTEGER UNIQUE,
                    rewarded BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                    FOREIGN KEY (referred_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица покупок
            await db.execute('''
                CREATE TABLE IF NOT EXISTS purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    purchase_type TEXT,
                    item_name TEXT,
                    amount INTEGER,
                    price REAL,
                    status TEXT DEFAULT 'pending',
                    player_nickname TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица транзакций
            await db.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount REAL,
                    type TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            await db.commit()
    
    async def add_user(self, user_id, username, first_name, last_name):
        """Добавление нового пользователя"""
        async with aiosqlite.connect(self.db_name) as db:
            referral_code = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8]
            
            # Проверяем, существует ли пользователь
            cursor = await db.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
            user_exists = await cursor.fetchone()
            
            if not user_exists:
                await db.execute('''
                    INSERT INTO users (user_id, username, first_name, last_name, referral_code)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username, first_name, last_name, referral_code))
                await db.commit()
                return True
            else:
                # Обновляем время последней активности
                await db.execute('''
                    UPDATE users SET last_active = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                ''', (user_id,))
                await db.commit()
                return False
    
    async def get_user(self, user_id):
        """Получение данных пользователя"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('''
                SELECT * FROM users WHERE user_id = ?
            ''', (user_id,))
            user = await cursor.fetchone()
            
            if user:
                # Получаем количество рефералов
                cursor = await db.execute('''
                    SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND rewarded = 1
                ''', (user_id,))
                referrals_count = (await cursor.fetchone())[0]
                
                # Получаем список рефералов
                cursor = await db.execute('''
                    SELECT referred_id FROM referrals WHERE referrer_id = ?
                ''', (user_id,))
                referrals = [row[0] for row in await cursor.fetchall()]
                
                return {
                    'user_id': user[0],
                    'username': user[1],
                    'first_name': user[2],
                    'last_name': user[3],
                    'balance': user[4],
                    'nickname': user[5],
                    'subscribed': bool(user[6]),
                    'referral_code': user[7],
                    'registered_at': user[8],
                    'last_active': user[9],
                    'referrals_count': referrals_count,
                    'referrals': referrals
                }
            return None
    
    async def update_balance(self, user_id, amount, description=""):
        """Обновление баланса пользователя"""
        async with aiosqlite.connect(self.db_name) as db:
            # Получаем текущий баланс
            cursor = await db.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            current_balance = (await cursor.fetchone())[0]
            new_balance = current_balance + amount
            
            # Обновляем баланс
            await db.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
            
            # Добавляем транзакцию
            transaction_type = "пополнение" if amount > 0 else "списание"
            await db.execute('''
                INSERT INTO transactions (user_id, amount, type, description)
                VALUES (?, ?, ?, ?)
            ''', (user_id, amount, transaction_type, description))
            
            await db.commit()
            return new_balance
    
    async def update_subscription(self, user_id, subscribed):
        """Обновление статуса подписки"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                UPDATE users SET subscribed = ? WHERE user_id = ?
            ''', (1 if subscribed else 0, user_id))
            await db.commit()
    
    async def update_nickname(self, user_id, nickname):
        """Обновление ника игрока"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                UPDATE users SET nickname = ? WHERE user_id = ?
            ''', (nickname, user_id))
            await db.commit()
    
    async def add_referral(self, referrer_id, referred_id):
        """Добавление реферальной связи"""
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute('''
                    INSERT INTO referrals (referrer_id, referred_id)
                    VALUES (?, ?)
                ''', (referrer_id, referred_id))
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False
    
    async def reward_referrer(self, referred_id):
        """Награждение реферера за реферала"""
        async with aiosqlite.connect(self.db_name) as db:
            # Находим реферера
            cursor = await db.execute('''
                SELECT referrer_id FROM referrals WHERE referred_id = ?
            ''', (referred_id,))
            result = await cursor.fetchone()
            
            if result:
                referrer_id = result[0]
                # Проверяем, не было ли уже награды
                cursor = await db.execute('''
                    SELECT rewarded FROM referrals WHERE referred_id = ?
                ''', (referred_id,))
                rewarded = (await cursor.fetchone())[0]
                
                if not rewarded:
                    # Начисляем 10 рублей рефереру
                    await self.update_balance(referrer_id, 10, "Награда за реферала")
                    
                    # Помечаем как награжденного
                    await db.execute('''
                        UPDATE referrals SET rewarded = 1 WHERE referred_id = ?
                    ''', (referred_id,))
                    await db.commit()
                    return referrer_id
        
        return None
    
    async def add_purchase(self, user_id, purchase_type, item_name, amount, price, player_nickname=""):
        """Добавление покупки"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('''
                INSERT INTO purchases (user_id, purchase_type, item_name, amount, price, player_nickname)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, purchase_type, item_name, amount, price, player_nickname))
            
            purchase_id = cursor.lastrowid
            await db.commit()
            return purchase_id
    
    async def complete_purchase(self, purchase_id):
        """Завершение покупки"""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute('''
                UPDATE purchases SET status = 'completed' WHERE id = ?
            ''', (purchase_id,))
            await db.commit()
    
    async def get_purchase(self, purchase_id):
        """Получение информации о покупке"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT * FROM purchases WHERE id = ?', (purchase_id,))
            return await cursor.fetchone()
    
    async def get_user_purchases(self, user_id, limit=10):
        """Получение истории покупок пользователя"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('''
                SELECT * FROM purchases 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, limit))
            return await cursor.fetchall()
    
    async def get_all_users(self):
        """Получение списка всех пользователей"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('SELECT user_id, username, balance FROM users ORDER BY registered_at DESC')
            return await cursor.fetchall()
    
    async def get_top_referrers(self, limit=10):
        """Получение топ рефереров"""
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute('''
                SELECT u.user_id, u.username, COUNT(r.id) as referral_count
                FROM users u
                LEFT JOIN referrals r ON u.user_id = r.referrer_id
                GROUP BY u.user_id
                ORDER BY referral_count DESC
                LIMIT ?
            ''', (limit,))
            return await cursor.fetchall()

# Инициализация базы данных
db = Database(DATABASE_NAME)

# Главное меню
def get_main_menu():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton('Донат'))
    keyboard.add(KeyboardButton('Ресурсы'), KeyboardButton('Валюта'))
    keyboard.add(KeyboardButton('Заработать'), KeyboardButton('Баланс'))
    keyboard.add(KeyboardButton('Поддержка'))
    return keyboard

# Меню выбора роли для доната
def get_donate_role_menu():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('Барон', callback_data='donate_baron'))
    keyboard.add(InlineKeyboardButton('Страж', callback_data='donate_strazh'))
    keyboard.add(InlineKeyboardButton('Герой', callback_data='donate_hero'))
    keyboard.add(InlineKeyboardButton('Назад', callback_data='back_main'))
    return keyboard

# Меню выбора срока для доната
def get_donate_period_menu(role):
    keyboard = InlineKeyboardMarkup()
    prices = DONATE_PRICES[role]
    
    for period, price in prices.items():
        keyboard.add(InlineKeyboardButton(f'{period}({price}р)', callback_data=f'buy_{role}_{period}_{price}'))
    
    keyboard.add(InlineKeyboardButton('Назад', callback_data='back_donate'))
    return keyboard

# Меню подтверждения покупки
def get_confirm_menu():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('Да', callback_data='confirm_yes'))
    keyboard.add(InlineKeyboardButton('Нет', callback_data='confirm_no'))
    return keyboard

# Меню подтверждения ника
def get_nick_confirm_menu():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('Подтвердить ник', callback_data='nick_confirm'))
    keyboard.add(InlineKeyboardButton('Изменить ник', callback_data='nick_change'))
    return keyboard

# Меню покупки валюты
def get_currency_menu():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('1кк (9р)', callback_data='currency_1kk_9'))
    keyboard.add(InlineKeyboardButton('Назад', callback_data='back_main'))
    return keyboard

# Меню выбора количества валюты
def get_currency_amount_menu():
    keyboard = InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 101):
        buttons.append(InlineKeyboardButton(str(i), callback_data=f'amount_{i}'))
    # Разделим на строки по 5 кнопок
    for i in range(0, 100, 5):
        keyboard.row(*buttons[i:i+5])
    keyboard.add(InlineKeyboardButton('Назад', callback_data='back_currency'))
    return keyboard

# Проверка подписки на канал
async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    
    # Добавляем пользователя в базу
    await db.add_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    
    # Проверяем реферальную ссылку
    args = message.get_args()
    if args and args.startswith('ref_'):
        referrer_code = args[4:]
        
        # Находим пользователя по реферальному коду
        async with aiosqlite.connect(DATABASE_NAME) as conn:
            cursor = await conn.execute('SELECT user_id FROM users WHERE referral_code = ?', (referrer_code,))
            result = await cursor.fetchone()
            
            if result and result[0] != user_id:
                referrer_id = result[0]
                # Добавляем реферальную связь
                if await db.add_referral(referrer_id, user_id):
                    logging.info(f"Добавлен реферал: {user_id} для пользователя {referrer_id}")
    
    # Проверяем подписку
    subscribed = await check_subscription(user_id)
    await db.update_subscription(user_id, subscribed)
    
    # Если реферал подписался, награждаем реферера
    if subscribed:
        referrer_id = await db.reward_referrer(user_id)
        if referrer_id:
            await bot.send_message(
                referrer_id,
                f'🎉 Новый реферал подписался! Ваш баланс пополнен на 10р.'
            )
    
    if not subscribed:
        # Просим подписаться
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton('Подписаться', url=f'https://t.me/{CHANNEL_USERNAME[1:]}'))
        keyboard.add(InlineKeyboardButton('✅ Я подписался', callback_data='check_subscription'))
        
        await message.answer(
            f"Привет! Ты в боте от сервера MedakFUN!\n"
            f"Для работы бота ты должен подписаться на канал {CHANNEL_USERNAME}",
            reply_markup=keyboard
        )
    else:
        await message.answer(
            "✅ Вы подписаны на канал! Добро пожаловать в бот MedakFUN!",
            reply_markup=get_main_menu()
        )

# Проверка подписки
@dp.callback_query_handler(lambda c: c.data == 'check_subscription')
async def check_subscription_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    subscribed = await check_subscription(user_id)
    
    if subscribed:
        await db.update_subscription(user_id, True)
        await bot.answer_callback_query(callback_query.id, "✅ Подписка подтверждена!")
        await bot.send_message(
            user_id,
            "✅ Вы подписаны на канал! Добро пожаловать в бот MedakFUN!",
            reply_markup=get_main_menu()
        )
        
        # Проверяем, нужно ли наградить реферера
        referrer_id = await db.reward_referrer(user_id)
        if referrer_id:
            await bot.send_message(
                referrer_id,
                f'🎉 Ваш реферал подписался на канал! Ваш баланс пополнен на 10р.'
            )
    else:
        await bot.answer_callback_query(
            callback_query.id,
            "❌ Вы не подписаны на канал. Пожалуйста, подпишитесь и нажмите снова.",
            show_alert=True
        )

# Обработка кнопок главного меню
@dp.message_handler(Text(equals='Донат'))
async def donate_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    await message.answer("Выберите роль:", reply_markup=get_donate_role_menu())

@dp.message_handler(Text(equals='Ресурсы'))
async def resources_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    await message.answer("🗃️ Нечего нету")

@dp.message_handler(Text(equals='Валюта'))
async def currency_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подписаться на канал!")
        return
    
    await message.answer("Выберите количество валюты:", reply_markup=get_currency_menu())

@dp.message_handler(Text(equals='Заработать'))
async def earn_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    ref_link = f"https://t.me/{await bot.get_me()['username']}?start=ref_{user['referral_code']}"
    
    # Получаем количество рефералов
    referrals_count = user['referrals_count']
    
    await message.answer(
        f"💰 Заработать с помощью рефералов!\n\n"
        f"👥 Ваших рефералов: {referrals_count}\n"
        f"💰 Заработано: {referrals_count * 10}р\n\n"
        f"Ваша реферальная ссылка:\n`{ref_link}`\n\n"
        f"За каждого реферала, который подпишется на канал, вы получите 10р на баланс!",
        parse_mode="Markdown"
    )

@dp.message_handler(Text(equals='Баланс'))
async def balance_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    # Получаем историю транзакций (последние 5)
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        cursor = await conn.execute('''
            SELECT amount, type, description, created_at 
            FROM transactions 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT 5
        ''', (user_id,))
        transactions = await cursor.fetchall()
    
    balance_text = f"💰 Ваш баланс: {user['balance']}р\n\n"
    balance_text += "📊 Последние транзакции:\n"
    
    if transactions:
        for trans in transactions:
            amount, trans_type, description, created_at = trans
            sign = "+" if amount > 0 else ""
            balance_text += f"{sign}{amount}р - {description} ({created_at[:10]})\n"
    else:
        balance_text += "История транзакций пуста\n"
    
    await message.answer(balance_text)

@dp.message_handler(Text(equals='Поддержка'))
async def support_menu(message: types.Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    
    if not user or not user['subscribed']:
        await message.answer("Сначала подпишитесь на канал!")
        return
    
    await message.answer("📞 По вопросам обращайтесь к администрации сервера.")

# Админ команды
@dp.message_handler(commands=['admin'])
async def admin_menu(message: types.Message):
    user_id = message.from_user.id
    
    if user_id != ADMIN_ID:
        await message.answer("У вас нет доступа к админ-панели")
        return
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton('Статистика', callback_data='admin_stats'))
    keyboard.add(InlineKeyboardButton('Пользователи', callback_data='admin_users'))
    keyboard.add(InlineKeyboardButton('Топ рефереров', callback_data='admin_top_ref'))
    
    await message.answer("Админ-панель:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == 'admin_stats')
async def admin_stats_callback(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "Нет доступа!")
        return
    
    async with aiosqlite.connect(DATABASE_NAME) as conn:
        # Общая статистика
        cursor = await conn.execute('SELECT COUNT(*) FROM users')
        total_users = (await cursor.fetchone())[0]
        
        cursor = await conn.execute('SELECT COUNT(*) FROM users WHERE subscribed = 1')
        subscribed_users = (await cursor.fetchone())[0]
        
        cursor = await conn.execute('SELECT SUM(balance) FROM users')
        total_balance = (await cursor.fetchone())[0] or 0
        
        cursor = await conn.execute('SELECT COUNT(*) FROM purchases WHERE status = "completed"')
        total_purchases = (await cursor.fetchone())[0]
        
        cursor = await conn.execute('SELECT SUM(price) FROM purchases WHERE status = "completed"')
        total_revenue = (await cursor.fetchone())[0] or 0
    
    stats_text = (
        f"📊 Статистика бота:\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"✅ Подписано: {subscribed_users}\n"
        f"💰 Общий баланс всех пользователей: {total_balance}р\n"
        f"🛒 Всего покупок: {total_purchases}\n"
        f"💵 Общая выручка: {total_revenue}р\n"
    )
    
    await bot.send_message(ADMIN_ID, stats_text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'admin_users')
async def admin_users_callback(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "Нет доступа!")
        return
    
    users = await db.get_all_users()
    
    if not users:
        await bot.send_message(ADMIN_ID, "Пользователей пока нет")
        return
    
    users_text = "👥 Последние 20 пользователей:\n\n"
    for i, user in enumerate(users[:20], 1):
        user_id, username, balance = user
        users_text += f"{i}. @{username or 'нет'} (ID: {user_id}) - {balance}р\n"
    
    await bot.send_message(ADMIN_ID, users_text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'admin_top_ref')
async def admin_top_ref_callback(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        await bot.answer_callback_query(callback_query.id, "Нет доступа!")
        return
    
    top_referrers = await db.get_top_referrers(10)
    
    if not top_referrers:
        await bot.send_message(ADMIN_ID, "Рефералов пока нет")
        return
    
    top_text = "🏆 Топ рефереров:\n\n"
    for i, (user_id, username, ref_count) in enumerate(top_referrers, 1):
        top_text += f"{i}. @{username or 'нет'} (ID: {user_id}) - {ref_count} рефералов\n"
    
    await bot.send_message(ADMIN_ID, top_text)
    await bot.answer_callback_query(callback_query.id)

# Обработка колбэков для доната
@dp.callback_query_handler(lambda c: c.data.startswith('donate_'))
async def donate_role_callback(callback_query: types.CallbackQuery):
    role = callback_query.data.split('_')[1]
    role_names = {'baron': 'Барон', 'strazh': 'Страж', 'hero': 'Герой'}
    
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        f"Вы выбрали: {role_names[role]}\nВыберите срок:",
        reply_markup=get_donate_period_menu(role)
    )

@dp.callback_query_handler(lambda c: c.data.startswith('buy_'))
async def buy_donate_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    _, role, period, price = callback_query.data.split('_')
    price = int(price)
    
    # Получаем данные пользователя
    user = await db.get_user(user_id)
    
    # Проверка баланса
    if user['balance'] < price:
        await bot.answer_callback_query(
            callback_query.id,
            f"❌ Недостаточно средств на балансе. Нужно: {price}р, у вас: {user['balance']}р",
            show_alert=True
        )
        return
    
    await bot.answer_callback_query(callback_query.id)
    
    # Сохраняем данные о покупке
    await state.update_data(
        purchase_type='donate',
        role=role,
        period=period,
        price=price
    )
    
    role_names = {'baron': 'Барон', 'strazh': 'Страж', 'hero': 'Герой'}
    await bot.send_message(
        user_id,
        f"Вы точно хотите купить {role_names[role]} ({period}) за {price}р?",
        reply_markup=get_confirm_menu()
    )

@dp.callback_query_handler(lambda c: c.data == 'confirm_yes')
async def confirm_yes_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data = await state.get_data()
    price = data['price']
    
    # Списываем средства
    new_balance = await db.update_balance(user_id, -price, "Покупка доната")
    
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        user_id,
        "✅ Покупка подтверждена! Теперь отправьте ваш игровой ник:"
    )
    # Устанавливаем состояние для ввода ника
    await state.set_state('waiting_for_nickname')

@dp.callback_query_handler(lambda c: c.data == 'confirm_no')
async def confirm_no_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "❌ Покупка отменена.",
        reply_markup=get_main_menu()
    )
    await state.finish()

# Обработка ввода ника
@dp.message_handler(state='waiting_for_nickname')
async def process_nickname(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    nickname = message.text
    
    # Сохраняем ник
    await db.update_nickname(user_id, nickname)
    await state.update_data(nickname=nickname)
    
    await message.answer(
        f"Ваш ник: {nickname}\n"
        "⚠️ Внимание: ник нельзя будет изменить после подтверждения!",
        reply_markup=get_nick_confirm_menu()
    )

@dp.callback_query_handler(lambda c: c.data == 'nick_confirm', state='*')
async def nick_confirm_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data = await state.get_data()
    
    # Добавляем покупку в базу данных
    if data['purchase_type'] == 'donate':
        role_names = {'baron': 'Барон', 'strazh': 'Страж', 'hero': 'Герой'}
        item_name = f"{role_names[data['role']]} {data['period']}"
        purchase_id = await db.add_purchase(
            user_id,
            'donate',
            item_name,
            1,
            data['price'],
            data.get('nickname', '')
        )
        
        # Завершаем покупку
        await db.complete_purchase(purchase_id)
        
        # Отправляем уведомление админу
        user = await db.get_user(user_id)
        purchase_info = (
            f"🛒 Новая покупка!\n\n"
            f"👤 Пользователь: @{callback_query.from_user.username or 'нет'} (ID: {user_id})\n"
            f"📦 Товар: {item_name}\n"
            f"💰 Цена: {data['price']}р\n"
            f"🎮 Ник игрока: {data.get('nickname', 'не указан')}\n"
            f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    await bot.send_message(ADMIN_ID, purchase_info)
    await bot.answer_callback_query(callback_query.id, "✅ Ник подтвержден! Администратор уведомлен.")
    
    await bot.send_message(
        user_id,
        "✅ Покупка завершена! Администратор получил уведомление.",
        reply_markup=get_main_menu()
    )
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == 'nick_change', state='*')
async def nick_change_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Введите новый ник:"
    )
    await state.set_state('waiting_for_nickname')

# Обработка валюты
@dp.callback_query_handler(lambda c: c.data == 'currency_1kk_9')
async def currency_1kk_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await state.update_data(currency_price=9)
    await bot.send_message(
        callback_query.from_user.id,
        "Выберите количество (от 1 до 100):",
        reply_markup=get_currency_amount_menu()
    )

@dp.callback_query_handler(lambda c: c.data.startswith('amount_'))
async def currency_amount_callback(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    amount = int(callback_query.data.split('_')[1])
    
    # Получаем данные из состояния
    data = await state.get_data()
    price_per_unit = data.get('currency_price', 9)
    total_price = amount * price_per_unit
    
    # Получаем данные пользователя
    user = await db.get_user(user_id)
    
    # Проверка баланса
    if user['balance'] < total_price:
        await bot.answer_callback_query(
            callback_query.id,
            f"❌ Недостаточно средств. Нужно: {total_price}р, у вас: {user['balance']}р",
            show_alert=True
        )
        return
    
    await bot.answer_callback_query(callback_query.id)
    
    # Сохраняем данные о покупке
    await state.update_data(
        purchase_type='currency',
        amount=amount,
        price=total_price,
        currency_price=price_per_unit
    )
    
    await bot.send_message(
        user_id,
        f"Вы хотите купить {amount}кк за {total_price}р?\n"
        f"После подтверждения нужно будет указать игровой ник.",
        reply_markup=get_confirm_menu()
    )

# Навигация назад
@dp.callback_query_handler(lambda c: c.data == 'back_main')
async def back_main_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Главное меню:",
        reply_markup=get_main_menu()
    )
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == 'back_donate')
async def back_donate_callback(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Выберите роль:",
        reply_markup=get_donate_role_menu()
    )

@dp.callback_query_handler(lambda c: c.data == 'back_currency')
async def back_currency_callback(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        "Выберите количество валюты:",
        reply_markup=get_currency_menu()
    )

# Обработчик команды для пополнения баланса (для тестирования)
@dp.message_handler(commands=['addbalance'])
async def add_balance_command(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.answer("Команда только для администратора")
        return
    
    try:
        # Формат: /addbalance <user_id> <amount>
        args = message.get_args().split()
        if len(args) != 2:
            await message.answer("Использование: /addbalance <user_id> <amount>")
            return
        
        target_user_id = int(args[0])
        amount = float(args[1])
        
        new_balance = await db.update_balance(target_user_id, amount, "Административное пополнение")
        await message.answer(f"Баланс пользователя {target_user_id} пополнен на {amount}р. Новый баланс: {new_balance}р")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# Запуск бота
async def on_startup(dp):
    """Действия при запуске бота"""
    await db.create_tables()
    logging.info("База данных инициализирована")
    
    # Отправляем сообщение админу о запуске бота
    try:
        await bot.send_message(ADMIN_ID, "🤖 Бот MedakFUN запущен и готов к работе!")
    except:
        pass

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
