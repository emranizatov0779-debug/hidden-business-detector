"""
ml/ingestion_engine.py  v2 — «Сигналы, не новости»
======================================================
ПЕРЕДЕЛАНО v2 (по итогам ревью):

Раньше модуль собирал ОБЗОРНЫЕ fincrime-новости (отчёты, аналитику, стратегии) —
аналитик банка такое и так читает сам, это не давало "вау"-эффекта.

Теперь модуль явно различает два типа контента:
  - ALERT  (сигнал): конкретное предупреждение/список/решение суда с датой,
            именами, MCC-кодами — то, что реально требует проверки СЕГОДНЯ
  - RESEARCH (исследование): обзорная статья, стратегия, тренд-репорт —
            полезно для общего понимания, но не actionable за 60 секунд

Источники переработаны под это разделение:
  - FATF grey/black list (конкретный список юрисдикций с датой изменения,
    не аналитическая статья про FATF)
  - АФМ РК — список организаций с признаками финансовых пирамид (конкретные
    названия, не обзор схем)
  - Источники новостей о задержаниях/приговорах (конкретные ФИО/компании/суммы)

Убраны источники, дающие преимущественно обзорную аналитику (AML Intelligence,
Kenneth Rijock blog, Global Initiative) — оставлен только Financial Crime News
как смешанный источник, прошедший через тот же alert/research фильтр.

Telegram-каналы НЕ добавлены в автоматический пайплайн — см. примечание
в конце файла. Технически и юридически это другой по рискам модуль.
"""

import os
import re
import json
import hashlib
from datetime import datetime, timedelta

INGESTION_CACHE = 'data/ingestion_cache.json'
DIGEST_PATH      = 'data/daily_digest.json'
SEEN_HASHES_PATH = 'data/ingestion_seen_hashes.json'

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


# ─── РЕЕСТР ИСТОЧНИКОВ ─────────────────────────────────────────────────────────
# Каждый источник помечен expected_signal: 'alert' (конкретные списки/решения)
# или 'mixed' (нужна классификация на уровне статьи, не только источника).
# Источники чисто аналитического жанра убраны — они систематически давали
# 0 совпадений с данными клиента и создавали шум без пользы.

SOURCES = [
    # ── ALERT-ИСТОЧНИКИ: конкретные списки/решения с датой ────────────────────
    {
        'id': 'fatf_greylist',
        'name': 'FATF — Black & Grey List (официальный список юрисдикций)',
        'type': 'html',
        'url': 'https://www.fatf-gafi.org/en/countries/black-and-grey-lists.html',
        'region': 'Global',
        'category': 'regulator_list',
        'expected_signal': 'alert',
        'link_pattern': r'/en/publications/[\w\-/]+\.html',
    },
    {
        'id': 'afm_kz_piramidy',
        'name': 'АФМ РК — Список организаций с признаками финансовых пирамид',
        'type': 'html',
        # ПРИМЕЧАНИЕ: страница на gov.kz рендерится через JavaScript — наш
        # простой HTML-парсер может не получить полный список без браузерного
        # рендеринга. Источник оставлен в реестре с явной пометкой needs_js,
        # чтобы это было видно в UI, а не выглядело как "молча сломалось".
        'url': 'https://www.gov.kz/memleket/entities/afm/press',
        'region': 'KZ',
        'category': 'regulator_list',
        'expected_signal': 'alert',
        'link_pattern': r'/memleket/entities/afm/press/(article|news)/details/\d+',
        'needs_js': True,
    },
    # ── MIXED: смешанный источник, классификация на уровне статьи ────────────
    {
        'id': 'financialcrimenews',
        'name': 'The Financial Crime News',
        'type': 'rss',
        'url': 'https://thefinancialcrimenews.com/feed/',
        'region': 'Global',
        'category': 'aml_news',
        'expected_signal': 'mixed',
    },
    {
        'id': 'finbold_fincrime',
        'name': 'FinBold — Financial Crime (аресты, приговоры, конфискации)',
        'type': 'rss',
        'url': 'https://finbold.com/category/financial-crime-news/feed/',
        'region': 'Global',
        'category': 'crypto_fincrime',
        'expected_signal': 'mixed',
    },
]

