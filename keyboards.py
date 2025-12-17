from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


# ============= TELEFON RAQAM TUGMASI =============
def phone_button():
    """Telefon raqam so'rash tugmasi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    return keyboard


# ============= ASOSIY MENYU =============
def main_menu():
    """Oddiy foydalanuvchi uchun asosiy menyu"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Kino kodi yuborish")],
            [KeyboardButton(text="ℹ️ Ma'lumot"), KeyboardButton(text="📞 Aloqa")]
        ],
        resize_keyboard=True
    )
    return keyboard


# ============= MAJBURIY KANALLAR TUGMALARI =============
def channels_keyboard(channels):
    """Majburiy kanallar uchun inline tugmalar"""
    buttons = []

    # Har bir kanal uchun tugma
    for channel_id, channel_username in channels:
        buttons.append([InlineKeyboardButton(
            text=f"📢 {channel_username}",
            url=f"https://t.me/{channel_username.replace('@', '')}"
        )])

    # Tekshirish tugmasi
    buttons.append([InlineKeyboardButton(
        text="✅ A'zolikni tekshirish",
        callback_data="check_subscription"
    )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


# ============= ADMIN PANEL ASOSIY MENYU =============
def admin_panel():
    """Admin uchun asosiy panel"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
            [KeyboardButton(text="📢 Reklama yuborish"), KeyboardButton(text="✉️ Habar yuborish")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="👥 Foydalanuvchilar")],
            [KeyboardButton(text="📺 Kanallar boshqaruvi"), KeyboardButton(text="🎬 Kinolar ro'yxati")],
            [KeyboardButton(text="🚪 Admin paneldan chiqish")]
        ],
        resize_keyboard=True
    )
    return keyboard


# ============= FOYDALANUVCHILAR BOSHQARUVI =============
def user_management():
    """Foydalanuvchilarni boshqarish menyusi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚫 Foydalanuvchini bloklash"), KeyboardButton(text="✅ Blokdan chiqarish")],
            [KeyboardButton(text="🔍 Foydalanuvchi ma'lumoti"), KeyboardButton(text="📋 Barcha userlar")],
            [KeyboardButton(text="◀️ Ortga qaytish")]
        ],
        resize_keyboard=True
    )
    return keyboard


# ============= KANALLAR BOSHQARUVI =============
def channels_management():
    """Kanallarni boshqarish menyusi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Yangi kanal qo'shish"), KeyboardButton(text="🗑 Kanalni o'chirish")],
            [KeyboardButton(text="📋 Kanallar ro'yxati"), KeyboardButton(text="🔄 Kanallarni yangilash")],
            [KeyboardButton(text="◀️ Ortga qaytish")]
        ],
        resize_keyboard=True
    )
    return keyboard


# ============= BEKOR QILISH TUGMASI =============
def cancel_button():
    """Bekor qilish tugmasi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Bekor qilish")]
        ],
        resize_keyboard=True
    )
    return keyboard


# ============= TASDIQLASH TUGMALARI =============
def confirm_keyboard():
    """Tasdiqlash uchun inline tugmalar"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, ishonchim komil", callback_data="confirm_yes"),
                InlineKeyboardButton(text="❌ Yo'q, bekor qilish", callback_data="confirm_no")
            ]
        ]
    )
    return keyboard


# ============= HA/YO'Q TUGMALARI =============
def yes_no_keyboard():
    """Oddiy Ha/Yo'q tugmalari"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha", callback_data="yes"),
                InlineKeyboardButton(text="❌ Yo'q", callback_data="no")
            ]
        ]
    )
    return keyboard


# ============= ADMIN ORTGA QAYTISH =============
def back_to_admin():
    """Admin paneliga qaytish tugmasi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="◀️ Admin panelga qaytish")]
        ],
        resize_keyboard=True
    )
    return keyboard


# ============= REKLAMA YUBORISH OPSIYALARI =============
def broadcast_options():
    """Reklama yuborish opsiyalari"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Hammaga yuborish", callback_data="broadcast_all")],
            [InlineKeyboardButton(text="👥 Faol userlarga", callback_data="broadcast_active")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="broadcast_cancel")]
        ]
    )
    return keyboard


# ============= KINO O'CHIRISH TASDIQLASH =============
def confirm_delete_movie(code):
    """Kinoni o'chirishni tasdiqlash"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Ha, o'chirish", callback_data=f"delete_movie_{code}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_delete")
            ]
        ]
    )
    return keyboard


# ============= KANAL O'CHIRISH TASDIQLASH =============
def confirm_delete_channel(channel_id):
    """Kanalni o'chirishni tasdiqlash"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Ha, o'chirish", callback_data=f"delete_channel_{channel_id}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_delete")
            ]
        ]
    )
    return keyboard


# ============= SAHIFALASH TUGMALARI =============
def pagination_keyboard(current_page, total_pages, callback_prefix):
    """Sahifalash uchun tugmalar"""
    buttons = []

    # Orqaga tugmasi
    if current_page > 1:
        buttons.append(InlineKeyboardButton(
            text="◀️ Orqaga",
            callback_data=f"{callback_prefix}_{current_page - 1}"
        ))

    # Hozirgi sahifa
    buttons.append(InlineKeyboardButton(
        text=f"📄 {current_page}/{total_pages}",
        callback_data="current_page"
    ))

    # Oldinga tugmasi
    if current_page < total_pages:
        buttons.append(InlineKeyboardButton(
            text="Oldinga ▶️",
            callback_data=f"{callback_prefix}_{current_page + 1}"
        ))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    return keyboard


# ============= INLINE YOPISH TUGMASI =============
def close_button():
    """Xabarni yopish tugmasi"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Yopish", callback_data="close_message")]
        ]
    )
    return keyboard


# ============= SOZLAMALAR MENYUSI =============
def settings_menu():
    """Sozlamalar menyusi (kelajak uchun)"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔔 Bildirishnomalar"), KeyboardButton(text="🌐 Til sozlamalari")],
            [KeyboardButton(text="📊 Mening statistikam"), KeyboardButton(text="🔒 Maxfiylik")],
            [KeyboardButton(text="◀️ Ortga")]
        ],
        resize_keyboard=True
    )
    return keyboard


# ============= YORDAM MENYUSI =============
def help_menu():
    """Yordam menyusi"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❓ Qo'llanma", callback_data="help_guide")],
            [InlineKeyboardButton(text="📞 Qo'llab-quvvatlash", callback_data="help_support")],
            [InlineKeyboardButton(text="💡 Ko'p so'raladigan savollar", callback_data="help_faq")],
            [InlineKeyboardButton(text="❌ Yopish", callback_data="close_message")]
        ]
    )
    return keyboard