"""
ml/merchant_profile.py — Единый профиль мерчанта
===================================================
Вместо того чтобы аналитик бегал по 4 вкладкам (Распределение → Internal Patterns
→ Adversarial Intel → Скрининг), собираем ВСЕ флаги в одном месте.

Ответ на вопрос "что с MER_001443?" должен давать одна страница:
  - Скор и его реальное объяснение (не просто цифра)
  - Все активные паттерны для этого мерчанта
  - Совпадения по санкциям / FATF / MCC
  - Совпадения с внешними новостями (Adversarial Intel)
  - Кластер похожих мерчантов
  - Рекомендуемое действие (одно конкретное, не шаблон)
"""

import os
import json
from datetime import datetime


def build_merchant_card(
    merchant_id: str,
    df_agg,
    patterns: list = None,
    screening_result: dict = None,
    adv_digest: dict = None,
    sem_results: dict = None,
) -> dict:
    """
    Собирает все доступные данные о мерчанте из разных модулей в единую структуру.

    Returns: dict с ключами:
        base: базовые поля (MCC, страна, вероятность, тир)
        score_factors: факторы, объясняющие скор (XAI)
        active_patterns: паттерны, в которые входит мерчант
        screening_flags: флаги санкций/FATF/MCC
        news_matches: совпадения с внешними новостями
        cluster: другие мерчанты с тем же паттерном (MCC+страна)
        recommended_action: одно конкретное действие
        risk_summary: итоговый уровень риска с обоснованием
    """
    if df_agg is None:
        return {}

    id_col      = next((c for c in ['merchant_id'] if c in df_agg.columns), df_agg.columns[0])
    mcc_col     = next((c for c in ['dominant_mcc', 'mcc'] if c in df_agg.columns), None)
    country_col = next((c for c in ['dominant_country', 'country'] if c in df_agg.columns), None)
    prob_col    = 'probability' if 'probability' in df_agg.columns else None
    tier_col    = 'tier' if 'tier' in df_agg.columns else None
    name_col    = next((c for c in ['merchant_name', 'name', 'business_name'] if c in df_agg.columns), None)

    # Ищем мерчанта
    mask = df_agg[id_col].astype(str).str.lower() == merchant_id.lower()
    if not mask.any():
        # Попробуем частичное совпадение
        mask = df_agg[id_col].astype(str).str.lower().str.contains(merchant_id.lower(), regex=False)
    if not mask.any():
        return {'error': f'Мерчант {merchant_id} не найден в базе'}

    row = df_agg[mask].iloc[0]

    mcc     = str(row.get(mcc_col, '?')) if mcc_col else '?'
    country = str(row.get(country_col, '?')) if country_col else '?'
    prob    = float(row.get(prob_col, 0)) if prob_col else 0
    tier    = str(row.get(tier_col, '?')) if tier_col else '?'
    name    = str(row.get(name_col, '')) if name_col else ''

    # ── Базовые поля ──────────────────────────────────────────────────────────
    base = {
        'merchant_id': str(row.get(id_col, merchant_id)),
        'merchant_name': name or 'Название не указано',
        'has_name': bool(name and name not in ('?', 'nan', 'None')),
        'mcc': mcc,
        'country': country,
        'probability': prob,
        'tier': tier,
    }

    # ── Объяснение скора (XAI) ───────────────────────────────────────────────
    # Честно: если trainer.py использует детерминированный хэш вместо ML,
    # то реальных факторов нет — показываем это прямо, не выдумываем.
    score_factors = []

    # Проверяем, есть ли числовые поля, которые реально объясняют скор
    numeric_candidates = {
        'txn_count': ('количество транзакций', 'ед.'),
        'avg_amount': ('средний чек', ''),
        'unique_cards': ('уникальных плательщиков', 'ед.'),
        'online_ratio': ('доля онлайн-платежей', '%', 100),
        'recurring_ratio': ('доля регулярных платежей', '%', 100),
        'amount_cv': ('волатильность сумм', ''),
        'night_ratio': ('доля ночных транзакций', '%', 100),
        'monthly_growth_rate': ('рост оборота', 'x'),
    }
    has_real_features = False
    for col, label_info in numeric_candidates.items():
        if col in df_agg.columns and col in row.index:
            try:
                val = float(row[col])
                if val > 0:
                    has_real_features = True
                    label = label_info[0]
                    unit = label_info[1]
                    multiplier = label_info[2] if len(label_info) > 2 else 1
                    display_val = val * multiplier
                    # Считаем перцентиль этого мерчанта
                    percentile = int((df_agg[col] <= val).mean() * 100)
                    if percentile >= 90:
                        score_factors.append({
                            'factor': label,
                            'value': f'{display_val:.1f}{unit}',
                            'context': f'top {100 - percentile}% среди всех мерчантов',
                            'weight': 'HIGH' if percentile >= 95 else 'MEDIUM',
                        })
            except (ValueError, TypeError):
                pass

    if not has_real_features:
        score_factors.append({
            'factor': 'ПРИМЕЧАНИЕ',
            'value': '-',
            'context': ('Скор рассчитан без транзакционных признаков — '
                       'только MCC + страна. Для реального XAI нужны '
                       'колонки: txn_count, avg_amount, unique_cards и т.д. '
                       'в загружаемом CSV.'),
            'weight': 'INFO',
        })

    # MCC как фактор (всегда показываем)
    from ml.sanctions_screener import HIGH_RISK_MCC
    if mcc in HIGH_RISK_MCC:
        mcc_info = HIGH_RISK_MCC[mcc]
        score_factors.insert(0, {
            'factor': f'MCC {mcc}',
            'value': mcc_info['label'],
            'context': f'Высокорисковая категория ({mcc_info["risk"]})',
            'weight': mcc_info['risk'],
        })

    # ── Активные паттерны этого мерчанта ─────────────────────────────────────
    active_patterns = []
    if patterns:
        for p in patterns:
            # Паттерн активен для мерчанта если его MCC или страна совпадают с условием
            threshold = p.get('threshold', '')
            mcc_in_threshold = mcc in threshold
            # Для known-схем проверяем через функцию если есть
            active_patterns.append({
                'name': p.get('name', ''),
                'risk': p.get('risk', ''),
                'type': p.get('type', ''),
                'description': p.get('description', ''),
                'bank_action': p.get('bank_action', ''),
                'mcc_matches': mcc_in_threshold,
            })
        # Оставляем только потенциально релевантные
        active_patterns = [p for p in active_patterns if p['mcc_matches']][:5]

    # ── Флаги скрининга ───────────────────────────────────────────────────────
    screening_flags = {
        'sanctions': [],
        'fatf': [],
        'high_risk_mcc': [],
    }
    if screening_result:
        mid = str(row.get(id_col, ''))
        for h in screening_result.get('sanctions_hits', []):
            if h.get('merchant_id') == mid:
                screening_flags['sanctions'].append(h)
        for h in screening_result.get('fatf_country_hits', []):
            if h.get('merchant_id') == mid:
                screening_flags['fatf'].append(h)
        for h in screening_result.get('high_risk_mcc_hits', []):
            if h.get('merchant_id') == mid:
                screening_flags['high_risk_mcc'].append(h)

    # ── Совпадения с новостями (Adversarial Intel) ────────────────────────────
    news_matches = []
    mid = str(row.get(id_col, ''))
    if adv_digest:
        for item in adv_digest.get('items', []):
            mm = item.get('matched_merchants', {})
            if mm and mm.get('has_match'):
                for ex in mm.get('ranked_examples', []):
                    if ex.get('merchant_id') == mid:
                        news_matches.append({
                            'title': item.get('title', ''),
                            'link': item.get('link', ''),
                            'relevance': item.get('relevance', ''),
                            'signal_type': item.get('signal_type', ''),
                            'score': ex.get('score', 0),
                            'reasons': ex.get('match_reasons', []),
                            'source': item.get('source_name', ''),
                        })
    if sem_results:
        for item_hash, matches in sem_results.items():
            for m in matches:
                if m.get('merchant_id') == mid and m.get('ai_score', 0) >= 40:
                    news_matches.append({
                        'title': f'[AI-матчинг] {m.get("ai_reasoning", "")}',
                        'link': '',
                        'relevance': 'HIGH' if (m.get('ai_score', 0) or 0) >= 70 else 'MEDIUM',
                        'signal_type': 'SEMANTIC',
                        'score': m.get('ai_score', 0),
                        'reasons': m.get('pre_reasons', []),
                        'source': 'AI Semantic Matcher',
                    })
    news_matches.sort(key=lambda x: -(x.get('score') or 0))

    # ── Кластер похожих мерчантов (MCC + страна) ─────────────────────────────
    cluster = []
    if mcc_col and country_col:
        similar = df_agg[
            (df_agg[mcc_col].astype(str) == mcc) &
            (df_agg[country_col].astype(str) == country) &
            (df_agg[id_col].astype(str) != mid)
        ]
        if prob_col:
            similar = similar.sort_values(prob_col, ascending=False)
        for _, s_row in similar.head(9).iterrows():
            cluster.append({
                'merchant_id': str(s_row.get(id_col, '?')),
                'probability': float(s_row.get(prob_col, 0)) if prob_col else None,
                'tier': str(s_row.get(tier_col, '?')) if tier_col else None,
                'name': str(s_row.get(name_col, '')) if name_col else '',
            })

    # ── Итоговый уровень риска и рекомендуемое действие ──────────────────────
    total_flags = (
        len(screening_flags['sanctions']) * 3 +
        len(screening_flags['fatf']) * 2 +
        (1 if mcc in HIGH_RISK_MCC and HIGH_RISK_MCC[mcc]['risk'] == 'CRITICAL' else 0) +
        len([n for n in news_matches if n.get('relevance') == 'HIGH'])
    )

    if screening_flags['sanctions']:
        risk_summary = 'CRITICAL — совпадение с санкционным списком, требует немедленной проверки'
        recommended_action = ('Немедленно: заморозить операции + уведомить комплаенс-офицера. '
                             f'Совпадение: {screening_flags["sanctions"][0].get("match_name","?")} '
                             f'(confidence: {screening_flags["sanctions"][0].get("confidence","?")})')
    elif screening_flags['fatf'] and any(f.get('risk_level') == 'BLACK_LIST' for f in screening_flags['fatf']):
        risk_summary = 'CRITICAL — транзакции со страной FATF Black List'
        recommended_action = 'Немедленно уведомить ФМС/регулятора. Операции со странами Black List требуют SAR.'
    elif tier == 'HOT' and len(news_matches) > 0:
        risk_summary = 'HIGH — HOT по модели + совпадение с внешними угрозами'
        recommended_action = (f'Приоритетная проверка: мерчант HOT по скоренгу И упоминается '
                             f'в контексте {news_matches[0]["title"][:60]}. Запросить документы.')
    elif tier == 'HOT':
        if active_patterns:
            risk_summary = f'HIGH — совпадение с паттерном «{active_patterns[0]["name"]}»'
            recommended_action = active_patterns[0].get('bank_action', 'Запросить KYC-документы')
        else:
            risk_summary = 'MEDIUM — HOT по скоренгу, но без дополнительных флагов'
            recommended_action = ('Ручная проверка: запросить выписку за последние 90 дней '
                                 'и уточнить основную деятельность.')
    else:
        risk_summary = f'{tier} — нет критических флагов'
        recommended_action = 'Мониторинг в штатном режиме'

    return {
        'base': base,
        'score_factors': score_factors,
        'active_patterns': active_patterns,
        'screening_flags': screening_flags,
        'news_matches': news_matches[:5],
        'cluster': cluster,
        'recommended_action': recommended_action,
        'risk_summary': risk_summary,
        'total_flags': total_flags,
        'built_at': datetime.now().isoformat(),
    }


