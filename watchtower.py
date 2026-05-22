#!/usr/bin/env python3
"""
watchtower.py - Универсальный мониторинг интернета

Мониторит Telegram каналы и RSS ленты на наличие ключевых слов.
Поддерживает конфигурационные файлы и параметры командной строки.
Автоматически фильтрует дубли и ограничивает период последними N днями.

Использование:
    python watchtower.py --config config.json
    python watchtower.py --keywords "запрет,блокировка" --sources "telegram,rss"
    python watchtower.py --topic "censorship" --channels "rian_ru,breakingmash"
"""

import feedparser
import re
import asyncio
import os
import json
import argparse
import sys
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from telethon import TelegramClient, errors

def check_telegram_config(config: Dict) -> Dict:
    """Проверяет и дополняет конфиг данными Telegram из переменных окружения"""
    if 'telegram' not in config:
        config['telegram'] = {}
    
    # Если в конфиге нет api_id, берем из окружения
    if not config['telegram'].get('api_id') or config['telegram']['api_id'] == 0:
        config['telegram']['api_id'] = int(os.environ.get("TG_API_ID", 0))
    
    if not config['telegram'].get('api_hash') or config['telegram']['api_hash'] == '':
        config['telegram']['api_hash'] = os.environ.get("TG_API_HASH", "")
    
    if not config['telegram'].get('phone') or config['telegram']['phone'] == '':
        config['telegram']['phone'] = os.environ.get("TG_PHONE", "")
    
    return config

# ========== КОНФИГУРАЦИЯ ПО УМОЛЧАНИЮ ==========

DEFAULT_CONFIG = {
    "name": "watchtower",
    "keywords": [],
    "targets": [],
    "time_filter": {
        "days_back": 30,
        "enabled": True
    },
    "sources": {
        "telegram_channels": [],
        "rss_feeds": {},
        "use_google_news": False
    },
    "telegram": {
        "api_id": int(os.environ.get("TG_API_ID", 0)),
        "api_hash": os.environ.get("TG_API_HASH", ""),
        "phone": os.environ.get("TG_PHONE", ""),
        "message_limit": 50
    },
    "output": {
        "html_report": True,
        "json_export": False,
        "output_dir": "reports"
    },
    "filters": {
        "min_text_length": 20,
        "exclude_spam": True,
        "case_sensitive": False
    }
}

# ========== ПРЕДУСТАНОВЛЕННЫЕ ТЕМЫ ==========

TOPICS = {
    "censorship": {
        "keywords": ["запрет", "блокировка", "цензура", "ограничение", "ban", "block", "censor"],
        "targets": ["интернет", "соцсети", "telegram", "youtube", "internet", "social media"]
    },
    "privacy": {
        "keywords": ["утечка", "данные", "конфиденциальность", "privacy", "data breach", "leak"],
        "targets": ["пользователи", "клиенты", "users", "personal data"]
    },
    "ai_regulation": {
        "keywords": ["искусственный интеллект", "ai", "regulation", "закон", "restrict"],
        "targets": ["chatgpt", "нейросети", "algorithms", "automation"]
    },
    "tech_news": {
        "keywords": ["запуск", "релиз", "обновление", "launch", "release", "update"],
        "targets": ["app", "платформа", "сервис", "service", "platform"]
    }
}

# ========== БАЗА ДАННЫХ ДЛЯ ДУБЛЕЙ ==========

