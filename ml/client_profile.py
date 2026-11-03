"""ml/client_profile.py — Профиль клиента."""
from datetime import datetime
import pandas as pd


def get_transaction_profile(merchant_id, df_agg, df_raw=None):
    """Строит транзакционный профиль мерчанта.

    Если df_agg содержит агрегированные колонки — берём оттуда.
    Если нет (например, dagg содержит только merchant_id/probability/tier) —
    вычисляем напрямую из df_raw.
    """
    # --- Пробуем взять из df_agg ---
    agg_row = None
    if df_agg is not None and not df_agg.empty and 'merchant_id' in df_agg.columns:
        rows = df_agg[df_agg['merchant_id'] == merchant_id]
        if not rows.empty:
            agg_row = rows.iloc[0].to_dict()

    if agg_row is None:
        return {}

    # Базовые поля (всегда есть в dagg)
    risk_score = round(float(agg_row.get('probability', 0)), 1)
    risk_tier  = str(agg_row.get('tier', '?'))

    # Агрегированные поля — могут отсутствовать если universal_trainer не отработал
    has_agg = 'txn_count' in agg_row and agg_row.get('txn_count', 0) != 0

    if has_agg:
        txn_count      = int(agg_row.get('txn_count', 0))
        total_amount   = round(float(agg_row.get('total_amount', 0)), 0)
        avg_amount     = round(float(agg_row.get('avg_amount', 0)), 0)
        unique_cards   = int(agg_row.get('unique_cards', 0))
        unique_banks   = int(agg_row.get('unique_banks', 0))
        online_ratio   = round(float(agg_row.get('online_ratio', 0)) * 100, 1)
        recurring_ratio= round(float(agg_row.get('recurring_ratio', 0)) * 100, 1)
        amount_cv      = round(float(agg_row.get('amount_cv', 0)), 2)
        dominant_mcc   = str(agg_row.get('dominant_mcc', agg_row.get('mcc', '?')))
        dominant_country = str(agg_row.get('dominant_country', agg_row.get('country', '?')))
    elif df_raw is not None and not df_raw.empty:
        # Вычисляем из сырых данных
        mid_col = 'merchant_id' if 'merchant_id' in df_raw.columns else df_raw.columns[0]
        sub = df_raw[df_raw[mid_col] == merchant_id]
        if sub.empty:
            # Попробуем строковое сравнение
            sub = df_raw[df_raw[mid_col].astype(str) == str(merchant_id)]

        if sub.empty:
            return {}

        amount_col = next((c for c in ['transaction_amount_kzt', 'amount', 'sum', 'transaction_amount'] if c in sub.columns), None)
        card_col   = next((c for c in ['card_number', 'card_id', 'card'] if c in sub.columns), None)
        bank_col   = next((c for c in ['bank_name', 'bank', 'bank_id'] if c in sub.columns), None)
        channel_col= next((c for c in ['channel', 'transaction_channel'] if c in sub.columns), None)
        mcc_col    = next((c for c in ['mcc', 'dominant_mcc'] if c in sub.columns), None)
        country_col= next((c for c in ['country', 'dominant_country'] if c in sub.columns), None)
        recur_col  = next((c for c in ['is_recurring', 'recurring'] if c in sub.columns), None)

        txn_count = len(sub)
        if amount_col:
            amounts = pd.to_numeric(sub[amount_col], errors='coerce').dropna()
            total_amount = round(float(amounts.sum()), 0)
            avg_amount   = round(float(amounts.mean()), 0) if len(amounts) else 0
            amount_cv    = round(float(amounts.std() / amounts.mean()), 2) if amounts.mean() > 0 else 0
        else:
            total_amount = avg_amount = amount_cv = 0

        unique_cards  = int(sub[card_col].nunique()) if card_col else 0
        unique_banks  = int(sub[bank_col].nunique()) if bank_col else 0

        if channel_col:
            online_ratio = round(float((sub[channel_col].str.lower() == 'online').mean()) * 100, 1)
        else:
            online_ratio = 0.0

        if recur_col:
            recurring_ratio = round(float(pd.to_numeric(sub[recur_col], errors='coerce').fillna(0).mean()) * 100, 1)
        else:
            recurring_ratio = 0.0

        dominant_mcc     = str(sub[mcc_col].mode().iloc[0]) if mcc_col and len(sub[mcc_col].mode()) else '?'
        dominant_country = str(sub[country_col].mode().iloc[0]) if country_col and len(sub[country_col].mode()) else '?'
    else:
        return {}

    return {
        'merchant_id':      merchant_id,
        'risk_score':       risk_score,
        'risk_tier':        risk_tier,
        'txn_count':        txn_count,
        'total_amount':     total_amount,
        'avg_amount':       avg_amount,
        'unique_cards':     unique_cards,
        'unique_banks':     unique_banks,
        'online_ratio':     online_ratio,
        'recurring_ratio':  recurring_ratio,
        'amount_cv':        amount_cv,
        'dominant_mcc':     dominant_mcc,
        'dominant_country': dominant_country,
        'source': 'transaction_data',
    }


