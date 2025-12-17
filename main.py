import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
import os
from dotenv import load_dotenv

from database import Database
from keyboards import *

# .env faylni yuklash
load_dotenv()

# Bot sozlamalari
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '2008')

# Logging sozlash
logging.basicConfig(level=logging.INFO)

# Bot va Dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Database
db = Database()


# ============= STATES =============
class AdminAuth(StatesGroup):
    waiting_password = State()


class AddMovie(StatesGroup):
    waiting_code = State()
    waiting_title = State()
    waiting_file = State()


class DeleteMovie(StatesGroup):
    waiting_code = State()


class Broadcast(StatesGroup):
    waiting_message = State()


class SendMessage(StatesGroup):
    waiting_user_id = State()
    waiting_message = State()


class BlockUser(StatesGroup):
    waiting_user_id = State()


class UnblockUser(StatesGroup):
    waiting_user_id = State()


class AddChannel(StatesGroup):
    waiting_channel = State()


class DeleteChannel(StatesGroup):
    waiting_channel = State()


class GetUserInfo(StatesGroup):
    waiting_user_id = State()


# ============= HELPER FUNCTIONS =============
async def check_subscription(user_id: int) -> bool:
    """Foydalanuvchi barcha kanallarga a'zo ekanligini tekshirish"""
    channels = db.get_all_channels()
    if not channels:
        return True

    for channel_id, _ in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            logging.error(f"Kanal tekshirishda xato: {e}")
            continue

    return True


def is_admin(user_id: int) -> bool:
    """Admin ekanligini tekshirish"""
    # Har kim parol bilan kirsa admin bo'lishi mumkin
    return True


def is_admin_authenticated(user_id: int) -> bool:
    """Admin autentifikatsiya qilinganligini tekshirish"""
    # Database'dan tekshiramiz
    return db.is_admin_authenticated(user_id)


# ============= START COMMAND =============
@dp.message(Command('start'))
async def cmd_start(message: Message):
    user_id = message.from_user.id

    # Bloklangan foydalanuvchini tekshirish
    if db.is_user_blocked(user_id):
        await message.answer("❌ Siz bloklangansiz. Botdan foydalana olmaysiz.")
        return

    # Foydalanuvchi bazada bormi tekshirish
    if not db.user_exists(user_id):
        db.add_user(
            user_id=user_id,
            full_name=message.from_user.full_name,
            username=message.from_user.username
        )
        await message.answer(
            f"👋 Assalomu alaykum, {message.from_user.full_name}!\n\n"
            "📱 Botdan foydalanish uchun telefon raqamingizni yuboring.",
            reply_markup=phone_button()
        )
        return

    # Telefon raqami bormi tekshirish
    user_info = db.get_user_info(user_id)
    if not user_info[1]:  # phone bo'sh bo'lsa
        await message.answer(
            "📱 Botdan foydalanish uchun telefon raqamingizni yuboring.",
            reply_markup=phone_button()
        )
        return

    # Kanalga a'zolikni tekshirish
    if not await check_subscription(user_id):
        channels = db.get_all_channels()
        await message.answer(
            "📢 Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:",
            reply_markup=channels_keyboard(channels)
        )
        return

    # Asosiy menyu
    await message.answer(
        f"🎬 Xush kelibsiz, {message.from_user.full_name}!\n\n"
        "Kino kodini yuboring va kinoni oling.",
        reply_markup=main_menu()
    )


# ============= TELEFON RAQAM QABUL QILISH =============
@dp.message(F.contact)
async def get_phone(message: Message):
    user_id = message.from_user.id
    phone = message.contact.phone_number

    db.update_user_phone(user_id, phone)

    # Kanalga a'zolikni tekshirish
    if not await check_subscription(user_id):
        channels = db.get_all_channels()
        await message.answer(
            "📢 Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:",
            reply_markup=channels_keyboard(channels)
        )
        return

    await message.answer(
        "✅ Telefon raqamingiz saqlandi!\n\n"
        "🎬 Endi kino kodini yuboring.",
        reply_markup=main_menu()
    )


# ============= KANALGA A'ZOLIKNI TEKSHIRISH =============
@dp.callback_query(F.data == 'check_subscription')
async def check_sub_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    if await check_subscription(user_id):
        await callback.message.delete()
        await callback.message.answer(
            "✅ Barcha kanallarga a'zo bo'lgansiz!\n\n"
            "🎬 Kino kodini yuboring.",
            reply_markup=main_menu()
        )
    else:
        await callback.answer("❌ Siz hali barcha kanallarga a'zo bo'lmagansiz!", show_alert=True)


