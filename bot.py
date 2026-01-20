import json
import os
import logging
import calendar
from datetime import datetime, timedelta, date, time as dtime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

TOKEN = "8244657716:AAG0bk2iV1jDODvbkbjyPa5HieznHgwbnPY"
DATA_FILE = "users.json"
TIMEZONE_NAME = "Europe/Kyiv"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --- Storage ---

def load_users():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_user(users: dict, chat_id: str):
    if chat_id not in users:
        users[chat_id] = {}

    u = users[chat_id]

    if "timezone" not in u:
        u["timezone"] = TIMEZONE_NAME

    if "tasks" not in u or not isinstance(u["tasks"], list):
        u["tasks"] = []

    if "settings" not in u or not isinstance(u["settings"], dict):
        u["settings"] = {}

    if "soft_check_enabled" not in u["settings"]:
        u["settings"]["soft_check_enabled"] = True
    if "soft_check_hour" not in u["settings"]:
        u["settings"]["soft_check_hour"] = 10

    # Нагадування
    if "reminders_enabled" not in u["settings"]:
        u["settings"]["reminders_enabled"] = True
    if "remind_before_min" not in u["settings"]:
        u["settings"]["remind_before_min"] = 10  # default

    if "stats" not in u or not isinstance(u["stats"], dict):
        u["stats"] = {}
    if "current_streak" not in u["stats"]:
        u["stats"]["current_streak"] = 0
    if "best_streak" not in u["stats"]:
        u["stats"]["best_streak"] = 0
    if "last_done_date" not in u["stats"]:
        u["stats"]["last_done_date"] = None
    if "done_total" not in u["stats"]:
        u["stats"]["done_total"] = 0

    users[chat_id] = u
    return users


def next_task_id(tasks: list) -> int:
    mx = 0
    for t in tasks:
        mx = max(mx, int(t.get("id", 0)))
    return mx + 1


# --- UI ---

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 План на день", callback_data="menu:day")],
        [InlineKeyboardButton("📆 План на тиждень", callback_data="menu:week")],
        [InlineKeyboardButton("🗓 План на місяць", callback_data="menu:month")],
        [InlineKeyboardButton("✅ Виконати", callback_data="menu:do")],
        [InlineKeyboardButton("➕ Додати задачу", callback_data="menu:add")],
        [InlineKeyboardButton("🔔 Нагадування", callback_data="menu:reminders")],
        [InlineKeyboardButton("📈 Статистика", callback_data="menu:stats")],
        [InlineKeyboardButton("⚙️ Налаштування", callback_data="menu:settings")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu:home")]])


def back_to_do_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu:do")]])


def fmt_task_line(t: dict) -> str:
    d = t.get("date", "")
    tm = t.get("time")
    title = t.get("title", "")
    if tm:
        return f"• {d} {tm} — {title}"
    return f"• {d} — {title}"


def filter_tasks_by_range(tasks: list, start: date, end: date):
    out = []
    for t in tasks:
        if t.get("done"):
            continue
        try:
            td = datetime.strptime(t["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if start <= td <= end:
            out.append(t)

    out.sort(key=lambda x: (x.get("date", "9999-99-99"), x.get("time") or "99:99"))
    return out


# --- Calendar keyboard ---

def calendar_kb(year: int, month: int):
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    rows = []
    rows.append([InlineKeyboardButton(f"📅 {month_name} {year}", callback_data="cal:ignore")])

    rows.append([
        InlineKeyboardButton("Пн", callback_data="cal:ignore"),
        InlineKeyboardButton("Вт", callback_data="cal:ignore"),
        InlineKeyboardButton("Ср", callback_data="cal:ignore"),
        InlineKeyboardButton("Чт", callback_data="cal:ignore"),
        InlineKeyboardButton("Пт", callback_data="cal:ignore"),
        InlineKeyboardButton("Сб", callback_data="cal:ignore"),
        InlineKeyboardButton("Нд", callback_data="cal:ignore"),
    ])

    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="cal:ignore"))
            else:
                row.append(InlineKeyboardButton(str(day), callback_data=f"cal:pick:{year}-{month:02d}-{day:02d}"))
        rows.append(row)

    rows.append([
        InlineKeyboardButton("◀️", callback_data=f"cal:prev:{year}-{month:02d}"),
        InlineKeyboardButton("Сьогодні", callback_data=f"cal:pick:{date.today().isoformat()}"),
        InlineKeyboardButton("▶️", callback_data=f"cal:next:{year}-{month:02d}"),
    ])

    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def add_month(year: int, month: int, delta: int):
    m = month + delta
    y = year
    if m == 0:
        m = 12
        y -= 1
    if m == 13:
        m = 1
        y += 1
    return y, m


# --- Add flow states ---
ADD_TITLE, ADD_DATE_PICK, ADD_TIME = range(3)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я твій Планер-бот 🧠✨\nОбирай дію в меню нижче 👇",
        reply_markup=main_menu_kb()
    )


