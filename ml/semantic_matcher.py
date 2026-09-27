"""
ml/semantic_matcher.py  — AI-семантический матчинг: новость vs профиль мерчанта
================================================================================
Пункт 4 из плана: "использовать AI не только для анализа, но и для поиска".

Проблема с текущим MCC-матчингом:
  - Мерчант описан как "IT-услуги" с MCC 7372, новость про Coinbase — нет совпадения,
    хотя мерчант реально может быть криптообменником, использующим "нейтральный" MCC
  - MCC 6051 совпадает, но это 1000 разных сценариев, не только крипта

Решение:
  Перед бинарным MCC-сравнением — подаём пару "текст новости + профиль мерчанта"
  в Groq AI с промптом "оцени вероятность связи от 0 до 100".

Использование токенов и стоимость:
  Для 2060 мерчантов × 30 новостей = 61 800 пар — это ОЧЕНЬ дорого по токенам.
  Поэтому реализован ДВУХЭТАПНЫЙ подход:
    1. Грубый фильтр: сначала отбираем кандидатов через быстрый текстовый поиск
       по ключевым словам из новости (бесплатно, без токенов)
    2. Тонкий AI-матчинг: только для кандидатов из шага 1 (обычно 5-50 мерчантов
       на одну новость, а не 2060)

Это делает AI-матчинг реальным даже при ограниченном количестве токенов Groq.
"""

import os
import re
import json
from datetime import datetime

SEMANTIC_CACHE_PATH = 'data/semantic_matches.json'

# MCC-кластеры по тематике — широкие группы, не точное совпадение
# Позволяет найти "возможного крипто-мерчанта" с MCC 7372, если он описан как
# "обмен цифровых активов", даже если у него не 6051
MCC_CLUSTERS = {
    'crypto': ['6051', '6099', '7372', '7374', '6211', '4829', '6012'],
    'gambling': ['7995', '7994', '7993', '7011'],
    'pharma': ['5912', '5122', '8099'],
    'trade': ['5045', '5065', '5999', '5940', '5941'],
    'transport': ['4111', '4121', '4131', '7512', '7523'],
    'financial': ['6020', '6022', '6035', '6036', '6211'],
}

# Ключевые слова по тематике — на нескольких языках (RU/EN/KZ-транслит)
TOPIC_KEYWORDS = {
    'crypto': [
        'crypto', 'bitcoin', 'btc', 'ethereum', 'usdt', 'binance', 'coinbase',
        'p2p', 'exchange', 'обмен', 'крипто', 'биткоин', 'токен', 'wallet', 'кошелёк',
        'defi', 'nft', 'блокчейн', 'blockchain', 'mining', 'майнинг',
    ],
    'gambling': [
        'casino', 'gambling', 'bet', 'betting', 'poker', 'казино', 'ставки', 'ставк',
        'игра', 'лотерея', 'lottery', 'slot', 'слот',
    ],
    'sanctions': [
        'sanction', 'санкц', 'ofac', 'ofsi', 'eu sanctions', 'black list',
        'embargo', 'запрет', 'заморозка', 'freeze', 'designated',
    ],
    'aml': [
        'laundering', 'money laundering', 'отмывание', 'обнал', 'cashing out',
        'structuring', 'смурфинг', 'смурф', 'smurfing', 'финмониторинг',
    ],
    'fraud': [
        'fraud', 'scam', 'phishing', 'фишинг', 'мошенничество', 'мошен', 'схем',
        'pump dump', 'ponzi', 'пирамида', 'pyramid',
    ],
}


def _extract_topics_from_text(text: str) -> list[str]:
    """Быстрое извлечение тематик из текста новости — без AI, без токенов."""
    text_lower = text.lower()
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(topic)
    return found


def _get_mcc_topics(mcc: str) -> list[str]:
    """Какие тематики совместимы с данным MCC-кодом."""
    topics = []
    for topic, mcc_list in MCC_CLUSTERS.items():
        if mcc in mcc_list:
            topics.append(topic)
    return topics


def _build_merchant_profile_text(row: dict) -> str:
    """
    Создаём текстовый профиль мерчанта для AI-сравнения.
    Берём все доступные поля — чем больше описания, тем лучше семантика.
    """
    parts = []
    for field, label in [
        ('merchant_name', 'Название'), ('name', 'Название'), ('business_name', 'Название'),
        ('dominant_mcc', 'MCC'), ('mcc', 'MCC'),
        ('dominant_country', 'Страна'), ('country', 'Страна'),
        ('merchant_id', 'ID'),
    ]:
        val = row.get(field, '')
        if val and str(val) not in ('?', 'nan', 'None', ''):
            # Добавляем расшифровку MCC если знаем
            if field in ('dominant_mcc', 'mcc'):
                from ml.sanctions_screener import HIGH_RISK_MCC
                mcc_label = HIGH_RISK_MCC.get(str(val), {}).get('label', '')
                parts.append(f"MCC {val}" + (f" ({mcc_label})" if mcc_label else ''))
            else:
                parts.append(f"{label}: {val}")
    return ', '.join(parts) if parts else 'Нет данных'


