"""
Универсальный trainer для Hidden Business Detector.
Автоматически определяет структуру любых транзакционных данных банка.
"""
import pandas as pd
import numpy as np
import os
import joblib
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.calibration import CalibratedClassifierCV


# ── СЛОВАРИ ДЛЯ АВТООПРЕДЕЛЕНИЯ КОЛОНОК ──────────────────────────────────────
AMOUNT_ALIASES = [
    'transaction_amount_kzt', 'amount', 'sum', 'amount_kzt',
    'txn_amount', 'transaction_amount', 'amt', 'payment_amount',
    'transaction_sum', 'операция_сумма', 'сумма'
]
MERCHANT_ALIASES = [
    'merchant_id', 'merchant', 'card_id', 'account_id',
    'client_id', 'card_number', 'id', 'мерчант_ид'
]
CHANNEL_ALIASES = ['channel', 'payment_channel', 'txn_channel', 'канал']
RECURRING_ALIASES = ['is_recurring', 'recurring', 'is_repeat', 'повтор']
COUNTRY_ALIASES = ['country', 'merchant_country', 'страна', 'region']
MCC_ALIASES = ['mcc', 'mcc_code', 'category_code', 'мсс']
BANK_ALIASES = ['bank_name', 'bank', 'bank_id', 'банк', 'issuer']
CARD_ALIASES = ['card_number', 'card_id', 'card', 'карта']
TIMESTAMP_ALIASES = [
    'transaction_timestamp', 'timestamp', 'datetime', 'created_at',
    'txn_date', 'date', 'дата', 'transaction_date'
]


def _find_col(df: pd.DataFrame, aliases: list) -> str | None:
    """Находит колонку по списку возможных имён (регистронезависимо)."""
    lower_cols = {c.lower(): c for c in df.columns}
    for alias in aliases:
        if alias.lower() in lower_cols:
            return lower_cols[alias.lower()]
    return None