class DuplicateChecker:
    """Проверка дублей с помощью SQLite"""
    
    def __init__(self, db_path: str = "watchtower_cache.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Создает таблицу для хранения хешей новостей"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT UNIQUE,
                    title TEXT,
                    source TEXT,
                    first_seen TIMESTAMP,
                    last_seen TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_hash ON seen_news(content_hash)
            """)
    
    def _get_content_hash(self, title: str, source: str) -> str:
        """Создает уникальный хеш новости (по заголовку + источнику)"""
        content = f"{title}_{source}".lower()
        # Убираем лишние пробелы и знаки препинания
        content = re.sub(r'[^\w\s]', '', content)
        content = re.sub(r'\s+', ' ', content).strip()
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def is_duplicate(self, title: str, source: str) -> bool:
        """Проверяет, не видели ли мы уже эту новость"""
        content_hash = self._get_content_hash(title, source)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM seen_news WHERE content_hash = ?",
                (content_hash,)
            )
            exists = cursor.fetchone() is not None
            
            # Обновляем время последнего просмотра
            if exists:
                conn.execute(
                    "UPDATE seen_news SET last_seen = ? WHERE content_hash = ?",
                    (datetime.now().isoformat(), content_hash)
                )
            else:
                conn.execute(
                    """INSERT INTO seen_news (content_hash, title, source, first_seen, last_seen)
                       VALUES (?, ?, ?, ?, ?)""",
                    (content_hash, title[:200], source, 
                     datetime.now().isoformat(), datetime.now().isoformat())
                )
        
        return exists
    
    def clear_old(self, days: int = 30):
        """Очищает записи старше N дней (освобождает место)"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM seen_news WHERE first_seen < ?",
                (cutoff,)
            ).rowcount
            if deleted:
                print(f"🧹 Очищено {deleted} старых записей из кеша")

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def load_config(config_path: str) -> Dict:
    """Загружает конфигурацию из JSON файла"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        print(f"✅ Загружена конфигурация: {config_path}")
        return config
    except FileNotFoundError:
        print(f"⚠️ Файл {config_path} не найден, использую стандартную конфигурацию")
        return DEFAULT_CONFIG.copy()
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка в JSON: {e}")
        sys.exit(1)

def parse_cli_args():
    """Парсит аргументы командной строки"""
    parser = argparse.ArgumentParser(
        description='Watchtower - Универсальный мониторинг интернета',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  %(prog)s --config my_monitor.json
  %(prog)s --keywords "запрет,блокировка" --channels "rian_ru,breakingmash"
  %(prog)s --topic "censorship" --rss "РИА=https://ria.ru/export/rss2/index.xml"
  %(prog)s --keywords "data breach" --sources "rss" --output report.html
        """
    )
    
    parser.add_argument('--config', '-c', type=str, help='Путь к JSON конфигурации')
    parser.add_argument('--keywords', '-k', type=str, help='Ключевые слова через запятую')
    parser.add_argument('--targets', '-t', type=str, help='Цели поиска через запятую')
    parser.add_argument('--channels', '-ch', type=str, help='Telegram каналы через запятую')
    parser.add_argument('--rss', '-r', type=str, help='RSS ленты (формат: имя=url,имя2=url2)')
    parser.add_argument('--topic', '-tp', type=str, help='Готовая тема (censorship, privacy, ai_regulation, tech_news)')
    parser.add_argument('--sources', '-s', type=str, help='Типы источников через запятую (telegram,rss)')
    parser.add_argument('--output', '-o', type=str, help='Имя выходного HTML файла')
    parser.add_argument('--days', '-d', type=int, help='Сколько дней назад искать (по умолчанию 30)')
    parser.add_argument('--limit', '-l', type=int, help='Лимит сообщений на канал')
    parser.add_argument('--no-html', action='store_true', help='Не создавать HTML отчет')
    parser.add_argument('--no-json', action='store_true', help='Не создавать JSON экспорт')
    parser.add_argument('--clear-cache', action='store_true', help='Очистить кеш дублей')
    
    return parser.parse_args()

def merge_config(base: Dict, cli_args, topic_keywords: Dict = None) -> Dict:
    """Объединяет конфиг с аргументами командной строки"""
    config = base.copy()
    
    # Обработка предустановленных тем
    if cli_args.topic and topic_keywords:
        topic = cli_args.topic.lower()
        if topic in topic_keywords:
            topic_data = topic_keywords[topic]
            config['keywords'] = topic_data.get('keywords', [])
            config['targets'] = topic_data.get('targets', [])
            print(f"📌 Тема '{topic}': {', '.join(config['keywords'][:5])}...")
    
    # CLI аргументы имеют приоритет
    if cli_args.keywords:
        config['keywords'] = [k.strip() for k in cli_args.keywords.split(',')]
    
    if cli_args.targets:
        config['targets'] = [t.strip() for t in cli_args.targets.split(',')]
    
    if cli_args.channels:
        config['sources']['telegram_channels'] = [ch.strip() for ch in cli_args.channels.split(',')]
    
    if cli_args.rss:
        rss_dict = {}
        for item in cli_args.rss.split(','):
            if '=' in item:
                name, url = item.split('=', 1)
                rss_dict[name.strip()] = url.strip()
        config['sources']['rss_feeds'] = rss_dict
    
    if cli_args.limit:
        config['telegram']['message_limit'] = cli_args.limit
    
    if cli_args.days:
        if 'time_filter' not in config:
            config['time_filter'] = {}
        config['time_filter']['days_back'] = cli_args.days
    
    # Если нет ни ключевых слов, ни целей, используем дефолтные
    if not config.get('keywords') and not config.get('targets'):
        config['keywords'] = ["запрет", "блокировка", "ограничение"]
        config['targets'] = ["интернет", "соцсети", "telegram"]
        print("⚠️ Не заданы ключевые слова, используются дефолтные")
    
    return config

