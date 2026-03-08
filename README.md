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
- Удалить клиента
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