def get_mcc_cluster_summary(df_agg) -> list[dict]:
    """
    Кластеризует мерчантов по MCC + страна и возвращает сводку кластеров.
    Вместо списка из 101 строки — 5-10 карточек с количеством и риском.

    Returns: список кластеров с {mcc, country, count, hot_count, avg_prob, action}
    """
    if df_agg is None:
        return []

    mcc_col     = next((c for c in ['dominant_mcc', 'mcc'] if c in df_agg.columns), None)
    country_col = next((c for c in ['dominant_country', 'country'] if c in df_agg.columns), None)
    prob_col    = 'probability' if 'probability' in df_agg.columns else None
    tier_col    = 'tier' if 'tier' in df_agg.columns else None
    id_col      = next((c for c in ['merchant_id'] if c in df_agg.columns), df_agg.columns[0])

    if not mcc_col or not country_col:
        return []

    from ml.sanctions_screener import HIGH_RISK_MCC

    # Только HOT и Warm — LOW не интересны для аналитика
    interesting = df_agg
    if tier_col:
        interesting = df_agg[df_agg[tier_col].isin(['HOT', 'Warm'])]

    if len(interesting) == 0:
        return []

    group_cols = [mcc_col, country_col]
    grouped = interesting.groupby(group_cols)

    clusters = []
    for (mcc, country), group in grouped:
        mcc_str = str(mcc)
        mcc_info = HIGH_RISK_MCC.get(mcc_str, {})
        hot_count = int((group[tier_col] == 'HOT').sum()) if tier_col else 0
        avg_prob = float(group[prob_col].mean()) if prob_col else 0

        # Гипотеза для кластера на основе MCC
        hypothesis = _generate_cluster_hypothesis(mcc_str, str(country), len(group), avg_prob)

        clusters.append({
            'mcc': mcc_str,
            'country': str(country),
            'count': int(len(group)),
            'hot_count': hot_count,
            'avg_prob': round(avg_prob, 1),
            'mcc_label': mcc_info.get('label', ''),
            'mcc_risk': mcc_info.get('risk', 'UNKNOWN'),
            'hypothesis': hypothesis,
            'merchant_ids': list(group[id_col].astype(str))[:20],
        })

    # Сортируем по риску и количеству HOT
    risk_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'UNKNOWN': 4}
    clusters.sort(key=lambda x: (risk_order.get(x['mcc_risk'], 4), -x['hot_count'], -x['avg_prob']))

    return clusters[:20]


