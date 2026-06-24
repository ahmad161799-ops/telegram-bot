import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, PreCheckoutQueryHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = os.environ.get("BOT_TOKEN", "8623730183:AAGRLAcLVYueH-bQJffByXLdVHHNEFMzhqE")
ADMIN_ID = 5917466750
DB_NAME = "bot.db"
STAR_VALUE_USD = 0.0234       # قيمة النجمة الواحدة بالدولار
MIN_WITHDRAW_USD = 15.0       # الحد الأدنى للسحب بالدولار
MIN_WITHDRAW_STARS = round(MIN_WITHDRAW_USD / STAR_VALUE_USD)  # ~641 نجمة

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

# ================= DB =================
def get_conn():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        stars_balance REAL DEFAULT 0,
        stars_locked REAL DEFAULT 0,
        stars_profit REAL DEFAULT 0
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS matches(
        match_id INTEGER PRIMARY KEY AUTOINCREMENT,
        team1 TEXT,
        team2 TEXT,
        status TEXT DEFAULT 'open',
        result TEXT DEFAULT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS bets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        user_id INTEGER,
        choice TEXT,
        amount_stars REAL,
        UNIQUE(user_id, match_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount_stars REAL,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS withdrawals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount_stars REAL,
        method TEXT,
        details TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

# ================= HELPERS =================
def stars_to_usd(stars):
    return round(stars * STAR_VALUE_USD, 2)

def get_user(uid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT stars_balance, stars_locked, stars_profit FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    conn.close()
    return row

def ensure_user(uid):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    conn.commit()
    conn.close()

def get_available_stars(uid):
    row = get_user(uid)
    if not row:
        return 0
    return row[0]

def get_total_stars(uid):
    row = get_user(uid)
    if not row:
        return 0
    return round(row[0] + row[2], 2)

# ================= KEYBOARDS =================
def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚽ المباريات المتاحة", callback_data="show_matches"),
            InlineKeyboardButton("👤 حسابي", callback_data="account")
        ],
        [
            InlineKeyboardButton("💰 طلب سحب", callback_data="withdraw_start"),
            InlineKeyboardButton("⭐ شحن رصيد", callback_data="topup")
        ]
    ])

def back_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="back_main")]
    ])

def bet_amounts_keyboard(mid, choice):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⭐ 250", callback_data=f"amt_{mid}_{choice}_250"),
            InlineKeyboardButton("⭐ 750", callback_data=f"amt_{mid}_{choice}_750")
        ],
        [
            InlineKeyboardButton("⭐ 2,500", callback_data=f"amt_{mid}_{choice}_2500"),
            InlineKeyboardButton("⭐ 10,000", callback_data=f"amt_{mid}_{choice}_10000")
        ],
        [InlineKeyboardButton("✏️ أدخل عدد النجوم يدوياً", callback_data=f"amt_{mid}_{choice}_custom")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="show_matches")]
    ])

def withdraw_method_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏦 تحويل بنكي", callback_data="wmethod_bank"),
            InlineKeyboardButton("📱 محفظة إلكترونية", callback_data="wmethod_wallet")
        ],
        [
            InlineKeyboardButton("₿ كريبتو", callback_data="wmethod_crypto"),
            InlineKeyboardButton("🌍 Western Union", callback_data="wmethod_western")
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
    ])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    await update.message.reply_text(
        "🎮 *أهلاً بك في بوت الرهانات!*\n\n"
        "اختر من القائمة أدناه:",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

# ================= ACCOUNT =================
async def show_account(query, context):
    uid = query.from_user.id
    ensure_user(uid)
    row = get_user(uid)
    balance, locked, profit = row
    total = round(balance + profit, 2)

    text = (
        f"👤 *حسابك*\n\n"
        f"⭐ الرصيد المتاح: `{balance:.0f}` نجمة ≈ `{stars_to_usd(balance):.2f}$`\n"
        f"🔒 محجوز للرهانات: `{locked:.0f}` نجمة ≈ `{stars_to_usd(locked):.2f}$`\n"
        f"🏆 الأرباح: `{profit:.0f}` نجمة ≈ `{stars_to_usd(profit):.2f}$`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 الإجمالي: `{total:.0f}` نجمة ≈ `{stars_to_usd(total):.2f}$`"
    )
    await query.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ شحن رصيد", callback_data="topup")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
        ])
    )

