#!/bin/bash
# =============================================================================
# AmneziaWG + Telegram Bot — Установщик
# Использование: bash <(curl -s https://raw.githubusercontent.com/yntoolsmail-prog/Vpn_AWG/main/setup.sh)
# =============================================================================

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info() { echo -e "${CYAN}[i]${NC} $1"; }

[[ $EUID -ne 0 ]] && err "Запускать от root: sudo bash <(curl -s https://raw.githubusercontent.com/yntoolsmail-prog/Vpn_AWG/main/setup.sh)"

clear
echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   AmneziaWG + Telegram Bot — Установка  ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ── Шаг 1: Зависимости ────────────────────────────────────────────────────────
log "Установка зависимостей..."
apt-get update -qq
apt-get install -y -qq curl wget software-properties-common resolvconf qrencode python3 python3-pip

# ── Шаг 2: AmneziaWG ──────────────────────────────────────────────────────────
log "Добавление PPA Amnezia..."
add-apt-repository -y ppa:amnezia/ppa > /dev/null 2>&1
apt-get update -qq

log "Установка AmneziaWG (компиляция ~3-5 мин)..."
apt-get install -y amneziawg amneziawg-tools

log "Загрузка модуля ядра..."
modprobe amneziawg || err "Не удалось загрузить модуль ядра"
echo "amneziawg" > /etc/modules-load.d/amneziawg.conf

# ── Шаг 3: Параметры сервера ──────────────────────────────────────────────────
echo ""
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s api.ipify.org)
IFACE=$(ip route | grep default | awk '{print $5}' | head -1)
info "Внешний IP: $SERVER_IP"
info "Интерфейс:  $IFACE"
echo ""
read -p "  Порт AWG [51820]: " AWG_PORT
AWG_PORT=${AWG_PORT:-51820}

# ── Шаг 4: Ключи сервера ──────────────────────────────────────────────────────
log "Генерация ключей сервера..."
mkdir -p /etc/amnezia/amneziawg/clients
chmod 700 /etc/amnezia/amneziawg
awg genkey | tee /etc/amnezia/amneziawg/server_private.key | awg pubkey > /etc/amnezia/amneziawg/server_public.key
chmod 600 /etc/amnezia/amneziawg/server_private.key
SERVER_PRIVATE=$(cat /etc/amnezia/amneziawg/server_private.key)
SERVER_PUBLIC=$(cat /etc/amnezia/amneziawg/server_public.key)

