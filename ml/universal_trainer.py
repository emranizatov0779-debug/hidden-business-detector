"""
ml/universal_trainer.py — Адаптивный ML под реальные транзакционные данные
===========================================================================
Колонки реального датасета:
  transaction_date, transaction_timestamp, transaction_amount_kzt,
  mcc, merchant_id, channel, bank_name, country, card_number,
  card_tier, tokenized, is_recurring

Без дат: строим паттерны по суммам, картам, каналам, банкам, регулярности.
С датами: добавляем ночную активность, рост оборота, частоту по дням.
"""
import os, json, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

SCHEMA_CACHE = 'data/detected_schema.json'


def detect_schema(df: pd.DataFrame) -> dict:
    schema = {
        'roles': {},
        'warnings': [],
        'row_count': len(df),
        'col_count': len(df.columns),
    }
    cols_lower = {c.lower().strip(): c for c in df.columns}

    ROLE_MAP = {
        'merchant_id':  ['merchant_id','mid','merch_id','merchant_no'],
        'amount':       ['transaction_amount_kzt','amount','sum','transaction_amount'],
        'mcc':          ['mcc','merchant_category','category_code'],
        'channel':      ['channel','payment_channel','tx_channel'],
        'country':      ['country','merchant_country'],
        'card_id':      ['card_number','card_id','card_no','payer_id'],
        'bank_name':    ['bank_name','issuer_bank','bank'],
        'card_tier':    ['card_tier','card_type','tier'],
        'is_recurring': ['is_recurring','recurring'],
        'tokenized':    ['tokenized','is_tokenized'],
        'timestamp':    ['transaction_timestamp','transaction_date','date','timestamp'],
    }
    for role, patterns in ROLE_MAP.items():
        for pat in patterns:
            for col_lower, col_orig in cols_lower.items():
                if pat == col_lower:
                    if role not in schema['roles']:
                        schema['roles'][role] = col_orig
                    break

    if 'merchant_id' not in schema['roles']:
        schema['warnings'].append('Нет колонки merchant_id — используем первую колонку')
    if 'amount' not in schema['roles']:
        schema['warnings'].append('Нет колонки с суммой — финансовые признаки недоступны')
    if 'timestamp' not in schema['roles']:
        schema['warnings'].append('Нет колонки с датой — временные признаки недоступны')

    # Проверяем заполненность дат
    ts_col = schema['roles'].get('timestamp')
    if ts_col and ts_col in df.columns:
        null_pct = df[ts_col].isnull().mean() * 100
        if null_pct > 90:
            schema['warnings'].append(
                f'Дата пустая на {null_pct:.0f}% — временные признаки недоступны для этого датасета'
            )
            schema['roles'].pop('timestamp', None)

    return schema


