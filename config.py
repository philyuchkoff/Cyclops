#!/usr/bin/env python3
"""
config.py - Конфигуратор для Cyclops

Создает JSON конфиги через командную строку.

Использование:
    # Базовый конфиг с ключевыми словами
    python config.py запрет блокировка ограничение --name my_config
    
    # С ключевыми словами в кавычках (с пробелами)
    python config.py "искусственный интеллект" "data breach" --name ai_watch
    
    # Полный конфиг с ключевыми словами, каналами и RSS
    python config.py запрет блокировка --channels rian_ru,breakingmash --rss "РИА=https://ria.ru/export/rss2/index.xml" --name test
    
    # С указанием целей и периода
    python config.py запрет --targets соцсети,telegram --days 14 --name short_monitor
"""

import json
import argparse
import sys
from pathlib import Path
from datetime import datetime

def parse_args():
    parser = argparse.ArgumentParser(
        description='Cyclops Configuration Creator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python config.py запрет блокировка ограничение --name my_config
  python config.py "искусственный интеллект" "нейросети" --channels tech_news,ai_daily
  python config.py ban suspend --rss "Reuters=http://feeds.reuters.com/reuters/technologyNews" --name eng_monitor
  python config.py запрет --targets соцсети,telegram --days 7 --name short
        """
    )
    
    parser.add_argument(
        'keywords', 
        nargs='+', 
        help='Ключевые слова (можно в кавычках с пробелами)'
    )
    
    parser.add_argument(
        '--name', '-n', 
        type=str, 
        default='my_monitor',
        help='Имя конфиг-файла (без .json)'
    )
    
    parser.add_argument(
        '--targets', '-t', 
        type=str, 
        default='соцсети,telegram,youtube,интернет',
        help='Цели поиска через запятую'
    )
    
    parser.add_argument(
        '--channels', '-ch', 
        type=str, 
        default='',
        help='Telegram каналы через запятую (без @)'
    )
    
    parser.add_argument(
        '--rss', '-r', 
        type=str, 
        default='',
        help='RSS ленты в формате: имя=url,имя2=url2'
    )
    
    parser.add_argument(
        '--days', '-d', 
        type=int, 
        default=30,
        help='Количество дней назад (по умолчанию 30)'
    )
    
    parser.add_argument(
        '--limit', '-l', 
        type=int, 
        default=50,
        help='Лимит сообщений на канал (по умолчанию 50)'
    )
    
    parser.add_argument(
        '--no-telegram', 
        action='store_true',
        help='Отключить Telegram (только RSS)'
    )
    
    parser.add_argument(
        '--no-rss', 
        action='store_true',
        help='Отключить RSS (только Telegram)'
    )
    
    parser.add_argument(
        '--json', 
        action='store_true',
        help='Экспортировать результаты в JSON (включено по умолчанию для отчетов)'
    )
    
    parser.add_argument(
        '--min-length', 
        type=int, 
        default=20,
        help='Минимальная длина текста (по умолчанию 20)'
    )
    
    parser.add_argument(
        '--output-dir', 
        type=str, 
        default='reports',
        help='Папка для отчетов'
    )
    
    parser.add_argument(
        '--list', 
        action='store_true',
        help='Показать все существующие конфиги'
    )
    
    return parser.parse_args()

def parse_keywords(keywords_list):
    """Обрабатывает ключевые слова, сохраняя фразы в кавычках"""
    result = []
    for kw in keywords_list:
        # Убираем лишние кавычки если есть
        kw = kw.strip('"').strip("'")
        if kw:
            result.append(kw)
    return result

def parse_targets(targets_str):
    """Парсит цели из строки с запятыми"""
    return [t.strip() for t in targets_str.split(',') if t.strip()]

def parse_channels(channels_str):
    """Парсит Telegram каналы"""
    if not channels_str:
        return []
    return [ch.strip() for ch in channels_str.split(',') if ch.strip()]

def parse_rss_feeds(rss_str):
    """Парсит RSS ленты из формата имя=url,имя2=url2"""
    if not rss_str:
        return {}
    
    feeds = {}
    for item in rss_str.split(','):
        if '=' in item:
            name, url = item.split('=', 1)
            feeds[name.strip()] = url.strip()
        else:
            print(f"⚠️ Пропущен некорректный RSS формат: {item}")
    return feeds

def create_config(args):
    """Создает конфиг из аргументов"""
    
    keywords = parse_keywords(args.keywords)
    targets = parse_targets(args.targets)
    channels = parse_channels(args.channels)
    rss_feeds = parse_rss_feeds(args.rss)
    
    # Если не указаны источники, добавляем стандартные
    if not channels and not rss_feeds:
        print("⚠️ Не указаны источники, добавляю стандартные RSS...")
        rss_feeds = {
            "РИА Новости": "https://ria.ru/export/rss2/index.xml",
            "Лента.ру": "https://lenta.ru/rss",
            "Интерфакс": "https://www.interfax.ru/rss.asp"
        }
    
    # Определяем источники
    sources = []
    if channels and not args.no_telegram:
        sources.append("telegram")
    if rss_feeds and not args.no_rss:
        sources.append("rss")
    
    if not sources:
        print("❌ Нет активных источников! Укажите --channels или --rss")
        sys.exit(1)
    
    config = {
        "name": args.name,
        "keywords": keywords,
        "targets": targets,
        "time_filter": {
            "days_back": args.days,
            "enabled": True
        },
        "sources": {
            "telegram_channels": channels,
            "rss_feeds": rss_feeds
        },
        "telegram": {
            "api_id": 0,
            "api_hash": "",
            "phone": "",
            "message_limit": args.limit
        },
        "output": {
            "html_report": True,
            "json_export": args.json,
            "output_dir": args.output_dir
        },
        "filters": {
            "min_text_length": args.min_length,
            "exclude_spam": True,
            "case_sensitive": False
        }
    }
    
    return config

def list_configs():
    """Показывает все существующие конфиги"""
    config_files = list(Path('.').glob('*.json'))
    if not config_files:
        print("📂 Нет сохраненных конфигов")
        return
    
    print("\n📁 Существующие конфиги:")
    print("-" * 40)
    for cf in config_files:
        try:
            with open(cf, 'r', encoding='utf-8') as f:
                data = json.load(f)
                name = data.get('name', cf.stem)
                keywords = data.get('keywords', [])
                print(f"  📄 {cf.name}")
                print(f"     Название: {name}")
                print(f"     Ключевые слова: {', '.join(keywords[:5])}{'...' if len(keywords) > 5 else ''}")
                print()
        except:
            print(f"  📄 {cf.name} (поврежден)")

def save_config(config, filename):
    """Сохраняет конфиг в JSON файл"""
    # Убедимся что имя файла имеет расширение .json
    if not filename.endswith('.json'):
        filename = f"{filename}.json"
    
    # Проверяем не существует ли уже
    if Path(filename).exists():
        print(f"⚠️ Файл {filename} уже существует")
        response = input("Перезаписать? (y/N): ")
        if response.lower() != 'y':
            print("❌ Отменено")
            return False
    
    # Сохраняем
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    return True

def print_summary(config, filename):
    """Печатает сводку созданного конфига"""
    print("\n" + "=" * 60)
    print("✅ Конфиг создан!")
    print("=" * 60)
    print(f"📄 Файл: {filename}")
    print(f"📝 Название: {config['name']}")
    print(f"\n🔍 Ключевые слова ({len(config['keywords'])}):")
    for i, kw in enumerate(config['keywords'][:10], 1):
        print(f"   {i}. {kw}")
    if len(config['keywords']) > 10:
        print(f"   ... и еще {len(config['keywords']) - 10}")
    
    print(f"\n🎯 Цели:")
    for target in config['targets']:
        print(f"   • {target}")
    
    print(f"\n📅 Период: последние {config['time_filter']['days_back']} дней")
    
    if config['sources']['telegram_channels']:
        print(f"\n📱 Telegram каналы ({len(config['sources']['telegram_channels'])}):")
        for ch in config['sources']['telegram_channels'][:5]:
            print(f"   • {ch}")
        if len(config['sources']['telegram_channels']) > 5:
            print(f"   ... и еще {len(config['sources']['telegram_channels']) - 5}")
    
    if config['sources']['rss_feeds']:
        print(f"\n📰 RSS ленты ({len(config['sources']['rss_feeds'])}):")
        for name, url in list(config['sources']['rss_feeds'].items())[:5]:
            print(f"   • {name}: {url[:60]}...")
        if len(config['sources']['rss_feeds']) > 5:
            print(f"   ... и еще {len(config['sources']['rss_feeds']) - 5}")
    
    print("\n" + "=" * 60)
    print("🚀 Запуск мониторинга:")
    print(f"   python cyclops.py {filename}")
    print("=" * 60)

def main():
    args = parse_args()
    
    if args.list:
        list_configs()
        return
    
    # Создаем конфиг
    config = create_config(args)
    
    # Определяем имя файла
    filename = args.name if args.name.endswith('.json') else f"{args.name}.json"
    
    # Сохраняем
    if save_config(config, filename):
        print_summary(config, filename)
        
        # Подсказка про Telegram настройку
        if config['sources']['telegram_channels']:
            print("\n💡 Для работы Telegram нужно добавить API данные в файл:")
            print(f"   Отредактируйте {filename} и вставьте:")
            print('   "telegram": {')
            print('       "api_id": 12345678,')
            print('       "api_hash": "your_hash",')
            print('       "phone": "+79123456789"')
            print('   }')
            print("\n   Или используйте переменные окружения:")
            print("   export TG_API_ID=12345678")
            print("   export TG_API_HASH=your_hash")
            print("   export TG_PHONE=+79123456789")

if __name__ == "__main__":
    main()