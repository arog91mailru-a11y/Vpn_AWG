#!/usr/bin/env python3
import os, subprocess, logging, json, zlib, base64, struct, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; B='\033[1m'; NC='\033[0m'
CONFIG_FILE  = "/etc/amnezia/amneziawg/bot.env"
ENV_FILE     = "/etc/amnezia/amneziawg/server.env"


def load_env(path):
    env = {}
    with open(path) as f:
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
    while True:
        token = input("  Вставьте токен бота: ").strip()
        if ":" in token and len(token) > 20: break
        print(f"  {R}Неверный формат токена{NC}")
    while True:
        admin_id = input("  Вставьте ваш Telegram ID: ").strip()
        if admin_id.isdigit(): break
        print(f"  {R}ID должен быть числом{NC}")
    os.makedirs("/etc/amnezia/amneziawg", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        f.write(f"BOT_TOKEN={token}\nADMIN_ID={admin_id}\n")
    os.chmod(CONFIG_FILE, 0o600)
    print(f"\n{G}✓ Готово!{NC}\n")

if not os.path.exists(CONFIG_FILE):
    setup()

cfg           = load_env(CONFIG_FILE)
BOT_TOKEN     = cfg["BOT_TOKEN"]
ADMIN_ID      = int(cfg["ADMIN_ID"])
srv           = load_env(ENV_FILE)
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

# ── Трафик ────────────────────────────────────────────────────────────────────
def load_traffic():
    try:
        return json.load(open(TRAFFIC_FILE))
    except:
        return {}

def save_traffic(data):
    json.dump(data, open(TRAFFIC_FILE, "w"), indent=2)

def get_awg_dump():
    """Возвращает dict: pub_key -> {rx, tx, endpoint, handshake, allowed_ips}"""
    try:
        out = subprocess.check_output(["awg", "show", AWG_IFACE, "dump"], text=True)
    except:
        return {}
    peers = {}
    for line in out.strip().split("\n")[1:]:  # пропускаем первую строку (интерфейс)
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        pub       = parts[0]
        endpoint  = parts[2] if parts[2] != "(none)" else ""
        allowed   = parts[3] if parts[3] != "(none)" else ""
        handshake = int(parts[4]) if parts[4] not in ("0", "(none)") else 0
        rx        = int(parts[5])
        tx        = int(parts[6])
        peers[pub] = {"rx": rx, "tx": tx, "endpoint": endpoint,
                      "allowed": allowed, "handshake": handshake}
    return peers

def accumulate_traffic():
    """Вызывается из cron каждые 5 минут — накапливает трафик"""
    data   = load_traffic()
    peers  = get_awg_dump()
    now    = datetime.now()
    month  = now.strftime("%Y-%m")

    # Сопоставляем пиры с клиентами по allowed_ips
    client_map = {}  # pub -> name
    for f in os.listdir(CLIENTS_DIR):
        if not f.endswith(".conf"):
            continue
        name = f[:-5]
        with open(f"{CLIENTS_DIR}/{f}") as cf:
            for line in cf:
                if line.startswith("PublicKey"):
                    pub = line.split("=", 1)[1].strip()
                    client_map[pub] = name

    for pub, stats in peers.items():
        name = client_map.get(pub, pub[:8])
        if name not in data:
            data[name] = {}
        if month not in data[name]:
            data[name][month] = {"rx": 0, "tx": 0, "last_rx": 0, "last_tx": 0}

        last_rx = data[name][month].get("last_rx", 0)
        last_tx = data[name][month].get("last_tx", 0)

        # AWG счётчики растут, но могут сброситься при перезагрузке
        if stats["rx"] >= last_rx:
            data[name][month]["rx"] += stats["rx"] - last_rx
        else:
            data[name][month]["rx"] += stats["rx"]  # сброс счётчика

        if stats["tx"] >= last_tx:
            data[name][month]["tx"] += stats["tx"] - last_tx
        else:
            data[name][month]["tx"] += stats["tx"]

        data[name][month]["last_rx"] = stats["rx"]
        data[name][month]["last_tx"] = stats["tx"]

    save_traffic(data)

def fmt_bytes(b):
    if b < 1024:
        return f"{b} B"
    elif b < 1024**2:
        return f"{b/1024:.1f} KB"
    elif b < 1024**3:
        return f"{b/1024**2:.1f} MB"
    else:
        return f"{b/1024**3:.2f} GB"

def fmt_handshake(ts):
    if not ts:
        return "никогда"
    diff = int(time.time()) - ts
    if diff < 60:
        return f"{diff} сек назад 🟢"
    elif diff < 180:
        return f"{diff//60} мин назад 🟢"
    elif diff < 3600:
        return f"{diff//60} мин назад"
    elif diff < 86400:
        return f"{diff//3600} ч назад"
    else:
        return f"{diff//86400} д назад"

# ── Обфускация ─────────────────────────────────────────────────────────────────
def gen_obfs():
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

def make_vpn_link(priv, pub, ip, psk, obfs, name):
    wg = (
        f"[Interface]\nAddress = {ip}/32\nDNS = $PRIMARY_DNS, $SECONDARY_DNS\n"
        f"PrivateKey = {priv}\nJc = {obfs['Jc']}\nJmin = {obfs['Jmin']}\nJmax = {obfs['Jmax']}\n"
        f"S1 = {obfs['S1']}\nS2 = {obfs['S2']}\nH1 = {obfs['H1']}\nH2 = {obfs['H2']}\n"
        f"H3 = {obfs['H3']}\nH4 = {obfs['H4']}\n\n"
        f"[Peer]\nPublicKey = {SERVER_PUBLIC}\nPresharedKey = {psk}\n"
        f"AllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = {SERVER_IP}:{SERVER_PORT}\nPersistentKeepalive = 25\n"
    )
    lc = {**obfs, "allowed_ips": ["0.0.0.0/0", "::/0"], "clientId": pub,
          "client_ip": ip, "client_priv_key": priv, "client_pub_key": pub,
          "config": wg, "hostName": SERVER_IP, "mtu": "1376",
          "persistent_keep_alive": "25", "port": int(SERVER_PORT),
          "psk_key": psk, "server_pub_key": SERVER_PUBLIC}
    c = {"containers": [{"awg": {**obfs, "last_config": json.dumps(lc, indent=4),
         "port": str(SERVER_PORT), "subnet_address": ".".join(ip.split(".")[:3]) + ".0",
         "transport_proto": "udp"}, "container": "amnezia-awg"}],
         "defaultContainer": "amnezia-awg", "description": name,
         "dns1": "1.1.1.1", "dns2": "1.0.0.1", "hostName": SERVER_IP, "nameOverriddenByUser": True}
    b = json.dumps(c, ensure_ascii=False).encode()
    p = struct.pack('>I', len(b)) + zlib.compress(b)
    return "vpn://" + base64.urlsafe_b64encode(p).decode().rstrip('=')

def make_wg_conf(priv, ip, psk, obfs):
    return "\n".join([
        "[Interface]",
        f"PrivateKey = {priv}", f"Address = {ip}/32", "DNS = 1.1.1.1",
        f"Jc = {obfs['Jc']}", f"Jmin = {obfs['Jmin']}", f"Jmax = {obfs['Jmax']}",
        f"S1 = {obfs['S1']}", f"S2 = {obfs['S2']}",
        f"H1 = {obfs['H1']}", f"H2 = {obfs['H2']}", f"H3 = {obfs['H3']}", f"H4 = {obfs['H4']}",
        "", "[Peer]", f"PublicKey = {SERVER_PUBLIC}", f"PresharedKey = {psk}",
        f"Endpoint = {SERVER_IP}:{SERVER_PORT}", "AllowedIPs = 0.0.0.0/0", "PersistentKeepalive = 25",
    ]) + "\n"

# ── Хелперы ────────────────────────────────────────────────────────────────────
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

def get_client_pub(name):
    """Получаем публичный ключ клиента из приватного ключа в [Interface]"""
    try:
        with open(f"{CLIENTS_DIR}/{name}.conf") as f:
            in_interface = False
            for line in f:
                line = line.strip()
                if line == "[Interface]":
                    in_interface = True
                elif line.startswith("["):
                    in_interface = False
                elif in_interface and line.startswith("PrivateKey"):
                    priv = line.split("=", 1)[1].strip()
                    pub = subprocess.check_output(["awg", "pubkey"], input=priv, text=True).strip()
                    return pub
    except:
        pass
    return None

def awg_show():
    try:
        return subprocess.check_output(["awg", "show", AWG_IFACE], text=True)
    except:
        return ""

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В меню", callback_data="back")]])

def vpn_path(name):
    p = f"{CLIENTS_DIR}/{name}.vpn"
    if not os.path.exists(p):
        alt = f"{CLIENTS_DIR}/{name}.vpnlink"
        if os.path.exists(alt):
            return alt
    return p

# ── Меню ───────────────────────────────────────────────────────────────────────
async def main_menu_msg(msg, edit=False):
    clients = get_clients()
    kb = [
        [InlineKeyboardButton("➕ Добавить клиента", callback_data="add")],
        [InlineKeyboardButton("👥 Список клиентов",  callback_data="list")],
        [InlineKeyboardButton("🗑 Удалить клиента",  callback_data="delete")],
        [InlineKeyboardButton("📊 Статус сервера",   callback_data="status")],
        [InlineKeyboardButton("🧹 Очистить мусор",   callback_data="cleanup")],
        [InlineKeyboardButton("📋 Инструкция",       callback_data="help")],
    ]
    text = f"🔐 AmneziaWG — Управление VPN\n\n🖥 Сервер: {SERVER_IP}:{SERVER_PORT}\n👤 Клиентов: {len(clients)}"
    if edit:
        await msg.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_msg(update.message)

# ── Кнопки ─────────────────────────────────────────────────────────────────────
@admin_only
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back":
        await main_menu_msg(query, edit=True)
    elif data == "list":
        await show_list(query)
    elif data == "delete":
        clients = get_clients()
        if not clients:
            await query.edit_message_text("👥 Клиентов нет.", reply_markup=back_kb())
            return
        kb = [[InlineKeyboardButton(f"🗑 {n}", callback_data=f"del_{n}")] for n in clients]
        kb.append([InlineKeyboardButton("◀️ В меню", callback_data="back")])
        await query.edit_message_text("Выберите клиента для удаления:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "status":
        await show_status(query)
    elif data == "cleanup":
        await do_cleanup(query)
    elif data == "help":
        await show_help(query)
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
    elif data.startswith("share_"):
        await send_share(query, data[6:])

# ── Список клиентов ────────────────────────────────────────────────────────────
async def show_list(query):
    clients = get_clients()
    if not clients:
        await query.edit_message_text("👥 Клиентов нет.", reply_markup=back_kb())
        return
    peers = get_awg_dump()
    lines = ["👥 Клиенты:\n"]
    for name in clients:
        pub   = get_client_pub(name)
        stats = peers.get(pub, {}) if pub else {}
        hs    = fmt_handshake(stats.get("handshake", 0))
        rx    = fmt_bytes(stats.get("rx", 0))
        tx    = fmt_bytes(stats.get("tx", 0))
        lines.append(f"• {name} | {hs} | ↓{rx} ↑{tx}")

    kb = [[InlineKeyboardButton(f"📋 {n}", callback_data=f"client_{n}")] for n in clients]
    kb.append([InlineKeyboardButton("◀️ В меню", callback_data="back")])
    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))