def build_features(df: pd.DataFrame, schema: dict) -> tuple:
    roles = schema['roles']
    feature_log = []

    mid_col = roles.get('merchant_id') or df.columns[0]
    amount_col  = roles.get('amount')
    mcc_col     = roles.get('mcc')
    channel_col = roles.get('channel')
    country_col = roles.get('country')
    card_col    = roles.get('card_id')
    bank_col    = roles.get('bank_name')
    tier_col    = roles.get('card_tier')
    recur_col   = roles.get('is_recurring')
    token_col   = roles.get('tokenized')
    ts_col      = roles.get('timestamp')

    pieces = [df.groupby(mid_col).size().rename('txn_count')]
    feature_log.append('✅ txn_count — количество транзакций')

    # ── Финансовые признаки ────────────────────────────────────────────────
    if amount_col and amount_col in df.columns:
        df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
        stats = df.groupby(mid_col)[amount_col].agg(
            avg_amount='mean', max_amount='max',
            total_amount='sum', std_amount='std',
            median_amount='median'
        )
        stats['amount_cv'] = (stats['std_amount'] / stats['avg_amount'].replace(0, np.nan)).fillna(0)
        # Низкий CV = подозрительно ровные суммы (дробление)
        pieces.append(stats[['avg_amount','max_amount','total_amount','amount_cv','median_amount']])
        feature_log.append('✅ avg_amount, total_amount, amount_cv (дробление)')

    # ── Уникальные плательщики ────────────────────────────────────────────
    if card_col and card_col in df.columns:
        unique_cards = df.groupby(mid_col)[card_col].nunique().rename('unique_cards')
        pieces.append(unique_cards)
        # Концентрация: один плательщик = подозрительно
        top_card_share = df.groupby(mid_col)[card_col].apply(
            lambda x: x.value_counts().iloc[0] / len(x) if len(x) > 0 else 0
        ).rename('top_card_share')
        pieces.append(top_card_share)
        feature_log.append('✅ unique_cards, top_card_share (концентрация плательщиков)')

    # ── Межбанковская диверсификация ──────────────────────────────────────
    if bank_col and bank_col in df.columns:
        unique_banks = df.groupby(mid_col)[bank_col].nunique().rename('unique_banks')
        pieces.append(unique_banks)
        feature_log.append('✅ unique_banks — деньги из N разных банков')

    # ── Канал: онлайн vs POS ─────────────────────────────────────────────
    if channel_col and channel_col in df.columns:
        online_ratio = df.groupby(mid_col)[channel_col].apply(
            lambda x: (x.str.lower() == 'online').mean()
        ).rename('online_ratio')
        pieces.append(online_ratio)
        feature_log.append('✅ online_ratio — доля онлайн транзакций')

    # ── Регулярные платежи ────────────────────────────────────────────────
    if recur_col and recur_col in df.columns:
        recur_series = df[recur_col].astype(str).str.lower().isin(['true','1','yes'])
        df['_is_recur'] = recur_series
        recurring_ratio = df.groupby(mid_col)['_is_recur'].mean().rename('recurring_ratio')
        pieces.append(recurring_ratio)
        feature_log.append('✅ recurring_ratio — доля регулярных платежей')

    # ── Tier плательщиков ─────────────────────────────────────────────────
    if tier_col and tier_col in df.columns:
        premium_ratio = df.groupby(mid_col)[tier_col].apply(
            lambda x: x.str.lower().isin(['gold','platinum','premium','business']).mean()
        ).rename('premium_card_ratio')
        pieces.append(premium_ratio)
        feature_log.append('✅ premium_card_ratio — доля премиальных карт')

    # ── Временные признаки (если есть даты) ──────────────────────────────
    if ts_col and ts_col in df.columns:
        try:
            df['_ts'] = pd.to_datetime(df[ts_col], errors='coerce')
            valid_ts = df['_ts'].notna().mean()
            if valid_ts > 0.1:
                df['_hour'] = df['_ts'].dt.hour
                night_mask = df['_hour'].between(22, 23) | df['_hour'].between(0, 5)
                night_ratio = df.groupby(mid_col).apply(
                    lambda g: night_mask.loc[g.index].mean()
                ).rename('night_ratio')
                pieces.append(night_ratio)
                feature_log.append('✅ night_ratio — доля ночных транзакций (22:00-06:00)')
        except Exception as e:
            feature_log.append(f'⛔ Временные признаки — ошибка: {e}')
    else:
        feature_log.append('⛔ night_ratio — нет дат в данных')

    # ── Категориальные: MCC, страна ───────────────────────────────────────
    for role_name, out_name in [('mcc','dominant_mcc'),('country','dominant_country')]:
        col = roles.get(role_name)
        if col and col in df.columns:
            dom = df.groupby(mid_col)[col].agg(
                lambda x: x.mode().iloc[0] if len(x.mode()) else None
            ).rename(out_name)
            pieces.append(dom)
            feature_log.append(f'✅ {out_name}')

    df_agg = pd.concat(pieces, axis=1).reset_index()
    df_agg = df_agg.rename(columns={mid_col: 'merchant_id'})

    # Заполняем NaN нулями только для числовых
    num_cols = df_agg.select_dtypes(include=[np.number]).columns
    df_agg[num_cols] = df_agg[num_cols].fillna(0)

    return df_agg, feature_log