# ================= MATCHES =================
async def show_matches(query, context):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT match_id, team1, team2 FROM matches WHERE status='open'")
    matches = cur.fetchall()
    conn.close()

    if not matches:
        await query.message.reply_text(
            "⚽ لا توجد مباريات متاحة حالياً.\nتابعنا للمزيد!",
            reply_markup=back_main_kb()
        )
        return

    await query.message.reply_text("⚽ *المباريات المتاحة للرهان:*", parse_mode="Markdown")

    for m in matches:
        mid, team1, team2 = m
        await query.message.reply_text(
            f"🏟️ *{team1}* vs *{team2}*\n\nاختر نتيجتك:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"1️⃣ {team1}", callback_data=f"bet_{mid}_1"),
                InlineKeyboardButton("🤝 تعادل", callback_data=f"bet_{mid}_X"),
                InlineKeyboardButton(f"2️⃣ {team2}", callback_data=f"bet_{mid}_2")
            ]])
        )

# ================= BET FLOW =================
async def show_bet_amounts(query, context, mid, choice):
    uid = query.from_user.id
    ensure_user(uid)
    balance = get_available_stars(uid)
    usd = stars_to_usd(balance)

    choice_text = {
        "1": "فوز الفريق الأول 1️⃣",
        "X": "تعادل 🤝",
        "2": "فوز الفريق الثاني 2️⃣"
    }.get(choice, choice)

    await query.message.reply_text(
        f"✅ اختيارك: *{choice_text}*\n\n"
        f"⭐ رصيدك المتاح: `{balance:.0f}` نجمة ≈ `{usd:.2f}$`\n\n"
        f"كم نجمة تريد أن تراهن؟",
        parse_mode="Markdown",
        reply_markup=bet_amounts_keyboard(mid, choice)
    )