async def show_client(query, name):
    peers = get_awg_dump()
    pub   = get_client_pub(name)
    stats = peers.get(pub, {}) if pub else {}

    hs = fmt_handshake(stats.get("handshake", 0))
    rx = fmt_bytes(stats.get("rx", 0))
    tx = fmt_bytes(stats.get("tx", 0))
    ep = stats.get("endpoint", "—")

    info = (
        f"👤 Клиент: {name}\n\n"
        f"🕐 Хендшейк: {hs}\n"
        f"📍 Endpoint: {ep}\n"
        f"📶 Трафик (с перезагрузки): ↓{rx} ↑{tx}"
    )
    kb = [
        [InlineKeyboardButton("📄 Скачать .conf",    callback_data=f"conf_{name}")],
        [InlineKeyboardButton("📱 QR-код",            callback_data=f"qr_{name}")],
        [InlineKeyboardButton("📤 Поделиться кодом", callback_data=f"share_{name}")],
        [InlineKeyboardButton("◀️ Назад",             callback_data="list")],
    ]
    await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(kb))

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
        subprocess.run(["qrencode", "-o", qr_path, "-r", conf_path], check=True)
        await query.message.reply_photo(
            photo=open(qr_path, "rb"),
            caption=f"📱 QR для AmneziaWG\nКлиент: {name}"
        )
        os.remove(qr_path)
    except Exception as e:
        await query.message.reply_text(f"❌ Ошибка QR: {e}")