async def show_menu(query):
    await query.edit_message_text("🏠 Головне меню:", reply_markup=main_menu_kb())


# --- Reminder scheduling ---

def parse_task_datetime(task: dict):
    if not task.get("date") or not task.get("time"):
        return None
    try:
        dt = datetime.strptime(task["date"] + " " + task["time"], "%Y-%m-%d %H:%M")
        return dt
    except Exception:
        return None


async def reminder_send(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = int(job.data["chat_id"])
    task = job.data["task"]

    # якщо задача вже виконана — не шлемо
    users = load_users()
    users = ensure_user(users, str(chat_id))
    tasks = users[str(chat_id)]["tasks"]

    still_exists = None
    for t in tasks:
        if int(t.get("id")) == int(task["id"]):
            still_exists = t
            break

    if not still_exists or still_exists.get("done"):
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔔 Нагадування:\n{fmt_task_line(still_exists)}"
    )


def schedule_reminder(app: Application, chat_id: int, task: dict, remind_before_min: int):
    """
    Надійний варіант: плануємо "через N секунд", а не на конкретний datetime.
    """
    dt = parse_task_datetime(task)
    if not dt:
        return

    remind_at = dt - timedelta(minutes=remind_before_min)
    now = datetime.now()

    delay = (remind_at - now).total_seconds()
    if delay <= 0:
        return

    job_name = f"rem:{chat_id}:{task['id']}"

    # прибираємо старе, якщо було
    for j in app.job_queue.get_jobs_by_name(job_name):
        j.schedule_removal()

    app.job_queue.run_once(
        reminder_send,
        when=delay,  # <-- головна зміна: seconds
        name=job_name,
        data={"chat_id": chat_id, "task": task}
    )



# --- Menu router ---

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]

    users = load_users()
    chat_id = str(query.message.chat.id)
    users = ensure_user(users, chat_id)
    save_users(users)

    if action == "home":
        await show_menu(query)
        return

    if action == "add":
        await query.edit_message_text("➕ Додавання задачі\n\nНапиши текст задачі:", reply_markup=back_kb())
        return ADD_TITLE

    if action == "day":
        await show_plan_day(query, users[chat_id]["tasks"])
        return

    if action == "week":
        await show_plan_week(query, users[chat_id]["tasks"])
        return

    if action == "month":
        await show_plan_month(query, users[chat_id]["tasks"])
        return

    if action == "do":
        await show_do_list(query, users[chat_id]["tasks"])
        return

    if action == "stats":
        await show_stats(query, users[chat_id])
        return

    if action == "settings":
        await show_settings(query, users[chat_id])
        return

    if action == "reminders":
        await show_reminders_info(query, users[chat_id])
        return


# --- Add task flow ---

async def add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("Напиши задачу трохи конкретніше 🙂")
        return ADD_TITLE

    context.user_data["new_task_title"] = text

    y = date.today().year
    m = date.today().month

    await update.message.reply_text("Обери дату виконання 📅", reply_markup=calendar_kb(y, m))
    return ADD_DATE_PICK