async def process_bet(query, context, mid, choice, stars_amount):
    uid = query.from_user.id
    ensure_user(uid)

    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()

        # التحقق من المباراة
        cur.execute("SELECT status, team1, team2 FROM matches WHERE match_id=?", (int(mid),))
        m = cur.fetchone()
        if not m or m[0] != 'open':
            conn.rollback()
            await query.message.reply_text("⚠️ هذه المباراة أُغلقت.", reply_markup=back_main_kb())
            return

        team1, team2 = m[1], m[2]

        # التحقق من الرصيد
        cur.execute("SELECT stars_balance FROM users WHERE user_id=?", (uid,))
        row = cur.fetchone()
        current_balance = row[0] if row else 0

        if current_balance < stars_amount:
        conn.rollback()
            needed = stars_amount - current_balance
            # فتح نافذة شراء النجوم مباشرة
            await query.message.reply_text(
                f"❌ *رصيدك غير كافٍ!*\n\n"
                f"⭐ رصيدك الحالي: `{current_balance:.0f}` نجمة\n"
                f"⭐ المطلوب: `{stars_amount:.0f}` نجمة\n"
                f"⭐ الناقص: `{needed:.0f}` نجمة\n\n"
                f"سيتم فتح نافذة الشراء لإتمام الرهان:",
                parse_mode="Markdown"
            )
            # إرسال فاتورة بالمبلغ الناقص
            await context.bot.send_invoice(
                chat_id=uid,
                title="⭐ شراء نجوم للرهان",
                description=f"تحتاج {needed:.0f} نجمة لإتمام رهانك على {team1} vs {team2}",
                payload=f"topup_{int(needed)}",
                currency="XTR",
                prices=[LabeledPrice(label=f"{int(needed)} نجمة", amount=int(needed))]
            )
            return

        # خصم الرصيد وحجزه
        cur.execute(
            "UPDATE users SET stars_balance = stars_balance - ?, stars_locked = stars_locked + ? WHERE user_id=?",
            (stars_amount, stars_amount, uid)
        )

        # حفظ الرهان
        cur.execute(
            "INSERT INTO bets(match_id, user_id, choice, amount_stars) VALUES (?,?,?,?)",
            (int(mid), uid, choice, stars_amount)
        )
        cur.execute(
            "INSERT INTO transactions(user_id, type, amount_stars, details) VALUES (?,?,?,?)",
            (uid, "bet", -stars_amount, f"رهان على مباراة #{mid} - {team1} vs {team2}")
        )
        conn.commit()

        choice_text = {"1": f"فوز {team1}", "X": "تعادل", "2": f"فوز {team2}"}.get(choice, choice)
        usd = stars_to_usd(stars_amount)

        await query.message.reply_text(
            f"✅ *تم تسجيل رهانك بنجاح!*\n\n"
            f"🏟️ المباراة: {team1} vs {team2}\n"
            f"🎯 اختيارك: {choice_text}\n"
            f"⭐ المبلغ: `{stars_amount:.0f}` نجمة ≈ `{usd:.2f}$`\n\n"
            f"بالتوفيق! 🍀",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    except sqlite3.IntegrityError:
        conn.rollback()
        await query.message.reply_text(
            "⚠️ لديك رهان مسبق على هذه المباراة.",
            reply_markup=back_main_kb()
        )
    except Exception as e:
        conn.rollback()
        log.error(f"process_bet error: {e}")
        await query.message.reply_text("❌ حدث خطأ. حاول مجدداً.", reply_markup=back_main_kb())
    finally:
        conn.close()

# ================= TOPUP =================
async def show_topup(query, context):
    await query.message.reply_text(
        "⭐ *شحن الرصيد*\n\n"
        "اختر عدد النجوم التي تريد شراءها:\n"
        f"_(كل نجمة = {STAR_VALUE_USD}$)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⭐ 100 نجمة", callback_data="buy_100"),
                InlineKeyboardButton("⭐ 500 نجمة", callback_data="buy_500")
            ],
            [
                InlineKeyboardButton("⭐ 1,000 نجمة", callback_data="buy_1000"),
                InlineKeyboardButton("⭐ 5,000 نجمة", callback_data="buy_5000")
            ],
            [InlineKeyboardButton("✏️ أدخل عدداً مخصصاً", callback_data="buy_custom")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
        ])
    )