def _generate_cluster_hypothesis(mcc: str, country: str, count: int, avg_prob: float) -> str:
    """
    Генерирует конкретную гипотезу для кластера — не шаблон, а привязанная
    к MCC и стране формулировка. Это то, что аналитик видит вместо
    абстрактного "проверьте KYC".
    """
    hypotheses = {
        ('4511', 'Kazakhstan'): f'{count} авиакомпаний KZ — проверить: чартерные рейсы без лицензии?',
        ('4511', 'China'): f'{count} авиакомпаний CN — проверить: P2P-переводы через авиатикеты?',
        ('4511', 'UAE'): f'{count} авиакомпаний UAE — проверить: транзитные схемы через ОАЭ?',
        ('5311', 'Kazakhstan'): f'{count} универмагов KZ — проверить: сплиттинг через кассы?',
        ('7011', 'Netherlands'): f'{count} отелей NL — проверить: фиктивные бронирования для вывода?',
        ('7011', 'UAE'): f'{count} отелей UAE — проверить: легализация через гостиничный сектор?',
        ('6051', 'Kazakhstan'): f'{count} крипто-мерчантов KZ — проверить: P2P без лицензии?',
        ('7995', 'Kazakhstan'): f'{count} гемблинг-мерчантов KZ — проверить: нелегальный букмекер?',
    }
    key = (mcc, country)
    if key in hypotheses:
        return hypotheses[key]
    # Общая формулировка если конкретной нет
    return (f'{count} мерчантов MCC {mcc} / {country} — '
            f'проверить общую бизнес-деятельность и связи между владельцами')