# Источники, которые были в v1 и убраны как преимущественно research-жанра:
# amlintelligence.com, rijock.blogspot.com, globalinitiative.net —
# систематически давали обзорные статьи без конкретных дат/списков/MCC,
# что и создавало эффект "FATF опубликовал отчёт → 0 совпадений → шум".

# ПРИМЕЧАНИЕ: этот список нужно периодически проверять — RSS-ленты иногда
# переезжают или закрываются. Перед первым запуском в проде рекомендуется
# вручную открыть каждый URL в браузере и убедиться, что он отдаёт валидный
# XML, а не страницу с ошибкой 404 или редиректом на платную подписку.


# ─── HTTP-ЗАПРОСЫ ─────────────────────────────────────────────────────────────

def _fetch_url(url: str, timeout: int = 15) -> str | None:
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'[ingestion] fetch error {url}: {e}')
        return None


def _parse_rss(xml_text: str, max_items: int = 15) -> list[dict]:
    """
    Лёгкий RSS-парсер без внешних зависимостей (используем встроенный
    xml.etree, чтобы не плодить requirements.txt без необходимости).
    """
    items = []
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
        # RSS 2.0: channel > item
        for item in root.findall('.//item')[:max_items]:
            title = item.findtext('title', default='').strip()
            link = item.findtext('link', default='').strip()
            desc = item.findtext('description', default='').strip()
            pub  = item.findtext('pubDate', default='').strip()
            if title:
                items.append({'title': title, 'link': link,
                              'description': re.sub('<[^<]+?>', '', desc)[:300],
                              'published': pub})
        # Atom fallback: feed > entry
        if not items:
            ns = {'a': 'http://www.w3.org/2005/Atom'}
            for entry in root.findall('.//a:entry', ns)[:max_items]:
                title = entry.findtext('a:title', default='', namespaces=ns).strip()
                link_el = entry.find('a:link', ns)
                link = link_el.get('href', '') if link_el is not None else ''
                summary = entry.findtext('a:summary', default='', namespaces=ns).strip()
                pub = entry.findtext('a:updated', default='', namespaces=ns).strip()
                if title:
                    items.append({'title': title, 'link': link,
                                  'description': re.sub('<[^<]+?>', '', summary)[:300],
                                  'published': pub})
    except Exception as e:
        print(f'[ingestion] RSS parse error: {e}')
    return items


def _parse_html_links(html_text: str, link_pattern: str, base_url: str,
                       max_items: int = 15) -> list[dict]:
    """
    Извлекает заголовки статей из HTML-страницы по паттерну ссылок.
    Не использует BeautifulSoup намеренно (избегаем лишней зависимости) —
    регулярка по <a href="...pattern...">текст</a> достаточно для новостных
    списков большинства регуляторных сайтов.
    """
    items = []
    seen_links = set()
    try:
        # Ищем <a href="...">текст</a> где href матчит link_pattern
        anchor_re = re.compile(
            r'<a[^>]+href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL
        )
        for match in anchor_re.finditer(html_text):
            href, inner = match.group(1), match.group(2)
            if not re.search(link_pattern, href):
                continue
            # Убираем вложенные теги из текста ссылки
            title = re.sub('<[^<]+?>', '', inner).strip()
            title = re.sub(r'\s+', ' ', title)
            if not title or len(title) < 10:
                continue
            full_link = href if href.startswith('http') else base_url.rstrip('/') + '/' + href.lstrip('/')
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            items.append({'title': title, 'link': full_link, 'description': '', 'published': ''})
            if len(items) >= max_items:
                break
    except Exception as e:
        print(f'[ingestion] HTML parse error: {e}')
    return items


# ─── ДЕДУПЛИКАЦИЯ ─────────────────────────────────────────────────────────────

