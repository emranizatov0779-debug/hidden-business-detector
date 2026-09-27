"""
ml/entity_linker.py  v2 — Explainable Entity Linking
=======================================================
ИСПРАВЛЕНО v2 (по итогам ревью Kimi):

1. «Матчинг слишком широкий / непонятно почему именно эти 4»
   → Добавлен composite score: MCC/страна — это ВХОДНОЙ фильтр (кто вообще
     может быть причастен), а ранжирование внутри идёт по факторам аномалии:
     - keyword-совпадение в названии мерчанта (если есть колонка с названием)
     - всплеск оборота, если в данных есть колонка роста
     - доля ночных операций, если есть night_ratio
     - внутренняя probability (HOT/Warm/Low)
     Каждый фактор явно показан, не скрыт за единым числом.

2. «Затрагивает 4 — а почему эти 4?»
   → Каждый матч теперь имеет поле 'match_reasons': список конкретных
     причин ("MCC 6051 совпадает", "оборот вырос на 340%", "название
     содержит 'exchange'") — это и есть мост между новостью и мерчантом.

3. «96 HOT LEAD, но только 4 совпадения»
   → Раньше top_examples обрезался до 5 ДО агрегации по приоритетному
     списку, из-за чего реальные совпадения терялись. Теперь полный
     список совпадений сохраняется, обрезка только в самом конце для UI.
   → Также теперь явно показывается: сколько ВСЕГО совпало по фильтру,
     и сколько из них реально показано — никаких скрытых обрезаний.

4. «Слишком много пустых карточек» — это лечится в app.py (UI), не здесь,
   но модуль теперь возвращает явный 'has_match' флаг для фильтрации.

ЧЕСТНО про точность связки (не изменилось):
  Совпадение — это сигнал для приоритизации ручной проверки, не доказательство
  причастности. Каждый сигнал подписан явно, ничего не скрыто за чёрным ящиком.
"""

import os
import json
from datetime import datetime

LINKED_CACHE_PATH = 'data/entity_links.json'

# Ключевые слова в названии мерчанта, повышающие релевантность для разных
# категорий угроз — НЕ доказательство, а дополнительный сигнал для скоринга
NAME_KEYWORDS_BY_CATEGORY = {
    'crypto': ['crypto', 'bitcoin', 'btc', 'eth', 'exchange', 'obmen', 'p2p', 'usdt', 'binance'],
    'gaming': ['casino', 'bet', 'stake', 'gambling', 'poker', 'игра', 'ставк'],
    'sanctions': ['trade', 'export', 'import', 'logistics', 'трейд'],
}

ISO_TO_NAMES = {
    'KZ': ['kazakhstan', 'kz'], 'RU': ['russia', 'ru'], 'UZ': ['uzbekistan', 'uz'],
    'AE': ['uae', 'united arab emirates', 'ae'], 'KH': ['cambodia', 'kh'],
    'CN': ['china', 'cn'], 'BY': ['belarus', 'by'], 'KG': ['kyrgyzstan', 'kg'],
    'TJ': ['tajikistan', 'tj'], 'TR': ['turkey', 'tr'], 'GE': ['georgia', 'ge'],
    'AM': ['armenia', 'am'], 'AZ': ['azerbaijan', 'az'],
}


def _find_col(df, candidates):
    return next((c for c in candidates if c in df.columns), None)