# ── Шаг 5: Генерация параметров обфускации ───────────────────────────────────
log "Генерация случайных параметров обфускации..."
read JC JMIN JMAX S1 S2 H1 H2 H3 H4 < <(python3 -c "
import random
print(
    random.randint(3,10),
    random.randint(10,50),
    random.randint(51,100),
    random.randint(20,100),
    random.randint(20,100),
    random.randint(100000000,2000000000),
    random.randint(100000000,2000000000),
    random.randint(100000000,2000000000),
    random.randint(100000000,2000000000),
)")
info "Jc=$JC Jmin=$JMIN Jmax=$JMAX S1=$S1 S2=$S2"

# ── Шаг 6: Конфиг AWG ────────────────────────────────────────────────────────
log "Создание конфига интерфейса..."
{
    printf "[Interface]\n"
    printf "PrivateKey = %s\n" "$SERVER_PRIVATE"
    printf "Address = 10.8.0.1/24\n"
    printf "ListenPort = %s\n" "$AWG_PORT"
    printf "DNS = 1.1.1.1\n"
    printf "Jc = %s\nJmin = %s\nJmax = %s\n" "$JC" "$JMIN" "$JMAX"
    printf "S1 = %s\nS2 = %s\n" "$S1" "$S2"
    printf "H1 = %s\nH2 = %s\nH3 = %s\nH4 = %s\n" "$H1" "$H2" "$H3" "$H4"
    printf "\n"
    printf "PostUp = iptables -A FORWARD -i awg0 -j ACCEPT; iptables -A FORWARD -o awg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o %s -j MASQUERADE\n" "$IFACE"
    printf "PostDown = iptables -D FORWARD -i awg0 -j ACCEPT; iptables -D FORWARD -o awg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o %s -j MASQUERADE\n" "$IFACE"
} > /etc/amnezia/amneziawg/awg0.conf
chmod 600 /etc/amnezia/amneziawg/awg0.conf

# ── Шаг 7: IP форвардинг и запуск ────────────────────────────────────────────
log "IP форвардинг..."
grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p > /dev/null

log "Запуск AWG интерфейса..."
awg-quick up /etc/amnezia/amneziawg/awg0.conf

log "Автозапуск AWG..."
cat > /etc/systemd/system/awg-quick@.service << 'EOF'
[Unit]
Description=AmneziaWG via awg-quick(8) for %I
After=network-online.target nss-lookup.target
Wants=network-online.target nss-lookup.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/awg-quick up /etc/amnezia/amneziawg/%i.conf
ExecStop=/usr/bin/awg-quick down /etc/amnezia/amneziawg/%i.conf

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable awg-quick@awg0

# ── Шаг 8: Сохраняем server.env ──────────────────────────────────────────────
printf "SERVER_IP=%s\nSERVER_PORT=%s\nSERVER_PUBLIC=%s\nVPN_IFACE=awg0\nVPN_SUBNET=10.8.0\nJC=%s\nJMIN=%s\nJMAX=%s\nS1=%s\nS2=%s\nH1=%s\nH2=%s\nH3=%s\nH4=%s\n"     "$SERVER_IP" "$AWG_PORT" "$SERVER_PUBLIC"     "$JC" "$JMIN" "$JMAX" "$S1" "$S2" "$H1" "$H2" "$H3" "$H4"     > /etc/amnezia/amneziawg/server.env

# ── Шаг 9: Скачиваем скрипты ─────────────────────────────────────────────────
log "Загрузка скриптов управления..."
curl -s https://raw.githubusercontent.com/yntoolsmail-prog/Vpn_AWG/main/vpn.sh -o /root/vpn.sh
curl -s https://raw.githubusercontent.com/yntoolsmail-prog/Vpn_AWG/main/bot.py  -o /root/bot.py
chmod +x /root/vpn.sh

# ── Шаг 10: Python зависимости ───────────────────────────────────────────────
log "Установка python-telegram-bot..."
pip3 install python-telegram-bot 2>/dev/null || pip3 install python-telegram-bot --break-system-packages 2>/dev/null

# ── Шаг 11: Настройка бота ───────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}Настройка Telegram бота${NC}"
echo ""
echo -e "  1. Найдите ${YELLOW}@BotFather${NC} в Telegram"
echo -e "  2. Напишите ${YELLOW}/newbot${NC} и следуйте инструкциям"
echo -e "  3. Скопируйте токен вида ${YELLOW}1234567890:AAF...${NC}"
echo ""
while true; do
    read -p "  Вставьте токен бота: " BOT_TOKEN
    [[ "$BOT_TOKEN" == *":"* && ${#BOT_TOKEN} -gt 20 ]] && break
    warn "Неверный формат токена."
done
echo ""
echo -e "  1. Найдите ${YELLOW}@userinfobot${NC} в Telegram"
echo -e "  2. Напишите ему любое сообщение"
echo -e "  3. Скопируйте ваш ID — число"
echo ""
while true; do
    read -p "  Вставьте ваш Telegram ID: " ADMIN_ID
    [[ "$ADMIN_ID" =~ ^[0-9]+$ ]] && break
    warn "ID должен быть числом."
done

printf "BOT_TOKEN=%s\nADMIN_ID=%s\n" "$BOT_TOKEN" "$ADMIN_ID" > /etc/amnezia/amneziawg/bot.env
chmod 600 /etc/amnezia/amneziawg/bot.env

# ── Шаг 12: systemd сервис для бота ──────────────────────────────────────────
log "Настройка автозапуска бота..."
cat > /etc/systemd/system/awg-bot.service << 'EOF'
[Unit]
Description=AmneziaWG Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /root/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable awg-bot
systemctl start awg-bot

# ── Шаг 13: Автообновление ───────────────────────────────────────────────────
log "Настройка автообновления..."
cat > /root/update.sh << 'EOF'
#!/bin/bash
RAW="https://raw.githubusercontent.com/yntoolsmail-prog/Vpn_AWG/main"
CURRENT=$(cat /root/.bot_version 2>/dev/null || echo "none")
LATEST=$(curl -s "https://api.github.com/repos/yntoolsmail-prog/Vpn_AWG/commits/main" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'][:7])")
if [ "$CURRENT" != "$LATEST" ]; then
    curl -s $RAW/bot.py -o /root/bot.py
    curl -s $RAW/vpn.sh -o /root/vpn.sh
    echo $LATEST > /root/.bot_version
    systemctl restart awg-bot
    echo "$(date) — обновлено до $LATEST" >> /var/log/awg-update.log
fi
EOF
chmod +x /root/update.sh
(crontab -l 2>/dev/null; echo "*/5 * * * * /root/update.sh") | crontab -

# ── Готово ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}   Установка завершена!${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${NC}"
echo ""
info "AWG запущен с параметрами: Jc=$JC Jmin=$JMIN Jmax=$JMAX"
info "Бот: systemctl status awg-bot"
echo ""
echo -e "  Терминал: ${CYAN}bash /root/vpn.sh${NC}"
echo -e "  Telegram: ${CYAN}напишите /start вашему боту${NC}"
echo -e "  Логи:     ${YELLOW}journalctl -u awg-bot -f${NC}"
echo ""