def _item_hash(item: dict) -> str:
    key = f"{item.get('title','')}_{item.get('link','')}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def _load_seen_hashes() -> set:
    if os.path.exists(SEEN_HASHES_PATH):
        try:
            with open(SEEN_HASHES_PATH, encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def _save_seen_hashes(hashes: set):
    os.makedirs('data', exist_ok=True)
    with open(SEEN_HASHES_PATH, 'w', encoding='utf-8') as f:
        json.dump(list(hashes)[-500:], f)


# ─── СБОР ДАННЫХ ИЗ ВСЕХ ИСТОЧНИКОВ ───────────────────────────────────────────

def collect_raw_items(only_new: bool = True) -> tuple[list[dict], list[str]]:
    """
    Проходит по всем источникам, собирает заголовки/описания.

    Returns:
        (items, warnings) — warnings содержит явные предупреждения, например
        если needs_js источник вернул 0 элементов (вероятно из-за того, что
        страница рендерится через JavaScript и наш парсер видит пустой каркас).
    """
    all_items = []
    warnings = []
    seen = _load_seen_hashes() if only_new else set()
    new_hashes = set()

    for src in SOURCES:
        raw = _fetch_url(src['url'])
        if not raw:
            warnings.append(f"Источник «{src['name']}» недоступен (не удалось получить ответ)")
            continue

        if src['type'] == 'rss':
            items = _parse_rss(raw)
        elif src['type'] == 'html':
            base = '/'.join(src['url'].split('/')[:3])  # https://domain.com
            items = _parse_html_links(raw, src.get('link_pattern', r'.*'), base)
        else:
            items = []

        if not items and src.get('needs_js'):
            warnings.append(
                f"Источник «{src['name']}» вернул 0 элементов — страница, вероятно, "
                f"рендерится через JavaScript и требует браузерного рендеринга "
                f"(headless browser), наш простой HTML-парсер этого не делает. "
                f"Список можно проверить вручную по ссылке: {src['url']}"
            )
        elif not items:
            warnings.append(f"Источник «{src['name']}» не дал новых элементов")

        for it in items:
            h = _item_hash(it)
            if only_new and h in seen:
                continue
            it['source_id'] = src['id']
            it['source_name'] = src['name']
            it['region'] = src['region']
            it['category'] = src['category']
            it['expected_signal'] = src.get('expected_signal', 'mixed')
            it['hash'] = h
            all_items.append(it)
            new_hashes.add(h)

    if only_new:
        seen |= new_hashes
        _save_seen_hashes(seen)

    return all_items, warnings


# ─── AI-АНАЛИЗ (через Groq, переиспользуем тот же ключ) ──────────────────────

_ANALYSIS_SYSTEM = """Ты аналитик AML/комплаенс, специализация — Казахстан, СНГ, Центральная Азия.
Тебе дают заголовки и описания из открытых источников.
КРИТИЧНО: банк и так читает FATF и общую аналитику. Твоя задача — отделить КОНКРЕТНЫЙ
сигнал (список, дата, решение, метод) от ОБЗОРНОЙ статьи (стратегия, тренд, "5-й раунд анализа").
Обзорные статьи — это ШУМ для оперативного AML, даже если они формально релевантны теме.
Отвечай ТОЛЬКО валидным JSON, без markdown, без пояснений до или после."""

_ANALYSIS_PROMPT_TEMPLATE = """Вот {count} элементов из открытых источников:

{items_text}

Для КАЖДОГО элемента определи:

1. signal_type: "ALERT" или "RESEARCH"
   - ALERT: содержит КОНКРЕТНИКУ — список юрисдикций/организаций с датой, решение суда с
     именами/суммами, регуляторное предупреждение о конкретной схеме. Можно действовать СЕГОДНЯ.
   - RESEARCH: обзорная статья, стратегия на годы, "сравнительный анализ", тренд-репорт,
     общие рекомендации без конкретных имён/списков/дат. Полезно для фона, не для действия.
   Если сомневаешься — выбирай RESEARCH (лучше недооценить срочность, чем создать ложную тревогу).

2. relevance: насколько релевантно банку в Казахстане/СНГ (HIGH/MEDIUM/LOW/NONE)
   - Для RESEARCH-элементов максимум MEDIUM, даже если тема релевантна — это не сигнал к действию
   - HIGH доступен только для ALERT-элементов с прямой связью к СНГ/Казахстану

3. mcc_codes: ТОЛЬКО если упомянута конкретная отрасль — массив 4-значных кодов строками.
   Примеры: 7995=казино/гемблинг, 6051=криптообмен, 5999=розница, 5945=хобби/игры,
   7372=ПО/IT, 5912=аптеки, 4829=денежные переводы, 0763=сельхозкооперативы.
   Если не уверен — пустой массив [].

4. countries: ISO-коды стран, упомянутых как очаг риска — массив заглавными (KZ, RU, UZ, AE...).

5. risk_keywords: 2-4 ключевых слова метода на русском.

6. one_line_summary: одно предложение на русском — ЧТО КОНКРЕТНО произошло (не "обсуждается тема X",
   а "регулятор внёс Y в список Z от {date}" или аналогичная конкретика для ALERT).

7. why_relevant: для ALERT с HIGH/MEDIUM — конкретная причина (1 предложение). Для RESEARCH — пустая строка.

8. what_if_ignored: ТОЛЬКО для ALERT с HIGH/MEDIUM — одно предложение о РЕАЛЬНОМ риске бездействия,
   основанное на тексте источника (например "регулятор требует отчёт по таким случаям до даты X"
   или "схема уже приводит к блокировкам счетов в других банках региона по данным источника").
   НЕ придумывай конкретные суммы ущерба или сроки, которых нет в тексте — если источник не
   называет последствие явно, напиши общую формулировку вида "требует проверки до следующей
   регуляторной отчётности" без выдуманных чисел. Для RESEARCH — пустая строка.

ВАЖНО: НЕ оценивай числовую "вероятность проникновения". НЕ придумывай mcc_codes/countries без
явного основания в тексте. НЕ придумывай суммы ущерба, штрафов или сроков, которых нет в источнике.

Верни JSON-массив объектов в том же порядке:
[{{"index": 0, "signal_type": "ALERT", "relevance": "HIGH", "mcc_codes": ["7995"], "countries": ["KH"], "risk_keywords": ["казино"], "one_line_summary": "...", "why_relevant": "...", "what_if_ignored": "..."}}]"""


def _call_groq_for_analysis(items: list[dict]) -> list[dict] | None:
    """Использует тот же Groq-ключ, что и ai_assistant.py / external_intelligence.py."""
    try:
        from ml.external_intelligence import get_api_key, _call_api
    except ImportError:
        return None

    api_key = get_api_key()
    if not api_key:
        return None

    items_text = '\n'.join([
        f"{i}. [{it['source_name']}] {it['title']} — {it.get('description','')[:150]}"
        for i, it in enumerate(items)
    ])
    today = datetime.now().strftime('%Y-%m-%d')
    prompt = _ANALYSIS_PROMPT_TEMPLATE.format(count=len(items), items_text=items_text, date=today)

    text, err = _call_api(prompt, _ANALYSIS_SYSTEM, api_key)
    if not text:
        print(f'[ingestion] analysis API error: {err}')
        return None

    clean = text.strip()
    for fence in ['```json', '```']:
        if clean.startswith(fence):
            clean = clean[len(fence):]
    if clean.endswith('```'):
        clean = clean[:-3]
    try:
        return json.loads(clean.strip())
    except Exception:
        import re as _re
        m = _re.search(r'\[.*\]', clean, _re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                return None
    return None


# ─── ГЕНЕРАЦИЯ ЕЖЕДНЕВНОГО ДАЙДЖЕСТА ──────────────────────────────────────────

def generate_digest(force_refetch: bool = False) -> dict:
    """
    Главная функция Фазы 1. Собирает новости, прогоняет через AI-анализ,
    сохраняет дайджест.

    Returns: dict с ключами: generated_at, total_collected, items (с анализом),
             source (ai_analyzed | raw_only), errors
    """
    items, collection_warnings = collect_raw_items(only_new=not force_refetch)

    result = {
        'generated_at': datetime.now().isoformat(),
        'total_collected': len(items),
        'items': [],
        'source': 'raw_only',
        'errors': list(collection_warnings),
    }

    if not items:
        result['errors'].append('Новых элементов не найдено (либо источники недоступны, '
                                'либо все уже были показаны ранее — попробуй force_refetch)')
        _save_digest(result)
        return result

    # Анализируем пачками по 10, чтобы не упираться в лимит токенов
    analyzed_all = []
    batch_size = 10
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        analysis = _call_groq_for_analysis(batch)
        if analysis:
            for a in analysis:
                idx = a.get('index', 0)
                if 0 <= idx < len(batch):
                    merged = {**batch[idx], **a}
                    analyzed_all.append(merged)
            result['source'] = 'ai_analyzed'
        else:
            # Без AI-анализа — просто помечаем как unrated, ничего не выдумываем
            for it in batch:
                it['signal_type'] = 'UNKNOWN'
                it['relevance'] = 'UNRATED'
                it['mcc_codes'] = []
                it['countries'] = []
                it['risk_keywords'] = []
                it['one_line_summary'] = it['title']
                it['why_relevant'] = ''
                it['what_if_ignored'] = ''
                analyzed_all.append(it)
            result['errors'].append('AI-анализ недоступен для части новостей (нет ключа Groq '
                                    'или ошибка API) — показаны необработанные заголовки')

    result['items'] = analyzed_all
    _save_digest(result)
    return result


def _save_digest(data: dict):
    os.makedirs('data', exist_ok=True)
    with open(DIGEST_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_last_digest() -> dict | None:
    if os.path.exists(DIGEST_PATH):
        try:
            with open(DIGEST_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None


def get_digest_summary(digest: dict) -> dict:
    """Краткая статистика для UI."""
    items = digest.get('items', [])
    by_relevance = {}
    alert_count = 0
    research_count = 0
    for it in items:
        r = it.get('relevance', 'UNRATED')
        by_relevance[r] = by_relevance.get(r, 0) + 1
        if it.get('signal_type') == 'ALERT':
            alert_count += 1
        elif it.get('signal_type') == 'RESEARCH':
            research_count += 1
    return {
        'total': len(items),
        'high': by_relevance.get('HIGH', 0),
        'medium': by_relevance.get('MEDIUM', 0),
        'low': by_relevance.get('LOW', 0) + by_relevance.get('NONE', 0),
        'unrated': by_relevance.get('UNRATED', 0),
        'alert_count': alert_count,
        'research_count': research_count,
        'generated_at': digest.get('generated_at', '')[:16],
        'is_ai_analyzed': digest.get('source') == 'ai_analyzed',
    }


# ═══════════════════════════════════════════════════════════════════════════
# ПРИМЕЧАНИЕ: почему здесь нет telegram_monitor.py с реальным парсингом
# ═══════════════════════════════════════════════════════════════════════════
#
# Технически мониторинг публичных Telegram-каналов возможен через Telegram
# Client API (библиотеки Telethon или Pyrogram), но это требует:
#
#   1. Авторизации РЕАЛЬНОГО Telegram-аккаунта (номер телефона + код),
#      который должен быть подписан на целевые каналы. Это не "API-ключ",
#      а полноценная сессия живого аккаунта.
#
#   2. Юридической оценки: согласно Telegram ToS, автоматический сбор
#      контента из каналов для коммерческого использования (а это
#      коммерческий продукт для банков) может нарушать условия
#      использования платформы. Это не блокер технически, но это вопрос,
#      который стоит обсудить с юристом ДО того как это станет частью
#      продаваемого банкам продукта — особенно если продукт будет
#      проходить комплаенс-проверку со стороны банка-клиента, который
#      сам спросит "откуда у вас эти данные и легально ли это".
#
#   3. Риска бана аккаунта при автоматизированном чтении многих каналов —
#      Telegram активно детектирует и банит аккаунты с паттерном бота.
#
# Если решишь двигаться в этом направлении — следующий шаг: выбрать
# 5-10 конкретных ПУБЛИЧНЫХ каналов (не закрытых чатов), на которые
# подписываешься вручную с обычного аккаунта, и через Telethon читаешь
# их историю. Это не даст доступа к закрытым P2P-чатам обменников —
# для этого нужны совсем другие методы (см. обсуждение про Flashpoint/
# Recorded Future в чате).