async def cal_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")

    if parts[1] == "ignore":
        return ADD_DATE_PICK

    if parts[1] == "prev":
        ym = parts[2]
        y, m = map(int, ym.split("-"))
        y2, m2 = add_month(y, m, -1)
        await query.edit_message_reply_markup(reply_markup=calendar_kb(y2, m2))
        return ADD_DATE_PICK

    if parts[1] == "next":
        ym = parts[2]
        y, m = map(int, ym.split("-"))
        y2, m2 = add_month(y, m, +1)
        await query.edit_message_reply_markup(reply_markup=calendar_kb(y2, m2))
        return ADD_DATE_PICK

    if parts[1] == "pick":
        picked = parts[2]
        context.user_data["new_task_date"] = picked

        await query.edit_message_text(
            f"Дата обрана ✅ {picked}\n\n"
            "Тепер введи час (HH:MM) або «-» якщо без часу:",
            reply_markup=back_kb()
        )
        return ADD_TIME


async def add_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tm = update.message.text.strip()

    if tm == "-" or tm.lower() in ["ні", "нема", "без", "пропустити"]:
        tm = None
    else:
        try:
            datetime.strptime(tm, "%H:%M")
        except Exception:
            await update.message.reply_text("Невірний час 😅 Напиши так: 18:30 або «-»")
            return ADD_TIME

    users = load_users()
    chat_id = str(update.effective_chat.id)
    users = ensure_user(users, chat_id)

    tasks = users[chat_id]["tasks"]
    task = {
        "id": next_task_id(tasks),
        "title": context.user_data["new_task_title"],
        "date": context.user_data["new_task_date"],
        "time": tm,
        "done": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    tasks.append(task)

    # плануємо нагадування, якщо є час і нагадування увімкнені
    settings = users[chat_id]["settings"]
    if settings.get("reminders_enabled", True) and task.get("time"):
        remind_before = int(settings.get("remind_before_min", 10))
        schedule_reminder(context.application, int(chat_id), task, remind_before)

    save_users(users)

    await update.message.reply_text(
        "✅ Задачу додано!\n\n"
        f"{fmt_task_line(task)}\n\n"
        "Повертаю в меню 👇",
        reply_markup=main_menu_kb()
    )

    return ConversationHandler.END


# --- Plans ---

async def show_plan_day(query, tasks):
    today = date.today()
    day_tasks = filter_tasks_by_range(tasks, today, today)
    text = "📝 План на сьогодні:\n\n" + ("(поки задач немає)" if not day_tasks else "\n".join(fmt_task_line(t) for t in day_tasks))
    await query.edit_message_text(text, reply_markup=back_kb())


async def show_plan_week(query, tasks):
    start = date.today()
    end = start + timedelta(days=6)
    week_tasks = filter_tasks_by_range(tasks, start, end)
    text = "📆 План на 7 днів:\n\n" + ("(поки задач немає)" if not week_tasks else "\n".join(fmt_task_line(t) for t in week_tasks))
    await query.edit_message_text(text, reply_markup=back_kb())


async def show_plan_month(query, tasks):
    start = date.today()
    end = start + timedelta(days=29)
    month_tasks = filter_tasks_by_range(tasks, start, end)
    text = "🗓 План на 30 днів:\n\n" + ("(поки задач немає)" if not month_tasks else "\n".join(fmt_task_line(t) for t in month_tasks))
    await query.edit_message_text(text, reply_markup=back_kb())


# --- Do list + streak ---

def update_streak(stats: dict):
    today = date.today().isoformat()
    last = stats.get("last_done_date")

    if last == today:
        return

    if last is None:
        stats["current_streak"] = 1
    else:
        last_date = datetime.strptime(last, "%Y-%m-%d").date()
        if last_date == date.today() - timedelta(days=1):
            stats["current_streak"] += 1
        else:
            stats["current_streak"] = 1

    stats["last_done_date"] = today
    stats["best_streak"] = max(stats.get("best_streak", 0), stats["current_streak"])


def build_do_kb(tasks: list):
    buttons = []
    visible = [t for t in tasks if not t.get("done")]
    visible.sort(key=lambda x: (x.get("date", "9999-99-99"), x.get("time") or "99:99"))
    visible = visible[:10]

    for t in visible:
        title = t.get("title", "")
        short = title if len(title) <= 24 else title[:24] + "…"
        buttons.append([InlineKeyboardButton(f"✅ {short}", callback_data=f"done:{t['id']}")])

    buttons.append([InlineKeyboardButton("➕ Додати задачу", callback_data="menu:add")])
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(buttons)


async def show_do_list(query, tasks):
    undone = [t for t in tasks if not t.get("done")]
    undone.sort(key=lambda x: (x.get("date", "9999-99-99"), x.get("time") or "99:99"))

    if not undone:
        await query.edit_message_text(
            "✅ У тебе немає невиконаних задач.\n\nМожеш додати нову 🙂",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Додати задачу", callback_data="menu:add")],
                [InlineKeyboardButton("◀️ Назад", callback_data="menu:home")],
            ])
        )
        return

    text_lines = ["✅ Виконати (невиконані задачі):", ""]
    for t in undone[:15]:
        text_lines.append(fmt_task_line(t))
    text_lines.append("")
    text_lines.append("Натисни на задачу нижче, щоб позначити виконаною 👇")

    await query.edit_message_text("\n".join(text_lines), reply_markup=build_do_kb(tasks))