async def send_share(query, name):
    p = vpn_path(name)
    if not os.path.exists(p):
        await query.message.reply_text(f"❌ Файл не найден для {name}")
        return
    code = open(p).read().strip()
    await query.message.reply_text(
        f"📤 Код для AmneziaVPN — {name}\n\nВставьте в приложении: + → Вставить ключ\n\n`{code}`",
        parse_mode="Markdown"
    )
    await query.message.reply_document(
        document=open(p, "rb"),
        filename=f"{name}.vpn",
        caption=f"📁 Файл .vpn для импорта в AmneziaVPN"
    )

# ── Статус сервера ─────────────────────────────────────────────────────────────
async def show_status(query):
    peers = get_awg_dump()
    now   = int(time.time())

    # Онлайн = handshake < 3 минут
    online = sum(1 for p in peers.values() if p.get("handshake") and now - p["handshake"] < 180)
    total  = len([p for p in peers.values() if p.get("allowed")])

    try:
        uptime = subprocess.check_output(["uptime", "-p"], text=True).strip()
    except:
        uptime = "—"

    mem   = subprocess.check_output(["free", "-m"], text=True).split("\n")[1].split()
    ram_used, ram_total = int(mem[2]), int(mem[1])
    ram_pct = int(ram_used / ram_total * 100)

    disk  = subprocess.check_output(["df", "-h", "/"], text=True).split("\n")[1].split()
    disk_used, disk_total, disk_pct = disk[2], disk[1], disk[4]

    load  = open("/proc/loadavg").read().split()[:3]
    cpu_cores = os.cpu_count() or 1

    try:
        cpu = subprocess.check_output(["top", "-bn1"], text=True)
        for line in cpu.split("\n"):
            if "Cpu" in line:
                idle = float(line.split("id")[0].split(",")[-1].strip().replace(",", "."))
                cpu_pct = f"{100 - idle:.1f}%"
                break
        else:
            cpu_pct = "—"
    except:
        cpu_pct = "—"

    # Суммарный трафик с перезагрузки
    total_rx = sum(p.get("rx", 0) for p in peers.values())
    total_tx = sum(p.get("tx", 0) for p in peers.values())

    text = (
        f"📊 Статус сервера\n\n"
        f"🟢 AWG: работает\n"
        f"🖥 IP: {SERVER_IP}:{SERVER_PORT}\n"
        f"⏱ Uptime: {uptime}\n\n"
        f"💻 CPU: {cpu_pct} | Ядер: {cpu_cores}\n"
        f"📈 Load: {load[0]} {load[1]} {load[2]}\n"
        f"💾 RAM: {ram_used}/{ram_total} MB ({ram_pct}%)\n"
        f"💿 Диск: {disk_used}/{disk_total} ({disk_pct})\n\n"
        f"👤 Клиентов: {len(get_clients())}\n"
        f"🟢 Онлайн: {online} / {total}\n"
        f"📶 Трафик (с перезагрузки): ↓{fmt_bytes(total_rx)} ↑{fmt_bytes(total_tx)}"
    )
    await query.edit_message_text(text, reply_markup=back_kb())

