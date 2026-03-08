#!/usr/bin/env python3
# =============================================================================
# AmneziaWG — Telegram бот управления
# =============================================================================

import os
import sys
import subprocess
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; NC='\033[0m'

CONFIG_FILE = "/etc/amnezia/amneziawg/bot.env"
ENV_FILE    = "/etc/amnezia/amneziawg/server.env"

def load_server_env():
    env = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

def setup():
    print(f"\n{C}{B}{'='*50}{NC}")
    print(f"{C}{B}   AmneziaWG — Настройка Telegram бота{NC}")
    print(f"{C}{B}{'='*50}{NC}\n")
    print(f"{B}Шаг 1: Токен бота{NC}")
    print(f"  Как получить:")
    print(f"  1. Откройте Telegram, найдите {Y}@BotFather{NC}")
    print(f"  2. Напишите {Y}/newbot{NC}")
    print(f"  3. Придумайте имя и username боту")
    print(f"  4. Скопируйте токен вида {Y}1234567890:AAF...{NC}\n")
    while True:
        token = input("  Вставьте токен: ").strip()
        if ":" in token and len(token) > 20:
            break
        print(f"  {R}Неверный формат. Токен выглядит как: 1234567890:AAFxxx...{NC}")
    print(f"\n{B}Шаг 2: Ваш Telegram ID{NC}")
    print(f"  Как получить:")
    print(f"  1. Найдите в Telegram бота {Y}@userinfobot{NC}")
    print(f"  2. Напишите ему любое сообщение")
    print(f"  3. Он ответит вашим ID — число вида {Y}123456789{NC}\n")
    while True:
        admin_id = input("  Вставьте ваш ID: ").strip()
        if admin_id.isdigit():
            break
        print(f"  {R}ID должен быть числом, например: 123456789{NC}")
    os.makedirs("/etc/amnezia/amneziawg", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        f.write(f"BOT_TOKEN={token}\n")
        f.write(f"ADMIN_ID={admin_id}\n")
    os.chmod(CONFIG_FILE, 0o600)
    print(f"\n{G}{'='*50}{NC}")
    print(f"{G}✓ Настройка завершена!{NC}")
    print(f"{G}{'='*50}{NC}")
    print(f"\n  Откройте вашего бота в Telegram и напишите /start\n")

def load_config():
    cfg = {}
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg

if not os.path.exists(CONFIG_FILE):
    setup()

cfg        = load_config()
BOT_TOKEN  = cfg["BOT_TOKEN"]
ADMIN_ID   = int(cfg["ADMIN_ID"])

srv           = load_server_env()
SERVER_IP     = srv["SERVER_IP"]
SERVER_PORT   = srv["SERVER_PORT"]
SERVER_PUBLIC = srv["SERVER_PUBLIC"]
VPN_SUBNET    = srv["VPN_SUBNET"]
AWG_IFACE     = srv["VPN_IFACE"]
CLIENTS_DIR   = "/etc/amnezia/amneziawg/clients"
AWG_CONF      = "/etc/amnezia/amneziawg/awg0.conf"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

WAITING_NAME = 1

# ─────────────────────────────────────────────
# Хелперы
# ─────────────────────────────────────────────
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.effective_message.reply_text("⛔ Доступ запрещён.")
            return
        return await func(update, context)
    return wrapper

def esc(text):
    """Экранируем спецсимволы для MarkdownV2"""
    for ch in r"_*[]()~`>#+-=|{}.!\\":
        text = text.replace(ch, f"\\{ch}")
    return text

def next_ip():
    i = 2
    while True:
        with open(AWG_CONF, encoding='utf-8', errors='replace') as f:
            if f"{VPN_SUBNET}.{i}/32" not in f.read():
                return i
        i += 1

def get_clients():
    if not os.path.exists(CLIENTS_DIR):
        return []
    return sorted([f[:-5] for f in os.listdir(CLIENTS_DIR) if f.endswith(".conf")])

def awg_show():
    try:
        return subprocess.check_output(["awg", "show", AWG_IFACE], text=True)
    except:
        return ""

def make_conf(name, private, client_ip):
    return "\n".join([
        "[Interface]",
        f"PrivateKey = {private}",
        f"Address = {client_ip}/32",
        "DNS = 1.1.1.1",
        "Jc = 4", "Jmin = 40", "Jmax = 70",
        "S1 = 0", "S2 = 0",
        "H1 = 1", "H2 = 2", "H3 = 3", "H4 = 4",
        "",
        "[Peer]",
        f"PublicKey = {SERVER_PUBLIC}",
        f"Endpoint = {SERVER_IP}:{SERVER_PORT}",
        "AllowedIPs = 0.0.0.0/0",
        "PersistentKeepalive = 25",
    ]) + "\n"

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]])