def link_items_to_merchants(items: list[dict], df_agg) -> list[dict]:
    """
    Для каждого item находит мерчантов клиента, совпадающих по MCC и/или стране,
    и СРАЗУ ранжирует их по composite score с явным объяснением каждой причины.

    Returns:
        items с полем 'matched_merchants':
        {
            'total_count': int,           # сколько ВСЕГО совпало по MCC/стране
            'by_mcc': {mcc: count},
            'by_country': {country: count},
            'ranked_examples': [{merchant_id, mcc, country, probability, tier,
                                 score, match_reasons}, ...],  # ПОЛНЫЙ список
            'hot_count': int,
            'has_match': bool,
        }
    """
    if df_agg is None or len(df_agg) == 0:
        for it in items:
            it['matched_merchants'] = None
        return items

    mcc_col     = _find_col(df_agg, ['dominant_mcc', 'mcc'])
    country_col = _find_col(df_agg, ['dominant_country', 'country'])
    id_col      = _find_col(df_agg, ['merchant_id']) or df_agg.columns[0]
    prob_col    = 'probability' if 'probability' in df_agg.columns else None
    tier_col    = 'tier' if 'tier' in df_agg.columns else None
    name_col    = _find_col(df_agg, ['merchant_name', 'name', 'business_name'])
    night_col   = _find_col(df_agg, ['night_ratio'])
    growth_col  = _find_col(df_agg, ['monthly_growth_rate', 'growth_rate'])

    for it in items:
        mcc_codes = [str(c).strip() for c in it.get('mcc_codes', []) if c]
        countries = [str(c).strip().upper() for c in it.get('countries', []) if c]
        risk_kw   = [str(k).strip() for k in it.get('risk_keywords', []) if k]
        category  = it.get('category', '')

        if not mcc_codes and not countries:
            it['matched_merchants'] = None
            continue

        mask = None
        if mcc_codes and mcc_col:
            mcc_mask = df_agg[mcc_col].astype(str).isin(mcc_codes)
            mask = mcc_mask if mask is None else (mask | mcc_mask)
        if countries and country_col:
            name_variants = set()
            for c in countries:
                name_variants.update(ISO_TO_NAMES.get(c, [c.lower()]))
            country_mask = df_agg[country_col].astype(str).str.lower().isin(name_variants)
            mask = country_mask if mask is None else (mask | country_mask)

        if mask is None or not mask.any():
            it['matched_merchants'] = {
                'total_count': 0, 'by_mcc': {}, 'by_country': {},
                'ranked_examples': [], 'hot_count': 0, 'has_match': False,
            }
            continue

        result_df = df_agg[mask]
        total_count = int(len(result_df))

        by_mcc = {}
        if mcc_codes and mcc_col:
            for mcc in mcc_codes:
                cnt = int((result_df[mcc_col].astype(str) == mcc).sum())
                if cnt > 0:
                    by_mcc[mcc] = cnt
        by_country = {}
        if countries and country_col:
            for c in countries:
                variants = ISO_TO_NAMES.get(c, [c.lower()])
                cnt = int(result_df[country_col].astype(str).str.lower().isin(variants).sum())
                if cnt > 0:
                    by_country[c] = cnt

        # ── COMPOSITE SCORE: ранжируем ВСЕХ совпавших, не только топ-5 ──────
        keyword_pool = list(risk_kw)
        if category in NAME_KEYWORDS_BY_CATEGORY:
            keyword_pool += NAME_KEYWORDS_BY_CATEGORY[category]

        scored = []
        for _, row in result_df.iterrows():
            score = 0.0
            reasons = []

            if mcc_col and str(row.get(mcc_col, '')) in mcc_codes:
                score += 1.0
                reasons.append(f"MCC {row.get(mcc_col)} совпадает с новостью")
            if country_col:
                row_country = str(row.get(country_col, '')).lower()
                for c in countries:
                    if row_country in ISO_TO_NAMES.get(c, [c.lower()]):
                        score += 1.0
                        reasons.append(f"Страна {row.get(country_col)} упомянута в новости")
                        break

            if name_col and keyword_pool:
                merchant_name = str(row.get(name_col, '')).lower()
                for kw in keyword_pool:
                    if kw.lower() in merchant_name:
                        score += 2.0
                        reasons.append(f"Название содержит «{kw}»")
                        break

            if growth_col and growth_col in row.index:
                try:
                    growth = float(row.get(growth_col, 0))
                    if growth > 2.0:
                        score += 1.5
                        reasons.append(f"Резкий рост оборота ({growth:.1f}x за период)")
                except (ValueError, TypeError):
                    pass

            if night_col and night_col in row.index:
                try:
                    night = float(row.get(night_col, 0))
                    if night > 0.5:
                        score += 0.8
                        reasons.append(f"{night*100:.0f}% транзакций ночью")
                except (ValueError, TypeError):
                    pass

            if prob_col:
                prob = float(row.get(prob_col, 0))
                if prob >= 75:
                    score += 1.2
                    reasons.append(f"Уже HOT по внутренней модели ({prob:.0f}%)")
                elif prob >= 50:
                    score += 0.5
                    reasons.append(f"WARM по внутренней модели ({prob:.0f}%)")

            ex = {
                'merchant_id': str(row.get(id_col, '?')),
                'score': round(score, 2),
                'match_reasons': reasons,
            }
            if mcc_col: ex['mcc'] = str(row.get(mcc_col, '?'))
            if country_col: ex['country'] = str(row.get(country_col, '?'))
            if prob_col: ex['probability'] = round(float(row.get(prob_col, 0)), 1)
            if tier_col: ex['tier'] = str(row.get(tier_col, '?'))
            scored.append(ex)

        scored.sort(key=lambda x: x['score'], reverse=True)

        it['matched_merchants'] = {
            'total_count': total_count,
            'by_mcc': by_mcc,
            'by_country': by_country,
            'ranked_examples': scored,
            'hot_count': int((result_df[tier_col] == 'HOT').sum()) if tier_col else 0,
            'has_match': total_count > 0,
        }

    return items