def is_relevant(text: str, keywords: List[str], targets: List[str], case_sensitive: bool = False, min_length: int = 20) -> bool:
    """Проверяет текст на релевантность"""
    if not text or len(text) < min_length:
        return False
    
    if case_sensitive:
        text_check = text
        keywords = [k for k in keywords]
        targets = [t for t in targets]
    else:
        text_check = text.lower()
        keywords = [k.lower() for k in keywords]
        targets = [t.lower() for t in targets]
    
    # Проверяем ключевые слова
    has_keyword = any(kw in text_check for kw in keywords) if keywords else True
    
    # Проверяем цели
    has_target = any(tgt in text_check for tgt in targets) if targets else True
    
    return has_keyword and has_target

# ========== TELEGRAM МОДУЛЬ ==========

async def init_telegram_client(api_id: int, api_hash: str, phone: str) -> Optional[TelegramClient]:
    """Инициализирует Telegram клиент"""
    if not api_id or not api_hash or not phone:
        return None
    
    session_dir = Path("telegram_sessions")
    session_dir.mkdir(exist_ok=True)
    session_path = session_dir / "watchtower"
    
    client = TelegramClient(str(session_path), api_id, api_hash)
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            print("\n📱 Первая авторизация в Telegram...")
            await client.send_code_request(phone)
            code = input("Введите код из Telegram: ")
            
            try:
                await client.sign_in(phone, code)
            except errors.SessionPasswordNeededError:
                password = input("Введите пароль 2FA: ")
                await client.sign_in(password=password)
        
        print("✅ Telegram авторизован")
        return client
        
    except Exception as e:
        print(f"❌ Ошибка Telegram: {e}")
        return None

async def parse_telegram_channel(client: TelegramClient, channel: str, keywords: List[str], 
                                  targets: List[str], limit: int, case_sensitive: bool, 
                                  days_back: int = 30, min_length: int = 20) -> List[Dict]:
    """Парсит Telegram канал с фильтром по дате"""
    news = []
    cutoff_date = datetime.now() - timedelta(days=days_back)
    
    try:
        entity = await client.get_entity(channel)
        print(f"  📡 {channel}...")
        
        async for message in client.iter_messages(entity, limit=limit):
            if not message.text:
                continue
            
            # Проверяем дату сообщения
            msg_date = message.date.replace(tzinfo=None)
            if msg_date < cutoff_date:
                # Сообщения старые, можно прекратить (Telegram возвращает в порядке убывания)
                break
            
            if is_relevant(message.text, keywords, targets, case_sensitive, min_length):
                news.append({
                    "title": message.text[:200].replace('\n', ' '),
                    "link": f"https://t.me/{channel}/{message.id}",
                    "source": f"tg://{channel}",
                    "date": msg_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "snippet": message.text[:400].replace('\n', ' '),
                    "type": "telegram",
                    "views": getattr(message, 'views', 0)
                })
        
        print(f"    Найдено: {len(news)} (за {days_back} дней)")
        
    except errors.FloodWaitError as e:
        print(f"    ⏳ FloodWait: ждем {e.seconds} сек")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"    ❌ Ошибка: {e}")
    
    return news

