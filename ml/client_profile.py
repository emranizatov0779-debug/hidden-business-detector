"""ml/client_profile.py — Профиль клиента."""
from datetime import datetime


def get_transaction_profile(merchant_id, df_agg):
    if df_agg is None or df_agg.empty:
        return {}
    row = df_agg[df_agg['merchant_id'] == merchant_id]
    if row.empty:
        return {}
    r = row.iloc[0].to_dict()
    return {
        'merchant_id':      merchant_id,
        'risk_score':       round(float(r.get('probability', 0)), 1),
        'risk_tier':        str(r.get('tier', '?')),
        'txn_count':        int(r.get('txn_count', 0)),
        'total_amount':     round(float(r.get('total_amount', 0)), 0),
        'avg_amount':       round(float(r.get('avg_amount', 0)), 0),
        'unique_cards':     int(r.get('unique_cards', 0)),
        'unique_banks':     int(r.get('unique_banks', 0)),
        'online_ratio':     round(float(r.get('online_ratio', 0)) * 100, 1),
        'recurring_ratio':  round(float(r.get('recurring_ratio', 0)) * 100, 1),
        'amount_cv':        round(float(r.get('amount_cv', 0)), 2),
        'dominant_mcc':     str(r.get('dominant_mcc', '?')),
        'dominant_country': str(r.get('dominant_country', '?')),
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


def build_full_profile(merchant_id, df_agg, patterns=None, screening_result=None):
    txn = get_transaction_profile(merchant_id, df_agg)

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