# ── Очистка мусора ─────────────────────────────────────────────────────────────
async def do_cleanup(query):
    peers = get_awg_dump()
    clients = get_clients()

    # Собираем известные публичные ключи
    known_pubs = set()
    for name in clients:
        pub = get_client_pub(name)
        if pub:
            known_pubs.add(pub)

    # Находим мусорные пиры — нет в known_pubs
    trash = [pub for pub in peers if pub not in known_pubs]

    if not trash:
        await query.edit_message_text("✅ Мусора нет — всё чисто!", reply_markup=back_kb())
        return

    removed = 0
    for pub in trash:
        result = subprocess.run(["awg", "set", AWG_IFACE, "peer", pub, "remove"])
        if result.returncode == 0:
            removed += 1

    await query.edit_message_text(
        f"🧹 Очистка завершена\n\nУдалено мусорных пиров: {removed}",
        reply_markup=back_kb()
    )

# ── Инструкция ────────────────────────────────────────────────────────────────
async def show_help(query):
    text = (
        "📋 Инструкция по подключению\n\n"
        "⚠️ Каждому устройству — свой профиль!\n"
        "Нельзя использовать один конфиг на нескольких устройствах — "
        "это вызовет конфликты и разрывы у всех.\n\n"
        "📝 Правило именования:\n"
        "Имя.Устройство через точку:\n"
        "• Lev.Phone — телефон Льва\n"
        "• Lev.PC — компьютер Льва\n"
        "• Artem.Telefon — телефон Артёма\n"
        "• Artem.Nout — ноутбук Артёма\n\n"
        "📲 Приложения:\n"
        "• AmneziaWG — простое подключение\n"
        "• AmneziaVPN — с раздельным туннелированием\n\n"
        "Для подключения обратитесь к администратору."
    )
    await query.edit_message_text(text, reply_markup=back_kb())