async def send_stars_invoice(chat_id, stars, context):
    usd = stars_to_usd(stars)
    await context.bot.send_invoice(
        chat_id=chat_id,
        title="⭐ شحن رصيد",
        description=f"{stars} نجمة ≈ {usd:.2f}$",
        payload=f"topup_{stars}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{stars} نجمة", amount=stars)]
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    stars = int(payload.split("_")[1])
    usd = stars_to_usd(stars)

    ensure_user(uid)
    conn = get_conn()
    conn.execute("UPDATE users SET stars_balance = stars_balance + ? WHERE user_id=?", (stars, uid))
    conn.execute(
        "INSERT INTO transactions(user_id, type, amount_stars, details) VALUES (?,?,?,?)",
        (uid, "topup", stars, f"شحن {stars} نجمة")
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ *تم الشحن بنجاح!*\n\n"
        f"⭐ النجوم المضافة: `{stars}` نجمة\n"
        f"💵 القيمة: ≈ `{usd:.2f}$`",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

# ================= WITHDRAW =================
WITHDRAW_STEPS = {
    "bank": [
        ("name", "👤 الاسم كما هو مسجل في البنك:"),
        ("bank_name", "🏦 اسم البنك:"),
        ("account_number", "🔢 رقم الحساب / IBAN:"),
        ("amount_stars", f"⭐ عدد النجوم المراد سحبها (الحد الأدنى {MIN_WITHDRAW_STARS} نجمة):"),
    ],
    "wallet": [
        ("name", "👤 الاسم المسجل في المحفظة:"),
        ("wallet_name", "📱 اسم المحفظة (STC، Zain، إلخ):"),
        ("phone", "📞 رقم الهاتف المرتبط بالمحفظة:"),
        ("amount_stars", f"⭐ عدد النجوم المراد سحبها (الحد الأدنى {MIN_WITHDRAW_STARS} نجمة):"),
    ],
    "crypto": [
        ("name", "👤 الاسم:"),
        ("currency", "💎 العملة (USDT، BTC، إلخ):"),
        ("network", "🌐 الشبكة (TRC20، ERC20، إلخ):"),
        ("address", "📋 عنوان المحفظة:"),
        ("amount_stars", f"⭐ عدد النجوم المراد سحبها (الحد الأدنى {MIN_WITHDRAW_STARS} نجمة):"),
    ],
    "western": [
        ("name", "👤 الاسم الكامل كما على الهوية:"),
        ("country", "🌍 الدولة:"),
        ("amount_stars", f"⭐ عدد النجوم المراد سحبها (الحد الأدنى {MIN_WITHDRAW_STARS} نجمة):"),
    ]
}

async def start_withdraw(query, context):
    uid = query.from_user.id
    ensure_user(uid)
    total = get_total_stars(uid)
    usd = stars_to_usd(total)

    if total < MIN_WITHDRAW_STARS:
        await query.message.reply_text(
            f"❌ *رصيدك غير كافٍ للسحب!*\n\n"
            f"⭐ رصيدك الحالي: `{total:.0f}` نجمة ≈ `{usd:.2f}$`\n"
            f"⭐ الحد الأدنى للسحب: `{MIN_WITHDRAW_STARS}` نجمة ≈ `{MIN_WITHDRAW_USD:.2f}$`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ شحن رصيد", callback_data="topup")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]
            ])
        )
        return

    await query.message.reply_text(
        f"💰 *طلب سحب*\n\n"
        f"⭐ رصيدك الإجمالي: `{total:.0f}` نجمة ≈ `{usd:.2f}$`\n"
        f"⭐ الحد الأدنى: `{MIN_WITHDRAW_STARS}` نجمة ≈ `{MIN_WITHDRAW_USD:.2f}$`\n\n"
        f"اختر طريقة الاستلام:",
        parse_mode="Markdown",
        reply_markup=withdraw_method_kb()
    )

async def withdraw_method_selected(query, context, method):
    context.user_data["withdraw"] = {"step": 0, "method": method, "data": {}}
    steps = WITHDRAW_STEPS[method]
    await query.message.reply_text(
        f"✏️ {steps[0][1]}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_withdraw")]
        ])
    )

async def process_withdraw_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "withdraw" not in context.user_data:
        return

    wd = context.user_data["withdraw"]
    method = wd.get("method")
    if not method:
        return

    steps = WITHDRAW_STEPS[method]
    step_index = wd["step"]
    field, _ = steps[step_index]
    text = update.message.text.strip()

    if field == "amount_stars":
        try:
            stars = float(text)
            if stars <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ أدخل عدداً صحيحاً من النجوم:")
            return

        if stars < MIN_WITHDRAW_STARS:
            await update.message.reply_text(
                f"❌ الحد الأدنى للسحب هو `{MIN_WITHDRAW_STARS}` نجمة ≈ `{MIN_WITHDRAW_USD:.2f}$`\n\n"
                f"أدخل عدداً أكبر:",
                parse_mode="Markdown"
            )
            return

        uid = update.effective_user.id
        total = get_total_stars(uid)
        if stars > total:
            await update.message.reply_text(
                f"❌ المبلغ أكبر من رصيدك!\n"
                f"⭐ رصيدك: `{total:.0f}` نجمة\n\n"
                f"أدخل عدداً أقل أو يساوي `{total:.0f}`:",
                parse_mode="Markdown"
            )
            return

        wd["data"]["amount_stars"] = stars
    else:
        wd["data"][field] = text

    wd["step"] += 1

    if wd["step"] >= len(steps):
        await finalize_withdraw(update, context, wd)
    else:
        next_field, next_question = steps[wd["step"]]
        await update.message.reply_text(
            f"✏️ {next_question}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel_withdraw")]
            ])
        )

