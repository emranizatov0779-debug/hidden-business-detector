"""ml/roi_calculator.py"""
from datetime import datetime

DEFAULT_ASSUMPTIONS = {
    "avg_regulatory_fine_usd": 15000,
    "fine_probability_per_unchecked_hot": 0.02,
    "compliance_hourly_cost_usd": 25,
    "manual_check_hours_per_merchant": 1.5,
    "reputation_incident_cost_usd": 50000,
    "reputation_incidents_per_year": 0.3,
    "platform_annual_cost_usd": 24000,
}

def calculate_roi(df_stats, screening_summary=None, assumptions=None):
    a = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}
    hot   = df_stats.get("hot", 0)
    warm  = df_stats.get("warm", 0)
    total = df_stats.get("total", 0)
    sc    = (screening_summary or {}).get("sanctions_hits", 0)
    fatf  = (screening_summary or {}).get("fatf_country_hits", 0)

    fines = round(hot * a["fine_probability_per_unchecked_hot"] * a["avg_regulatory_fine_usd"])
    fines += round((sc + fatf) * a["avg_regulatory_fine_usd"] * 0.3)
    ops   = round(max(0, total*0.1 - (hot+warm)*0.3) * a["manual_check_hours_per_merchant"] * a["compliance_hourly_cost_usd"])
    rep   = round(a["reputation_incident_cost_usd"] * a["reputation_incidents_per_year"] * (hot / max(total,1)) * 10)

    total_val = fines + ops + rep
    return {
        "categories": [
            {"label": "Избежание штрафов регулятора", "value_usd": fines,
             "formula": f"{hot} HOT x {a['fine_probability_per_unchecked_hot']*100:.0f}% x ${a['avg_regulatory_fine_usd']:,}",
             "detail": f"Риск на {hot} необработанных HOT"},
            {"label": "Снижение издержек комплаенс-отдела", "value_usd": ops,
             "formula": f"Экономия часов x ${a['compliance_hourly_cost_usd']}/час",
             "detail": f"Приоритизация {hot+warm} кейсов вместо выборки из {total}"},
            {"label": "Снижение репутационного риска", "value_usd": rep,
             "formula": f"${a['reputation_incident_cost_usd']:,} x {a['reputation_incidents_per_year']} x доля HOT",
             "detail": "HOT = риск инцидента, не возможность продажи"},
        ],
        "total_value_usd": total_val,
        "platform_cost_usd": a["platform_annual_cost_usd"],
        "net_roi_usd": total_val - a["platform_annual_cost_usd"],
        "roi_multiple": round(total_val / max(a["platform_annual_cost_usd"], 1), 1),
        "calculated_at": datetime.now().isoformat(),
        "disclaimer": "Оценка на основе предположений. Замените на реальные цифры банка.",
    }
