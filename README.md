# Vpn_AWG — AmneziaWG + Telegram Bot

AmneziaWG нативно в kernelspace (300+ мбит) с управлением через Telegram бота.

## Особенности

- **AWG нативно** — модуль ядра, не userspace/Go, полная скорость
- **Обфускация** — не детектируется РКН/DPI
- **Telegram бот** — добавление клиентов, список, удаление, статус
- **Терминальное меню** — управление через vpn.sh
- **Автозапуск** — AWG и бот стартуют при перезагрузке сервера

## Требования

- Ubuntu 22.04
- VPS с root доступом
- Telegram бот (получить у @BotFather)

## Установка

```bash
bash <(curl -s https://raw.githubusercontent.com/yntoolsmail-prog/Vpn_AWG/main/setup.sh)
```

Установщик сам:
1. Установит AmneziaWG (модуль ядра)
2. Настроит сетевой интерфейс
3. Установит Telegram бота
4. Настроит автозапуск

## Управление

**Через Telegram бот** — напишите `/start` вашему боту:
- Добавить клиента → получить .conf файл
- Список клиентов с трафиком
- Удалить клиента (с подтверждением)
- Статус сервера

**Через терминал:**
```bash
bash /root/vpn.sh
```

**Управление ботом:**
```bash
systemctl status awg-bot   # статус
systemctl restart awg-bot  # перезапуск
journalctl -u awg-bot -f   # логи
```

## Клиент

Используйте [AmneziaVPN](https://amnezia.org) — поддерживает AWG и раздельное туннелирование.

---

<details>
<summary>🔄 Автообновление с GitHub</summary>

### Как это работает

Скрипт `update.sh` каждые 5 минут проверяет последний коммит на GitHub. Если появился новый — скачивает обновлённые файлы и перезапускает бота автоматически.

### Установка

Выполните на сервере:

```bash
cat > /root/update.sh << 'SCRIPT'
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
SCRIPT
chmod +x /root/update.sh
(crontab -l 2>/dev/null; echo "*/5 * * * * /root/update.sh") | crontab -
```

### Запуск вручную

```bash
bash /root/update.sh
```

### Проверить лог обновлений

```bash
cat /var/log/awg-update.log
```

### Отключить автообновление

```bash
crontab -e
# удалите строку с update.sh
```

</details>
