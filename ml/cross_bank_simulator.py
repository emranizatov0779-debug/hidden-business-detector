"""ml/cross_bank_simulator.py — Симуляция кросс-банкового эффекта"""
import random
from datetime import datetime

def simulate_cross_bank_effect(df_agg, n_virtual_banks: int = 3, seed: int = 42) -> dict:
    if df_agg is None or len(df_agg) < 20:
        return {'is_simulation': True, 'error': 'Недостаточно данных (нужно минимум 20 мерчантов)'}
    rng = random.Random(seed)
    indices = list(range(len(df_agg))); rng.shuffle(indices)
    chunk_size = len(df_agg) // n_virtual_banks
    chunks = [indices[i*chunk_size:(i+1)*chunk_size] for i in range(n_virtual_banks)]
    if len(indices) > chunk_size * n_virtual_banks: chunks[-1] += indices[chunk_size*n_virtual_banks:]
    mcc_col     = next((c for c in ['dominant_mcc','mcc'] if c in df_agg.columns), None)
    country_col = next((c for c in ['dominant_country','country'] if c in df_agg.columns), None)
    tier_col    = 'tier' if 'tier' in df_agg.columns else None
    isolated_view = {}; isolated_clusters = {}
    for i, chunk_idx in enumerate(chunks):
        bank_id = f'Банк-{chr(65+i)}'
        chunk_df = df_agg.iloc[chunk_idx]
        hot_count = int((chunk_df[tier_col] == 'HOT').sum()) if tier_col else 0
        clusters = set()
        if mcc_col and country_col:
            g = chunk_df.groupby([mcc_col, country_col]).size()
            clusters = set(g[g >= 2].index)
        isolated_view[bank_id] = {'total': len(chunk_df), 'hot_count': hot_count, 'visible_clusters': len(clusters)}
        isolated_clusters[bank_id] = clusters
    combined_clusters = set()
    if mcc_col and country_col:
        g_all = df_agg.groupby([mcc_col, country_col]).size()
        combined_clusters = set(g_all[g_all >= 2].index)
    total_hot = int((df_agg[tier_col] == 'HOT').sum()) if tier_col else 0
    union_isolated = set().union(*isolated_clusters.values())
    only_combined = combined_clusters - union_isolated
    combined_view = {
        'total': len(df_agg), 'hot_count': total_hot,
        'visible_clusters': len(combined_clusters),
        'clusters_invisible_alone': len(only_combined),
        'example_hidden_clusters': [{'mcc': str(c[0]), 'country': str(c[1])} for c in list(only_combined)[:5]],
    }
    best_alone = max((v['visible_clusters'] for v in isolated_view.values()), default=0)
    pct_more = round((len(combined_clusters) - best_alone) / max(len(combined_clusters), 1) * 100)
    return {
        'is_simulation': True, 'n_virtual_banks': n_virtual_banks,
        'isolated_view': isolated_view, 'combined_view': combined_view,
        'pct_additional_clusters_visible': pct_more,
        'explanation': (
            f"⚠️ СИМУЛЯЦИЯ на ваших же данных, разделённых на {n_virtual_banks} части — "
            f"НЕ реальные данные других банков. "
            f"При объединении видно на {pct_more}% больше кластеров риска."
        ),
        'calculated_at': datetime.now().isoformat(),
    }

def get_consortium_roadmap() -> list:
    return [
        {'phase': 'Фаза 0 (сейчас)', 'status': 'done',
         'description': 'Симуляция эффекта на собственных данных. Демонстрирует ценность без партнёров.'},
        {'phase': 'Фаза 1 — Pilot с 2 банками', 'status': 'requires_partnership',
         'description': 'Обмен ТОЛЬКО агрегированной статистикой (count по MCC+country), не raw data. '
                       'Требует юридического соглашения об обмене анонимизированной статистикой.'},
        {'phase': 'Фаза 2 — Federated statistics (3-5 банков)', 'status': 'requires_infrastructure',
         'description': 'Secure aggregation протокол. Банки не видят данные друг друга, только итоговую сумму.'},
        {'phase': 'Фаза 3 — Отраслевой консорциум', 'status': 'future',
         'description': 'Участие регулятора как наблюдателя — аналог FinCEN 314(b) в США.'},
    ]