async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    task_id = int(query.data.split(":")[1])

    users = load_users()
    chat_id = str(query.message.chat.id)
    users = ensure_user(users, chat_id)

    tasks = users[chat_id]["tasks"]

    found = None
    for t in tasks:
        if int(t.get("id")) == task_id:
            found = t
            break

    if not found:
        await query.edit_message_text("Не знайшла цю задачу 😅", reply_markup=back_kb())
        return

    if found.get("done"):
        await query.edit_message_text("Ця задача вже виконана ✅", reply_markup=back_to_do_kb())
        return

    found["done"] = True
    found["done_at"] = datetime.now().isoformat(timespec="seconds")

    users[chat_id]["stats"]["done_total"] = users[chat_id]["stats"].get("done_total", 0) + 1
    update_streak(users[chat_id]["stats"])

    save_users(users)

    st = users[chat_id]["stats"]["current_streak"]
    await query.edit_message_text(
        f"✅ Виконано!\n\n{fmt_task_line(found)}\n\n🔥 Серія: {st} днів",
        reply_markup=back_to_do_kb()
    )


# --- Stats + Settings + Reminders UI ---

async def show_stats(query, user_data):
    st = user_data["stats"]
    text = (
        "📈 Твоя статистика\n\n"
        f"✅ Виконано задач всього: {st.get('done_total', 0)}\n"
        f"🔥 Серія днів: {st.get('current_streak', 0)}\n"
        f"🏆 Найкраща серія: {st.get('best_streak', 0)}\n"
    )
    await query.edit_message_text(text, reply_markup=back_kb())


def settings_kb(u):
    enabled = u["settings"].get("soft_check_enabled", True)
    reminders_on = u["settings"].get("reminders_enabled", True)
    remind_before = int(u["settings"].get("remind_before_min", 10))

    soft_state = "увімкнено ✅" if enabled else "вимкнено 🛑"
    rem_state = "увімкнено ✅" if reminders_on else "вимкнено 🛑"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🫶 М’який контроль: {soft_state}", callback_data="set:soft")],
        [InlineKeyboardButton(f"🔔 Нагадування: {rem_state}", callback_data="set:rem")],
        [InlineKeyboardButton(f"⏱ За скільки хв: {remind_before}", callback_data="set:mins")],
        [InlineKeyboardButton("◀️ Назад", callback_data="menu:home")],
    ])