async def finalize_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE, wd: dict):
    uid = update.effective_user.id
    method = wd["method"]
    data = wd["data"]
    stars = data["amount_stars"]
    usd = stars_to_usd(stars)

    method_names = {
        "bank": "تحويل بنكي 🏦",
        "wallet": "محفظة إلكترونية 📱",
        "crypto": "كريبتو ₿",
        "western": "Western Union 🌍"
    }

    details_lines = [f"{k}: {v}" for k, v in data.items() if k != "amount_stars"]
    details_text = "\n".join(details_lines)

    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()

        # خصم من الرصيد (أولاً من الأرباح ثم من الرصيد الأساسي)
        cur.execute("SELECT stars_balance, stars_profit FROM users WHERE user_id=?", (uid,))
        row = cur.fetchone()
        balance, profit = row

        if profit >= stars:
            cur.execute("UPDATE users SET stars_profit = stars_profit - ? WHERE user_id=?", (stars, uid))
        elif profit > 0:
            remaining = stars - profit
            cur.execute(
                "UPDATE users SET stars_profit = 0, stars_balance = stars_balance - ? WHERE user_id=?",
                (remaining, uid)
            )
        else:
            cur.execute("UPDATE users SET stars_balance = stars_balance - ? WHERE user_id=?", (stars, uid))

        cur.execute(
            "INSERT INTO withdrawals(user_id, amount_stars, method, details) VALUES (?,?,?,?)",
            (uid, stars, method, details_text)
        )
        withdrawal_id = cur.lastrowid

        cur.execute(
            "INSERT INTO transactions(user_id, type, amount_stars, details) VALUES (?,?,?,?)",
            (uid, "withdraw_request", -stars, f"طلب سحب #{withdrawal_id}")
        )
        conn.commit()

        await update.message.reply_text(
            f"✅ *تم إرسال طلب السحب!*\n\n"
            f"🆔 رقم الطلب: `#{withdrawal_id}`\n"
            f"⭐ النجوم: `{stars:.0f}`\n"
            f"💵 القيمة: ≈ `{usd:.2f}$`\n"
            f"📋 الطريقة: {method_names[method]}\n\n"
            f"⏳ سيتم مراجعة طلبك وإشعارك بالنتيجة خلال 24 ساعة.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

        admin_msg = (
            f"🔔 *طلب سحب جديد!*\n\n"
            f"🆔 رقم الطلب: `#{withdrawal_id}`\n"
            f"👤 User ID: `{uid}`\n"
            f"⭐ النجوم: `{stars:.0f}`\n"
            f"💵 القيمة: ≈ `{usd:.2f}$`\n"
            f"📋 الطريقة: {method_names[method]}\n\n"
            f"📝 *التفاصيل:*\n{details_text}\n\n"
            f"للقبول: `/confirm_withdraw {withdrawal_id}`\n"
            f"للرفض: `/reject_withdraw {withdrawal_id}`"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")

    except Exception as e:
        conn.rollback()
        log.error(f"finalize_withdraw error: {e}")
        await update.message.reply_text("❌ حدث خطأ. حاول مجدداً.", reply_markup=back_main_kb())
    finally:
        conn.close()

    context.user_data.pop("withdraw", None)

# ================= ADMIN COMMANDS =================
async def add_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ الاستخدام: /add_match فريق1 فريق2")
        return
    team1, team2 = context.args[0], " ".join(context.args[1:]) if len(context.args) > 2 else context.args[1]
    team1, team2 = context.args[0], context.args[1]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO matches(team1, team2) VALUES (?,?)", (team1, team2))
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"✅ تمت إضافة المباراة!\n\n"
        f"🆔 رقم المباراة: #{mid}\n"
        f"⚽ {team1} vs {team2}"
    )

async def distribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ الاستخدام: /distribute match_id النتيجة\n"
            "النتيجة: 1 (فوز الأول) أو X (تعادل) أو 2 (فوز الثاني)"
        )
        return

    mid = context.args[0]
    result = context.args[1].upper()

    if result not in ("1", "X", "2"):
        await update.message.reply_text("❌ النتيجة يجب أن تكون: 1 أو X أو 2")
        return

    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()

        cur.execute(
            "UPDATE matches SET status='finished', result=? WHERE match_id=? AND status='open'",
            (result, int(mid))
        )
        if cur.rowcount == 0:
            conn.rollback()
            await update.message.reply_text("⚠️ المباراة مغلقة بالفعل أو غير موجودة.")
            return

        # جلب كل الرهانات
        cur.execute("SELECT user_id, choice, amount_stars FROM bets WHERE match_id=?", (int(mid),))
        all_bets = cur.fetchall()

        if not all_bets:
            conn.commit()
            await update.message.reply_text(f"✅ تم إغلاق المباراة #{mid} — لا توجد رهانات.")
            return

        # حساب المجاميع
        total_stars = sum(b[2] for b in all_bets)
        loser_stars = sum(b[2] for b in all_bets if b[1] != result)
        winner_pool_stars = sum(b[2] for b in all_bets if b[1] == result)

        no_winners = (winner_pool_stars == 0)

        # الأرباح الموزعة على الرابحين (80% من خسارات الخاسرين)
        profit_pool = loser_stars * 0.8
        admin_cut = loser_stars * 0.2

        winners_count = 0
        losers_count = 0

        for uid, choice, amount in all_bets:
            # إلغاء الحجز
            cur.execute(
                "UPDATE users SET stars_locked = stars_locked - ? WHERE user_id=?",
                (amount, uid)
            )

            if no_winners:
                # لا يوجد رابحون: استرداد كامل
                cur.execute(
                    "UPDATE users SET stars_balance = stars_balance + ? WHERE user_id=?",
                    (amount, uid)
                )
                cur.execute(
                    "INSERT INTO transactions(user_id, type, amount_stars, details) VALUES (?,?,?,?)",
                    (uid, "refund", amount, f"استرداد مباراة #{mid} — لا يوجد رابحون")
                )
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=f"↩️ *تم استرداد رهانك!*\n\n"
                             f"مباراة #{mid} — لا يوجد رابحون\n"
                             f"⭐ المبلغ المسترد: `{amount:.0f}` نجمة",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

            elif choice == result:
                # رابح: يسترد رهانه + حصته من الأرباح
                share = round((amount / winner_pool_stars) * profit_pool, 2)
                total_return = amount + share
                cur.execute(
                    "UPDATE users SET stars_balance = stars_balance + ?, stars_profit = stars_profit + ? WHERE user_id=?",
                    (amount, share, uid)
                )
                cur.execute(
                    "INSERT INTO transactions(user_id, type, amount_stars, details) VALUES (?,?,?,?)",
                    (uid, "win", share, f"ربح مباراة #{mid}")
                )
                winners_count += 1
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=f"🏆 *تهانينا! فزت!*\n\n"
                             f"مباراة #{mid}\n"
                             f"⭐ رهانك: `{amount:.0f}` نجمة\n"
                             f"💰 ربحك: `{share:.0f}` نجمة\n"
                             f"✅ الإجمالي المضاف: `{total_return:.0f}` نجمة ≈ `{stars_to_usd(total_return):.2f}$`",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

            else:
                # خاسر
                cur.execute(
                    "INSERT INTO transactions(user_id, type, amount_stars, details) VALUES (?,?,?,?)",
                    (uid, "loss", -amount, f"خسارة مباراة #{mid}")
                )
                losers_count += 1
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=f"😔 *للأسف خسرت هذه المرة*\n\n"
                             f"مباراة #{mid}\n"
                             f"⭐ المبلغ الخسارة: `{amount:.0f}` نجمة\n\n"
                             f"حظاً أوفر في المرة القادمة! 💪",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

        conn.commit()

        await update.message.reply_text(
            f"✅ *تم توزيع نتائج المباراة #{mid}*\n\n"
            f"🏆 النتيجة: `{result}`\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👥 إجمالي المشاركين: `{len(all_bets)}`\n"
            f"🏆 الرابحون: `{winners_count}`\n"
            f"😔 الخاسرون: `{losers_count}`\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⭐ إجمالي الرهانات: `{total_stars:.0f}` نجمة\n"
            f"⭐ خسارات الخاسرين: `{loser_stars:.0f}` نجمة\n"
            f"💰 موزع على الرابحين (80%): `{profit_pool:.0f}` نجمة\n"
            f"🏦 عمولتك (20%): `{admin_cut:.0f}` نجمة ≈ `{stars_to_usd(admin_cut):.2f}$`",
            parse_mode="Markdown"
        )

    except Exception as e:
        conn.rollback()
        log.error(f"distribute error: {e}")
        await update.message.reply_text(f"❌ فشل: {e}")
    finally:
        conn.close()