def _detect_merchant_col(df: pd.DataFrame) -> str | None:
    """Определяет колонку с merchant_id — ищет колонку с достаточным числом уникальных значений."""
    explicit = _find_col(df, MERCHANT_ALIASES)
    if explicit:
        return explicit
    # Fallback: колонка типа object/int с разумным числом уникальных значений
    for col in df.columns:
        u = df[col].nunique()
        if 10 < u < len(df) * 0.5:
            return col
    return None


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Универсальная агрегация транзакций.
    Автоматически находит нужные колонки по алиасам.
    Работает с любой структурой транзакционных данных банка.
    """
    df = df.copy()

    # Определяем ключевые колонки
    merchant_col  = _detect_merchant_col(df)
    amount_col    = _find_col(df, AMOUNT_ALIASES)
    channel_col   = _find_col(df, CHANNEL_ALIASES)
    recurring_col = _find_col(df, RECURRING_ALIASES)
    country_col   = _find_col(df, COUNTRY_ALIASES)
    mcc_col       = _find_col(df, MCC_ALIASES)
    bank_col      = _find_col(df, BANK_ALIASES)
    card_col      = _find_col(df, CARD_ALIASES)
    ts_col        = _find_col(df, TIMESTAMP_ALIASES)

    # Если нет merchant_id — создаём синтетический
    if merchant_col is None:
        df['_merchant_id'] = 'UNKNOWN'
        merchant_col = '_merchant_id'

    # Нормализуем имя
    if merchant_col != 'merchant_id':
        df = df.rename(columns={merchant_col: 'merchant_id'})
        merchant_col = 'merchant_id'

    # Определяем: сырые транзакции или агрегированные?
    vc = df['merchant_id'].value_counts()
    if vc.max() <= 1:
        # Уже агрегированные — просто добавляем признаки
        return _ensure_features(df)

    # Сырые транзакции — агрегируем
    return _aggregate_raw(df, amount_col, channel_col, recurring_col,
                          country_col, mcc_col, bank_col, card_col, ts_col)


def _aggregate_raw(df, amount_col, channel_col, recurring_col,
                   country_col, mcc_col, bank_col, card_col, ts_col):
    """Агрегация сырых транзакций — универсальная для любых данных банка."""
    agg = {}

    # Сумма транзакций
    if amount_col and amount_col in df.columns:
        df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce').fillna(0)
        agg.update({
            'txn_count':    (amount_col, 'count'),
            'avg_amount':   (amount_col, 'mean'),
            'max_amount':   (amount_col, 'max'),
            'min_amount':   (amount_col, 'min'),
            'total_amount': (amount_col, 'sum'),
            'std_amount':   (amount_col, 'std'),
        })
    else:
        agg['txn_count'] = ('merchant_id', 'count')

    # Канал
    if channel_col and channel_col in df.columns:
        agg['online_ratio'] = (channel_col, lambda x: (x.astype(str).str.lower() == 'online').mean())
        agg['pos_ratio']    = (channel_col, lambda x: (x.astype(str).str.lower() == 'pos').mean())

    # Recurring
    if recurring_col and recurring_col in df.columns:
        try:
            df[recurring_col] = df[recurring_col].astype(bool).astype(float)
            agg['recurring_ratio'] = (recurring_col, 'mean')
        except Exception:
            pass

    # Страна
    if country_col and country_col in df.columns:
        agg['unique_countries'] = (country_col, 'nunique')
        agg['dominant_country'] = (country_col, lambda x: x.mode().iloc[0] if len(x) > 0 else 'Unknown')

    # MCC
    if mcc_col and mcc_col in df.columns:
        agg['unique_mcc'] = (mcc_col, 'nunique')
        agg['dominant_mcc'] = (mcc_col, lambda x: x.mode().iloc[0] if len(x) > 0 else 0)
        agg['mcc'] = (mcc_col, lambda x: x.mode().iloc[0] if len(x) > 0 else 0)

    # Банк
    if bank_col and bank_col in df.columns:
        agg['unique_banks'] = (bank_col, 'nunique')

    # Карта (число уникальных плательщиков)
    if card_col and card_col in df.columns and card_col != 'merchant_id':
        agg['unique_cards'] = (card_col, 'nunique')

    # Время
    if ts_col and ts_col in df.columns:
        try:
            df[ts_col] = pd.to_datetime(df[ts_col], errors='coerce')
            valid_ts = df[ts_col].dropna()
            if len(valid_ts) > len(df) * 0.1:  # хотя бы 10% непустых
                df['_hour']      = df[ts_col].dt.hour.fillna(12)
                df['_dayofweek'] = df[ts_col].dt.dayofweek.fillna(0)
                df['_ts_sec']    = df[ts_col].astype(np.int64).replace(-9223372036854775808, 0) // 10**9
                agg['night_ratio']   = ('_hour', lambda x: ((x >= 22) | (x <= 6)).mean())
                agg['weekend_ratio'] = ('_dayofweek', lambda x: (x >= 5).mean())
                agg['avg_interval_days'] = ('_ts_sec',
                    lambda x: float(x.sort_values().diff().dropna().mean() / 86400)
                              if len(x) > 1 else 30.0)
        except Exception:
            pass

    # Агрегируем
    result = df.groupby('merchant_id').agg(
        **{k: pd.NamedAgg(column=v[0], aggfunc=v[1]) for k, v in agg.items()}
    ).reset_index()

    return _ensure_features(result)


def _ensure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Гарантирует наличие всех нужных признаков, заполняет отсутствующие."""
    # Производные признаки
    if 'std_amount' in df.columns and 'avg_amount' in df.columns:
        df['std_amount'] = df['std_amount'].fillna(0)
        df['amount_cv']  = df['std_amount'] / (df['avg_amount'].replace(0, 1))
    elif 'amount_cv' not in df.columns:
        df['amount_cv'] = 0.0

    # Кодируем категории
    for src, tgt in [
        ('dominant_country', 'country_enc'),
        ('mcc', 'mcc_enc'),
        ('dominant_mcc', 'mcc_enc'),
    ]:
        if src in df.columns and tgt not in df.columns:
            le = LabelEncoder()
            df[tgt] = le.fit_transform(df[src].astype(str))

    # Гарантируем числовые поля
    required = {
        'txn_count': 1, 'avg_amount': 0, 'max_amount': 0,
        'total_amount': 0, 'std_amount': 0, 'amount_cv': 0,
        'unique_cards': 1, 'online_ratio': 0, 'recurring_ratio': 0,
        'pos_ratio': 0, 'unique_banks': 1, 'unique_mcc': 1,
        'unique_countries': 1, 'night_ratio': 0, 'weekend_ratio': 0,
        'avg_interval_days': 30, 'mcc_enc': 0, 'country_enc': 0,
    }
    for col, default in required.items():
        if col not in df.columns:
            df[col] = float(default)
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(float(default))

    return df


