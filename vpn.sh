#!/bin/bash
# =============================================================================
# AmneziaWG — управление клиентами
# Запускать: bash vpn.sh
# =============================================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

AWG_CONF="/etc/amnezia/amneziawg/awg0.conf"
CLIENTS_DIR="/etc/amnezia/amneziawg/clients"
ENV_FILE="/etc/amnezia/amneziawg/server.env"

[[ $EUID -ne 0 ]] && echo -e "${RED}Запускать от root: sudo bash vpn.sh${NC}" && exit 1
[[ ! -f "$ENV_FILE" ]] && echo -e "${RED}Сначала запустите install.sh${NC}" && exit 1

source "$ENV_FILE"
mkdir -p "$CLIENTS_DIR"

next_ip() {
    local i=2
    while grep -q "AllowedIPs = ${VPN_SUBNET}.${i}/32" "$AWG_CONF" 2>/dev/null; do
        ((i++))
    done
    echo "$i"
}

show_header() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════════╗"
    echo "  ║      AmneziaWG — Управление      ║"
    echo "  ╚══════════════════════════════════╝"
    echo -e "${NC}"
}

show_qr() {
    local CONF="$CLIENTS_DIR/$1.conf"
    if command -v qrencode &>/dev/null; then
        echo -e "${CYAN}QR-код:${NC}"
        echo ""
        qrencode -t ansiutf8 -l L < "$CONF"
        echo ""
    fi
}