async def confirm_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ الاستخدام: /confirm_withdraw withdrawal_id")
        return

    wid = int(context.args[0])
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id, amount_stars FROM withdrawals WHERE id=? AND status='pending'", (wid,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("⚠️ الطلب غير موجود أو تمت معالجته.")
            return

        uid, stars = row
        usd = stars_to_usd(stars)
        conn.execute("UPDATE withdrawals SET status='confirmed' WHERE id=?", (wid,))
        conn.commit()

        await update.message.reply_text(
            f"✅ تم تأكيد طلب السحب #{wid}\n"
            f"⭐ النجوم: {stars:.0f}\n"
            f"💵 القيمة: ≈ {usd:.2f}$"
        )
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"✅ *تم قبول طلب السحب!*\n\n"
                     f"🆔 رقم الطلب: `#{wid}`\n"
                     f"⭐ النجوم: `{stars:.0f}`\n"
                     f"💵 القيمة: ≈ `{usd:.2f}$`\n\n"
                     f"سيصلك التحويل قريباً. 🙏",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    finally:
        conn.close()

async def reject_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ الاستخدام: /reject_withdraw withdrawal_id")
        return

    wid = int(context.args[0])
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id, amount_stars FROM withdrawals WHERE id=? AND status='pending'", (wid,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("⚠️ الطلب غير موجود أو تمت معالجته.")
            return

        uid, stars = row
        usd = stars_to_usd(stars)

        # إعادة الرصيد للمستخدم
        conn.execute("UPDATE users SET stars_balance = stars_balance + ? WHERE user_id=?", (stars, uid))
        conn.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
        conn.execute(
            "INSERT INTO transactions(user_id, type, amount_stars, details) VALUES (?,?,?,?)",
            (uid, "withdraw_rejected", stars, f"رفض طلب سحب #{wid} — تم إعادة الرصيد")
        )
        conn.commit()

        await update.message.reply_text(
            f"❌ تم رفض طلب السحب #{wid}\n"
            f"⭐ تم إعادة {stars:.0f} نجمة للمستخدم {uid}"
        )
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"❌ *تم رفض طلب السحب*\n\n"
                     f"🆔 رقم الطلب: `#{wid}`\n"
                     f"⭐ تم إعادة `{stars:.0f}` نجمة لرصيدك.\n\n"
                     f"للاستفسار تواصل مع الدعم.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    finally:
        conn.close()

