#!/usr/bin/env python3
# =============================================================================
# AmneziaWG — Telegram бот управления
# =============================================================================

import os, sys, subprocess, logging, json, zlib, base64, struct
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
    print(f"  1. Откройте Telegram, найдите {Y}@BotFather{NC}")
    print(f"  2. Напишите {Y}/newbot{NC}")
    print(f"  3. Скопируйте токен вида {Y}1234567890:AAF...{NC}\n")
    while True:
        token = input("  Вставьте токен: ").strip()
        if ":" in token and len(token) > 20: break
        print(f"  {R}Неверный формат токена{NC}")
    print(f"\n{B}Шаг 2: Ваш Telegram ID{NC}")
    print(f"  1. Найдите {Y}@userinfobot{NC} в Telegram")
    print(f"  2. Напишите ему любое сообщение")
    print(f"  3. Скопируйте число — ваш ID\n")
    while True:
        admin_id = input("  Вставьте ваш ID: ").strip()
        if admin_id.isdigit(): break
        print(f"  {R}ID должен быть числом{NC}")
    os.makedirs("/etc/amnezia/amneziawg", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        f.write(f"BOT_TOKEN={token}\nADMIN_ID={admin_id}\n")
    os.chmod(CONFIG_FILE, 0o600)
    print(f"\n{G}✓ Настройка завершена! Напишите /start вашему боту.{NC}\n")

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

cfg           = load_config()
BOT_TOKEN     = cfg["BOT_TOKEN"]
ADMIN_ID      = int(cfg["ADMIN_ID"])
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
# Генерация конфига в формате Amnezia
# ─────────────────────────────────────────────
def gen_obfs():
    """Читаем параметры обфускации с сервера — клиент должен совпадать с сервером"""
    return {
        "Jc":   srv.get("JC",   "4"),
        "Jmin": srv.get("JMIN", "40"),
        "Jmax": srv.get("JMAX", "70"),
        "S1":   srv.get("S1",   "0"),
        "S2":   srv.get("S2",   "0"),
        "H1":   srv.get("H1",   "1"),
        "H2":   srv.get("H2",   "2"),
        "H3":   srv.get("H3",   "3"),
        "H4":   srv.get("H4",   "4"),
    }

def make_vpn_link(client_priv, client_pub, client_ip, psk, obfs, name):
    wg_conf = (
        f"[Interface]\n"
        f"Address = {client_ip}/32\n"
        f"DNS = $PRIMARY_DNS, $SECONDARY_DNS\n"
        f"PrivateKey = {client_priv}\n"
        f"Jc = {obfs['Jc']}\nJmin = {obfs['Jmin']}\nJmax = {obfs['Jmax']}\n"
        f"S1 = {obfs['S1']}\nS2 = {obfs['S2']}\n"
        f"H1 = {obfs['H1']}\nH2 = {obfs['H2']}\nH3 = {obfs['H3']}\nH4 = {obfs['H4']}\n\n"
        f"[Peer]\n"
        f"PublicKey = {SERVER_PUBLIC}\n"
        f"PresharedKey = {psk}\n"
        f"AllowedIPs = 0.0.0.0/0, ::/0\n"
        f"Endpoint = {SERVER_IP}:{SERVER_PORT}\n"
        f"PersistentKeepalive = 25\n"
    )
    last_config = {
        **obfs,
        "allowed_ips": ["0.0.0.0/0", "::/0"],
        "clientId": client_pub,
        "client_ip": client_ip,
        "client_priv_key": client_priv,
        "client_pub_key": client_pub,
        "config": wg_conf,
        "hostName": SERVER_IP,
        "mtu": "1376",
        "persistent_keep_alive": "25",
        "port": int(SERVER_PORT),
        "psk_key": psk,
        "server_pub_key": SERVER_PUBLIC,
    }
    container = {
        "containers": [{
            "awg": {
                **obfs,
                "last_config": json.dumps(last_config, indent=4),
                "port": str(SERVER_PORT),
                "subnet_address": ".".join(client_ip.split(".")[:3]) + ".0",
                "transport_proto": "udp"
            },
            "container": "amnezia-awg"
        }],
        "defaultContainer": "amnezia-awg",
        "description": name,
        "dns1": "1.1.1.1",
        "dns2": "1.0.0.1",
        "hostName": SERVER_IP,
        "nameOverriddenByUser": True
    }
    json_bytes = json.dumps(container, ensure_ascii=False).encode('utf-8')
    compressed = zlib.compress(json_bytes)
    header = struct.pack('>I', len(json_bytes))
    payload = header + compressed
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip('=')
    return f"vpn://{encoded}"

def make_wg_conf(client_priv, client_ip, psk, obfs):
    lines = [
        "[Interface]",
        f"PrivateKey = {client_priv}",
        f"Address = {client_ip}/32",
        "DNS = 1.1.1.1",
        f"Jc = {obfs['Jc']}", f"Jmin = {obfs['Jmin']}", f"Jmax = {obfs['Jmax']}",
        f"S1 = {obfs['S1']}", f"S2 = {obfs['S2']}",
        f"H1 = {obfs['H1']}", f"H2 = {obfs['H2']}", f"H3 = {obfs['H3']}", f"H4 = {obfs['H4']}",
        "",
        "[Peer]",
        f"PublicKey = {SERVER_PUBLIC}",
        f"PresharedKey = {psk}",
        f"Endpoint = {SERVER_IP}:{SERVER_PORT}",
        "AllowedIPs = 0.0.0.0/0",
        "PersistentKeepalive = 25",
    ]
    return "\n".join(lines) + "\n"

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

def next_ip():
    i = 2
    while True:
        with open(AWG_CONF) as f:
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
    elif data.startswith("confirm_del_"):
        await confirm_delete(query, data[12:])
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
        ip, pub = "", ""
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
    await query.edit_message_text(f"👤 Клиент: {name}\n\nВыберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))

async def send_conf(query, name):
    conf_path = f"{CLIENTS_DIR}/{name}.conf"
    await query.message.reply_document(
        document=open(conf_path, "rb"),
        filename=f"{name}.conf",
        caption=f"📄 Конфиг клиента {name}"
    )

async def send_qr(query, name):
    conf_path = f"{CLIENTS_DIR}/{name}.conf"
    vpn_path  = f"{CLIENTS_DIR}/{name}.vpnlink"
    qr_path   = f"/tmp/{name}_qr.png"

    # QR 1 — из .conf для AmneziaWG
    try:
        subprocess.run(["qrencode", "-o", qr_path, "-l", "L", "-r", conf_path], check=True)
        await query.message.reply_photo(
            photo=open(qr_path, "rb"),
            caption=f"📱 QR для AmneziaWG (стандартный клиент)\nКлиент: {name}"
        )
        os.remove(qr_path)
    except Exception as e:
        await query.message.reply_text(f"❌ Ошибка QR (AmneziaWG): {e}")

    # QR 2 — из vpn:// для AmneziaVPN
    if os.path.exists(vpn_path):
        try:
            subprocess.run(["qrencode", "-o", qr_path, "-l", "L", "-r", vpn_path], check=True)
            await query.message.reply_photo(
                photo=open(qr_path, "rb"),
                caption=f"📱 QR для AmneziaVPN (с раздельным туннелированием)\nКлиент: {name}"
            )
            os.remove(qr_path)
        except Exception as e:
            await query.message.reply_text(f"❌ Ошибка QR (AmneziaVPN): {e}")

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
# Удаление с подтверждением
# ─────────────────────────────────────────────
async def do_delete(query, name):
    conf_path = f"{CLIENTS_DIR}/{name}.conf"
    if not os.path.exists(conf_path):
        await query.edit_message_text(f"❌ Клиент {name} не найден.", reply_markup=back_kb())
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_del_{name}")],
        [InlineKeyboardButton("❌ Отмена",      callback_data="delete")],
    ])
    await query.edit_message_text(
        f"🗑 Удаление клиента {name}\n\nХорошо подумал? Это действие необратимо.",
        reply_markup=keyboard
    )