# ─────────────────────────────────────────────
# Главное меню
# ─────────────────────────────────────────────
async def main_menu_msg(msg, edit=False):
    clients = get_clients()
    keyboard = [
        [InlineKeyboardButton("➕ Добавить клиента", callback_data="add")],
        [InlineKeyboardButton("👥 Список клиентов",  callback_data="list")],
        [InlineKeyboardButton("🗑 Удалить клиента",  callback_data="delete")],
        [InlineKeyboardButton("📊 Статус сервера",   callback_data="status")],
    ]
    text = (
        f"🔐 AmneziaWG — Управление VPN\n\n"
        f"🖥 Сервер: {SERVER_IP}:{SERVER_PORT}\n"
        f"👤 Клиентов: {len(clients)}"
    )
    if edit:
        await msg.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_msg(update.message)

# ─────────────────────────────────────────────
# Кнопки
# ─────────────────────────────────────────────
@admin_only
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "back":
        await main_menu_msg(query, edit=True)

    elif data == "list":
        await show_list(query)

    elif data == "delete":
        clients = get_clients()
        if not clients:
            await query.edit_message_text("👥 Клиентов нет.", reply_markup=back_kb())
            return
        keyboard = [[InlineKeyboardButton(f"🗑 {n}", callback_data=f"del_{n}")] for n in clients]
        keyboard.append([InlineKeyboardButton("◀️ В меню", callback_data="back")])
        await query.edit_message_text("Выберите клиента для удаления:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "status":
        await show_status(query)

    elif data.startswith("del_"):
        await do_delete(query, data[4:])

    elif data.startswith("client_"):
        await show_client(query, data[7:])

    elif data.startswith("conf_"):
        await send_conf(query, data[5:])

    elif data.startswith("qr_"):
        await send_qr(query, data[3:])

# ─────────────────────────────────────────────
# Список клиентов
# ─────────────────────────────────────────────
async def show_list(query):
    clients = get_clients()
    if not clients:
        await query.edit_message_text("👥 Клиентов нет.", reply_markup=back_kb())
        return

    output = awg_show()
    lines  = ["👥 Клиенты:\n"]

    for name in clients:
        conf_path = f"{CLIENTS_DIR}/{name}.conf"
        ip, pub   = "", ""
        with open(conf_path) as f:
            for line in f:
                if line.startswith("Address"):
                    ip = line.split("=")[1].strip().split("/")[0]
                if line.startswith("PublicKey"):
                    pub = line.split("=", 1)[1].strip()

        handshake = "никогда"
        if pub and pub in output:
            for i, l in enumerate(output.split("\n")):
                if pub in l:
                    for j in range(i, min(i+6, len(output.split("\n")))):
                        if "latest handshake" in output.split("\n")[j]:
                            handshake = output.split("\n")[j].split(":", 1)[1].strip()
        lines.append(f"• {name} — {ip} — {handshake}")

    keyboard = [[InlineKeyboardButton(f"📋 {n}", callback_data=f"client_{n}")] for n in clients]
    keyboard.append([InlineKeyboardButton("◀️ В меню", callback_data="back")])
    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

async def show_client(query, name):
    keyboard = [
        [InlineKeyboardButton("📄 Скачать .conf", callback_data=f"conf_{name}")],
        [InlineKeyboardButton("📱 QR-код",         callback_data=f"qr_{name}")],
        [InlineKeyboardButton("◀️ Назад",          callback_data="list")],
    ]
    await query.edit_message_text(
        f"👤 Клиент: {name}\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def send_conf(query, name):
    conf_path = f"{CLIENTS_DIR}/{name}.conf"
    await query.message.reply_document(
        document=open(conf_path, "rb"),
        filename=f"{name}.conf",
        caption=f"📄 Конфиг клиента {name}"
    )

async def send_qr(query, name):
    conf_path = f"{CLIENTS_DIR}/{name}.conf"
    qr_path   = f"/tmp/{name}_qr.png"
    try:
        subprocess.run(["qrencode", "-o", qr_path, "-l", "L", "-r", conf_path], check=True)
        await query.message.reply_photo(
            photo=open(qr_path, "rb"),
            caption=f"📱 QR-код клиента {name}"
        )
        os.remove(qr_path)
    except Exception as e:
        await query.message.reply_text(f"❌ Ошибка QR: {e}")

# ─────────────────────────────────────────────
# Статус
# ─────────────────────────────────────────────
async def show_status(query):
    output = awg_show()
    peers  = output.count("peer:")
    try:
        uptime = subprocess.check_output(["uptime", "-p"], text=True).strip()
    except:
        uptime = "—"
    mem = subprocess.check_output(["free", "-m"], text=True).split("\n")[1].split()
    ram = f"{mem[2]} MB / {mem[1]} MB"

    text = (
        f"📊 Статус сервера\n\n"
        f"🟢 AWG: работает\n"
        f"🖥 IP: {SERVER_IP}:{SERVER_PORT}\n"
        f"⏱ Uptime: {uptime}\n"
        f"💾 RAM: {ram}\n"
        f"👤 Клиентов: {len(get_clients())}\n"
        f"🔗 Активных пиров: {peers}"
    )
    await query.edit_message_text(text, reply_markup=back_kb())

# ─────────────────────────────────────────────
# Удаление
# ─────────────────────────────────────────────
async def do_delete(query, name):
    conf_path = f"{CLIENTS_DIR}/{name}.conf"
    if not os.path.exists(conf_path):
        await query.edit_message_text(f"❌ Клиент {name} не найден.", reply_markup=back_kb())
        return

    with open(conf_path) as f:
        for line in f:
            if line.startswith("PublicKey"):
                pub = line.split("=", 1)[1].strip()
                subprocess.run(["awg", "set", AWG_IFACE, "peer", pub, "remove"])
                break

    with open(AWG_CONF, encoding='utf-8', errors='replace') as f:
        lines = f.read().split("\n")
    new_lines = []
    skip = False
    for line in lines:
        if line.strip() == f"# Client: {name}":
            skip = True
        elif skip and line.strip().startswith("[") and line.strip() != "[Peer]":
            skip = False
            new_lines.append(line)
        elif not skip:
            new_lines.append(line)
    with open(AWG_CONF, "w") as f:
        f.write("\n".join(new_lines))

    os.remove(conf_path)
    await query.edit_message_text(f"✅ Клиент {name} удалён.", reply_markup=back_kb())

# ─────────────────────────────────────────────
# Добавление — приём имени
# ─────────────────────────────────────────────
async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    name = "".join(c for c in update.message.text.strip() if c.isalnum() or c in "_-")

    if not name:
        await update.message.reply_text("❌ Имя пустое. Используйте латиницу, цифры, _ или -.")
        return ConversationHandler.END

    if os.path.exists(f"{CLIENTS_DIR}/{name}.conf"):
        await update.message.reply_text(f"❌ Клиент {name} уже существует.")
        return ConversationHandler.END

    private    = subprocess.check_output(["awg", "genkey"], text=True).strip()
    public     = subprocess.check_output(["awg", "pubkey"], input=private, text=True).strip()
    client_ip  = f"{VPN_SUBNET}.{next_ip()}"

    with open(AWG_CONF, "a") as f:
        f.write(f"\n# Client: {name}\n[Peer]\nPublicKey = {public}\nAllowedIPs = {client_ip}/32\n")
    subprocess.run(["awg", "set", AWG_IFACE, "peer", public, "allowed-ips", f"{client_ip}/32"])

    os.makedirs(CLIENTS_DIR, exist_ok=True)
    conf_path = f"{CLIENTS_DIR}/{name}.conf"
    with open(conf_path, "w") as f:
        f.write(make_conf(name, private, client_ip))

    await update.message.reply_document(
        document=open(conf_path, "rb"),
        filename=f"{name}.conf",
        caption=f"✅ Клиент {name} добавлен\n🌐 IP: {client_ip}"
    )

    qr_path = f"/tmp/{name}_qr.png"
    try:
        subprocess.run(["qrencode", "-o", qr_path, "-l", "L", "-r", conf_path], check=True)
        await update.message.reply_photo(
            photo=open(qr_path, "rb"),
            caption=f"📱 QR-код для {name}"
        )
        os.remove(qr_path)
    except:
        pass

    await main_menu_msg(update.message)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END

# ─────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    async def add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "✏️ Введите имя клиента\n\nТолько латиница, цифры, _ или -\nНапример: phone, laptop, work"
        )
        return WAITING_NAME

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_entry, pattern="^add$")],
        states={WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info(f"Бот запущен. Admin ID: {ADMIN_ID}")
    print(f"\n{G}✓ Бот запущен! Напишите /start вашему боту в Telegram.{NC}\n")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