# --- Добавить клиента ---
add_client() {
    show_header
    echo -e "${BOLD}Добавление клиента${NC}"
    echo ""
    read -p "Имя клиента (только латиница): " NAME

    NAME=$(echo "$NAME" | tr -d '\r\xef\xbb\xbf' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//' | tr -cd '[:alnum:]_-')

    [[ -z "$NAME" ]] && echo -e "${RED}Имя пустое. Используйте только латиницу, цифры, _ или -.${NC}" && sleep 3 && return
    [[ -f "$CLIENTS_DIR/${NAME}.conf" ]] && echo -e "${RED}Клиент '$NAME' уже существует${NC}" && sleep 2 && return

    CLIENT_PRIVATE=$(awg genkey)
    CLIENT_PUBLIC=$(echo "$CLIENT_PRIVATE" | awg pubkey)
    CLIENT_IP="${VPN_SUBNET}.$(next_ip)"

    printf "\n# Client: %s\n[Peer]\nPublicKey = %s\nAllowedIPs = %s/32\n" \
        "$NAME" "$CLIENT_PUBLIC" "$CLIENT_IP" >> "$AWG_CONF"

    awg set "$VPN_IFACE" peer "$CLIENT_PUBLIC" allowed-ips "${CLIENT_IP}/32"

    {
        printf "[Interface]\n"
        printf "PrivateKey = %s\n" "$CLIENT_PRIVATE"
        printf "Address = %s/32\n" "$CLIENT_IP"
        printf "DNS = 1.1.1.1\n"
        printf "Jc = 4\nJmin = 40\nJmax = 70\n"
        printf "S1 = 0\nS2 = 0\n"
        printf "H1 = 1\nH2 = 2\nH3 = 3\nH4 = 4\n"
        printf "\n[Peer]\n"
        printf "PublicKey = %s\n" "$SERVER_PUBLIC"
        printf "Endpoint = %s:%s\n" "$SERVER_IP" "$SERVER_PORT"
        printf "AllowedIPs = 0.0.0.0/0\n"
        printf "PersistentKeepalive = 25\n"
    } > "$CLIENTS_DIR/${NAME}.conf"

    echo ""
    echo -e "${GREEN}✓ Клиент '${NAME}' добавлен — IP: ${CLIENT_IP}${NC}"
    echo ""
    show_qr "$NAME"
    echo -e "${CYAN}Конфиг:${NC} ${CLIENTS_DIR}/${NAME}.conf"
    echo ""
    echo "Скачать на Windows (выполнить в cmd локально):"
    echo -e "${YELLOW}  scp root@${SERVER_IP}:${CLIENTS_DIR}/${NAME}.conf .\\${NAME}.conf${NC}"
    echo ""
    read -p "Показать текст конфига? (y/N): " SHOW
    if [[ "$SHOW" == "y" || "$SHOW" == "Y" ]]; then
        echo ""
        echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━${NC}"
        cat "$CLIENTS_DIR/${NAME}.conf"
        echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
    fi
    read -p "Нажмите Enter..."
}

# --- Список клиентов ---
list_clients() {
    show_header
    echo -e "${BOLD}Список клиентов${NC}"
    echo ""

    AWG_OUTPUT=$(awg show "$VPN_IFACE" 2>/dev/null)

    if [[ -z $(ls "$CLIENTS_DIR"/*.conf 2>/dev/null) ]]; then
        echo -e "${YELLOW}Клиентов нет. Добавьте первого через меню.${NC}"
        echo ""
        read -p "Нажмите Enter..."
        return
    fi

    printf "  %-4s %-20s %-16s %-22s %s\n" "N" "ИМЯ" "IP" "ПОСЛЕДНЕЕ СОЕДИНЕНИЕ" "ТРАФИК"
    echo "  ──────────────────────────────────────────────────────────────────────"

    local i=1
    local NAMES=()
    for CONF in "$CLIENTS_DIR"/*.conf; do
        NAME=$(basename "$CONF" .conf)
        CLIENT_IP=$(grep "^Address" "$CONF" | awk '{print $3}' | cut -d'/' -f1)
        CLIENT_PUBLIC=$(grep "^PublicKey" "$CONF" | awk '{print $3}')

        HANDSHAKE=$(echo "$AWG_OUTPUT" | grep -A5 "$CLIENT_PUBLIC" | grep "latest handshake" | sed 's/.*latest handshake: //' || true)
        TRANSFER=$(echo "$AWG_OUTPUT" | grep -A5 "$CLIENT_PUBLIC" | grep "transfer" | sed 's/.*transfer: //' || true)

        [[ -z "$HANDSHAKE" ]] && HANDSHAKE="никогда"
        [[ -z "$TRANSFER" ]] && TRANSFER="—"

        printf "  %-4s %-20s %-16s %-22s %s\n" "$i)" "$NAME" "$CLIENT_IP" "$HANDSHAKE" "$TRANSFER"
        NAMES+=("$NAME")
        ((i++))
    done

    echo ""
    read -p "Открыть клиента (введите номер) или Enter для выхода: " NUM
    [[ -z "$NUM" ]] && return
    [[ "$NUM" -lt 1 || "$NUM" -gt "${#NAMES[@]}" ]] 2>/dev/null && return

    NAME="${NAMES[$((NUM-1))]}"

    while true; do
        show_header
        echo -e "${BOLD}Клиент: ${CYAN}${NAME}${NC}"
        echo ""
        echo "  1) Показать QR-код"
        echo "  2) Показать текст конфига"
        echo "  3) Команда для скачивания"
        echo "  0) Назад"
        echo ""
        read -p "  Выбор: " ACTION
        case $ACTION in
            1)
                echo ""
                show_qr "$NAME"
                read -p "Нажмите Enter..."
                ;;
            2)
                echo ""
                echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━${NC}"
                cat "$CLIENTS_DIR/${NAME}.conf"
                echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━${NC}"
                echo ""
                read -p "Нажмите Enter..."
                ;;
            3)
                echo ""
                echo "Windows (cmd):"
                echo -e "${YELLOW}  scp root@${SERVER_IP}:${CLIENTS_DIR}/${NAME}.conf .\\${NAME}.conf${NC}"
                echo ""
                echo "Linux/Mac:"
                echo -e "${YELLOW}  scp root@${SERVER_IP}:${CLIENTS_DIR}/${NAME}.conf ./${NAME}.conf${NC}"
                echo ""
                read -p "Нажмите Enter..."
                ;;
            0) return ;;
        esac
    done
}

# --- Удалить клиента ---
delete_client() {
    show_header
    echo -e "${BOLD}Удаление клиента${NC}"
    echo ""

    if [[ -z $(ls "$CLIENTS_DIR"/*.conf 2>/dev/null) ]]; then
        echo -e "${YELLOW}Клиентов нет.${NC}"
        sleep 2; return
    fi

    echo "Текущие клиенты:"
    local i=1
    local NAMES=()
    for CONF in "$CLIENTS_DIR"/*.conf; do
        NAME=$(basename "$CONF" .conf)
        IP=$(grep "^Address" "$CONF" | awk '{print $3}')
        echo "  $i) $NAME ($IP)"
        NAMES+=("$NAME")
        ((i++))
    done

    echo ""
    read -p "Номер клиента для удаления (0 — отмена): " NUM

    [[ "$NUM" == "0" || -z "$NUM" ]] && return
    [[ "$NUM" -lt 1 || "$NUM" -gt "${#NAMES[@]}" ]] && echo -e "${RED}Неверный номер${NC}" && sleep 2 && return

    NAME="${NAMES[$((NUM-1))]}"
    CONF="$CLIENTS_DIR/${NAME}.conf"
    CLIENT_PUBLIC=$(grep "^PublicKey" "$CONF" | awk '{print $3}')

    echo ""
    read -p "Удалить '$NAME'? (y/N): " CONFIRM
    [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]] && return

    awg set "$VPN_IFACE" peer "$CLIENT_PUBLIC" remove

    python3 - "$AWG_CONF" "$NAME" << 'PYEOF'
import sys
conf_path, name = sys.argv[1], sys.argv[2]
with open(conf_path, 'r') as f:
    content = f.read()
lines = content.split('\n')
new_lines = []
skip = False
for line in lines:
    if line.strip() == f'# Client: {name}':
        skip = True
    elif skip and line.strip().startswith('[') and line.strip() != '[Peer]':
        skip = False
        new_lines.append(line)
    elif not skip:
        new_lines.append(line)
with open(conf_path, 'w') as f:
    f.write('\n'.join(new_lines))
PYEOF

    rm -f "$CLIENTS_DIR/${NAME}.conf"
    echo -e "${GREEN}✓ Клиент '$NAME' удалён${NC}"
    sleep 2
}

# --- Статус сервера ---
show_status() {
    show_header
    echo -e "${BOLD}Статус сервера${NC}"
    echo ""

    if awg show "$VPN_IFACE" > /dev/null 2>&1; then
        echo -e "  AWG интерфейс:  ${GREEN}● работает${NC}"
    else
        echo -e "  AWG интерфейс:  ${RED}● остановлен${NC}"
    fi

    UPTIME=$(uptime -p 2>/dev/null || uptime)
    echo -e "  Сервер uptime:  ${CYAN}${UPTIME}${NC}"
    CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d. -f1)
    echo -e "  CPU:            ${CYAN}${CPU}%${NC}"
    RAM=$(free -m | awk 'NR==2{printf "%s MB / %s MB (%.0f%%)", $3, $2, $3*100/$2}')
    echo -e "  RAM:            ${CYAN}${RAM}${NC}"
    CLIENTS=$(ls "$CLIENTS_DIR"/*.conf 2>/dev/null | wc -l)
    echo -e "  Клиентов:       ${CYAN}${CLIENTS}${NC}"
    echo ""
    echo -e "${BOLD}awg show:${NC}"
    awg show "$VPN_IFACE" 2>/dev/null
    echo ""
    read -p "Нажмите Enter..."
}

# --- Главное меню ---
main_menu() {
    while true; do
        show_header
        CLIENTS_COUNT=$(ls "$CLIENTS_DIR"/*.conf 2>/dev/null | wc -l)
        echo -e "  IP сервера: ${CYAN}${SERVER_IP}:${SERVER_PORT}${NC}  |  Клиентов: ${CYAN}${CLIENTS_COUNT}${NC}"
        echo ""
        echo "  1) Добавить клиента"
        echo "  2) Список клиентов"
        echo "  3) Удалить клиента"
        echo "  4) Статус сервера"
        echo "  0) Выход"
        echo ""
        read -p "  Выбор: " CHOICE

        case $CHOICE in
            1) add_client ;;
            2) list_clients ;;
            3) delete_client ;;
            4) show_status ;;
            0) echo ""; exit 0 ;;
            *) echo -e "${RED}Неверный выбор${NC}"; sleep 1 ;;
        esac
    done
}

main_menu