async def confirm_delete(query, name):
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
    for ext in [".conf", ".vpnlink"]:
        path = f"{CLIENTS_DIR}/{name}{ext}"
        if os.path.exists(path):
            os.remove(path)
    await query.edit_message_text(f"✅ Клиент {name} удалён.", reply_markup=back_kb())

# ─────────────────────────────────────────────
# Добавление клиента
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

    # Генерируем ключи
    private = subprocess.check_output(["awg", "genkey"], text=True).strip()
    public  = subprocess.check_output(["awg", "pubkey"], input=private, text=True).strip()
    psk     = subprocess.check_output(["awg", "genpsk"], text=True).strip()
    client_ip = f"{VPN_SUBNET}.{next_ip()}"
    obfs    = gen_obfs()

    # Добавляем пир на сервер
    with open(AWG_CONF, "a") as f:
        f.write(f"\n# Client: {name}\n[Peer]\nPublicKey = {public}\nPresharedKey = {psk}\nAllowedIPs = {client_ip}/32\n")
    subprocess.run(["awg", "set", AWG_IFACE, "peer", public,
                    "preshared-key", "/dev/stdin",
                    "allowed-ips", f"{client_ip}/32"],
                   input=psk, text=True)

    os.makedirs(CLIENTS_DIR, exist_ok=True)

    # Сохраняем .conf
    conf_path = f"{CLIENTS_DIR}/{name}.conf"
    with open(conf_path, "w") as f:
        f.write(make_wg_conf(private, client_ip, psk, obfs))

    # Сохраняем vpn:// ссылку
    vpn_link = make_vpn_link(private, public, client_ip, psk, obfs, name)
    vpnlink_path = f"{CLIENTS_DIR}/{name}.vpnlink"
    with open(vpnlink_path, "w") as f:
        f.write(vpn_link)

    # Отправляем .conf файл
    await update.message.reply_document(
        document=open(conf_path, "rb"),
        filename=f"{name}.conf",
        caption=f"✅ Клиент {name} добавлен\n🌐 IP: {client_ip}\n\nИмпорт в AmneziaVPN: Файл с настройками"
    )

    qr_path = f"/tmp/{name}_qr.png"

    # QR 1 — из .conf для AmneziaWG
    try:
        subprocess.run(["qrencode", "-o", qr_path, "-l", "L", "-r", conf_path], check=True)
        await update.message.reply_photo(
            photo=open(qr_path, "rb"),
            caption=f"📱 QR для AmneziaWG (стандартный клиент)"
        )
        os.remove(qr_path)
    except:
        pass

    # QR 2 — из vpn:// для AmneziaVPN
    try:
        subprocess.run(["qrencode", "-o", qr_path, "-l", "L", "-r", vpnlink_path], check=True)
        await update.message.reply_photo(
            photo=open(qr_path, "rb"),
            caption=f"📱 QR для AmneziaVPN (с раздельным туннелированием)"
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
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info(f"Бот запущен. Admin ID: {ADMIN_ID}")
    print(f"\n{G}✓ Бот запущен! Напишите /start вашему боту в Telegram.{NC}\n")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