def find_semantic_candidates(news_items: list[dict], df_agg) -> dict:
    """
    Шаг 1: Быстрый фильтр кандидатов по тематическому совпадению.
    Без AI, без токенов — только текстовый поиск по ключевым словам.

    Returns: {news_item_hash → [candidate_rows]}
    Обычно 5-50 кандидатов на новость из 2060 мерчантов.
    """
    if df_agg is None or not news_items:
        return {}

    mcc_col     = next((c for c in ['dominant_mcc', 'mcc'] if c in df_agg.columns), None)
    name_col    = next((c for c in ['merchant_name', 'name', 'business_name'] if c in df_agg.columns), None)
    country_col = next((c for c in ['dominant_country', 'country'] if c in df_agg.columns), None)

    candidates = {}

    for it in news_items:
        # Составляем полный текст новости для анализа
        full_text = (
            it.get('title', '') + ' ' +
            it.get('one_line_summary', '') + ' ' +
            it.get('why_relevant', '') + ' ' +
            ' '.join(it.get('risk_keywords', []))
        )
        news_topics = _extract_topics_from_text(full_text)
        news_mcc_codes = [str(c) for c in it.get('mcc_codes', [])]
        news_countries = [str(c).upper() for c in it.get('countries', [])]

        if not news_topics and not news_mcc_codes and not news_countries:
            continue

        item_key = it.get('hash', str(hash(it.get('title', '')))[:12])
        item_candidates = []

        for _, row in df_agg.iterrows():
            row_dict = row.to_dict()
            mcc = str(row.get(mcc_col, '')) if mcc_col else ''
            country = str(row.get(country_col, '')).lower() if country_col else ''
            name = str(row.get(name_col, '')).lower() if name_col else ''

            score = 0
            reasons = []

            # Точное MCC из новости
            if mcc and mcc in news_mcc_codes:
                score += 3
                reasons.append(f'MCC {mcc} точно совпадает')

            # Тематическое совпадение MCC (расширенный матчинг)
            mcc_topics = _get_mcc_topics(mcc)
            for topic in news_topics:
                if topic in mcc_topics:
                    score += 2
                    reasons.append(f'MCC {mcc} совместим с тематикой «{topic}»')
                    break

            # Ключевые слова из новости в названии мерчанта
            if name:
                for topic in news_topics:
                    for kw in TOPIC_KEYWORDS.get(topic, []):
                        if kw in name:
                            score += 2
                            reasons.append(f'Название содержит «{kw}» (тематика: {topic})')
                            break

            # Совпадение страны
            if news_countries and country:
                from ml.entity_linker import ISO_TO_NAMES
                for iso in news_countries:
                    variants = ISO_TO_NAMES.get(iso, [iso.lower()])
                    if country in variants:
                        score += 1
                        reasons.append(f'Страна {country} упомянута в новости')
                        break

            if score > 0:
                item_candidates.append({
                    'row': row_dict,
                    'pre_score': score,
                    'pre_reasons': reasons,
                })

        # Сортируем кандидатов по pre_score, берём топ-50
        item_candidates.sort(key=lambda x: x['pre_score'], reverse=True)
        candidates[item_key] = item_candidates[:50]

    return candidates