def remind_minutes_kb():
    options = [0, 5, 10, 15, 30, 60]
    rows = []
    row = []
    for i, m in enumerate(options, start=1):
        row.append(InlineKeyboardButton(str(m), callback_data=f"mins:{m}"))
        if i % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


async def show_settings(query, user_data):
    await query.edit_message_text(
        "⚙️ Налаштування\n\n"
        "Тут можна вмикати/вимикати нагадування та вибрати, за скільки хвилин попереджати.",
        reply_markup=settings_kb(user_data)
    )


async def show_reminders_info(query, user_data):
    enabled = user_data["settings"].get("reminders_enabled", True)
    mins = int(user_data["settings"].get("remind_before_min", 10))
    text = (
        "🔔 Нагадування\n\n"
        f"Стан: {'увімкнено ✅' if enabled else 'вимкнено 🛑'}\n"
        f"За скільки хвилин: {mins}\n\n"
        "Нагадування спрацьовують для задач, де ти вказуєш час."
    )
    await query.edit_message_text(text, reply_markup=back_kb())


async def settings_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    users = load_users()
    chat_id = str(query.message.chat.id)
    users = ensure_user(users, chat_id)

    key = query.data.split(":")[1]

    if key == "soft":
        cur = users[chat_id]["settings"].get("soft_check_enabled", True)
        users[chat_id]["settings"]["soft_check_enabled"] = not cur
        save_users(users)
        await query.edit_message_reply_markup(reply_markup=settings_kb(users[chat_id]))
        return

    if key == "rem":
        cur = users[chat_id]["settings"].get("reminders_enabled", True)
        users[chat_id]["settings"]["reminders_enabled"] = not cur
        save_users(users)
        await query.edit_message_reply_markup(reply_markup=settings_kb(users[chat_id]))
        return

    if key == "mins":
        await query.edit_message_text(
            "⏱ Обери за скільки хвилин надсилати нагадування:",
            reply_markup=remind_minutes_kb()
        )
        return


async def minutes_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    mins = int(query.data.split(":")[1])

    users = load_users()
    chat_id = str(query.message.chat.id)
    users = ensure_user(users, chat_id)

    users[chat_id]["settings"]["remind_before_min"] = mins
    save_users(users)

    await query.edit_message_text(
        f"✅ Готово! Тепер нагадування будуть за {mins} хв.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu:settings")]])
    )


# --- Soft control job ---

async def soft_check_job(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    today = date.today()

    for chat_id, u in users.items():
        if not u.get("settings", {}).get("soft_check_enabled", True):
            continue

        tasks = u.get("tasks", [])
        today_tasks = filter_tasks_by_range(tasks, today, today)

        if len(today_tasks) == 0:
            try:
                await context.bot.send_message(
                    chat_id=int(chat_id),
                    text="🫶 На сьогодні немає задач.\nХочеш додати одну маленьку задачу?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Додати задачу", callback_data="menu:add")],
                        [InlineKeyboardButton("Ок, пізніше", callback_data="menu:home")]
                    ])
                )
            except Exception:
                pass


def main():
    app = Application.builder().token(TOKEN).build()

    add_flow = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_router, pattern=r"^menu:add$")],
        states={
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            ADD_DATE_PICK: [CallbackQueryHandler(cal_click, pattern=r"^cal:")],
            ADD_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_time)],
        },
        fallbacks=[CallbackQueryHandler(menu_router, pattern=r"^menu:home$")],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(add_flow)

    app.add_handler(CallbackQueryHandler(menu_router, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(done_task, pattern=r"^done:"))
    app.add_handler(CallbackQueryHandler(settings_click, pattern=r"^set:"))
    app.add_handler(CallbackQueryHandler(minutes_pick, pattern=r"^mins:"))

    # Soft check: кожного дня о 10:00
    app.job_queue.run_daily(
        soft_check_job,
        time=dtime(hour=10, minute=0)
    )

    app.run_polling()


if __name__ == "__main__":
    main()