def select_and_train(df_agg: pd.DataFrame, feature_cols: list) -> dict:
    n = len(df_agg)
    avail = [c for c in feature_cols if c in df_agg.columns
             and df_agg[c].dtype in (np.float64, np.int64, float, int)
             and df_agg[c].std() > 0]

    if n < 50 or len(avail) < 2:
        scores = pd.Series(30.0, index=df_agg.index)
        for col in avail:
            scores += df_agg[col].rank(pct=True) * (50 / max(len(avail), 1))
        return {
            'method': 'rules',
            'scores': scores.clip(0, 96),
            'explanation': f'Мало данных ({n} мерч.), перцентильные правила'
        }

    try:
        from sklearn.ensemble import IsolationForest
        from sklearn.preprocessing import RobustScaler

        X = df_agg[avail].fillna(0).values
        X_scaled = RobustScaler().fit_transform(X)
        contamination = min(0.15, max(0.02, 50/n))

        iso = IsolationForest(
            n_estimators=200 if n > 50000 else 100,
            contamination=contamination,
            random_state=42, n_jobs=-1
        )
        iso.fit(X_scaled)
        raw = iso.decision_function(X_scaled)
        normalized = (raw.max() - raw) / (raw.max() - raw.min() + 1e-9)
        return {
            'method': 'isolation_forest',
            'scores': pd.Series(normalized * 100, index=df_agg.index),
            'explanation': (
                f'IsolationForest: {n:,} мерчантов, {len(avail)} признаков: '
                f'{", ".join(avail[:6])}{"..." if len(avail)>6 else ""}. '
                f'Скор = аномальность транзакционного профиля (0=норма, 100=максимальная аномалия).'
            )
        }
    except ImportError:
        scores = pd.Series(30.0, index=df_agg.index)
        for col in avail:
            scores += df_agg[col].rank(pct=True) * (50 / max(len(avail), 1))
        return {'method': 'rules_fallback', 'scores': scores.clip(0, 96),
                'explanation': 'scikit-learn недоступен — перцентильные правила'}


def run_universal_pipeline(df_raw: pd.DataFrame) -> dict:
    schema = detect_schema(df_raw)
    os.makedirs('data', exist_ok=True)
    with open(SCHEMA_CACHE, 'w', encoding='utf-8') as f:
        json.dump(schema, f, ensure_ascii=False, indent=2, default=str)

    df_agg, feature_log = build_features(df_raw, schema)

    feature_cols = [c for c in df_agg.columns if c not in
                    ('merchant_id', 'dominant_mcc', 'dominant_country')]

    model_result = select_and_train(df_agg, feature_cols)
    df_agg['probability'] = model_result['scores'].round(1)
    df_agg['tier'] = pd.cut(
        df_agg['probability'],
        bins=[-1, 50, 75, 101],
        labels=['Low', 'Warm', 'HOT']
    )

    validation_lines = [
        f"📊 {schema['row_count']:,} транзакций → {len(df_agg):,} мерчантов",
        f"🤖 Модель: {model_result['method']}",
        f"   {model_result['explanation']}", "",
        "Построенные признаки:",
    ] + [f"  {line}" for line in feature_log]

    if schema['warnings']:
        validation_lines += ["", "⚠️ Предупреждения:"] + [f"  • {w}" for w in schema['warnings']]

    return {
        'df_agg': df_agg,
        'schema': schema,
        'feature_log': feature_log,
        'model_info': {
            'method': model_result['method'],
            'explanation': model_result['explanation']
        },
        'feature_cols': [c for c in feature_cols if c in df_agg.columns],
        'validation_report': '\n'.join(validation_lines),
    }
