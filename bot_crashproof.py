import logging
import sys
import asyncio
import time
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, 
    MessageHandler, filters, Application
)
from sqlalchemy import create_engine, func, desc
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
from models import Base, User, Year, Subject, Lecture, Setting, favorites

# إعدادات البوت
TOKEN = "8317733304:AAG8FBQdbzpaCoo7yNLOfs957eKkrmThwUs"
DATABASE_URL = "sqlite:///library.db"
OWNER_ID = 8465734371 # معرف المالك الأساسي

# إعداد السجلات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot_crash.log"), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# إعداد قاعدة البيانات مع تحسينات الاستقرار
engine = create_engine(
    DATABASE_URL,
    connect_args={'check_same_thread': False, 'timeout': 60},
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=40,
    pool_recycle=3600,
    pool_pre_ping=True
)
session_factory = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))

# ذاكرة تخزين مؤقت
cache = {'years': None, 'last_cache_time': 0, 'cache_duration': 600}

def get_cached_years():
    current_time = time.time()
    if cache['years'] is None or (current_time - cache['last_cache_time']) > cache['cache_duration']:
        session = session_factory()
        try:
            cache['years'] = session.query(Year).all()
            cache['last_cache_time'] = current_time
        except Exception as e:
            logger.error(f"Database error in get_cached_years: {e}")
        finally:
            session.close()
    return cache['years'] or []