# Признаки для модели — используем те которые реально информативны
FEATURE_COLS = [
    'txn_count', 'avg_amount', 'max_amount', 'total_amount',
    'std_amount', 'amount_cv', 'unique_cards', 'online_ratio',
    'recurring_ratio', 'pos_ratio', 'unique_banks', 'unique_mcc',
    'night_ratio', 'weekend_ratio', 'avg_interval_days',
    'mcc_enc', 'country_enc',
]


def train_model(df: pd.DataFrame):
    """Обучает модель. Принимает сырые транзакции или агрегированные данные."""
    os.makedirs('models', exist_ok=True)
    df_agg    = engineer_features(df)
    feat_cols = [c for c in FEATURE_COLS if c in df_agg.columns]

    # Убираем константные признаки (все значения одинаковые)
    feat_cols = [c for c in feat_cols if df_agg[c].std() > 1e-8]

    if len(feat_cols) < 2:
        raise ValueError(f"Недостаточно информативных признаков: {feat_cols}")

    X = df_agg[feat_cols].fillna(0).values

    # Isolation Forest
    contamination = min(0.20, max(0.05, 20 / max(len(df_agg), 1)))
    iso = IsolationForest(n_estimators=150, contamination=contamination,
                          random_state=42, n_jobs=-1)
    iso_labels    = iso.fit_predict(X)
    pseudo_labels = (iso_labels == -1).astype(int)

    # RandomForest с калибровкой
    n_cv = min(3, max(2, pseudo_labels.sum() // 5))  # адаптивный cv
    base_clf = RandomForestClassifier(
        n_estimators=100, max_depth=7, min_samples_leaf=2,
        random_state=42, n_jobs=-1, class_weight='balanced'
    )
    if n_cv >= 2 and pseudo_labels.sum() >= 4:
        clf = CalibratedClassifierCV(base_clf, cv=n_cv, method='sigmoid')
    else:
        clf = base_clf
    clf.fit(X, pseudo_labels)

    joblib.dump({
        'model':    clf,
        'iso':      iso,
        'features': feat_cols,
    }, 'models/model.pkl')
    return clf, iso, feat_cols


def predict_scores(df: pd.DataFrame) -> pd.Series:
    """
    Возвращает Series: merchant_id → score (0.28-0.96).
    Принимает сырые транзакции или агрегированные данные.
    """
    if not os.path.exists('models/model.pkl'):
        return None

    bundle  = joblib.load('models/model.pkl')
    df_agg  = engineer_features(df)

    feat_cols = [c for c in bundle['features'] if c in df_agg.columns]
    X         = df_agg[feat_cols].fillna(0).values
    probs     = bundle['model'].predict_proba(X)[:, 1]

    # Нормализуем в диапазон 28-96%
    pmin, pmax = probs.min(), probs.max()
    if pmax > pmin:
        probs = (probs - pmin) / (pmax - pmin)
    probs = np.clip(0.28 + probs * 0.68, 0.28, 0.96)

    merchant_ids = df_agg['merchant_id'].values if 'merchant_id' in df_agg.columns else np.arange(len(probs))
    return pd.Series(probs, index=merchant_ids)


def get_aggregated(df: pd.DataFrame) -> pd.DataFrame:
    """Публичный метод — возвращает агрегированный DataFrame для pattern_discovery."""
    return engineer_features(df)