def _external_source(label, description, fields, path, roadmap):
    return {
        'label': label,
        'status': 'pending_integration',
        'description': description,
        'fields_when_connected': fields,
        'integration_path': path,
        'roadmap': roadmap,
    }


def build_full_profile(merchant_id, df_agg, patterns=None, screening_result=None, df_raw=None):
    txn = get_transaction_profile(merchant_id, df_agg, df_raw=df_raw)

    matched_patterns = []
    if patterns and isinstance(patterns, list):
        for p in patterns:
            if not isinstance(p, dict):
                continue
            merchants = p.get('merchants', [])
            if isinstance(merchants, list):
                for m in merchants:
                    if isinstance(m, dict) and m.get('merchant_id') == merchant_id:
                        matched_patterns.append({
                            'name': p.get('name', ''),
                            'risk': p.get('risk', ''),
                            'bank_action': p.get('bank_action', ''),
                        })
                        break

    sanctions_flags = []
    if screening_result and isinstance(screening_result, list):
        for item in screening_result:
            if not isinstance(item, dict):
                continue
            if item.get('merchant_id') == merchant_id and item.get('has_match'):
                sanctions_flags.append(item.get('match_type', 'Санкционное совпадение'))

    tier = txn.get('risk_tier', 'Low')
    if tier == 'HOT' or sanctions_flags:
        recommendation = {
            'action': 'Запросить документы',
            'priority': 'ВЫСОКИЙ',
            'reason': 'Высокий скор риска или санкционные совпадения',
            'documents': [
                'Паспорт / удостоверение личности',
                'Подтверждение вида деятельности',
                'Источник дохода',
                'Договоры с контрагентами',
            ],
        }
    elif tier == 'Warm':
        recommendation = {
            'action': 'Мониторинг',
            'priority': 'СРЕДНИЙ',
            'reason': 'Средний уровень риска — наблюдение без запроса документов',
            'documents': [],
        }
    else:
        recommendation = {
            'action': 'Без действий',
            'priority': 'НИЗКИЙ',
            'reason': 'Профиль соответствует норме',
            'documents': [],
        }

    return {
        'merchant_id': merchant_id,
        'transaction_profile': txn,
        'matched_patterns': matched_patterns,
        'sanctions_flags': sanctions_flags,
        'external_sources': {
            'gcvp': _external_source(
                'Пенсионные отчисления (ГЦВП)',
                'Показывает официальный доход. Если оборот значительно превышает задекларированный — индикатор скрытого бизнеса.',
                ['Ежемесячные отчисления (тенге)', 'Работодатель / статус самозанятого', 'Период отчислений', 'Расчётный годовой доход'],
                'Соглашение с ГЦВП → API ключ',
                'Q1 2027'
            ),
            'pkb': _external_source(
                'Кредитная история (ПКБ)',
                'Мерчант с крупным оборотом но без кредитной истории может указывать на использование чужих карт.',
                ['Количество активных кредитов', 'Суммарная задолженность', 'Просрочки', 'Кредитный скор'],
                'Договор с ПКБ → API ключ',
                'Q1 2027'
            ),
            'kgd': _external_source(
                'Налоговые данные (КГД МФ РК)',
                'Если оборот >4 млн тенге/год а ИП нет — нарушение налогового законодательства.',
                ['Статус ИП/ТОО', 'Налоговые задолженности', 'Режим налогообложения', 'БИН/ИИН соответствие'],
                'data.egov.kz API ключ',
                'Q4 2026 (приоритет)'
            ),
        },
        'recommendation': recommendation,
        'generated_at': datetime.now().isoformat(),
    }