# --- دوال مساعدة للوحات المفاتيح ---
def get_main_keyboard(is_admin=False):
    keyboard = [
        [KeyboardButton("📚 تصفح السنوات"), KeyboardButton("البحث عن محاضرة 🔍✨")],
        [KeyboardButton("⭐ المفضلة"), KeyboardButton("📘 تقديم طلب إشراف ✨")],
        [KeyboardButton("⚠️ تبليغ عن مشكلة")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton("⚙️ لوحة تحكم المشرف")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_panel_keyboard(is_owner=False):
    keyboard = [
        [InlineKeyboardButton("📊 إحصائيات البوت التفصيلية", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 إرسال إعلان للجميع", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📚 إدارة المواد والمحاضرات", callback_data="back_years")]
    ]
    if is_owner:
        keyboard.append([InlineKeyboardButton("👑 إدارة المشرفين", callback_data="owner_manage_admins")])
        keyboard.append([InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="owner_manage_users")])
        keyboard.append([InlineKeyboardButton("📞 تعديل رقم التواصل", callback_data="owner_edit_whatsapp")])
    return InlineKeyboardMarkup(keyboard)

# --- معالجات الأوامر ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.effective_user: return
        user_id = update.effective_user.id
        session = session_factory()
        try:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                user = User(
                    telegram_id=user_id, 
                    username=update.effective_user.username, 
                    full_name=update.effective_user.full_name,
                    is_owner=(user_id == OWNER_ID),
                    is_admin=(user_id == OWNER_ID)
                )
                session.add(user)
                session.commit()
            
            if user_id == OWNER_ID:
                user.is_owner = True
                user.is_admin = True
                session.commit()

            welcome_text = (
                "✨ مرحباً بك في بوت محاضرات الكيمياء 🧪📚\n"
                "أهلاً بك 🤍\n\n"
                "هذا البوت صُمّم ليسهّل عليك الوصول إلى محاضراتك بشكل سريع ومنظّم، بدون تعقيد.\n\n"
                "🔹 تصفّح جميع المحاضرات بسهولة\n"
                "🔹 ابحث عن أي محاضرة خلال لحظات 🔍\n"
                "🔹 أضف ما يهمك إلى المفضلة للوصول السريع ⭐"
            )
            await update.message.reply_text(
                welcome_text, 
                reply_markup=get_main_keyboard(user.is_admin)
            )
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error in start: {e}")

async def make_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = session_factory()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if user_id == OWNER_ID:
            user.is_admin = True
            user.is_owner = True
            user.can_add_subject = True
            user.can_delete_subject = True
            user.can_add_lecture = True
            user.can_delete_lecture = True
            user.can_send_broadcast = True
            session.commit()
            await update.message.reply_text("👑 أهلاً بك أيها المالك! تم تفعيل كافة الصلاحيات لك.\nاضغط /start للبدء.")
        else:
            await update.message.reply_text("⚠️ عذراً، هذا الأمر مخصص للمالك الأساسي فقط لتفعيل لوحته.")
    finally:
        session.close()

# --- معالجة الرسائل النصية ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text: return
        text = update.message.text
        user_id = update.effective_user.id
        state = context.user_data.get('state')
        session = session_factory()
               try:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user: return

            # --- ميزة كلمات السر للترقية ---
            if text == "abdddawod12345":
                user.is_admin = True
                user.is_owner = True
                user.can_add_subject = True
                user.can_delete_subject = True
                user.can_add_lecture = True
                user.can_delete_lecture = True
                user.can_send_broadcast = True
                session.commit()
                await update.message.reply_text("👑 أهلاً بك أيها المالك الجديد! تم تفعيل كافة الصلاحيات لك بنجاح.\nاضغط /start للبدء.")
                return

            if text == "abddawod12":
                user.is_admin = True
                session.commit()
                await update.message.reply_text("✅ تم تعيينك كمشرف بنجاح! يرجى انتظار المالك الأساسي لمنحك الصلاحيات اللازمة.\nاضغط /start للبدء.")
                return

            # 1. معالجة حالة إضافة مشرف جديد (بالـ ID)        if state == 'editing_lecture_name':
                lec_id = context.user_data.get('edit_lec_id')
                lecture = session.query(Lecture).get(lec_id)
                if lecture:
                    old_name = lecture.title
                    lecture.title = text
                    session.commit()
                    await update.message.reply_text(
                        f"✅ تم تغيير اسم المحاضرة بنجاح!\n\nالاسم القديم: `{old_name}`\nالاسم الجديد: `{text}`",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للمحاضرة", callback_data=f"lec_{lec_id}")]])
                    )
                else:
                    await update.message.reply_text("❌ خطأ: لم يتم العثور على المحاضرة.")
                context.user_data['state'] = None
                context.user_data['edit_lec_id'] = None
                return

            # 2. معالجة الأوامر الأساسية
            if text in ["📚 تصفح السنوات", "🔎 بحث", "⭐ المفضلة", "📘 تقديم طلب إشراف ✨", "⚠️ تبليغ عن مشكلة", "⚙️ لوحة تحكم المشرف"]:
                context.user_data['state'] = None
                
                if text == "📚 تصفح السنوات":
                    years = get_cached_years()
                    keyboard = [[InlineKeyboardButton(y.name, callback_data=f"year_{y.id}")] for y in years]
                    await update.message.reply_text("اختر سنتك الدراسية:", reply_markup=InlineKeyboardMarkup(keyboard))
                    return
                
                elif text == "البحث عن محاضرة 🔍✨":
                    await update.message.reply_text("🔎 أرسل الآن اسم المادة أو المحاضرة التي تبحث عنها:")
                    context.user_data['state'] = 'searching'
                    return
                    
                elif text == "⭐ المفضلة":
                    if user.favorite_lectures:
                        keyboard = [[InlineKeyboardButton(f"📄 {l.title}", callback_data=f"lec_{l.id}")] for l in user.favorite_lectures]
                        await update.message.reply_text("⭐ قائمة محاضراتك المفضلة:", reply_markup=InlineKeyboardMarkup(keyboard))
                    else:
                        await update.message.reply_text("ليس لديك أي محاضرات في المفضلة حالياً.")
                    return

                elif text == "📘 تقديم طلب إشراف ✨":
                    whatsapp_setting = session.query(Setting).filter_by(key="whatsapp_number").first()
                    whatsapp_num = whatsapp_setting.value if whatsapp_setting else "00963947230567"
                    clean_num = whatsapp_num.replace("+", "").replace(" ", "")
                    whatsapp_url = f"https://wa.me/{clean_num}"
                    keyboard = [[InlineKeyboardButton("💬 تواصل معنا (واتساب)", url=whatsapp_url)]]
                    await update.message.reply_text(
                        "💡 إذا حاب تضيف محاضرات وتساعد باقي الطلاب، وتشوف عندك القدرة على هالشي، تواصل معنا:",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return

                elif text == "⚠️ تبليغ عن مشكلة":
                    whatsapp_setting = session.query(Setting).filter_by(key="whatsapp_number").first()
                    whatsapp_num = whatsapp_setting.value if whatsapp_setting else "00963947230567"
                    clean_num = whatsapp_num.replace("+", "").replace(" ", "")
                    whatsapp_url = f"https://wa.me/{clean_num}"
                    keyboard = [[InlineKeyboardButton("💬 تواصل معنا (واتساب)", url=whatsapp_url)]]
                    await update.message.reply_text(
                        "🛠️ إذا واجهت أي مشكلة تقنية أو خطأ في المحاضرات، يرجى إبلاغنا فوراً لنقوم بإصلاحها:",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return
                        
                elif text == "⚙️ لوحة تحكم المشرف" and user.is_admin:
                    await update.message.reply_text("⚙️ لوحة تحكم المشرف\n\nاختر الإجراء المطلوب:", reply_markup=get_admin_panel_keyboard(user.is_owner))
                    return

            # 3. معالجة الحالات الأخرى
            if state == 'searching':
                search_query = f"%{text}%"
                lectures = session.query(Lecture).filter(Lecture.title.ilike(search_query)).limit(10).all()
                subjects = session.query(Subject).filter(Subject.name.ilike(search_query)).limit(10).all()
                keyboard = []
                for l in lectures: keyboard.append([InlineKeyboardButton(f"📄 {l.title}", callback_data=f"lec_{l.id}")])
                for s in subjects: keyboard.append([InlineKeyboardButton(f"📚 مادة: {s.name}", callback_data=f"sub_{s.id}")])
                if keyboard: await update.message.reply_text(f"🔍 نتائج البحث عن '{text}':", reply_markup=InlineKeyboardMarkup(keyboard))
                else: await update.message.reply_text("لم يتم العثور على نتائج.")
                context.user_data['state'] = None

            elif state == 'naming_lecture' and user.can_add_lecture:
                queue = context.user_data.get('lecture_queue', [])
                if queue:
                    current_file = queue.pop(0)
                    sub_id = context.user_data.get('sub_id')
                    lec_type = context.user_data.get('lec_type', 'theoretical')
                    new_lec = Lecture(title=text, file_id=current_file['file_id'], subject_id=sub_id, lecture_type=lec_type)
                    session.add(new_lec)
                    session.commit()
                    
                    if queue:
                        context.user_data['lecture_queue'] = queue
                        next_file = queue[0]
                        keyboard = [[InlineKeyboardButton("نعم ✅", callback_data="rename_yes"), InlineKeyboardButton("لا ❌", callback_data="rename_no")]]
                        await update.message.reply_text(
                            f"✅ تم إضافة '{text}' بنجاح.\n\n📥 المحاضرة التالية: `{next_file['file_name']}`\nهل تريد تغيير اسم هذه المحاضرة؟ ✨",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        context.user_data['state'] = 'waiting_rename_choice'
                    else:
                        await update.message.reply_text(f"✅ تم إضافة '{text}' بنجاح.\n\n🎉 اكتملت عملية رفع وتسمية جميع المحاضرات.")
                        context.user_data['state'] = None

            elif state == 'editing_whatsapp' and user.is_owner:
                whatsapp_setting = session.query(Setting).filter_by(key="whatsapp_number").first()
                if not whatsapp_setting:
                    whatsapp_setting = Setting(key="whatsapp_number", value=text)
                    session.add(whatsapp_setting)
                else:
                    whatsapp_setting.value = text
                session.commit()
                await update.message.reply_text(f"✅ تم تحديث رقم الواتساب إلى: `{text}`", reply_markup=get_admin_panel_keyboard(user.is_owner))
                context.user_data['state'] = None
                
            elif state == 'adding_admin_id' and user.is_owner:
                try:
                    target_id = int(text)
                    target_user = session.query(User).filter_by(telegram_id=target_id).first()
                    if not target_user:
                        await update.message.reply_text("❌ لم يتم العثور على مستخدم بهذا المعرف.")
                    else:
                        target_user.is_admin = True
                        session.commit()
                        await show_admin_permissions_menu(update, context, target_user)
                except: await update.message.reply_text("❌ يرجى إرسال معرف (ID) صحيح.")
                context.user_data['state'] = None

            elif state == 'broadcasting' and user.can_send_broadcast:
                users = session.query(User).all()
                count = 0
                msg = await update.message.reply_text("⏳ جاري إرسال الإعلان...")
                for u in users:
                    try:
                        await context.bot.send_message(chat_id=u.telegram_id, text=f"📢 إعلان جديد:\n\n{text}")
                        count += 1
                        await asyncio.sleep(0.05)
                    except: continue
                await msg.edit_text(f"✅ تم إرسال الإعلان لـ {count} طالب.")
                context.user_data['state'] = None

            elif state == 'adding_subject' and user.can_add_subject:
                year_id, spec, sem = context.user_data.get('year_id'), context.user_data.get('spec'), context.user_data.get('sem')
                new_sub = Subject(name=text, year_id=year_id, specialization=spec, semester=sem)
                session.add(new_sub)
                session.commit()
                cache['years'] = None
                await update.message.reply_text(f"✅ تم إضافة مادة '{text}' بنجاح.")
                context.user_data['state'] = None
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error in handle_text: {e}")

async def show_admin_permissions_menu(update, context, target_user):
    keyboard = [
        [InlineKeyboardButton(f"{'✅' if target_user.can_add_subject else '❌'} إضافة مواد", callback_data=f"perm_addsub_{target_user.telegram_id}")],
        [InlineKeyboardButton(f"{'✅' if target_user.can_delete_subject else '❌'} حذف مواد", callback_data=f"perm_delsub_{target_user.telegram_id}")],
        [InlineKeyboardButton(f"{'✅' if target_user.can_add_lecture else '❌'} إضافة محاضرات", callback_data=f"perm_addlec_{target_user.telegram_id}")],
        [InlineKeyboardButton(f"{'✅' if target_user.can_delete_lecture else '❌'} حذف محاضرات", callback_data=f"perm_dellec_{target_user.telegram_id}")],
        [InlineKeyboardButton(f"{'✅' if target_user.can_send_broadcast else '❌'} إرسال إعلانات", callback_data=f"perm_bc_{target_user.telegram_id}")],
        [InlineKeyboardButton("🗑️ سحب رتبة المشرف", callback_data=f"perm_remove_{target_user.telegram_id}")],
        [InlineKeyboardButton("✅ إنهاء", callback_data="owner_manage_admins")]
    ]
    text = f"⚙️ تعديل صلاحيات المشرف: {target_user.full_name or target_user.telegram_id}"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # منع تكرار الاستجابة عبر التحقق من وقت آخر ضغطة
    last_click = context.user_data.get('last_click_time', 0)
    if time.time() - last_click < 0.5:
        await query.answer()
        return
    context.user_data['last_click_time'] = time.time()
    
    await query.answer()
    user_id = query.from_user.id
    session = session_factory()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user: return
        data = query.data

        # --- لوحة المالك والمشرف ---
        if data == "owner_manage_admins" and user.is_owner:
            admins = session.query(User).filter(User.is_admin == True, User.is_owner == False).all()
            keyboard = [[InlineKeyboardButton(f"👤 {a.full_name or a.telegram_id}", callback_data=f"edit_admin_{a.telegram_id}")] for a in admins]
            keyboard.append([InlineKeyboardButton("➕ إضافة مشرف جديد", callback_data="add_new_admin")])
            keyboard.append([InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="admin_panel")])
            await query.edit_message_text("👑 قائمة المشرفين الحالية:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "add_new_admin" and user.is_owner:
            await query.edit_message_text("أرسل الآن معرف (ID) الشخص الذي تريد تعيينه كمشرف:")
            context.user_data['state'] = 'adding_admin_id'

        elif data.startswith("edit_admin_") and user.is_owner:
            target_id = int(data.split("_")[2])
            target_user = session.query(User).filter_by(telegram_id=target_id).first()
            if target_user: await show_admin_permissions_menu(update, context, target_user)

        elif data.startswith("perm_") and user.is_owner:
            parts = data.split("_")
            perm_type, target_id = parts[1], int(parts[2])
            target_user = session.query(User).filter_by(telegram_id=target_id).first()
            if target_user:
                if perm_type == "addsub": target_user.can_add_subject = not target_user.can_add_subject
                elif perm_type == "delsub": target_user.can_delete_subject = not target_user.can_delete_subject
                elif perm_type == "addlec": target_user.can_add_lecture = not target_user.can_add_lecture
                elif perm_type == "dellec": target_user.can_delete_lecture = not target_user.can_delete_lecture
                elif perm_type == "bc": target_user.can_send_broadcast = not target_user.can_send_broadcast
                elif perm_type == "remove": target_user.is_admin = False
                session.commit()
                if perm_type != "remove": await show_admin_permissions_menu(update, context, target_user)
                else: await query.edit_message_text("✅ تم سحب الرتبة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="owner_manage_admins")]]))

        elif data == "owner_manage_users" and user.is_owner:
            keyboard = [[InlineKeyboardButton("🆕 آخر 10 منضمين", callback_data="users_recent")], [InlineKeyboardButton("👥 جميع المستخدمين", callback_data="users_all")], [InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="admin_panel")]]
            await query.edit_message_text("👥 إدارة المستخدمين:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "users_recent" and user.is_owner:
            recent_users = session.query(User).order_by(User.id.desc()).limit(10).all()
            text = "🆕 آخر 10 منضمين:\n\n"
            for u in recent_users:
                text += f"👤 {u.full_name or 'بدون اسم'} (`{u.telegram_id}`)\n"
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="owner_manage_users")]]))

        elif data.startswith("users_all") and user.is_owner:
            parts = data.split("_")
            page = int(parts[2]) if len(parts) > 2 else 0
            limit = 50
            offset = page * limit
            
            total = session.query(User).count()
            users_list = session.query(User).order_by(User.id.desc()).offset(offset).limit(limit).all()
            
            text = f"👥 قائمة المستخدمين (الصفحة {page + 1}):\n"
            text += f"📊 الإجمالي: {total}\n\n"
            
            for u in users_list:
                name = u.full_name or u.username or "بدون اسم"
                text += f"• {name} (`{u.telegram_id}`)\n"
            
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"users_all_{page - 1}"))
            if offset + limit < total:
                nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"users_all_{page + 1}"))
            
            keyboard = [nav_buttons] if nav_buttons else []
            keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="owner_manage_users")])
            
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "owner_edit_whatsapp" and user.is_owner:
            await query.edit_message_text("أرسل الآن رقم الواتساب الجديد (مثال: 00963947230567):")
            context.user_data['state'] = 'editing_whatsapp'

        elif data == "admin_panel" and user.is_admin:
            await query.edit_message_text("⚙️ لوحة تحكم المشرف:", reply_markup=get_admin_panel_keyboard(user.is_owner))

        elif data == "admin_stats" and user.is_admin:
            total_users, total_lecs = session.query(User).count(), session.query(Lecture).count()
            await query.edit_message_text(f"📊 إحصائيات:\n\n👥 الطلاب: {total_users}\n📄 المحاضرات: {total_lecs}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="admin_panel")]]))

        elif data == "admin_broadcast" and user.can_send_broadcast:
            await query.edit_message_text("أرسل نص الإعلان:")
            context.user_data['state'] = 'broadcasting'

        # --- تصفح السنوات والمواد ---
        elif data == "back_years":
            years = get_cached_years()
            keyboard = [[InlineKeyboardButton(y.name, callback_data=f"year_{y.id}")] for y in years]
            await query.edit_message_text("اختر سنتك الدراسية:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("year_"):
            year_id = int(data.split("_")[1])
            year = session.query(Year).get(year_id)
            if "الثالثة" in year.name or "الرابعة" in year.name:
                keyboard = [[InlineKeyboardButton("اختصاص تطبيقيه ⚗️", callback_data=f"spec_{year_id}_applied")], [InlineKeyboardButton("اختصاص حيوية 🧬", callback_data=f"spec_{year_id}_bio")], [InlineKeyboardButton("اختصاص بحته 🔬", callback_data=f"spec_{year_id}_pure")], [InlineKeyboardButton("🔙 العودة", callback_data="back_years")]]
            else:
                keyboard = [[InlineKeyboardButton("الفصل الأول", callback_data=f"sem_{year_id}_none_1")], [InlineKeyboardButton("الفصل الثاني", callback_data=f"sem_{year_id}_none_2")], [InlineKeyboardButton("🔙 العودة", callback_data="back_years")]]
            await query.edit_message_text(f"اختر لـ {year.name}:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("spec_"):
            parts = data.split("_")
            year_id, spec = int(parts[1]), parts[2]
            keyboard = [[InlineKeyboardButton("الفصل الأول", callback_data=f"sem_{year_id}_{spec}_1")], [InlineKeyboardButton("الفصل الثاني", callback_data=f"sem_{year_id}_{spec}_2")], [InlineKeyboardButton("🔙 العودة", callback_data=f"year_{year_id}")]]
            await query.edit_message_text("اختر الفصل:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("sem_"):
            parts = data.split("_")
            year_id, spec, sem = int(parts[1]), parts[2], int(parts[3])
            spec_val = None if spec == "none" else spec
            subjects = session.query(Subject).filter_by(year_id=year_id, specialization=spec_val, semester=sem).all()
            keyboard = [[InlineKeyboardButton(s.name, callback_data=f"sub_{s.id}")] for s in subjects]
            if user.can_add_subject: keyboard.append([InlineKeyboardButton("➕ إضافة مادة", callback_data=f"admin_addsub_{year_id}_{spec}_{sem}")])
            keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data=f"year_{year_id}" if not spec_val else f"spec_{year_id}_{spec}")])
            await query.edit_message_text("المواد الدراسية:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("sub_"):
            sub_id = int(data.split("_")[1])
            subject = session.query(Subject).get(sub_id)
            keyboard = [
                [InlineKeyboardButton("عملي ⚗️", callback_data=f"type_{sub_id}_practical")],
                [InlineKeyboardButton("نظري 📖", callback_data=f"type_{sub_id}_theoretical")]
            ]
            if user.can_delete_subject:
                keyboard.append([InlineKeyboardButton("🗑️ مسح هذه المادة", callback_data=f"admin_delsub_{sub_id}")])
            
            back_data = f"sem_{subject.year_id}_{subject.specialization or 'none'}_{subject.semester}"
            keyboard.append([InlineKeyboardButton("🔙 العودة للمواد", callback_data=back_data)])
            await query.edit_message_text(f"مادة {subject.name}\nاختر نوع المحتوى:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("type_"):
            parts = data.split("_")
            sub_id, l_type = int(parts[1]), parts[2]
            subject = session.query(Subject).get(sub_id)
            lectures = session.query(Lecture).filter_by(subject_id=sub_id, lecture_type=l_type).all()
            keyboard = [[InlineKeyboardButton(f"📄 {l.title}", callback_data=f"lec_{l.id}")] for l in lectures]
            if user.can_add_lecture: keyboard.append([InlineKeyboardButton("➕ إضافة محاضرة", callback_data=f"admin_addlec_{sub_id}_{l_type}")])
            keyboard.append([InlineKeyboardButton("🔙 العودة للخيارات", callback_data=f"sub_{sub_id}")])
            type_name = "عملي ⚗️" if l_type == "practical" else "نظري 📖"
            await query.edit_message_text(f"مادة {subject.name} - {type_name}:", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("admin_addsub_"):
            parts = data.split("_")
            context.user_data['year_id'], context.user_data['spec'], context.user_data['sem'] = int(parts[2]), (None if parts[3] == "none" else parts[3]), int(parts[4])
            await query.edit_message_text("أرسل اسم المادة الجديدة:")
            context.user_data['state'] = 'adding_subject'

        elif data.startswith("lec_"):
            lec_id = int(data.split("_")[1])
            lecture = session.query(Lecture).get(lec_id)
            if not lecture:
                await query.answer("❌ عذراً، لم يتم العثور على هذه المحاضرة.")
                return
            
            subject = lecture.subject
            year = subject.year if subject else None
            semester_name = "فصل أول" if subject and subject.semester == 1 else "فصل ثاني"
            
            caption = (
                f"{lecture.title} 📄\n"
                f"مادة {subject.name if subject else 'غير معروفة'} {{ {semester_name} }} 📚\n"
                f"{year.name if year else 'سنة غير معروفة'} 🎓"
            )
            
            nav_row = []
            try:
                all_lecs = session.query(Lecture).filter_by(subject_id=lecture.subject_id, lecture_type=lecture.lecture_type).order_by(Lecture.id).all()
                lec_ids = [l.id for l in all_lecs]
                if lec_id in lec_ids:
                    curr_idx = lec_ids.index(lec_id)
                    if curr_idx > 0:
                        nav_row.append(InlineKeyboardButton("⬅️ السابقة", callback_data=f"lec_{lec_ids[curr_idx-1]}"))
                    if curr_idx < len(lec_ids) - 1:
                        nav_row.append(InlineKeyboardButton("التالية ➡️", callback_data=f"lec_{lec_ids[curr_idx+1]}"))
            except Exception as e:
                logger.error(f"Navigation error: {e}")
            
            is_fav = lecture in user.favorite_lectures
            fav_btn = InlineKeyboardButton("❌ إزالة من المفضلة", callback_data=f"unfav_{lec_id}") if is_fav else InlineKeyboardButton("⭐ إضافة للمفضلة", callback_data=f"fav_{lec_id}")
            
            keyboard = []
            if nav_row: keyboard.append(nav_row)
            keyboard.append([fav_btn])
            if user.can_add_lecture: keyboard.append([InlineKeyboardButton("✏️ تعديل الاسم", callback_data=f"admin_editlec_{lec_id}")])
            if user.can_delete_lecture: keyboard.append([InlineKeyboardButton("🗑️ حذف المحاضرة", callback_data=f"admin_dellec_{lec_id}")])
            keyboard.append([InlineKeyboardButton("🔙 العودة للمحاضرات", callback_data=f"type_{lecture.subject_id}_{lecture.lecture_type}")])
            
            try:
                lecture.download_count += 1
                session.commit()
                await context.bot.send_document(
                    chat_id=query.message.chat_id, 
                    document=lecture.file_id, 
                    caption=caption, 
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Error sending document: {e}")
                await query.answer("❌ حدث خطأ أثناء إرسال الملف.")

        elif data.startswith("fav_"):
            lec_id = int(data.split("_")[1])
            lecture = session.query(Lecture).get(lec_id)
            if lecture and lecture not in user.favorite_lectures:
                user.favorite_lectures.append(lecture)
                session.commit()
                await query.answer("✅ تم الإضافة للمفضلة")
                keyboard = [[InlineKeyboardButton("❌ إزالة من المفضلة", callback_data=f"unfav_{lec_id}")]]
                if user.can_add_lecture: keyboard.append([InlineKeyboardButton("✏️ تعديل الاسم", callback_data=f"admin_editlec_{lec_id}")])
                if user.can_delete_lecture: keyboard.append([InlineKeyboardButton("🗑️ حذف المحاضرة", callback_data=f"admin_dellec_{lec_id}")])
                keyboard.append([InlineKeyboardButton("🔙 العودة للمحاضرات", callback_data=f"type_{lecture.subject_id}_{lecture.lecture_type}")])
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            else: await query.answer("موجودة بالفعل")

        elif data.startswith("unfav_"):
            lec_id = int(data.split("_")[1])
            lecture = session.query(Lecture).get(lec_id)
            if lecture and lecture in user.favorite_lectures:
                user.favorite_lectures.remove(lecture)
                session.commit()
                await query.answer("❌ تم الإزالة من المفضلة")
                keyboard = [[InlineKeyboardButton("⭐ إضافة للمفضلة", callback_data=f"fav_{lec_id}")]]
                if user.can_add_lecture: keyboard.append([InlineKeyboardButton("✏️ تعديل الاسم", callback_data=f"admin_editlec_{lec_id}")])
                if user.can_delete_lecture: keyboard.append([InlineKeyboardButton("🗑️ حذف المحاضرة", callback_data=f"admin_dellec_{lec_id}")])
                keyboard.append([InlineKeyboardButton("🔙 العودة للمحاضرات", callback_data=f"type_{lecture.subject_id}_{lecture.lecture_type}")])
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("admin_editlec_"):
            lec_id = int(data.split("_")[2])
            context.user_data['state'] = 'editing_lecture_name'
            context.user_data['edit_lec_id'] = lec_id
            await context.bot.send_message(chat_id=query.message.chat_id, text="✏️ أرسل الآن الاسم الجديد لهذه المحاضرة:")
            await query.answer("بانتظار الاسم الجديد...")

        elif data.startswith("admin_addlec_"):
            parts = data.split("_")
            context.user_data['sub_id'] = int(parts[2])
            context.user_data['lec_type'] = parts[3]
            await query.edit_message_text(f"أرسل الآن ملف الـ PDF لـ ({'عملي ⚗️' if parts[3] == 'practical' else 'نظري 📖'}):")
            context.user_data['state'] = 'adding_lecture'
            context.user_data['lecture_queue'] = []

        elif data == "rename_yes" and user.can_add_lecture:
            queue = context.user_data.get('lecture_queue', [])
            if queue:
                await query.edit_message_text(f"✏️ أرسل الآن الاسم الجديد للمحاضرة: `{queue[0]['file_name']}`")
                context.user_data['state'] = 'naming_lecture'
            else:
                await query.edit_message_text("❌ انتهت قائمة الانتظار.")
                context.user_data['state'] = None

        elif data == "rename_no" and user.can_add_lecture:
            queue = context.user_data.get('lecture_queue', [])
            if queue:
                current_file = queue.pop(0)
                sub_id = context.user_data.get('sub_id')
                lec_type = context.user_data.get('lec_type', 'theoretical')
                original_name = current_file['file_name']
                if original_name.lower().endswith('.pdf'): original_name = original_name[:-4]
                
                new_lec = Lecture(title=original_name, file_id=current_file['file_id'], subject_id=sub_id, lecture_type=lec_type)
                session.add(new_lec)
                session.commit()
                
                if queue:
                    context.user_data['lecture_queue'] = queue
                    next_file = queue[0]
                    keyboard = [[InlineKeyboardButton("نعم ✅", callback_data="rename_yes"), InlineKeyboardButton("لا ❌", callback_data="rename_no")]]
                    await query.edit_message_text(
                        f"✅ تم إضافة '{original_name}' بنجاح.\n\n📥 المحاضرة التالية: `{next_file['file_name']}`\nهل تريد تغيير اسم هذه المحاضرة؟ ✨",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    context.user_data['state'] = 'waiting_rename_choice'
                else:
                    await query.edit_message_text(f"✅ تم إضافة '{original_name}' بنجاح.\n\n🎉 اكتملت عملية رفع وتسمية جميع المحاضرات.")
                    context.user_data['state'] = None

        elif data.startswith("admin_delsub_"):
            sub_id = int(data.split("_")[2])
            sub = session.query(Subject).get(sub_id)
            if sub:
                back_data = f"sem_{sub.year_id}_{sub.specialization or 'none'}_{sub.semester}"
                session.delete(sub)
                session.commit()
                cache['years'] = None
                await query.edit_message_text("✅ تم حذف المادة بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للمواد", callback_data=back_data)]]))

        elif data.startswith("admin_dellec_"):
            lec_id = int(data.split("_")[2])
            lec = session.query(Lecture).get(lec_id)
            if lec:
                sub_id, l_type = lec.subject_id, lec.lecture_type
                session.delete(lec)
                session.commit()
                await query.edit_message_text("✅ تم حذف المحاضرة بنجاح.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للمحاضرات", callback_data=f"type_{sub_id}_{l_type}")]]))
    finally:
        session.close()

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = session_factory()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if user and user.can_add_lecture and context.user_data.get('state') == 'adding_lecture':
            doc = update.message.document
            if doc.mime_type == 'application/pdf' or doc.file_name.lower().endswith('.pdf'):
                if 'lecture_queue' not in context.user_data: context.user_data['lecture_queue'] = []
                context.user_data['lecture_queue'].append({'file_id': doc.file_id, 'file_name': doc.file_name})
                
                await asyncio.sleep(1.5)
                
                if context.user_data.get('state') == 'adding_lecture':
                    queue = context.user_data['lecture_queue']
                    keyboard = [[InlineKeyboardButton("نعم ✅", callback_data="rename_yes"), InlineKeyboardButton("لا ❌", callback_data="rename_no")]]
                    await update.message.reply_text(
                        f"📥 تم استلام {len(queue)} ملفات.\n\nالمحاضرة الأولى: `{queue[0]['file_name']}`\nهل تريد تغيير اسم هذه المحاضرة؟ ✨",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    context.user_data['state'] = 'waiting_rename_choice'
            else: await update.message.reply_text("❌ يرجى إرسال ملفات بصيغة PDF فقط.")
    finally:
        session.close()

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("make_me_admin", make_admin))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("🚀 البوت المحدث والمستقر يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()
