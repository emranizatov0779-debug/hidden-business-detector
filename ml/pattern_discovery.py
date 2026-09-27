"""
ml/pattern_discovery.py
=======================
Паттерны скрытого бизнеса — основаны на реальном распределении данных.
Пороги рассчитываются динамически из перцентилей загруженного датасета.
"""
import pandas as pd
import numpy as np
import json
import os

PATTERNS_CACHE = 'data/patterns.json'


def _pct(series, p):
    """Возвращает перцентиль серии."""
    return float(np.percentile(series.dropna(), p))


def discover_new_patterns(df_agg: pd.DataFrame, force: bool = False) -> list:
    """
    Находит паттерны скрытого бизнеса на основе реального распределения данных.
    Пороги рассчитываются динамически — результат зависит от конкретных данных.
    """
    if not force and os.path.exists(PATTERNS_CACHE):
        try:
            with open(PATTERNS_CACHE, encoding='utf-8') as f:
                cached = json.load(f)
            if cached:
                return cached
        except Exception:
            pass

    if df_agg is None or df_agg.empty:
        return []

    results = []
    n = len(df_agg)
    id_col = 'merchant_id' if 'merchant_id' in df_agg.columns else df_agg.columns[0]

    def get_merchants(mask):
        matched = df_agg[mask].copy()
        matched = matched.sort_values('probability', ascending=False) if 'probability' in matched.columns else matched
        return [
            {
                'merchant_id': str(row[id_col]),
                'probability': round(float(row.get('probability', 0)), 1),
                'tier': str(row.get('tier', '?')),
                'mcc': str(row.get('dominant_mcc', '?')),
                'country': str(row.get('dominant_country', '?')),
                'trigger_values': {
                    k: round(float(row[k]), 2) if isinstance(row.get(k), (int, float)) else str(row.get(k, ''))
                    for k in ['txn_count', 'unique_cards', 'unique_banks', 'online_ratio',
                              'total_amount', 'avg_amount', 'amount_cv', 'recurring_ratio']
                    if k in df_agg.columns
                }
            }
            for _, row in matched.head(20).iterrows()
        ]

    # ── 1. АНОМАЛЬНАЯ КОНЦЕНТРАЦИЯ ПЛАТЕЛЬЩИКОВ ───────────────────────────────
    # Мерчант получает деньги от числа карт значительно выше среднего
    if 'unique_cards' in df_agg.columns and 'txn_count' in df_agg.columns:
        cards_p85 = _pct(df_agg['unique_cards'], 85)  # верхние 15%
        txn_p70   = _pct(df_agg['txn_count'], 70)
        # Отношение уникальных карт к транзакциям — показывает широту охвата
        df_agg['_cards_ratio'] = df_agg['unique_cards'] / df_agg['txn_count'].clip(lower=1)
        ratio_p85 = _pct(df_agg['_cards_ratio'], 85)

        mask = (
            (df_agg['unique_cards'] > cards_p85) &
            (df_agg['_cards_ratio'] > ratio_p85) &
            (df_agg['txn_count'] > txn_p70)
        )
        matched = df_agg[mask]
        if len(matched) > 0 and len(matched) < n * 0.15:  # не больше 15% базы
            results.append({
                'id': 'high_card_concentration',
                'name': 'Аномальная концентрация плательщиков',
                'description': (
                    f'Мерчант получает платежи от аномально большого числа уникальных карт '
                    f'(порог: >{cards_p85:.0f} карт, верхние 15% по базе). '
                    f'Широкий охват плательщиков нетипичен для физлица — признак агрегации платежей.'
                ),
                'why_suspicious': (
                    f'Медиана по базе: {_pct(df_agg["unique_cards"], 50):.0f} карт. '
                    f'Эти мерчанты имеют >{cards_p85:.0f} карт — статистически аномально.'
                ),
                'risk': 'HIGH',
                'bank_action': 'Запросить подтверждение вида деятельности и регистрацию ИП/ТОО',
                'matched_count': len(matched),
                'match_rate_pct': round(len(matched) / n * 100, 1),
                'merchants': get_merchants(mask),
                'threshold': f'unique_cards > {cards_p85:.0f} AND cards/txn_ratio > {ratio_p85:.2f}',
                'type': 'known',
            })

    # ── 2. ДРОБЛЕНИЕ СУММ ─────────────────────────────────────────────────────
    # Очень низкий коэффициент вариации сумм = все платежи одинаковые
    if 'amount_cv' in df_agg.columns and 'txn_count' in df_agg.columns:
        cv_p10  = _pct(df_agg['amount_cv'], 10)   # нижние 10% — самые "ровные"
        txn_p60 = _pct(df_agg['txn_count'], 60)

        mask = (
            (df_agg['amount_cv'] < cv_p10) &
            (df_agg['txn_count'] > txn_p60) &
            (df_agg['amount_cv'] > 0)  # исключаем нулевую дисперсию (ошибка данных)
        )
        matched = df_agg[mask]
        if len(matched) > 0 and len(matched) < n * 0.12:
            avg_cv = float(df_agg['amount_cv'].mean())
            results.append({
                'id': 'amount_structuring',
                'name': 'Дробление — ровные суммы платежей',
                'description': (
                    f'Мерчант принимает платежи с аномально низкой вариацией сумм '
                    f'(CV < {cv_p10:.2f}, нижние 10% по базе). '
                    f'Ровные суммы от разных плательщиков — признак схемы дробления или сбора фиксированных взносов.'
                ),
                'why_suspicious': (
                    f'Средний CV по базе: {avg_cv:.2f}. '
                    f'У этих мерчантов CV < {cv_p10:.2f} — суммы подозрительно одинаковые.'
                ),
                'risk': 'CRITICAL',
                'bank_action': 'Запросить назначения платежей, проверить на схему дробления',
                'matched_count': len(matched),
                'match_rate_pct': round(len(matched) / n * 100, 1),
                'merchants': get_merchants(mask),
                'threshold': f'amount_cv < {cv_p10:.3f} AND txn_count > {txn_p60:.0f}',
                'type': 'known',
            })

    # ── 3. ОНЛАЙН-АНОМАЛИЯ ────────────────────────────────────────────────────
    # Аномально высокая доля онлайн-транзакций
    if 'online_ratio' in df_agg.columns:
        online_p90 = _pct(df_agg['online_ratio'], 90)  # верхние 10%
        online_p10 = _pct(df_agg['online_ratio'], 10)  # нижние 10%
        online_mean = float(df_agg['online_ratio'].mean())

        # Почти 100% онлайн
        mask_high = (df_agg['online_ratio'] >= online_p90) & (df_agg['txn_count'] > _pct(df_agg['txn_count'], 50))
        matched_high = df_agg[mask_high]
        if len(matched_high) > 0 and len(matched_high) < n * 0.12:
            results.append({
                'id': 'online_only',
                'name': 'Исключительно онлайн-транзакции',
                'description': (
                    f'Мерчант проводит >{online_p90*100:.0f}% транзакций онлайн '
                    f'(верхние 10% по базе, средняя по базе: {online_mean*100:.0f}%). '
                    f'Отсутствие POS-транзакций при большом обороте — признак онлайн-агрегатора или виртуального бизнеса.'
                ),
                'why_suspicious': (
                    f'Средняя доля онлайн: {online_mean*100:.0f}%. '
                    f'Аномально высокая онлайн-доля (>{online_p90*100:.0f}%).'
                ),
                'risk': 'MEDIUM',
                'bank_action': 'Верифицировать наличие физической точки продаж',
                'matched_count': len(matched_high),
                'match_rate_pct': round(len(matched_high) / n * 100, 1),
                'merchants': get_merchants(mask_high),
                'threshold': f'online_ratio >= {online_p90:.2f}',
                'type': 'known',
            })

        # Почти 0% онлайн при большом обороте — также аномалия
        if 'total_amount' in df_agg.columns:
            amount_p80 = _pct(df_agg['total_amount'], 80)
            mask_low = (
                (df_agg['online_ratio'] <= online_p10) &
                (df_agg['total_amount'] > amount_p80)
            )
            matched_low = df_agg[mask_low]
            if len(matched_low) > 0 and len(matched_low) < n * 0.08:
                results.append({
                    'id': 'cash_heavy_high_volume',
                    'name': 'Высокий оборот без онлайн-транзакций',
                    'description': (
                        f'Мерчант имеет большой оборот (>{amount_p80/1e6:.1f}M тенге) '
                        f'но почти нет онлайн-платежей (<{online_p10*100:.0f}%). '
                        f'Нетипично для современного бизнеса — возможен нал или обход цифровых каналов.'
                    ),
                    'why_suspicious': 'Высокий оборот через POS без онлайн нетипичен для большинства легальных бизнесов.',
                    'risk': 'MEDIUM',
                    'bank_action': 'Проверить соответствие деятельности транзакционному профилю',
                    'matched_count': len(matched_low),
                    'match_rate_pct': round(len(matched_low) / n * 100, 1),
                    'merchants': get_merchants(mask_low),
                    'threshold': f'online_ratio <= {online_p10:.2f} AND total_amount > {amount_p80:.0f}',
                    'type': 'known',
                })

    # ── 4. АНОМАЛЬНЫЙ ОБОРОТ ─────────────────────────────────────────────────
    # Мерчанты с оборотом в топ-5% но средним чеком в нижних 30%
    if 'total_amount' in df_agg.columns and 'avg_amount' in df_agg.columns:
        amount_p95  = _pct(df_agg['total_amount'], 95)
        avg_amt_p30 = _pct(df_agg['avg_amount'], 30)

        mask = (
            (df_agg['total_amount'] > amount_p95) &
            (df_agg['avg_amount'] < avg_amt_p30)
        )
        matched = df_agg[mask]
        if len(matched) > 0 and len(matched) < n * 0.07:
            results.append({
                'id': 'micro_payment_aggregator',
                'name': 'Крупный оборот через микроплатежи',
                'description': (
                    f'Мерчант входит в топ-5% по обороту (>{amount_p95/1e6:.1f}M тенге) '
                    f'но средний чек ниже 30-го перцентиля (<{avg_amt_p30:,.0f} тенге). '
                    f'Паттерн характерен для P2P агрегаторов, нелегальных букмекеров и криптообменников.'
                ),
                'why_suspicious': (
                    f'Топ-5% по обороту но низкий средний чек — '
                    f'признак большого числа мелких транзакций от разных лиц.'
                ),
                'risk': 'HIGH',
                'bank_action': 'Проверить источники поступлений, запросить документы о деятельности',
                'matched_count': len(matched),
                'match_rate_pct': round(len(matched) / n * 100, 1),
                'merchants': get_merchants(mask),
                'threshold': f'total_amount > {amount_p95:.0f} AND avg_amount < {avg_amt_p30:.0f}',
                'type': 'known',
            })

    # ── 5. АНОМАЛЬНО ВЫСОКАЯ РЕГУЛЯРНОСТЬ ────────────────────────────────────
    if 'recurring_ratio' in df_agg.columns and 'unique_cards' in df_agg.columns:
        recur_p85   = _pct(df_agg['recurring_ratio'], 85)
        cards_p60   = _pct(df_agg['unique_cards'], 60)

        mask = (
            (df_agg['recurring_ratio'] > recur_p85) &
            (df_agg['unique_cards'] > cards_p60)
        )
        matched = df_agg[mask]
        if len(matched) > 0 and len(matched) < n * 0.15:
            results.append({
                'id': 'recurring_anomaly',
                'name': 'Аномальная регулярность платежей',
                'description': (
                    f'>{recur_p85*100:.0f}% транзакций помечены как регулярные (recurring) '
                    f'при широкой базе плательщиков (верхние 15% и 40% соответственно). '
                    f'Нетипично если мерчант не является сервисом подписки или коммунальной службой.'
                ),
                'why_suspicious': (
                    f'Высокая регулярность от многих разных карт = автоматизированный сбор средств.'
                ),
                'risk': 'MEDIUM',
                'bank_action': 'Проверить MCC на соответствие подписочной модели, запросить договоры',
                'matched_count': len(matched),
                'match_rate_pct': round(len(matched) / n * 100, 1),
                'merchants': get_merchants(mask),
                'threshold': f'recurring_ratio > {recur_p85:.2f} AND unique_cards > {cards_p60:.0f}',
                'type': 'known',
            })

    # ── 6. ИНОСТРАННЫЕ ТРАНЗАКЦИИ ─────────────────────────────────────────────
    if 'dominant_country' in df_agg.columns:
        foreign = df_agg[df_agg['dominant_country'].str.lower().isin(
            ['us', 'usa', 'united states', 'uae', 'china', 'russia', 'ru']
        )]
        if 'total_amount' in df_agg.columns and len(foreign) > 0:
            amount_p70 = _pct(df_agg['total_amount'], 70)
            mask = (
                df_agg['dominant_country'].str.lower().isin(
                    ['us', 'usa', 'united states', 'uae', 'china', 'russia', 'ru']
                ) & (df_agg['total_amount'] > amount_p70)
            )
            matched = df_agg[mask]
            if len(matched) > 0 and len(matched) < n * 0.15:
                results.append({
                    'id': 'foreign_high_volume',
                    'name': 'Крупные транзакции из иностранных юрисдикций',
                    'description': (
                        f'{len(matched)} мерчантов получают основной поток из иностранных '
                        f'юрисдикций (US, UAE, China, RU) с оборотом выше медианы. '
                        f'Повышенный риск санкционных нарушений и обхода валютного контроля.'
                    ),
                    'why_suspicious': 'Иностранные транзакции при высоком обороте требуют проверки источника.',
                    'risk': 'HIGH',
                    'bank_action': 'Запросить обоснование иностранных платежей, проверить санкционные списки',
                    'matched_count': len(matched),
                    'match_rate_pct': round(len(matched) / n * 100, 1),
                    'merchants': get_merchants(mask),
                    'threshold': 'dominant_country IN (US, UAE, China, RU) AND high total_amount',
                    'type': 'known',
                })

    # Сортируем по риску
    risk_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
    results.sort(key=lambda x: risk_order.get(x['risk'], 4))

    # Сохраняем
    os.makedirs('data', exist_ok=True)
    with open(PATTERNS_CACHE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    return results