async def list_withdraws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, user_id, amount_stars, method, created_at FROM withdrawals WHERE status='pending' ORDER BY created_at DESC LIMIT 20"
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("✅ لا توجد طلبات سحب معلقة.")
        return

    msg = "📋 *طلبات السحب المعلقة:*\n\n"
    for r in rows:
        usd = stars_to_usd(r[2])
        msg += f"🆔 `#{r[0]}` | 👤 `{r[1]}` | ⭐ `{r[2]:.0f}` ≈ `{usd:.2f}$` | {r[3]} | {r[4]}\n"
    msg += "\n✅ للقبول: `/confirm_withdraw ID`\n❌ للرفض: `/reject_withdraw ID`"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def set_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ الاستخدام: /set_balance user_id عدد_النجوم")
        return
    try:
        uid = int(context.args[0])
        stars = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ قيم غير صحيحة.")
        return

    ensure_user(uid)
    conn = get_conn()
    conn.execute("UPDATE users SET stars_balance=? WHERE user_id=?", (stars, uid))
    conn.execute(
        "INSERT INTO transactions(user_id, type, amount_stars, details) VALUES (?,?,?,?)",
        (uid, "admin_set", stars, "تعديل يدوي بواسطة الأدمن")
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"✅ تم تعديل رصيد المستخدم `{uid}`\n"
        f"⭐ الرصيد الجديد: `{stars:.0f}` نجمة ≈ `{stars_to_usd(stars):.2f}$`",
        parse_mode="Markdown"
    )