# ── Удаление ───────────────────────────────────────────────────────────────────
async def do_delete(query, name):
    if not os.path.exists(f"{CLIENTS_DIR}/{name}.conf"):
        await query.edit_message_text(f"❌ Клиент {name} не найден.", reply_markup=back_kb())
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_del_{name}")],
        [InlineKeyboardButton("❌ Отмена",      callback_data="delete")],
    ])
    await query.edit_message_text(
        f"🗑 Удаление клиента {name}\n\nХорошо подумал? Это действие необратимо.",
        reply_markup=kb
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
    new_lines, skip = [], False
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
    for ext in [".conf", ".vpn", ".vpnlink"]:
        p = f"{CLIENTS_DIR}/{name}{ext}"
        if os.path.exists(p):
            os.remove(p)
    await query.edit_message_text(f"✅ Клиент {name} удалён.", reply_markup=back_kb())

# ── Добавление клиента ─────────────────────────────────────────────────────────
async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    name = "".join(c for c in update.message.text.strip() if c.isalnum() or c in "_-.")
    if not name:
        await update.message.reply_text("❌ Имя пустое.")
        return ConversationHandler.END
    if os.path.exists(f"{CLIENTS_DIR}/{name}.conf"):
        await update.message.reply_text(f"❌ Клиент {name} уже существует.")
        return ConversationHandler.END

    priv = subprocess.check_output(["awg", "genkey"], text=True).strip()
    pub  = subprocess.check_output(["awg", "pubkey"], input=priv, text=True).strip()
    psk  = subprocess.check_output(["awg", "genpsk"], text=True).strip()
    ip   = f"{VPN_SUBNET}.{next_ip()}"
    obfs = gen_obfs()

    with open(AWG_CONF, "a") as f:
        f.write(f"\n# Client: {name}\n[Peer]\nPublicKey = {pub}\nPresharedKey = {psk}\nAllowedIPs = {ip}/32\n")
    subprocess.run(["awg", "set", AWG_IFACE, "peer", pub,
                    "preshared-key", "/dev/stdin", "allowed-ips", f"{ip}/32"],
                   input=psk, text=True)

    os.makedirs(CLIENTS_DIR, exist_ok=True)
    conf_path = f"{CLIENTS_DIR}/{name}.conf"
    vpn_file  = f"{CLIENTS_DIR}/{name}.vpn"

    with open(conf_path, "w") as f:
        f.write(make_wg_conf(priv, ip, psk, obfs))
    with open(vpn_file, "w") as f:
        f.write(make_vpn_link(priv, pub, ip, psk, obfs, name))

    await update.message.reply_document(
        document=open(conf_path, "rb"),
        filename=f"{name}.conf",
        caption=f"✅ Клиент {name} добавлен\n🌐 IP: {ip}"
    )
    qr_path = f"/tmp/{name}_qr.png"
    try:
        subprocess.run(["qrencode", "-o", qr_path, "-r", conf_path], check=True)
        await update.message.reply_photo(
            photo=open(qr_path, "rb"),
            caption=f"📱 QR для AmneziaWG\nКлиент: {name}"
        )
        os.remove(qr_path)
    except:
        pass

    await main_menu_msg(update.message)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END

# ── Запуск ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    async def add_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "✏️ Введите имя клиента\n\n"
            "Формат: Имя.Устройство\n"
            "Например: Lev.Phone, Artem.PC, Ivan.Nout\n\n"
            "Каждому устройству — свой профиль!"
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
    print(f"\n\033[0;32m✓ Бот запущен!\033[0m\n")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