# ============= ADMIN PANEL =============
@dp.message(Command('admin'))
async def cmd_admin(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Agar allaqachon autentifikatsiya qilingan bo'lsa
    if is_admin_authenticated(user_id):
        stats = f"""
📊 <b>Statistika</b>

👥 Jami foydalanuvchilar: {db.get_total_users()}
✅ Faol foydalanuvchilar: {db.get_active_users()}
🎬 Jami kinolar: {db.get_total_movies()}
📢 Majburiy kanallar: {len(db.get_all_channels())}
        """
        await message.answer(stats, reply_markup=admin_panel(), parse_mode='HTML')
        return

    # Parol so'rash
    await message.answer("🔐 Admin paneliga kirish uchun parolni kiriting:")
    await state.set_state(AdminAuth.waiting_password)


@dp.message(AdminAuth.waiting_password)
async def process_admin_password(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if message.text == ADMIN_PASSWORD:
        # Sessiyani database'ga yozamiz
        db.create_admin_session(user_id)
        await state.clear()

        stats = f"""
📊 <b>Statistika</b>

👥 Jami foydalanuvchilar: {db.get_total_users()}
✅ Faol foydalanuvchilar: {db.get_active_users()}
🎬 Jami kinolar: {db.get_total_movies()}
📢 Majburiy kanallar: {len(db.get_all_channels())}
        """
        await message.answer("✅ Xush kelibsiz, Admin!\n\n" + stats, reply_markup=admin_panel(), parse_mode='HTML')
    else:
        await message.answer("❌ Parol noto'g'ri. Qaytadan urinib ko'ring:")


# ============= ADMIN CHIQISH =============
@dp.message(F.text == "🚪 Admin paneldan chiqish")
async def admin_logout(message: Message):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        return

    db.logout_admin(user_id)
    await message.answer("👋 Admin paneldan chiqdingiz.", reply_markup=main_menu())


# ============= STATISTIKA =============
@dp.message(F.text == "📊 Statistika")
async def show_statistics(message: Message):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    stats = f"""
📊 <b>Batafsil Statistika</b>

👥 Jami foydalanuvchilar: {db.get_total_users()}
✅ Faol foydalanuvchilar: {db.get_active_users()}
🚫 Bloklangan: {db.get_blocked_users()}
🎬 Jami kinolar: {db.get_total_movies()}
📢 Majburiy kanallar: {len(db.get_all_channels())}
    """

    await message.answer(stats, parse_mode='HTML')


# ============= KINO QO'SHISH =============
@dp.message(F.text == "➕ Kino qo'shish")
async def add_movie_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer("🎬 Kino kodini kiriting:", reply_markup=cancel_button())
    await state.set_state(AddMovie.waiting_code)


@dp.message(AddMovie.waiting_code)
async def process_movie_code(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=admin_panel())
        return

    await state.update_data(code=message.text)
    await message.answer("📝 Kino nomini kiriting:")
    await state.set_state(AddMovie.waiting_title)


@dp.message(AddMovie.waiting_title)
async def process_movie_title(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=admin_panel())
        return

    await state.update_data(title=message.text)
    await message.answer("🎥 Kino faylini yuboring (video):")
    await state.set_state(AddMovie.waiting_file)


@dp.message(AddMovie.waiting_file)
async def process_movie_file(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=admin_panel())
        return

    if not message.video:
        await message.answer("❌ Iltimos, video fayl yuboring!")
        return

    data = await state.get_data()
    code = data['code']
    title = data['title']
    file_id = message.video.file_id

    if db.add_movie(code, title, file_id):
        await message.answer(f"✅ Kino muvaffaqiyatli qo'shildi!\n\n📝 Kod: {code}\n🎬 Nom: {title}",
                             reply_markup=admin_panel())
    else:
        await message.answer("❌ Bu kod allaqachon mavjud!", reply_markup=admin_panel())

    await state.clear()


# ============= KINO O'CHIRISH =============
@dp.message(F.text == "🗑 Kino o'chirish")
async def delete_movie_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer("🗑 O'chirish uchun kino kodini kiriting:", reply_markup=cancel_button())
    await state.set_state(DeleteMovie.waiting_code)


@dp.message(DeleteMovie.waiting_code)
async def process_delete_movie(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=admin_panel())
        return

    code = message.text
    movie = db.get_movie(code)

    if movie:
        db.delete_movie(code)
        await message.answer(f"✅ Kino o'chirildi!\n\n📝 Kod: {code}\n🎬 Nom: {movie[1]}", reply_markup=admin_panel())
    else:
        await message.answer("❌ Bu kod bilan kino topilmadi!", reply_markup=admin_panel())

    await state.clear()


# ============= REKLAMA YUBORISH =============
@dp.message(F.text == "📢 Reklama yuborish")
async def broadcast_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer(
        "📢 Reklama xabarini yuboring (matn, rasm, video):\n\n"
        "⚠️ Bu xabar barcha foydalanuvchilarga yuboriladi!",
        reply_markup=cancel_button()
    )
    await state.set_state(Broadcast.waiting_message)


@dp.message(Broadcast.waiting_message)
async def process_broadcast(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=admin_panel())
        return

    users = db.get_all_users()
    success = 0
    failed = 0

    status_msg = await message.answer(f"📤 Yuborilmoqda...\n\n✅ Yuborildi: {success}\n❌ Xato: {failed}")

    for user in users:
        user_id = user[0]
        try:
            await message.copy_to(user_id)
            success += 1

            if success % 10 == 0:
                await status_msg.edit_text(f"📤 Yuborilmoqda...\n\n✅ Yuborildi: {success}\n❌ Xato: {failed}")

            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logging.error(f"Reklama yuborishda xato: {e}")

    await status_msg.edit_text(
        f"✅ Reklama yuborish yakunlandi!\n\n"
        f"📊 Jami: {len(users)}\n"
        f"✅ Yuborildi: {success}\n"
        f"❌ Xato: {failed}"
    )
    await message.answer("Asosiy menyu:", reply_markup=admin_panel())
    await state.clear()


# ============= HABAR YUBORISH =============
@dp.message(F.text == "✉️ Habar yuborish")
async def send_message_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer("👤 Foydalanuvchi ID sini kiriting:", reply_markup=cancel_button())
    await state.set_state(SendMessage.waiting_user_id)


@dp.message(SendMessage.waiting_user_id)
async def process_send_message_user(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=admin_panel())
        return

    try:
        target_user_id = int(message.text)
        if not db.user_exists(target_user_id):
            await message.answer("❌ Bu foydalanuvchi topilmadi!")
            return

        await state.update_data(target_user_id=target_user_id)
        await message.answer("✉️ Yubormoqchi bo'lgan xabaringizni yozing:")
        await state.set_state(SendMessage.waiting_message)
    except ValueError:
        await message.answer("❌ Noto'g'ri ID! Faqat raqam kiriting.")


@dp.message(SendMessage.waiting_message)
async def process_send_message_text(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=admin_panel())
        return

    data = await state.get_data()
    target_user_id = data['target_user_id']

    try:
        await message.copy_to(target_user_id)
        await message.answer(f"✅ Xabar foydalanuvchiga yuborildi! (ID: {target_user_id})", reply_markup=admin_panel())
    except Exception as e:
        await message.answer(f"❌ Xabar yuborishda xato: {e}", reply_markup=admin_panel())

    await state.clear()


# ============= FOYDALANUVCHILAR =============
@dp.message(F.text == "👥 Foydalanuvchilar")
async def user_management_menu(message: Message):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer("👥 Foydalanuvchilarni boshqarish:", reply_markup=user_management())


# ============= BLOKLASH =============
@dp.message(F.text == "🚫 Foydalanuvchini bloklash")
async def block_user_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer("👤 Bloklash uchun foydalanuvchi ID sini kiriting:", reply_markup=cancel_button())
    await state.set_state(BlockUser.waiting_user_id)


@dp.message(BlockUser.waiting_user_id)
async def process_block_user(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=user_management())
        return

    try:
        target_user_id = int(message.text)
        if not db.user_exists(target_user_id):
            await message.answer("❌ Bu foydalanuvchi topilmadi!")
            return

        db.block_user(target_user_id)
        await message.answer(f"✅ Foydalanuvchi bloklandi! (ID: {target_user_id})", reply_markup=user_management())

        try:
            await bot.send_message(target_user_id, "❌ Siz admin tomonidan bloklandingiz.")
        except:
            pass
    except ValueError:
        await message.answer("❌ Noto'g'ri ID! Faqat raqam kiriting.")

    await state.clear()


# ============= BLOKDAN CHIQARISH =============
@dp.message(F.text == "✅ Blokdan chiqarish")
async def unblock_user_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer("👤 Blokdan chiqarish uchun foydalanuvchi ID sini kiriting:", reply_markup=cancel_button())
    await state.set_state(UnblockUser.waiting_user_id)


@dp.message(UnblockUser.waiting_user_id)
async def process_unblock_user(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=user_management())
        return

    try:
        target_user_id = int(message.text)
        if not db.user_exists(target_user_id):
            await message.answer("❌ Bu foydalanuvchi topilmadi!")
            return

        db.unblock_user(target_user_id)
        await message.answer(f"✅ Foydalanuvchi blokdan chiqarildi! (ID: {target_user_id})",
                             reply_markup=user_management())

        try:
            await bot.send_message(target_user_id, "✅ Siz admin tomonidan blokdan chiqarildingiz.")
        except:
            pass
    except ValueError:
        await message.answer("❌ Noto'g'ri ID! Faqat raqam kiriting.")

    await state.clear()


# ============= FOYDALANUVCHI MA'LUMOTI =============
@dp.message(F.text == "🔍 Foydalanuvchi ma'lumoti")
async def get_user_info_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer("👤 Foydalanuvchi ID sini kiriting:", reply_markup=cancel_button())
    await state.set_state(GetUserInfo.waiting_user_id)


@dp.message(GetUserInfo.waiting_user_id)
async def process_get_user_info(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=user_management())
        return

    try:
        target_user_id = int(message.text)
        user_info = db.get_user_info(target_user_id)

        if not user_info:
            await message.answer("❌ Bu foydalanuvchi topilmadi!")
            return

        status = "🚫 Bloklangan" if user_info[5] == 1 else "✅ Faol"

        info_text = f"""
👤 <b>Foydalanuvchi ma'lumotlari</b>

🆔 ID: <code>{user_info[0]}</code>
📱 Telefon: {user_info[1] or 'Yoq'}
👤 Ism: {user_info[2] or 'Yoq'}
🔗 Username: @{user_info[3] or 'Yoq'}
📅 Qo'shilgan: {user_info[4]}
📊 Status: {status}
        """

        await message.answer(info_text, parse_mode='HTML', reply_markup=user_management())
    except ValueError:
        await message.answer("❌ Noto'g'ri ID! Faqat raqam kiriting.")

    await state.clear()


# ============= KANALLAR BOSHQARUVI =============
@dp.message(F.text == "📺 Kanallar boshqaruvi")
async def channels_menu(message: Message):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer("📺 Kanallarni boshqarish:", reply_markup=channels_management())


@dp.message(F.text == "➕ Yangi kanal qo'shish")
async def add_channel_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer(
        "📺 Kanal ID yoki username kiriting:\n\n"
        "Masalan: @mychannel yoki -1001234567890",
        reply_markup=cancel_button()
    )
    await state.set_state(AddChannel.waiting_channel)


@dp.message(AddChannel.waiting_channel)
async def process_add_channel(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=channels_management())
        return

    channel_input = message.text.strip()

    try:
        # Kanal ma'lumotlarini olish
        chat = await bot.get_chat(channel_input)
        channel_id = str(chat.id)
        channel_username = chat.username if chat.username else channel_id

        if db.add_channel(channel_id, f"@{channel_username}"):
            await message.answer(
                f"✅ Kanal muvaffaqiyatli qo'shildi!\n\n"
                f"📺 ID: {channel_id}\n"
                f"🔗 Username: @{channel_username}",
                reply_markup=channels_management()
            )
        else:
            await message.answer("❌ Bu kanal allaqachon qo'shilgan!", reply_markup=channels_management())
    except Exception as e:
        await message.answer(f"❌ Xato: {e}\n\nKanal ID yoki username to'g'ri ekanligini tekshiring.",
                             reply_markup=channels_management())

    await state.clear()


@dp.message(F.text == "🗑 Kanalni o'chirish")
async def delete_channel_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    await message.answer(
        "🗑 O'chirish uchun kanal ID kiriting:",
        reply_markup=cancel_button()
    )
    await state.set_state(DeleteChannel.waiting_channel)


@dp.message(DeleteChannel.waiting_channel)
async def process_delete_channel(message: Message, state: FSMContext):
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Asosiy menyu:", reply_markup=channels_management())
        return

    channel_id = message.text.strip()
    db.delete_channel(channel_id)
    await message.answer(f"✅ Kanal o'chirildi! (ID: {channel_id})", reply_markup=channels_management())
    await state.clear()


@dp.message(F.text == "📋 Kanallar ro'yxati")
async def list_channels(message: Message):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    channels = db.get_all_channels()

    if not channels:
        await message.answer("📋 Hozircha majburiy kanallar yo'q.")
        return

    text = "📋 <b>Majburiy kanallar ro'yxati:</b>\n\n"
    for i, (channel_id, channel_username) in enumerate(channels, 1):
        text += f"{i}. {channel_username}\n   ID: <code>{channel_id}</code>\n\n"

    await message.answer(text, parse_mode='HTML')


# ============= ORTGA QAYTISH =============
@dp.message(F.text == "◀️ Ortga qaytish")
async def back_to_admin(message: Message):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    stats = f"""
📊 <b>Statistika</b>

👥 Jami foydalanuvchilar: {db.get_total_users()}
✅ Faol foydalanuvchilar: {db.get_active_users()}
🎬 Jami kinolar: {db.get_total_movies()}
📢 Majburiy kanallar: {len(db.get_all_channels())}
    """
    await message.answer(stats, reply_markup=admin_panel(), parse_mode='HTML')


# ============= KINOLAR RO'YXATI =============
@dp.message(F.text == "🎬 Kinolar ro'yxati")
async def show_movies_list(message: Message):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    movies = db.get_all_movies()

    if not movies:
        await message.answer("📋 Hozircha kinolar ro'yxati bo'sh.")
        return

    text = "🎬 <b>Kinolar ro'yxati:</b>\n\n"
    for i, (code, title, added_date) in enumerate(movies[:20], 1):  # Faqat 20 ta ko'rsatish
        text += f"{i}. <b>{title}</b>\n"
        text += f"   📝 Kod: <code>{code}</code>\n"
        text += f"   📅 Qo'shilgan: {added_date}\n\n"

    if len(movies) > 20:
        text += f"\n... va yana {len(movies) - 20} ta kino"

    await message.answer(text, parse_mode='HTML')


# ============= MA'LUMOT VA ALOQA =============
@dp.message(F.text == "ℹ️ Ma'lumot")
async def show_info(message: Message):
    info_text = """
ℹ️ <b>Bot haqida ma'lumot</b>

Bu bot orqali siz kinolar kodlari yordamida filmlarni yuklab olishingiz mumkin.

🎬 Kino kodini bizning kanallarda topishingiz mumkin.
📢 Kanallarimizga a'zo bo'ling va kinolardan bahramand bo'ling!

💡 Qanday foydalanish:
1. Kanallarimizga a'zo bo'ling
2. Kino kodini oling
3. Botga kodni yuboring
4. Kinoni yuklab oling!
Admin @mirzayyevv
    """
    await message.answer(info_text, parse_mode='HTML')


@dp.message(F.text == "📞 Aloqa")
async def show_contact(message: Message):
    contact_text = """
📞 <b>Aloqa</b>

Savollar va takliflar uchun:
👤 Admin: @mirzayyevv

📧 Email: 978851477.j@gmail.com
🌐 Website: www.example.com

📝 Takliflar va shikoyatlar qabul qilinadi!
    """
    await message.answer(contact_text, parse_mode='HTML')


# ============= BARCHA USERLAR RO'YXATI =============
@dp.message(F.text == "📋 Barcha userlar")
async def show_all_users(message: Message):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    all_users = db.cursor.execute('''
        SELECT user_id, full_name, username, phone, joined_date, is_blocked
        FROM users
        ORDER BY joined_date DESC
        LIMIT 15
    ''').fetchall()

    if not all_users:
        await message.answer("📋 Hozircha foydalanuvchilar yo'q.")
        return

    text = "📋 <b>So'nggi 15 ta foydalanuvchi:</b>\n\n"
    for i, (uid, name, username, phone, joined, blocked) in enumerate(all_users, 1):
        status = "🚫" if blocked else "✅"
        username_text = f"@{username}" if username else "Username yo'q"
        text += f"{i}. {status} <b>{name}</b>\n"
        text += f"   🆔 ID: <code>{uid}</code>\n"
        text += f"   👤 {username_text}\n"
        text += f"   📱 {phone or 'Telefon yoq'}\n"
        text += f"   📅 {joined}\n\n"

    total = db.get_total_users()
    text += f"📊 Jami: {total} ta foydalanuvchi"

    await message.answer(text, parse_mode='HTML')


# ============= KANALLARNI YANGILASH =============
@dp.message(F.text == "🔄 Kanallarni yangilash")
async def refresh_channels(message: Message):
    user_id = message.from_user.id

    if not is_admin_authenticated(user_id):
        await message.answer("❌ Admin huquqi yo'q. Avval /admin buyrug'i bilan kirishingiz kerak.")
        return

    channels = db.get_all_channels()

    if not channels:
        await message.answer("📋 Hozircha kanallar yo'q.")
        return

    text = "🔄 <b>Kanallar yangilanmoqda...</b>\n\n"
    status_msg = await message.answer(text, parse_mode='HTML')

    active_channels = []
    inactive_channels = []

    for channel_id, channel_username in channels:
        try:
            chat = await bot.get_chat(channel_id)
            active_channels.append((channel_id, channel_username, chat.title))
        except Exception as e:
            inactive_channels.append((channel_id, channel_username))
            logging.error(f"Kanal tekshirishda xato: {e}")

    result_text = "✅ <b>Kanallar yangilandi!</b>\n\n"

    if active_channels:
        result_text += "✅ <b>Faol kanallar:</b>\n"
        for i, (cid, cusername, title) in enumerate(active_channels, 1):
            result_text += f"{i}. {title}\n   {cusername}\n\n"

    if inactive_channels:
        result_text += "\n❌ <b>Nofaol kanallar:</b>\n"
        for i, (cid, cusername) in enumerate(inactive_channels, 1):
            result_text += f"{i}. {cusername}\n   ID: <code>{cid}</code>\n\n"

    await status_msg.edit_text(result_text, parse_mode='HTML')


# ============= KINO KODI QABUL QILISH =============
@dp.message(F.text == "🎬 Kino kodi yuborish")
async def request_movie_code(message: Message):
    await message.answer("🎬 Kino kodini yuboring:")


@dp.message(F.text)
async def handle_movie_code(message: Message):
    user_id = message.from_user.id

    # Bloklangan foydalanuvchini tekshirish
    if db.is_user_blocked(user_id):
        await message.answer("❌ Siz bloklangansiz. Botdan foydalana olmaysiz.")
        return

    # Admin buyruqlarini tekshirish
    admin_commands = ["➕ Kino qo'shish", "🗑 Kino o'chirish", "📢 Reklama yuborish", "✉️ Habar yuborish",
                      "📊 Statistika", "👥 Foydalanuvchilar", "📺 Kanallar boshqaruvi", "🎬 Kinolar ro'yxati",
                      "🚪 Admin paneldan chiqish", "◀️ Ortga qaytish", "➕ Yangi kanal qo'shish",
                      "🗑 Kanalni o'chirish", "📋 Kanallar ro'yxati", "🔄 Kanallarni yangilash",
                      "🚫 Foydalanuvchini bloklash", "✅ Blokdan chiqarish", "🔍 Foydalanuvchi ma'lumoti",
                      "📋 Barcha userlar"]

    if message.text in admin_commands:
        return

    # Asosiy menyu buyruqlarini tekshirish
    if message.text in ["ℹ️ Ma'lumot", "📞 Aloqa", "🎬 Kino kodi yuborish"]:
        return

    # Foydalanuvchi mavjudligini tekshirish
    if not db.user_exists(user_id):
        await message.answer("📱 Iltimos avval /start buyrug'ini yuboring.")
        return

    # Telefon raqami borligini tekshirish
    user_info = db.get_user_info(user_id)
    if not user_info[1]:
        await message.answer("📱 Botdan foydalanish uchun telefon raqamingizni yuboring.", reply_markup=phone_button())
        return

    # Kanalga a'zolikni tekshirish
    if not await check_subscription(user_id):
        channels = db.get_all_channels()
        await message.answer(
            "📢 Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:",
            reply_markup=channels_keyboard(channels)
        )
        return

    # Kino kodini tekshirish
    code = message.text.strip()

    # Bo'sh matn yoki maxsus buyruq emasligini tekshirish
    if not code or code.startswith('/'):
        return

    movie = db.get_movie(code)

    if not movie:
        await message.answer("❌ Bu kod bilan kino topilmadi. Kodni tekshirib qayta urinib ko'ring.")
        return

    try:
        # Kinoni yuborish
        await message.answer_video(
            movie[2],  # file_id
            caption=f"🎬 {movie[1]}\n\n✅ Kino muvaffaqiyatli yuklab olindi!"
        )
    except Exception as e:
        await message.answer(f"❌ Kinoni yuborishda xato: {e}")
        logging.error(f"Kino yuborishda xato: {e}")


# ============= BOTNI ISHGA TUSHIRISH =============
async def main():
    logging.info("Bot ishga tushmoqda...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())