def get_priority_action_list(items: list[dict], max_items: int = 20) -> list[dict]:
    """
    «Кого проверить первым» — берёт ВСЕХ совпавших мерчантов (не обрезанный
    топ-5 на уровне отдельной новости), объединяет по мерчанту через все
    релевантные новости, считает совокупный score.
    """
    candidates = {}

    for it in items:
        if it.get('relevance') not in ('HIGH', 'MEDIUM'):
            continue
        mm = it.get('matched_merchants')
        if not mm or not mm.get('has_match'):
            continue

        for ex in mm.get('ranked_examples', []):
            mid = ex['merchant_id']
            if mid not in candidates:
                candidates[mid] = {
                    **{k: v for k, v in ex.items() if k not in ('score', 'match_reasons')},
                    'total_score': 0.0,
                    'matched_news': [],
                    'max_relevance': it['relevance'],
                    'all_reasons': set(),
                }
            candidates[mid]['total_score'] += ex['score']
            candidates[mid]['all_reasons'].update(ex['match_reasons'])
            candidates[mid]['matched_news'].append({
                'title': it.get('title', ''),
                'relevance': it.get('relevance'),
                'source': it.get('source_name', ''),
                'link': it.get('link', ''),
                'reasons_for_this_news': ex['match_reasons'],
            })
            if it['relevance'] == 'HIGH':
                candidates[mid]['max_relevance'] = 'HIGH'
                candidates[mid]['total_score'] += 0.5

    result = []
    for mid, data in candidates.items():
        data['all_reasons'] = sorted(data['all_reasons'])
        result.append(data)

    result.sort(key=lambda x: x['total_score'], reverse=True)
    return result[:max_items]


def get_match_summary_stats(items: list[dict]) -> dict:
    """
    Честная статистика покрытия — отвечает на вопрос "почему только 4 из 96
    HOT": показывает сколько новостей вообще дали MCC/страну, и сколько
    из них реально пересеклись с базой клиента.
    """
    total_with_entities = 0
    total_with_matches = 0
    total_matched_merchants = set()

    for it in items:
        has_entities = bool(it.get('mcc_codes')) or bool(it.get('countries'))
        if has_entities:
            total_with_entities += 1
        mm = it.get('matched_merchants')
        if mm and mm.get('has_match'):
            total_with_matches += 1
            for ex in mm.get('ranked_examples', []):
                total_matched_merchants.add(ex['merchant_id'])

    return {
        'news_with_entities': total_with_entities,
        'news_with_matches': total_with_matches,
        'news_without_entities': len(items) - total_with_entities,
        'unique_merchants_matched': len(total_matched_merchants),
    }


def save_links_cache(items: list[dict]):
    os.makedirs('data', exist_ok=True)
    with open(LINKED_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump({'generated_at': datetime.now().isoformat(), 'items': items},
                  f, ensure_ascii=False, indent=2, default=str)