async def list_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT match_id, team1, team2, status, result FROM matches ORDER BY match_id DESC LIMIT 20")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("لا توجد مباريات.")
        return

    msg = "📋 *قائمة المباريات:*\n\n"
    for r in rows:
        status_icon = "🟢" if r[3] == "open" else "🔴"
        result_text = f" — النتيجة: {r[4]}" if r[4] else ""
        msg += f"{status_icon} `#{r[0]}` {r[1]} vs {r[2]}{result_text}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ================= CALLBACK HANDLER =================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "back_main":
        await q.message.reply_text("🎮 القائمة الرئيسية:", reply_markup=main_menu())

    elif data == "show_matches":
        await show_matches(q, context)

    elif data == "account":
        await show_account(q, context)

    elif data == "topup":
        await show_topup(q, context)

    elif data.startswith("buy_"):
        val = data.split("_")[1]
        if val == "custom":
            context.user_data["buy_custom"] = True
            await q.message.reply_text(
                "✏️ أدخل عدد النجوم التي تريد شراءها:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ إلغاء", callback_data="back_main")]
                ])
            )
        else:
            stars = int(val)
            await send_stars_invoice(q.from_user.id, stars, context)

    elif data == "withdraw_start":
        await start_withdraw(q, context)

    elif data.startswith("wmethod_"):
        method = data.split("_")[1]
        await withdraw_method_selected(q, context, method)

    elif data == "cancel_withdraw":
        context.user_data.pop("withdraw", None)
        await q.message.reply_text("❌ تم إلغاء طلب السحب.", reply_markup=main_menu())

    elif data.startswith("bet_"):
        parts = data.split("_")
        mid, choice = parts[1], parts[2]
        await show_bet_amounts(q, context, mid, choice)

    elif data.startswith("amt_"):
        parts = data.split("_")
        mid, choice, amt_str = parts[1], parts[2], parts[3]

        if amt_str == "custom":
            context.user_data["custom_bet"] = {"match": mid, "choice": choice}
            await q.message.reply_text(
                "✏️ أدخل عدد النجوم التي تريد الرهان بها:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ إلغاء", callback_data="show_matches")]
                ])
            )
        else:
            stars = float(amt_str)
            await process_bet(q, context, mid, choice, stars)

# ================= MESSAGE HANDLER =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if update.message.text else ""

    # معالجة خطوات السحب
    if "withdraw" in context.user_data and context.user_data["withdraw"].get("method"):
        await process_withdraw_step(update, context)
        return

    # معالجة شراء نجوم مخصص
    if context.user_data.get("buy_custom"):
        try:
            stars = int(text)
            if stars <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ أدخل عدداً صحيحاً من النجوم:")
            return
        context.user_data.pop("buy_custom", None)
        await send_stars_invoice(update.effective_user.id, stars, context)
        return

    # معالجة مبلغ الرهان المخصص
    if "custom_bet" in context.user_data:
        try:
            stars = float(text)
            if stars <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ أدخل عدداً صحيحاً من النجوم:")
            return

        bet = context.user_data.pop("custom_bet")

        class FakeQuery:
            def __init__(self, msg, user):
                self.message = msg
                self.from_user = user
            async def answer(self): pass

        fq = FakeQuery(update.message, update.effective_user)
        await process_bet(fq, context, bet["match"], bet["choice"], stars)
        return

# ================= MAIN =================
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # أوامر المستخدم
    app.add_handler(CommandHandler("start", start))

    # أوامر الأدمن
    app.add_handler(CommandHandler("add_match", add_match))
    app.add_handler(CommandHandler("distribute", distribute))
    app.add_handler(CommandHandler("confirm_withdraw", confirm_withdraw))
    app.add_handler(CommandHandler("reject_withdraw", reject_withdraw))
    app.add_handler(CommandHandler("withdraws", list_withdraws))
    app.add_handler(CommandHandler("set_balance", set_balance))
    app.add_handler(CommandHandler("matches", list_matches))

    # الدفع
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # الأزرار والرسائل
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    log.info("✅ البوت يعمل...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