async def parse_all_telegram(config: Dict, duplicate_checker: DuplicateChecker) -> List[Dict]:
    """Парсит все Telegram каналы с проверкой дублей"""
    channels = config['sources'].get('telegram_channels', [])
    if not channels:
        return []
    
    tg_config = config['telegram']
    if not tg_config.get('api_id'):
        print("⚠️ Telegram не настроен (нужен api_id, api_hash, phone)")
        return []
    
    client = await init_telegram_client(
        tg_config['api_id'], 
        tg_config['api_hash'], 
        tg_config['phone']
    )
    
    if not client:
        return []
    
    all_news = []
    days_back = config.get('time_filter', {}).get('days_back', 30)
    min_length = config['filters'].get('min_text_length', 20)
    
    try:
        for channel in channels:
            news = await parse_telegram_channel(
                client, channel,
                config['keywords'],
                config['targets'],
                tg_config.get('message_limit', 50),
                config['filters'].get('case_sensitive', False),
                days_back,
                min_length
            )
            
            # Фильтруем дубли
            unique_news = []
            for item in news:
                if not duplicate_checker.is_duplicate(item['title'], item['source']):
                    unique_news.append(item)
            
            if len(news) != len(unique_news):
                print(f"    🚫 Отфильтровано дублей: {len(news) - len(unique_news)}")
            
            all_news.extend(unique_news)
            await asyncio.sleep(2)
    finally:
        await client.disconnect()
    
    return all_news

# ========== RSS МОДУЛЬ ==========

def parse_rss_feed(url: str, name: str, keywords: List[str], targets: List[str], 
                   case_sensitive: bool, days_back: int = 30, limit: int = 50, min_length: int = 20) -> List[Dict]:
    """Парсит RSS ленту с фильтром по дате"""
    news = []
    cutoff_date = datetime.now() - timedelta(days=days_back)
    
    try:
        feed = feedparser.parse(url)
        
        for entry in feed.entries[:limit]:
            # Парсим дату публикации
            pub_date = entry.get("published", entry.get("pubDate", ""))
            if pub_date:
                try:
                    from dateutil import parser
                    dt = parser.parse(pub_date)
                    # Пропускаем старые новости
                    if dt.replace(tzinfo=None) < cutoff_date:
                        continue
                    date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            title = entry.get("title", "")
            description = BeautifulSoup(entry.get("description", ""), "html.parser").get_text()
            full_text = f"{title} {description}"
            
            if is_relevant(full_text, keywords, targets, case_sensitive, min_length):
                news.append({
                    "title": title[:200],
                    "link": entry.get("link", ""),
                    "source": name,
                    "date": date_str,
                    "snippet": full_text[:400],
                    "type": "rss",
                    "views": 0
                })
    except Exception as e:
        print(f"    ❌ {name}: {e}")
    
    return news

def parse_all_rss(config: Dict, duplicate_checker: DuplicateChecker) -> List[Dict]:
    """Парсит все RSS ленты с проверкой дублей"""
    rss_feeds = config['sources'].get('rss_feeds', {})
    if not rss_feeds:
        return []
    
    all_news = []
    days_back = config.get('time_filter', {}).get('days_back', 30)
    min_length = config['filters'].get('min_text_length', 20)
    
    for name, url in rss_feeds.items():
        print(f"  📰 {name}...")
        news = parse_rss_feed(
            url, name,
            config['keywords'],
            config['targets'],
            config['filters'].get('case_sensitive', False),
            days_back,
            50,
            min_length
        )
        
        # Фильтруем дубли
        unique_news = []
        for item in news:
            if not duplicate_checker.is_duplicate(item['title'], item['source']):
                unique_news.append(item)
        
        if len(news) != len(unique_news):
            print(f"    🚫 Отфильтровано дублей: {len(news) - len(unique_news)}")
        
        print(f"    Найдено новых: {len(unique_news)}")
        all_news.extend(unique_news)
    
    return all_news

# ========== ГЕНЕРАТОР ОТЧЕТОВ ==========

