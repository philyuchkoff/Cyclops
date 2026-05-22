# 👁️ Cyclops - универсальный мониторинг интернета

**Cyclops** — это инструмент командной строки для мониторинга интернета. Он автоматически сканирует Telegram-каналы и RSS-ленты, находит новости по заданным ключевым словам и создает красивые HTML-отчеты.

## ✨ Возможности

- 🔍 **Поиск по ключевым словам** — находите любые темы: запреты, блокировки, новости ИИ, утечки данных и т.д.
- **Telegram интеграция** — читает публичные каналы (через Telethon)
- **RSS поддержка** — парсит любые RSS-ленты
- **Фильтр по дате** — только новости за последние N дней (по умолчанию 30)
- **Защита от дублей** — SQLite база для хешей, одинаковые новости не попадают в отчет
- **Красивые HTML-отчеты** — стильные карточки с сортировкой по дате
- **Гибкая настройка** — конфиги в JSON, переменные окружения, аргументы CLI

## Установка

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/philyuchkoff/cyclops.git
cd cyclops
```

### 2. Установите зависимости

```bash
pip install feedparser beautifulsoup4 telethon python-dateutil
```

### 3. (опционально) Настройте Telegram

Для работы с Telegram нужно получить API данные:

1. Перейдите на https://my.telegram.org/apps
2. Авторизуйтесь под своим аккаунтом
3. Создайте приложение (App title: "Cyclops или как хотите")
4. Скопируйте `api_id` и `api_hash`
5. Настройте переменные окружения:

```bash
export TG_API_ID=api_id
export TG_API_HASH=api_hash
export TG_PHONE=+79123456789
```

Или создайте файл `.env`:

```bash
TG_API_ID=api_id
TG_API_HASH=api_hash
TG_PHONE=+79123456789
```

## Как пользоваться

### Способ 1: через конфигуратор (рекомендуется)

Создайте конфиг с ключевыми словами:

```bash
# Простейший конфиг
python config.py запрет блокировка ограничение --name my_monitor

# С Telegram каналами
python config.py запрет блокировка --channels rian_ru,breakingmash --name monitor

# С RSS лентами
python config.py "искусственный интеллект" --rss "TechCrunch=https://techcrunch.com/feed" --name ai_news

# За последние 7 дней
python config.py запрет --days 7 --name short_monitor
```

### Запустите

```bash
python cyclops.py my_monitor.json
```

### Способ 2: без конфигуратора

```bash
python cyclops.py --keywords "запрет,блокировка" --channels "rian_ru,breakingmash" --rss "РИА=https://ria.ru/export/rss2/index.xml"
```

## config.py - создание конфигов

```bash
python config.py [ключевые_слова] [опции]
```

### Обязательные аргументы

`ключевые_слова` - слова или фразы для поиска (можно в кавычках)

### Опции

`--name`, `-n` - имя конфиг-файла (по умолчанию: `my_monitor`)

`--targets`, `-t` - цели поиска (по умолчанию: соцсети,telegram,youtube,интернет)

`--channels`, `-ch` - Telegram каналы через запятую (без `@`)

`--rss`, `-r` - RSS ленты в формате: `имя=url,имя2=url2`

`--days`, `-d` - количество дней назад (по умолчанию: 30)

`--limit`, `-l` - лимит сообщений на канал (по умолчанию: 50)

`--no-telegram` - отключить Telegram

`--no-rss` - отключить RSS

`--list` - показать все существующие конфиги

### Примеры

```bash
# Базовый конфиг
python config.py запрет блокировка --name my_config

# С фразами в кавычках
python config.py "искусственный интеллект" "data breach" --name security

# Полный конфиг
python config.py запрет ограничение \
  --channels rian_ru,breakingmash \
  --rss "РИА=https://ria.ru/export/rss2/index.xml,Лента=https://lenta.ru/rss" \
  --days 14 \
  --name full_monitor

# Только RSS
python config.py запрет --rss "Reuters=http://feeds.reuters.com/reuters/technologyNews" --no-telegram

# Список конфигов
python config.py --list
```

## cyclops.py - запуск

```bash
python cyclops.py [конфиг.json] [опции]
```

### Опции

`--config`, `-c` - путь к JSON конфигурации

`--keywords`, `-k` - переопределить ключевые слова

`--channels`, `-ch` - переопределить Telegram каналы

`--rss`, `-r` - переопределить RSS ленты

`--days`, `-d` - переопределить период

`--sources`, `-s` - какие источники использовать (telegram,rss)

`--output`, `-o` - имя выходного HTML файла

`--no-html` - не создавать HTML отчет

`--no-json` - не создавать JSON экспорт

`--clear-cache` - очистить кеш дублей

### Примеры

```bash
# С конфигом
python cyclops.py my_config.json

# Только RSS из конфига
python cyclops.py my_config.json --sources "rss"

# Переопределить ключевые слова
python cyclops.py my_config.json --keywords "запрет,блокировка,цензура"

# За последние 7 дней с очисткой кеша
python cyclops.py my_config.json --days 7 --clear-cache

# Без конфига, всё через CLI
python cyclops.py --keywords "запрет" --channels "rian_ru" --rss "РИА=https://ria.ru/export/rss2/index.xml"
```

## Возможные проблемы и решения

### Telegram не работает

Появляется ошибка `⚠️ Telegram не настроен`

1. Получите API данные на https://my.telegram.org/apps
2. Настройте переменные окружения или добавьте в конфиг
3. При первом запуске введите код из Telegram

### Не находит новости

Появляется ошибка `⚠️ Новых новостей не найдено`

- уменьшите `--days` (например, до 7)
- добавьте больше ключевых слов
- проверьте источники (они существуют?)
- уберите слишком специфичные слова

### Новости дублируются

Cyclops автоматически фильтрует дубли через SQLite. Если нужно начать сбор заново:

```bash
python cyclops.py my_config.json --clear-cache
```

### Получили FloodWait от Telegram

Telegram ограничивает частоту запросов. Скрипт автоматически ждет указанное время. Уменьшите количество каналов или увеличьте задержку между запросами.

## Примеры использования

### Мониторинг новостей об AI

```bash
python config.py "искусственный интеллект" "нейросети" "chatgpt" \
  --targets "закон,регуляция,ограничение" \
  --rss "TechCrunch=https://techcrunch.com/feed,Wired=https://www.wired.com/feed/rss" \
  --no-telegram \
  --name ai_news

python cyclops.py ai_news.json

```

### Ежедневный мониторинг (cron)

```bash
# Создайте скрипт daily.sh
#!/bin/bash
cd /path/to/cyclops
python cyclops.py my_config.json --days 1
```

Добавьте в crontab:

```bash
0 9 * * * /path/to/cyclops/daily.sh
```

## Используется

- [Telethon](https://github.com/LonamiWebs/Telethon) для работы с Telegram API
- [feedparser](https://github.com/kurtmckee/feedparser) для парсинга RSS
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) для очистки HTML