def ai_match_candidates(
    news_item: dict,
    candidates: list[dict],
    api_key: str,
    max_to_score: int = 10,
) -> list[dict]:
    """
    Шаг 2: AI-матчинг топ кандидатов из шага 1.
    Подаём пачку пар "новость + профиль мерчанта" в Groq.
    Scorim только топ-10 по pre_score — это ~5-10 запросов к API на всю новость.

    Returns: список dict с полями merchant_id, ai_score (0-100), ai_reasoning
    """
    from ml.external_intelligence import _call_api, _SYS as _BASE_SYS

    if not api_key or not candidates:
        return []

    to_score = candidates[:max_to_score]

    system = """Ты AML-аналитик. Тебе дают текст новости о финансовом преступлении
и профиль мерчанта из базы банка. Оцени вероятность связи между новостью и мерчантом.

ВАЖНО: отвечай ТОЛЬКО валидным JSON-массивом, без markdown, без пояснений."""

    # Батч-формат: одна новость + все кандидаты в одном запросе
    news_text = (
        f"Новость: {news_item.get('title', '')}\n"
        f"Описание: {news_item.get('one_line_summary', '')}\n"
        f"Ключевые слова: {', '.join(news_item.get('risk_keywords', []))}\n"
        f"MCC из новости: {', '.join(str(c) for c in news_item.get('mcc_codes', []))}\n"
        f"Страны из новости: {', '.join(str(c) for c in news_item.get('countries', []))}"
    )

    profiles_text = '\n'.join([
        f"{i}. {_build_merchant_profile_text(c['row'])}"
        for i, c in enumerate(to_score)
    ])

    prompt = f"""{news_text}

Мерчанты для оценки:
{profiles_text}

Для каждого мерчанта (0 до {len(to_score)-1}) оцени вероятность связи с новостью от 0 до 100.
Где 100 = прямая связь (тот же тип бизнеса, та же схема, та же страна),
50 = косвенная (похожий тип, другая страна или неявная схема),
0 = нет связи.

НЕ придумывай факты. Если профиль мерчанта пустой — ставь 0.
Возвращай только индекс и оценку.

[{{"index": 0, "score": 75, "reasoning": "Мерчант — криптообменник (MCC 6051), новость про схему через P2P-биржи"}}]"""

    text, err = _call_api(prompt, system, api_key)
    if not text:
        print(f'[semantic] AI match error: {err}')
        return []

    clean = text.strip()
    for fence in ['```json', '```']:
        if clean.startswith(fence):
            clean = clean[len(fence):]
    if clean.endswith('```'):
        clean = clean[:-3]

    try:
        scored = json.loads(clean.strip())
        if not isinstance(scored, list):
            return []
    except Exception:
        import re as _re
        m = _re.search(r'\[.*\]', clean, _re.DOTALL)
        if m:
            try:
                scored = json.loads(m.group())
            except Exception:
                return []
        else:
            return []

    results = []
    id_col = next((c for c in ['merchant_id'] if c in to_score[0]['row']) if to_score else iter([]), None)
    if not id_col:
        id_col = list(to_score[0]['row'].keys())[0] if to_score else 'merchant_id'

    for item in scored:
        idx = item.get('index', -1)
        if 0 <= idx < len(to_score):
            candidate = to_score[idx]
            ai_score = int(item.get('score', 0))
            if ai_score >= 40:  # Порог: ниже 40 — не показываем
                results.append({
                    'merchant_id': str(candidate['row'].get(id_col, '?')),
                    'ai_score': ai_score,
                    'ai_reasoning': item.get('reasoning', ''),
                    'pre_score': candidate['pre_score'],
                    'pre_reasons': candidate['pre_reasons'],
                    'mcc': str(candidate['row'].get('dominant_mcc', candidate['row'].get('mcc', '?'))),
                    'country': str(candidate['row'].get('dominant_country', candidate['row'].get('country', '?'))),
                    'probability': float(candidate['row'].get('probability', 0)),
                    'tier': str(candidate['row'].get('tier', '?')),
                })

    results.sort(key=lambda x: x['ai_score'], reverse=True)
    return results


def run_semantic_matching(
    news_items: list[dict],
    df_agg,
    api_key: str,
    max_items_to_ai_score: int = 5,  # Сколько новостей пропускаем через дорогой AI
) -> dict:
    """
    Полный пайплайн семантического матчинга.

    Args:
        max_items_to_ai_score: сколько новостей (по убыванию релевантности)
            пропускаем через AI. AI-этап расходует токены — ограничиваем.

    Returns: {news_item_hash → [ai-scored matches]}
    """
    if not news_items or df_agg is None:
        return {}

    # Шаг 1: грубый фильтр (бесплатный, быстрый)
    candidate_map = find_semantic_candidates(news_items, df_agg)

    if not api_key:
        # Без AI возвращаем только кандидатов из грубого фильтра
        result = {}
        for key, candidates in candidate_map.items():
            result[key] = [{
                'merchant_id': str(c['row'].get('merchant_id', c['row'].get(list(c['row'].keys())[0], '?'))),
                'ai_score': None,  # Явно None, не 0 — нет AI, не "нет совпадения"
                'ai_reasoning': 'AI-анализ недоступен (нет Groq ключа)',
                'pre_score': c['pre_score'],
                'pre_reasons': c['pre_reasons'],
                'mcc': str(c['row'].get('dominant_mcc', c['row'].get('mcc', '?'))),
                'country': str(c['row'].get('dominant_country', c['row'].get('country', '?'))),
                'probability': float(c['row'].get('probability', 0)),
                'tier': str(c['row'].get('tier', '?')),
            } for c in candidates[:10]]
        return result

    # Шаг 2: AI-матчинг только для топ-N новостей
    high_relevance_items = [
        it for it in news_items if it.get('relevance') in ('HIGH', 'MEDIUM')
    ][:max_items_to_ai_score]

    result = {}
    for it in high_relevance_items:
        item_key = it.get('hash', str(hash(it.get('title', '')))[:12])
        candidates = candidate_map.get(item_key, [])
        if not candidates:
            continue
        ai_results = ai_match_candidates(it, candidates, api_key)
        if ai_results:
            result[item_key] = ai_results

    return result