def generate_html(news: List[Dict], config: Dict, output_file: str) -> None:
    """Генерирует HTML отчет (светлая тема)"""
    if not news:
        html = f"""
        <!DOCTYPE html>
        <html><head><meta charset="UTF-8"><title>Watchtower - Ничего не найдено</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 20px;
            }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .card {{
                background: white;
                border-radius: 16px;
                padding: 40px;
                text-align: center;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            }}
            h1 {{ color: #667eea; margin-bottom: 20px; }}
            p {{ color: #4a5568; line-height: 1.6; }}
        </style>
        </head><body>
        <div class="container">
            <div class="card">
                <h1>🏰 Watchtower</h1>
                <p>По запросу "{', '.join(config.get('keywords', ['-'])[:5])}" ничего не найдено</p>
                <p>Проверьте источники или ключевые слова</p>
            </div>
        </div>
        </body></html>
        """
        Path(output_file).write_text(html, encoding='utf-8')
        return
    
    # Сортируем по дате
    news.sort(key=lambda x: x.get('date', ''), reverse=True)
    
    tg_count = sum(1 for x in news if x['type'] == 'telegram')
    rss_count = len(news) - tg_count
    days_back = config.get('time_filter', {}).get('days_back', 30)
    
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Watchtower - {len(news)} новостей</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            background: white;
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }}
        h1 {{
            font-size: 2.5em;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 10px;
        }}
        .subtitle {{
            color: #718096;
            margin-bottom: 20px;
        }}
        .stats {{
            display: flex;
            gap: 20px;
            margin-top: 20px;
            flex-wrap: wrap;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 25px;
            border-radius: 12px;
            font-weight: bold;
        }}
        .stat-number {{
            font-size: 2em;
            display: block;
        }}
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        .keywords {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #e2e8f0;
            color: #718096;
            font-size: 0.9em;
        }}
        .news-grid {{
            display: grid;
            gap: 20px;
        }}
        .news-card {{
            background: white;
            border-radius: 12px;
            padding: 25px;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        .news-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.15);
        }}
        .news-title {{
            font-size: 1.2em;
            margin-bottom: 12px;
        }}
        .news-title a {{
            color: #2d3748;
            text-decoration: none;
            font-weight: 600;
            transition: color 0.2s;
        }}
        .news-title a:hover {{
            color: #667eea;
        }}
        .news-meta {{
            display: flex;
            gap: 15px;
            margin-bottom: 15px;
            font-size: 0.85em;
            color: #718096;
            flex-wrap: wrap;
            align-items: center;
        }}
        .source {{
            background: #edf2f7;
            padding: 4px 10px;
            border-radius: 20px;
            display: inline-block;
        }}
        .date {{
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }}
        .badge {{
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.75em;
            font-weight: 600;
        }}
        .badge-telegram {{
            background: #48bb78;
            color: white;
        }}
        .badge-rss {{
            background: #4299e1;
            color: white;
        }}
        .snippet {{
            color: #4a5568;
            line-height: 1.6;
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #e2e8f0;
        }}
        .views {{
            color: #a0aec0;
            font-size: 0.8em;
            margin-top: 8px;
        }}
        .footer {{
            margin-top: 40px;
            text-align: center;
            color: rgba(255,255,255,0.9);
            padding: 20px;
            font-size: 0.9em;
        }}
        @media (max-width: 768px) {{
            .news-card {{
                padding: 15px;
            }}
            .news-title {{
                font-size: 1em;
            }}
            .stats {{
                gap: 10px;
            }}
            .stat-card {{
                padding: 10px 15px;
            }}
            .stat-number {{
                font-size: 1.5em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏰 Watchtower</h1>
            <div class="subtitle">Универсальный мониторинг интернета • последние {days_back} дней</div>
            <div class="stats">
                <div class="stat-card">
                    <span class="stat-number">{len(news)}</span>
                    <span class="stat-label">новостей</span>
                </div>
                <div class="stat-card">
                    <span class="stat-number">{tg_count}</span>
                    <span class="stat-label">Telegram</span>
                </div>
                <div class="stat-card">
                    <span class="stat-number">{rss_count}</span>
                    <span class="stat-label">RSS</span>
                </div>
            </div>
            <div class="keywords">
                🔍 Ключевые слова: {', '.join(config.get('keywords', ['-'])[:12])}
            </div>
        </div>
        
        <div class="news-grid">
"""
    
    for item in news:
        badge_class = "badge-telegram" if item['type'] == 'telegram' else "badge-rss"
        badge_text = "TELEGRAM" if item['type'] == 'telegram' else "RSS"
        
        html += f"""
            <div class="news-card">
                <div class="news-title">
                    <a href="{item['link']}" target="_blank" rel="noopener noreferrer">
                        {item['title']}
                    </a>
                </div>
                <div class="news-meta">
                    <span class="source">📰 {item['source']}</span>
                    <span class="badge {badge_class}">{badge_text}</span>
                    <span class="date">📅 {item['date']}</span>
                </div>
                <div class="snippet">
                    {item['snippet']}...
                </div>
                {f'<div class="views">👁️ Просмотров: {item["views"]}</div>' if item.get('views') else ''}
            </div>
"""
    
    html += f"""
        </div>
        
        <div class="footer">
            <p>🤖 Сгенерировано Watchtower | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>
"""
    
    Path(output_file).write_text(html, encoding='utf-8')
    print(f"✅ HTML отчет: {output_file}")

def generate_json(news: List[Dict], config: Dict, output_file: str) -> None:
    """Экспорт в JSON"""
    export = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "keywords": config.get('keywords', []),
            "targets": config.get('targets', []),
            "days_back": config.get('time_filter', {}).get('days_back', 30)
        },
        "total": len(news),
        "items": news
    }
    
    Path(output_file).write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ JSON экспорт: {output_file}")

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========

async def main():
    print("=" * 60)
    print("🏰 Watchtower - Универсальный мониторинг интернета")
    print("=" * 60)
    
    # Парсим аргументы
    args = parse_cli_args()
    
    # Очистка кеша если нужно
    if args.clear_cache:
        cache_file = Path("watchtower_cache.db")
        if cache_file.exists():
            cache_file.unlink()
            print("🧹 Кеш дублей очищен")
        else:
            print("ℹ️ Файл кеша не найден")
        if not args.config and not args.keywords:
            return
    
    # Загружаем конфиг
    if args.config:
        config = load_config(args.config)
    else:
        config = DEFAULT_CONFIG.copy()
    
    # Добавляем Telegram данные из переменных окружения
    config = check_telegram_config(config)
    
    # Объединяем с CLI аргументами
    config = merge_config(config, args, TOPICS)
    
    # Инициализируем проверку дублей
    duplicate_checker = DuplicateChecker()
    
    # Очищаем старые записи
    days_back = config.get('time_filter', {}).get('days_back', 30)
    duplicate_checker.clear_old(days=days_back)
    
    min_length = config['filters'].get('min_text_length', 20)
    
    print(f"\n🔍 Ключевые слова: {', '.join(config['keywords'][:10])}")
    if config.get('targets'):
        print(f"🎯 Цели: {', '.join(config['targets'][:5])}")
    print(f"📅 Период: последние {days_back} дней")
    print(f"📏 Мин. длина текста: {min_length} символов")
    print(f"📡 Источники: Telegram({len(config['sources']['telegram_channels'])}) RSS({len(config['sources']['rss_feeds'])})")
    
    all_news = []
    
    # Парсинг источников
    sources = args.sources.split(',') if args.sources else ['telegram', 'rss']
    
    if 'telegram' in sources and config['sources']['telegram_channels']:
        print("\n📱 Парсинг Telegram...")
        tg_news = await parse_all_telegram(config, duplicate_checker)
        all_news.extend(tg_news)
        print(f"✅ Найдено {len(tg_news)} новых новостей в Telegram")
    
    if 'rss' in sources and config['sources']['rss_feeds']:
        print("\n📰 Парсинг RSS...")
        rss_news = parse_all_rss(config, duplicate_checker)
        all_news.extend(rss_news)
        print(f"✅ Найдено {len(rss_news)} новых новостей в RSS")
    
    # Результаты
    print("\n" + "=" * 60)
    print(f"📊 ВСЕГО НОВЫХ НОВОСТЕЙ: {len(all_news)}")
    print("=" * 60)
    
    # Сохраняем отчеты
    if all_news or not args.no_html:
        output_dir = Path(config['output'].get('output_dir', 'reports'))
        output_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = config.get('name', 'watchtower')
        
        if args.output:
            html_file = args.output
        else:
            html_file = output_dir / f"{base_name}_{timestamp}.html"
        
        if not args.no_html:
            generate_html(all_news, config, html_file)
        
        if config['output'].get('json_export', False) and not args.no_json:
            json_file = output_dir / f"{base_name}_{timestamp}.json"
            generate_json(all_news, config, json_file)
    
    if not all_news:
        print(f"\n⚠️ Новых новостей не найдено за последние {days_back} дней")
        print("   Попробуйте:")
        print("   - Уменьшить количество дней: --days 7")
        print("   - Добавить больше ключевых слов")
        print("   - Добавить больше источников")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()