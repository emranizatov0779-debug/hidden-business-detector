"""
html_report.py — HTML-отчёт для регулятора (без внешних зависимостей)
======================================================================
Решает проблему "экспорт PDF/Excel не работает из-за PEP 668 на macOS".

Подход: генерируем самодостаточный HTML-файл с встроенными стилями.
Пользователь открывает в браузере и делает Ctrl+P → Print to PDF.
Это работает везде без единого `pip install`.

Дополнительно: CSV-экспорт тоже здесь — как fallback к HTML.
"""

from datetime import datetime


def _esc(s: str) -> str:
    return (str(s)
            .replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def generate_html_report(
    df_stats: dict,
    patterns: list,
    screening_result: dict = None,
    ext_intel: dict = None,
    cluster_summary: list = None,
) -> str:
    """
    Генерирует полный HTML-отчёт. Возвращает строку HTML.
    Никаких зависимостей кроме стандартной библиотеки Python.
    """
    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    screening = screening_result or {}

    # ── CSS ───────────────────────────────────────────────────────────────────
    css = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', Arial, sans-serif; color: #1a2332;
           background: #f8fafc; padding: 24px; }
    .header { background: linear-gradient(135deg,#0d3b8e,#1565c0);
              color: white; padding: 28px 32px; border-radius: 12px;
              margin-bottom: 24px; }
    .header h1 { font-size: 1.6rem; margin-bottom: 4px; }
    .header p  { opacity: 0.82; font-size: 0.9rem; }
    .section { background: white; border-radius: 10px; padding: 20px 24px;
               margin-bottom: 18px; border: 1px solid #e2e8f0;
               box-shadow: 0 2px 6px rgba(0,0,0,0.04); }
    .section h2 { font-size: 1rem; color: #1565c0; margin-bottom: 14px;
                  padding-bottom: 8px; border-bottom: 2px solid #c5d8f0; }
    .kpi-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; }
    .kpi { background: #f0f4fa; border-radius: 8px; padding: 14px 16px;
           border-left: 4px solid #1565c0; }
    .kpi .label { font-size: 0.7rem; color: #5b7a9d; text-transform: uppercase;
                  letter-spacing: 0.5px; }
    .kpi .value { font-size: 1.6rem; font-weight: 700; color: #0d1f35; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th { background: #1565c0; color: white; padding: 8px 12px;
         text-align: left; font-weight: 600; }
    td { padding: 7px 12px; border-bottom: 1px solid #e8edf5; }
    tr:hover td { background: #f0f4fa; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
             font-size: 0.72rem; font-weight: 600; }
    .critical { background: #fce4e4; color: #b71c1c; }
    .high     { background: #fff3e0; color: #e65100; }
    .medium   { background: #fffde7; color: #7a5500; }
    .low      { background: #f0fdf4; color: #14532d; }
    .cluster-card { background: #f8fafc; border-radius: 8px; padding: 14px 16px;
                    margin-bottom: 10px; border-left: 4px solid #1565c0; }
    .cluster-card h3 { font-size: 0.9rem; color: #0d1f35; margin-bottom: 4px; }
    .cluster-card p  { font-size: 0.82rem; color: #5b7a9d; }
    .flag-note { font-size: 0.78rem; color: #5b7a9d; margin-top: 8px; }
    .page-break { page-break-before: always; }
    @media print {
        body { padding: 0; background: white; }
        .header { border-radius: 0; }
        .no-print { display: none; }
    }
    """

    # ── ШАПКА ─────────────────────────────────────────────────────────────────
    header_html = f"""
    <div class="header">
        <h1>🔍 Hidden Business Detector — Аналитический отчёт</h1>
        <p>Cashless Avengers · Дата формирования: {now} · CONFIDENTIAL</p>
    </div>
    <p class="no-print" style="color:#5b7a9d;font-size:0.82rem;margin-bottom:16px;">
        💡 Для сохранения в PDF: Ctrl+P → «Сохранить как PDF» · Рекомендуем альбомную ориентацию
    </p>
    """

    # ── KPI ───────────────────────────────────────────────────────────────────
    total      = df_stats.get('total', 0)
    hot        = df_stats.get('hot', 0)
    warm       = df_stats.get('warm', 0)
    low        = df_stats.get('low', 0)
    hot_pct    = round(hot / total * 100, 1) if total else 0
    sc_hits    = len(screening.get('sanctions_hits', []))
    fatf_hits  = len(screening.get('fatf_country_hits', []))
    mcc_crit   = sum(1 for h in screening.get('high_risk_mcc_hits', []) if h.get('risk') == 'CRITICAL')

    kpi_html = f"""
    <div class="section">
        <h2>Сводная статистика</h2>
        <div class="kpi-grid">
            <div class="kpi"><div class="label">Всего мерчантов</div><div class="value">{total:,}</div></div>
            <div class="kpi" style="border-color:#b71c1c;">
                <div class="label">HOT LEAD</div>
                <div class="value" style="color:#b71c1c;">{hot:,} ({hot_pct}%)</div>
            </div>
            <div class="kpi" style="border-color:#e65100;">
                <div class="label">WARM LEAD</div>
                <div class="value" style="color:#e65100;">{warm:,}</div>
            </div>
            <div class="kpi" style="border-color:#14532d;">
                <div class="label">LOW риск</div>
                <div class="value" style="color:#14532d;">{low:,}</div>
            </div>
        </div>
    </div>
    """

    if sc_hits or fatf_hits or mcc_crit:
        kpi_html += f"""
    <div class="section" style="border-left:4px solid #b71c1c;">
        <h2 style="color:#b71c1c;">🚨 Флаги скрининга</h2>
        <div class="kpi-grid">
            <div class="kpi" style="border-color:#b71c1c;">
                <div class="label">Санкционных совпадений</div>
                <div class="value" style="color:#b71c1c;">{sc_hits}</div>
            </div>
            <div class="kpi" style="border-color:#e65100;">
                <div class="label">FATF Grey/Black List</div>
                <div class="value" style="color:#e65100;">{fatf_hits}</div>
            </div>
            <div class="kpi" style="border-color:#7c3aed;">
                <div class="label">CRITICAL MCC</div>
                <div class="value" style="color:#7c3aed;">{mcc_crit}</div>
            </div>
            <div class="kpi">
                <div class="label">Схем обнаружено</div>
                <div class="value">{len(patterns)}</div>
            </div>
        </div>
    </div>
    """

    # ── КЛАСТЕРЫ ──────────────────────────────────────────────────────────────
    clusters_html = ''
    if cluster_summary:
        cards = ''.join([
            f"""<div class="cluster-card">
                <h3>MCC {_esc(c['mcc'])} · {_esc(c['country'])} — {c['count']} мерчантов
                    <span class="badge {c['mcc_risk'].lower()}">{c['mcc_risk']}</span>
                </h3>
                <p>{_esc(c.get('mcc_label',''))} · HOT: {c['hot_count']} · Средняя вер.: {c['avg_prob']}%</p>
                <p style="color:#1565c0;margin-top:4px;">💡 {_esc(c['hypothesis'])}</p>
            </div>"""
            for c in cluster_summary[:10]
        ])
        clusters_html = f'<div class="section"><h2>🎯 Кластеры риска (HOT+WARM)</h2>{cards}</div>'

    # ── ПАТТЕРНЫ ──────────────────────────────────────────────────────────────
    pat_rows = ''.join([
        f"""<tr>
            <td><span class="badge {'critical' if p.get('risk')=='CRITICAL' else 'high' if p.get('risk')=='HIGH' else 'medium'}">{_esc(p.get('risk',''))}</span></td>
            <td>{_esc(p.get('name',''))}</td>
            <td>{p.get('matched_count',0):,} ({p.get('match_rate_pct',0)}%)</td>
            <td>{_esc(p.get('description',''))[:120]}...</td>
            <td>{_esc(p.get('bank_action',''))[:80]}</td>
        </tr>"""
        for p in sorted(patterns, key=lambda x: {'CRITICAL':0,'HIGH':1,'MEDIUM':2}.get(x.get('risk',''),3))[:30]
    ])
    patterns_html = f"""
    <div class="section page-break">
        <h2>🔍 Обнаруженные схемы ({len(patterns)} паттернов)</h2>
        <table>
            <tr><th>Риск</th><th>Схема</th><th>Мерчантов</th><th>Описание</th><th>Действие банка</th></tr>
            {pat_rows if pat_rows else '<tr><td colspan="5">Паттерны не обнаружены</td></tr>'}
        </table>
    </div>
    """ if patterns else ''

    # ── САНКЦИИ ───────────────────────────────────────────────────────────────
    sc_html = ''
    if sc_hits:
        rows = ''.join([
            f"""<tr>
                <td>{_esc(h['merchant_id'])}</td>
                <td>{_esc(h.get('merchant_name',''))}</td>
                <td><span class="badge {'critical' if h.get('confidence')=='HIGH' else 'medium'}">{_esc(h.get('confidence',''))}</span></td>
                <td>{_esc(h.get('match_name',''))}</td>
                <td>{_esc(h.get('datasets',''))}</td>
                <td>{h.get('probability','')}</td>
                <td>{_esc(h.get('tier',''))}</td>
            </tr>"""
            for h in screening.get('sanctions_hits', [])[:50]
        ])
        sc_html = f"""
        <div class="section page-break" style="border-top:4px solid #b71c1c;">
            <h2 style="color:#b71c1c;">🚫 Санкционные совпадения (требуют ручной проверки)</h2>
            <p class="flag-note">⚠️ Все совпадения требуют ручной верификации.
            HIGH confidence = точное совпадение после нормализации. MEDIUM/LOW = частичное.</p>
            <table>
                <tr><th>ID</th><th>Название</th><th>Уверенность</th>
                    <th>Совпадение</th><th>Списки</th><th>Вер-ть %</th><th>Тир</th></tr>
                {rows}
            </table>
        </div>"""

    # ── FATF ──────────────────────────────────────────────────────────────────
    fatf_html = ''
    if fatf_hits:
        rows = ''.join([
            f"""<tr>
                <td>{_esc(h['merchant_id'])}</td>
                <td>{_esc(h['country_name'])} ({h['country_iso']})</td>
                <td><span class="badge {'critical' if h.get('risk_level')=='BLACK_LIST' else 'high'}">{_esc(h.get('risk_level',''))}</span></td>
                <td>{h.get('probability','')}</td>
                <td>{_esc(h.get('tier',''))}</td>
            </tr>"""
            for h in screening.get('fatf_country_hits', [])
        ])
        fatf_html = f"""
        <div class="section" style="border-top:4px solid #e65100;">
            <h2 style="color:#e65100;">🌍 FATF Grey/Black List</h2>
            <table>
                <tr><th>ID</th><th>Страна</th><th>Статус</th><th>Вер-ть %</th><th>Тир</th></tr>
                {rows}
            </table>
        </div>"""

    # ── ПОДПИСЬ ───────────────────────────────────────────────────────────────
    footer = f"""
    <div style="text-align:center;color:#8aaccc;font-size:0.75rem;
                margin-top:32px;padding-top:16px;border-top:1px solid #c5d8f0;">
        Hidden Business Detector · Cashless Avengers 2026 · {now} · CONFIDENTIAL
    </div>
    """

    html = f"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HBD Report · {now}</title>
<style>{css}</style>
</head><body>
{header_html}{kpi_html}{clusters_html}{patterns_html}{sc_html}{fatf_html}{footer}
</body></html>"""

    return html


def generate_csv_report(df_stats: dict, patterns: list, screening_result: dict = None) -> str:
    """CSV-отчёт как fallback или дополнение к HTML."""
    lines = [
        '# Hidden Business Detector — Отчёт',
        f'# Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}',
        '',
        '## СТАТИСТИКА',
        f'Всего мерчантов,{df_stats.get("total",0)}',
        f'HOT LEAD,{df_stats.get("hot",0)}',
        f'WARM LEAD,{df_stats.get("warm",0)}',
        f'LOW риск,{df_stats.get("low",0)}',
        '',
        '## ПАТТЕРНЫ',
        'Риск,Название,Мерчантов,Доля %,Описание,Действие',
    ]
    for p in patterns:
        lines.append(
            f'{p.get("risk","")},{_esc(p.get("name","")).replace(",",";")},'
            f'{p.get("matched_count",0)},{p.get("match_rate_pct",0)},'
            f'"{p.get("description","")[:100]}",'
            f'"{p.get("bank_action","")[:80]}"'
        )

    sc = screening_result or {}
    if sc.get('sanctions_hits'):
        lines += ['', '## САНКЦИОННЫЕ СОВПАДЕНИЯ',
                  'ID,Название,Совпадение,Уверенность,Списки,Вероятность,Тир']
        for h in sc['sanctions_hits']:
            lines.append(
                f'{h["merchant_id"]},{_esc(h.get("merchant_name",""))},'
                f'{_esc(h.get("match_name",""))},{h.get("confidence","")},'
                f'{_esc(h.get("datasets",""))},{h.get("probability","")},'
                f'{h.get("tier","")}'
            )
    if sc.get('fatf_country_hits'):
        lines += ['', '## FATF GREY/BLACK LIST', 'ID,Страна,ISO,Статус,Вероятность,Тир']
        for h in sc['fatf_country_hits']:
            lines.append(
                f'{h["merchant_id"]},{h["country_name"]},{h["country_iso"]},'
                f'{h.get("risk_level","")},{h.get("probability","")},{h.get("tier","")}'
            )

    return '\n'.join(lines)
