"""
app.py — Hidden Business Detector v2.2
=======================================
ИСПРАВЛЕНО:
  - External Intelligence теперь реально вызывает Claude API (не молчит при ошибке)
  - force=True всегда делает новый запрос, удаляет кэш перед запросом
  - Показывает реальные ошибки API вместо тихого fallback
НОВОЕ:
  - Federated Learning: внешние паттерны обогащаются статистикой из ваших данных
  - Scheduled refresh: автообновление External Intelligence каждые N часов
  - Export PDF / Excel: выгрузка отчёта для регулятора
  - Webhook alerts: уведомления в Telegram/Slack/Email при CRITICAL
"""

import streamlit as st
import pandas as pd
import numpy as np
import os, json, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from model_cache import should_reprocess, mark_processed

st.set_page_config(
    page_title="Hidden Business Detector",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ═══════════════════════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #e8edf5 !important; color: #1a2332; }
.main .block-container {
    max-width: 1380px;
    padding: 1rem 2rem 2rem 2rem;
    background: #e8edf5;
}
@keyframes gradientShift {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}
.platform-header {
    background: linear-gradient(135deg, #0d3b8e, #1565c0, #0288d1, #00acc1);
    background-size: 300% 300%;
    animation: gradientShift 8s ease infinite;
    border-radius: 16px; padding: 24px 32px; margin-bottom: 20px;
    position: relative; overflow: hidden;
    box-shadow: 0 4px 24px rgba(21,101,192,0.25);
}
.platform-header::before {
    content: ''; position: absolute; top: -40%; right: -5%;
    width: 300px; height: 300px;
    background: radial-gradient(circle, rgba(255,255,255,0.07) 0%, transparent 70%);
    border-radius: 50%;
}
.platform-header h1 { color:#fff; font-size:1.75rem; font-weight:700; margin:0 0 6px; line-height:1.2; }
.platform-header p  { color:rgba(255,255,255,0.82); margin:0; font-size:0.88rem; line-height:1.4; }
.platform-badge {
    display:inline-block; background:rgba(255,255,255,0.18); border:1px solid rgba(255,255,255,0.3);
    color:white; font-size:0.7rem; padding:3px 12px; border-radius:20px; margin-top:10px; font-weight:500;
}
.sec-h {
    color:#1565c0; font-size:1rem; font-weight:600;
    margin:22px 0 12px; padding-bottom:10px; border-bottom:2px solid #c5d8f0; line-height:1.3;
}
div[data-testid="metric-container"] {
    background:#fff !important; border-radius:14px; padding:18px 20px;
    border:1px solid #d1dce8; box-shadow:0 2px 10px rgba(0,0,0,0.05);
    transition:all 0.25s ease; min-height:90px;
}
div[data-testid="metric-container"]:hover {
    transform:translateY(-2px); box-shadow:0 6px 20px rgba(21,101,192,0.12); border-color:#90caf9;
}
div[data-testid="metric-container"] label {
    color:#5b7a9d !important; font-size:0.7rem !important; font-weight:600 !important;
    text-transform:uppercase; letter-spacing:0.6px; white-space:nowrap;
    overflow:hidden; text-overflow:ellipsis; display:block;
}
div[data-testid="metric-container"] [data-testid="metric-value"] {
    color:#0d1f35 !important; font-size:1.8rem !important; font-weight:700 !important;
    line-height:1.1; white-space:nowrap;
}
div[data-testid="metric-container"] [data-testid="metric-delta"] { font-size:0.78rem !important; margin-top:2px; }
.stButton > button {
    background:linear-gradient(135deg,#1565c0,#1976d2); color:white !important;
    border:none; border-radius:10px; padding:8px 20px; font-weight:500; font-size:0.83rem;
    transition:all 0.2s ease; box-shadow:0 2px 8px rgba(21,101,192,0.22); white-space:nowrap;
}
.stButton > button:hover {
    background:linear-gradient(135deg,#1976d2,#2196f3);
    box-shadow:0 4px 16px rgba(21,101,192,0.35); transform:translateY(-1px);
}
.stTabs [data-baseweb="tab-list"] {
    background:#dde5f0; border-radius:12px; padding:4px; gap:2px;
    border:1px solid #c5d8f0; flex-wrap:wrap;
}
.stTabs [data-baseweb="tab"] {
    color:#5b7a9d; border-radius:9px; font-size:0.8rem; font-weight:500;
    padding:7px 14px; transition:all 0.2s ease; white-space:nowrap;
}
.stTabs [aria-selected="true"] {
    background:linear-gradient(135deg,#1565c0,#1976d2) !important;
    color:white !important; box-shadow:0 2px 8px rgba(21,101,192,0.28);
}
.stTextInput > div > div > input {
    background:#fff; border:1.5px solid #c5d8f0; border-radius:10px;
    color:#1a2332; padding:10px 14px; font-size:0.85rem; transition:all 0.2s ease;
}
.stTextInput > div > div > input:focus {
    border-color:#1976d2; box-shadow:0 0 0 3px rgba(25,118,210,0.1);
}
div[data-testid="stDataFrame"] {
    border-radius:12px; border:1px solid #d1dce8; overflow:hidden;
    box-shadow:0 2px 6px rgba(0,0,0,0.04);
}
.streamlit-expanderHeader { background:#edf2f9; border-radius:10px; color:#1565c0; font-size:0.83rem; }
::-webkit-scrollbar { width:5px; height:5px; }
::-webkit-scrollbar-track { background:#e8edf5; }
::-webkit-scrollbar-thumb { background:#90b4d8; border-radius:3px; }
::-webkit-scrollbar-thumb:hover { background:#1976d2; }
#MainMenu { visibility:hidden; } footer { visibility:hidden; } header { visibility:hidden; }
.stAlert { border-radius:10px; font-size:0.84rem; }
.stRadio > div { gap:8px; flex-wrap:wrap; }
.stRadio label { font-size:0.84rem !important; }
.intel-card {
    background:#fff; border-radius:12px; padding:16px 20px; margin-bottom:12px;
    box-shadow:0 2px 8px rgba(0,0,0,0.05); border:1px solid #e2eaf5; transition:all 0.2s ease;
}
.intel-card:hover { box-shadow:0 4px 14px rgba(0,0,0,0.09); transform:translateY(-1px); }
@media (max-width:768px) {
    .main .block-container { padding-left:0.75rem; padding-right:0.75rem; }
    .platform-header { padding:16px 18px; }
    .platform-header h1 { font-size:1.3rem; }
    div[data-testid="metric-container"] [data-testid="metric-value"] { font-size:1.4rem !important; }
    .stTabs [data-baseweb="tab"] { font-size:0.72rem; padding:6px 10px; }
}
</style>
""", unsafe_allow_html=True)

CACHE_PATH = 'data/cached_df.parquet'
AGG_CACHE  = 'data/cached_agg.parquet'


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _render_client_profile_tab(df_u, df_stats):
    st.markdown(
        "<div style='background:#1a2332;border-radius:8px;padding:20px 24px;margin-bottom:16px;'>"
        "<div style='color:white;font-size:1rem;font-weight:600;'>Профиль клиента</div>"
        "<div style='color:rgba(255,255,255,0.7);font-size:0.82rem;'>"
        "Все сигналы по мерчанту в одном месте. Внешние источники подключаются по мере получения доступа."
        "</div></div>",
        unsafe_allow_html=True
    )

    if df_u is None or df_u.empty:
        st.info("Загрузите данные для анализа")
        return

    mc_col = 'merchant_id' if 'merchant_id' in df_u.columns else df_u.columns[0]

    col_search, col_quick = st.columns([2, 1])
    with col_search:
        merchant_id = st.text_input("ID мерчанта", placeholder="MER_000001", key="profile_mid")
    with col_quick:
        hot_merch = df_u[df_u['tier'] == 'HOT'][mc_col].tolist() if 'tier' in df_u.columns else []
        if hot_merch:
            if st.button(f"Случайный HOT ({len(hot_merch)})", key="profile_random_hot"):
                import random
                st.session_state['_profile_selected'] = random.choice(hot_merch)
                st.rerun()

    if not merchant_id and st.session_state.get('_profile_selected'):
        merchant_id = st.session_state['_profile_selected']

    if not merchant_id:
        if hot_merch:
            st.markdown("#### Топ HOT мерчантов")
            top = df_u[df_u['tier'] == 'HOT'].nlargest(10, 'probability') if 'probability' in df_u.columns else df_u[df_u['tier'] == 'HOT'].head(10)
            for _, row in top.iterrows():
                mid = str(row[mc_col])
                prob = float(row.get('probability', 0))
                mcc = str(row.get('dominant_mcc', '?'))
                if st.button(f"{mid}  —  риск {prob:.0f}%  —  MCC {mcc}", key=f"sel_{mid}"):
                    st.session_state['_profile_selected'] = mid
                    st.rerun()
        return

    st.markdown(f"### Мерчант: {merchant_id}")
    st.divider()

    from ml.client_profile import build_full_profile
    patterns = st.session_state.get('patterns') or []
    screening = st.session_state.get('screening_result')
    profile = build_full_profile(merchant_id, df_u, patterns, screening)

    txn = profile.get('transaction_profile', {})
    rec = profile.get('recommendation', {})

    if not txn:
        st.error(f"Мерчант {merchant_id} не найден в данных")
        return

    # Рекомендация
    priority = rec.get('priority', '')
    color = {'ВЫСОКИЙ': '#c0392b', 'СРЕДНИЙ': '#e67e22', 'НИЗКИЙ': '#27ae60'}.get(priority, '#666')
    docs_html = ""
    if rec.get('documents'):
        docs_html = "<div style='margin-top:8px;font-size:0.8rem;'><b>Запросить:</b> " + ", ".join(rec['documents']) + "</div>"
    st.markdown(
        f"<div style='background:{color}15;border-left:4px solid {color};border-radius:6px;"
        f"padding:14px 18px;margin-bottom:16px;'>"
        f"<div style='font-weight:700;color:{color};'>Рекомендация: {rec.get('action','')} — приоритет {priority}</div>"
        f"<div style='color:#444;font-size:0.83rem;margin-top:4px;'>{rec.get('reason','')}</div>"
        f"{docs_html}</div>",
        unsafe_allow_html=True
    )

    # Транзакционный профиль
    st.markdown("#### Транзакционный профиль")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("Скор риска", f"{txn.get('risk_score',0):.0f}%")
    with c2: st.metric("Tier", txn.get('risk_tier','?'))
    with c3: st.metric("Транзакций", f"{txn.get('txn_count',0):,}")
    with c4: st.metric("Оборот (тенге)", f"{txn.get('total_amount',0):,.0f}")
    with c5: st.metric("Уник. карт", f"{txn.get('unique_cards',0):,}")

    c6, c7, c8 = st.columns(3)
    with c6: st.metric("Банков", f"{txn.get('unique_banks',0):,}")
    with c7: st.metric("Онлайн", f"{txn.get('online_ratio',0):.0f}%")
    with c8: st.metric("MCC", txn.get('dominant_mcc','?'))

    # Паттерны
    matched = profile.get('matched_patterns', [])
    if matched:
        st.markdown("#### Совпадения с паттернами")
        for p in matched:
            risk_c = {'CRITICAL':'#c0392b','HIGH':'#e67e22','MEDIUM':'#f39c12'}.get(p.get('risk',''),'#666')
            st.markdown(
                f"<div style='border-left:3px solid {risk_c};padding:8px 12px;margin-bottom:6px;"
                f"background:#fafafa;border-radius:4px;'>"
                f"<span style='color:{risk_c};font-weight:600;'>{p.get('risk','')}</span>: {p.get('name','')}"
                f"<div style='font-size:0.78rem;color:#666;margin-top:2px;'>Действие: {p.get('bank_action','')}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

    sanctions = profile.get('sanctions_flags', [])
    if sanctions:
        st.error(f"Санкционные совпадения: {', '.join(sanctions)}")

    st.divider()

    # Внешние источники
    st.markdown("#### Внешние источники данных")
    st.caption("Архитектура готова к подключению. Требуется соглашение с организациями.")

    sources = profile.get('external_sources', {})
    for key, src in sources.items():
        label = src['label']
        with st.expander(f"{label} — Ожидает подключения"):
            st.markdown(f"**Что даёт:** {src['description']}")
            st.markdown("**Поля после подключения:** " + ", ".join(src.get('fields_when_connected', [])))
            col_p, col_r = st.columns(2)
            with col_p:
                st.info(f"Путь: {src.get('integration_path','')}")
            with col_r:
                st.caption(f"Roadmap: {src.get('roadmap','')}")


def _render_ai_sidebar():
    st.markdown("### AI-ассистент")
    saved_key = st.session_state.get('groq_api_key', '')
    if not saved_key:
        nk = st.text_input("Groq API ключ", placeholder="gsk_...",
                           type="password", key="groq_key_sb")
        if nk:
            st.session_state['groq_api_key'] = nk
            st.rerun()
        st.caption("Бесплатно: console.groq.com")
        return
    st.caption(f"Ключ: ...{saved_key[-6:]}")
    if st.button("Сменить", key="chg_key_sb"):
        st.session_state.pop('groq_api_key', None)
        st.rerun()
    if 'ai_hist' not in st.session_state:
        st.session_state.ai_hist = []
    with st.container(height=350):
        if not st.session_state.ai_hist:
            st.caption("Спросите про HOT LEAD, паттерны, скрининг...")
        for m in st.session_state.ai_hist:
            st.markdown(f"**{'Вы' if m['role']=='user' else 'AI'}:** {m['content']}")
    q = st.chat_input("Вопрос...", key="ai_q_sb")
    if q:
        st.session_state.ai_hist.append({'role': 'user', 'content': q})
        dagg = st.session_state.get('df_agg')
        ctx = f" Данные: {len(dagg)} мерч." if dagg is not None else ""
        sys_p = ("Ты ассистент Hidden Business Detector для банков Казахстана. "
                 "Платформа выявляет физлиц ведущих незарегистрированный бизнес. "
                 "HOT LEAD = риск >75%." + ctx + " Отвечай кратко на русском.")
        try:
            import urllib.request as _ur, json as _jj
            _pl = _jj.dumps({
                "model": "qwen/qwen3.8-27b",
                "messages": [{"role": "system", "content": sys_p}] +
                    [{"role": m["role"], "content": m["content"]}
                     for m in st.session_state.ai_hist[-6:]],
                "max_tokens": 350, "temperature": 0.3
            }).encode('utf-8')
            _rq = _ur.Request(
                'https://api.groq.com/openai/v1/chat/completions',
                data=_pl, method="POST",
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + saved_key,
                         "User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(_rq, timeout=20) as _rs:
                ans = _jj.loads(_rs.read().decode())["choices"][0]["message"]["content"]
        except Exception as e:
            ans = f"Ошибка: {e}"
        st.session_state.ai_hist.append({'role': 'assistant', 'content': ans})
        st.rerun()
    if st.session_state.ai_hist:
        if st.button("Очистить", key="clr_ai_sb"):
            st.session_state.ai_hist = []
            st.rerun()


def save_df(df):
    os.makedirs('data', exist_ok=True)
    s = df.copy()
    for c in s.select_dtypes(['category']).columns: s[c] = s[c].astype(str)
    s.to_parquet(CACHE_PATH, index=False)

def save_agg(df):
    os.makedirs('data', exist_ok=True)
    s = df.copy()
    for c in s.select_dtypes(['category']).columns: s[c] = s[c].astype(str)
    s.to_parquet(AGG_CACHE, index=False)

def load_df():
    if os.path.exists(CACHE_PATH):
        try: return pd.read_parquet(CACHE_PATH)
        except: return None
    return None

def load_agg():
    if os.path.exists(AGG_CACHE):
        try: return pd.read_parquet(AGG_CACHE)
        except: return None
    return None

def process_and_score(df_raw):
    """Universal trainer: auto-detects schema, builds features from available columns."""
    try:
        from ml.universal_trainer import run_universal_pipeline
        with st.spinner('🔍 Анализирую схему данных...'):
            result = run_universal_pipeline(df_raw)
        with st.expander('📋 Отчёт о схеме данных и модели', expanded=True):
            st.code(result['validation_report'], language=None)
        df_agg = result['df_agg']
        st.success(f"✅ {result['model_info']['method'].upper()} · {len(df_agg):,} мерчантов · {len(result['feature_cols'])} признаков")
        return df_raw, df_agg
    except Exception as e:
        st.warning(f'⚠️ Universal trainer недоступен ({e}), fallback на базовую агрегацию')
        mid_col = next((c for c in ['merchant_id'] if c in df_raw.columns), df_raw.columns[0])
        df_agg = df_raw.groupby(mid_col).size().reset_index(name='txn_count').rename(columns={mid_col:'merchant_id'})
        pct = df_agg['txn_count'].rank(pct=True)
        df_agg['probability'] = (pct * 80 + 10).round(1)
        df_agg['tier'] = pd.cut(df_agg['probability'], bins=[-1,50,75,101], labels=['Low','Warm','HOT'])
        for col in ['mcc','dominant_mcc','country','dominant_country','merchant_name','name']:
            if col in df_raw.columns:
                mode_vals = df_raw.groupby(mid_col)[col].agg(lambda x: x.mode().iloc[0] if len(x.mode()) else None)
                df_agg[col] = df_agg['merchant_id'].map(mode_vals.to_dict())
        return df_raw, df_agg

def run_patterns(df_raw, df_agg, force=False):
    from ml.pattern_discovery import discover_new_patterns
    if df_agg is None:
        return []
    # universal_trainer уже поставил probability в df_agg
    if 'probability' not in df_agg.columns and 'score' in df_raw.columns:
        mid = next((c for c in ['merchant_id'] if c in df_raw.columns), df_raw.columns[0])
        pm = df_raw.groupby(mid)['score'].mean() * 100
        df_agg2 = df_agg.copy()
        id_col = 'merchant_id' if 'merchant_id' in df_agg2.columns else df_agg2.columns[0]
        df_agg2['probability'] = df_agg2[id_col].map(pm.to_dict()).fillna(50)
        return discover_new_patterns(df_agg2, force=force)
    return discover_new_patterns(df_agg, force=force)


def render_pattern_card(p):
    risk  = p.get('risk', 'MEDIUM')
    is_ai = p.get('is_ai', False)
    ptype = p.get('type', 'known')
    rc    = {'CRITICAL':'#b71c1c','HIGH':'#e65100','MEDIUM':'#f57f17'}.get(risk,'#1976d2')
    tb    = '#7c3aed' if ptype == 'discovered' and not is_ai else '#00897b' if is_ai else 'transparent'
    rb    = {'CRITICAL':'#fce4e4','HIGH':'#fff3e0','MEDIUM':'#fffde7'}.get(risk,'#e8f0fe')
    rt    = {'CRITICAL':'#8b0000','HIGH':'#8b3a00','MEDIUM':'#7a5500'}.get(risk,'#1565c0')
    rl    = {'CRITICAL':'КРИТИЧЕСКИЙ','HIGH':'ВЫСОКИЙ','MEDIUM':'СРЕДНИЙ'}.get(risk, risk)
    def esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    badges = ''
    if is_ai: badges += '<span style="background:#e0f2f1;color:#00695c;font-size:0.7rem;padding:2px 8px;border-radius:20px;font-weight:600;margin-right:6px;">🤖 AI-КЛАСТЕР</span>'
    if ptype == 'discovered': badges += f'<span style="background:#ede9fe;color:#5b21b6;font-size:0.7rem;padding:2px 8px;border-radius:20px;font-weight:600;">✨ НОВЫЙ · {esc(p.get("discovered_at",""))}</span>'
    dims_html = ''
    if is_ai and p.get('anomaly_dims'):
        dims = ' &nbsp;|&nbsp; '.join([f'{esc(d[0])}: {d[1]:+.1f}σ' for d in p['anomaly_dims'][:4]])
        dims_html = f'<div style="font-size:0.76rem;color:#00695c;margin:6px 0;"><b>Аномальные признаки:</b> {dims}</div>'
    st.markdown(f"""
<div style="background:#fff;border-radius:14px;padding:16px 20px;margin-bottom:12px;
     border-left:5px solid {rc};border-top:2px solid {tb};
     border-right:1px solid #d1dce8;border-bottom:1px solid #d1dce8;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
  <div style="font-size:0.95rem;font-weight:600;color:#0d1f35;margin-bottom:8px;line-height:1.3;">{esc(p.get('name',''))} &nbsp; {badges}</div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
    <span style="background:{rb};color:{rt};font-size:0.7rem;padding:2px 10px;border-radius:20px;font-weight:600;">Риск: {rl}</span>
    <span style="background:#e8f0fe;color:#1565c0;font-size:0.74rem;padding:2px 10px;border-radius:20px;">~{p.get('matched_count',0):,} мерч. ({p.get('match_rate_pct',0)}%)</span>
    <span style="background:#e8f0fe;color:#1565c0;font-size:0.74rem;padding:2px 10px;border-radius:20px;">MCC: {esc(p.get('dominant_mcc','N/A'))}</span>
  </div>
  <div style="font-size:0.83rem;color:#4a6080;line-height:1.65;margin-bottom:8px;">{esc(p.get('description',''))}</div>
  {dims_html}
  <div style="font-size:0.78rem;color:#5b7a9d;margin-bottom:8px;">Условие:&nbsp;<code style="background:#e8f0fe;padding:2px 7px;border-radius:5px;color:#1565c0;font-size:0.76rem;">{esc(p.get('threshold',''))}</code></div>
  <div style="font-size:0.8rem;color:#1e3a8a;background:#eff6ff;padding:9px 13px;border-radius:9px;border-left:3px solid #3b82f6;margin-top:6px;"><b>🔍 Как обнаружить:</b> {esc(p.get('prevention',''))}</div>
  <div style="font-size:0.8rem;color:#14532d;background:#f0fdf4;padding:9px 13px;border-radius:9px;border-left:3px solid #22c55e;margin-top:7px;"><b>💡 Действие банка:</b> {esc(p.get('bank_action',''))}</div>
</div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# EXTERNAL INTELLIGENCE TAB
# ═══════════════════════════════════════════════════════════════════════════════
def _render_adversarial_intel_tab():
    """
    Фаза 1 + Entity Linking v2 (explainable).
    Мониторинг открытых публичных источников с AI-классификацией релевантности
    + объяснимая связка найденных угроз с конкретными мерчантами клиента
    + приоритизированный список «кого проверить первым» с причинами.

    ЧЕСТНО: это НЕ парсинг закрытых Telegram-чатов и НЕ dark web —
    см. подробное объяснение прямо в интерфейсе ниже и в docstring
    ml/ingestion_engine.py
    """
    from ml.ingestion_engine import generate_digest, load_last_digest, get_digest_summary, SOURCES
    from ml.entity_linker import link_items_to_merchants, get_priority_action_list, get_match_summary_stats

    st.markdown("""
    <div style="background:linear-gradient(135deg,#4c1d95,#7c3aed,#a855f7);border-radius:14px;
                padding:20px 24px;margin-bottom:16px;box-shadow:0 4px 20px rgba(124,58,237,0.25);">
        <div style="color:white;font-size:1.05rem;font-weight:600;margin-bottom:4px;">
            🕵️ Adversarial Intelligence — внешние угрозы × ваши данные
        </div>
        <div style="color:rgba(255,255,255,0.82);font-size:0.82rem;line-height:1.5;">
            Мониторинг открытых источников + объяснимая связка с вашими мерчантами
        </div>
    </div>""", unsafe_allow_html=True)

    with st.expander('ℹ️ Что это и чего здесь НЕТ (важно прочитать)'):
        st.markdown("""
**Что делает этот модуль:**
- Опрашивает источники, дающие КОНКРЕТНЫЕ сигналы (списки юрисдикций FATF,
  списки организаций АФМ РК, новости о приговорах/задержаниях) — не обзорную аналитику
- Каждый элемент классифицируется как **🚨 ALERT** (конкретика — список/дата/решение,
  можно действовать сегодня) или **📄 RESEARCH** (обзорная статья — для фона, не для
  действия). RESEARCH скрыта по умолчанию.
- AI (Groq, бесплатно) извлекает MCC-коды и страны из ALERT-элементов
- **Entity Linking:** сопоставляет MCC/страны с вашими мерчантами, РАНЖИРУЕТ
  совпадения по дополнительным факторам (ключевые слова в названии, аномалия оборота,
  ночная активность, внутренняя вероятность модели) — с явным объяснением каждой причины
- Строит приоритизированный список "кого проверить первым" с конкретным обоснованием
- Кнопки действия: экспорт затронутых ID, отметка "проверено"

**Чего здесь сознательно НЕТ:**
- ❌ Парсинга закрытых Telegram-чатов / dark web — отдельный по рискам модуль,
  требует авторизации живого аккаунта и юридической оценки ToS
- ❌ "Кросс-банковых алертов" вида «банк Х уже заблокировал похожего мерчанта» —
  у нас физически нет доступа к данным других банков. Если в карточке такое увидишь —
  это не должно быть в системе; если увидел, считай багом
- ❌ Выдуманных сумм ущерба или сроков ("ущерб $240K", "до пятницы") — модель НЕ
  придумывает числа, которых нет в источнике. Если источник не называет конкретику —
  показывается общая формулировка без чисел
- ❌ Числовой "вероятности проникновения схемы в ваш банк" — нет калибровочных данных

MCC/страна — это входной фильтр ("кто вообще может быть причастен"), а не финальный
вердикт. Дальше каждый кандидат получает явно объяснённый score.
        """)
        st.write('**Источники в реестре:**')
        for src in SOURCES:
            sig = src.get('expected_signal', 'mixed')
            sig_label = '🚨 alert-источник' if sig == 'alert' else '📄/🚨 смешанный'
            js_note = ' · ⚠️ требует JS-рендеринга (может не парситься)' if src.get('needs_js') else ''
            st.write(f"• {src['name']} ({src['region']}) — {sig_label}{js_note}")

    col_a, col_b, col_c = st.columns([2, 1, 1])
    with col_b:
        refresh_btn = st.button('🔄 Загрузить новое', key='adv_refresh', use_container_width=True,
                                help='Собирает только новые элементы с момента последнего запуска')
    with col_c:
        full_btn = st.button('♻️ Полный пересбор', key='adv_full', use_container_width=True,
                             help='Игнорирует историю просмотренного, собирает заново')

    if refresh_btn or full_btn:
        with st.spinner('🌐 Опрашиваю источники и анализирую через AI (10-40 сек)...'):
            digest = generate_digest(force_refetch=full_btn)
        st.session_state.adv_digest = digest

        if digest.get('errors'):
            for err in digest['errors']:
                st.warning(f'⚠️ {err}')
        if digest.get('total_collected', 0) > 0:
            st.success(f'✅ Собрано {digest["total_collected"]} новых элементов')

    digest = st.session_state.get('adv_digest') or load_last_digest()
    if not digest:
        st.info('📭 Нажми "Загрузить новое" чтобы собрать первый дайджест')
        return

    items = digest.get('items', [])

    # ── ENTITY LINKING: связываем с данными клиента, если они загружены ──────
    df_agg = st.session_state.get('df_agg')
    has_client_data = df_agg is not None and len(df_agg) > 0
    if has_client_data:
        items = link_items_to_merchants(items, df_agg)
        digest['items'] = items

    summary = get_digest_summary(digest)

    s1, s2, s3, s4 = st.columns(4)
    with s1: st.metric('🔴 HIGH релевантность', summary['high'])
    with s2: st.metric('🟡 MEDIUM', summary['medium'])
    with s3: st.metric('⚪ LOW/NONE', summary['low'])
    with s4:
        ai_label = '🤖 AI-анализ' if summary['is_ai_analyzed'] else '📄 Без анализа'
        st.metric('Статус', ai_label)

    st.markdown(
        f"<p style='color:#5b7a9d;font-size:0.78rem;margin-bottom:14px;'>"
        f"🕐 Собрано: {summary['generated_at']} &nbsp;·&nbsp; Всего элементов: {summary['total']}</p>",
        unsafe_allow_html=True)

    if not items:
        st.info('Список пуст — все источники уже были просмотрены ранее, или они недоступны. '
                'Попробуй "Полный пересбор".')
        return

    if not has_client_data:
        st.markdown(
            "<div style='background:#fff8e1;border:1px solid #ffe082;border-radius:8px;"
            "padding:10px 16px;font-size:0.83rem;color:#5d4037;margin-bottom:14px;'>"
            "💡 <b>Загрузи базу мерчантов</b>, чтобы система автоматически показывала, "
            "сколько ТВОИХ мерчантов попадают в зону каждой найденной угрозы.</div>",
            unsafe_allow_html=True)
    else:
        # ── ЧЕСТНАЯ СТАТИСТИКА ПОКРЫТИЯ ────────────────────────────────────────
        # Отвечает на вопрос "почему 96 HOT, но только 4 совпадения?"
        cov = get_match_summary_stats(items)
        with st.expander(f"📊 Статистика покрытия: {cov['news_with_matches']} из {cov['news_with_entities']} новостей "
                         f"с MCC/страной дали совпадение · {cov['unique_merchants_matched']} уникальных мерчантов затронуто"):
            st.write(f"• Новостей с извлечёнными MCC/странами: **{cov['news_with_entities']}**")
            st.write(f"• Новостей без конкретных MCC/стран (общие/глобальные): **{cov['news_without_entities']}** "
                    f"— такие новости физически не с чем сопоставить, это не баг матчинга")
            st.write(f"• Из новостей с сущностями — реально пересеклись с вашей базой: **{cov['news_with_matches']}**")
            st.write(f"• Уникальных мерчантов, затронутых хотя бы одной новостью: **{cov['unique_merchants_matched']}**")
            st.caption("Если эта цифра намного меньше числа HOT LEAD — значит внешние источники пока "
                      "просто не пишут про MCC/страны, в которых сосредоточены ваши HOT-мерчанты. "
                      "Это сигнал о ПОКРЫТИИ источников, не об ошибке системы.")

    # ── ПРИОРИТИЗИРОВАННЫЙ СПИСОК ДЕЙСТВИЙ ────────────────────────────────────
    if has_client_data:
        priority_list = get_priority_action_list(items, max_items=20)
        if priority_list:
            st.markdown('#### 🎯 Кого проверить первым')
            st.markdown(
                "<p style='color:#5b7a9d;font-size:0.8rem;margin-top:-8px;margin-bottom:12px;'>"
                "Ранжировано по совокупному score: совпадение MCC/страны + ключевые слова в названии + "
                "аномалия оборота + ночная активность + внутренняя вероятность. Каждая причина показана явно.</p>",
                unsafe_allow_html=True)

            def esc(s): return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

            for p in priority_list[:10]:
                rel_badge_color = '#b71c1c' if p.get('max_relevance') == 'HIGH' else '#e65100'
                tier = p.get('tier', '?')
                tier_color = {'HOT': '#b71c1c', 'Warm': '#e65100', 'Low': '#1565c0'}.get(tier, '#64748b')

                reasons_html = ''.join([
                    f'<div style="font-size:0.76rem;color:#3f3f46;margin-top:2px;">✓ {esc(r)}</div>'
                    for r in p.get('all_reasons', [])
                ])
                news_links = ''.join([
                    f'<div style="font-size:0.74rem;color:#5b7a9d;margin-top:3px;">'
                    f'• <a href="{esc(n["link"])}" target="_blank" style="color:#1565c0;">{esc(n["title"][:70])}</a></div>'
                    for n in p.get('matched_news', [])[:3]
                ])
                st.markdown(f"""
<div style="background:#fff;border-radius:10px;padding:12px 16px;margin-bottom:8px;
     border-left:4px solid {rel_badge_color};box-shadow:0 1px 4px rgba(0,0,0,0.04);">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span style="font-weight:600;color:#0d1f35;font-size:0.86rem;">{esc(p.get('merchant_id',''))}</span>
    <div style="display:flex;gap:6px;align-items:center;">
      <span style="background:#f1f5f9;color:#475569;font-size:0.7rem;padding:2px 8px;border-radius:12px;">MCC {esc(p.get('mcc','?'))}</span>
      <span style="background:#f1f5f9;color:#475569;font-size:0.7rem;padding:2px 8px;border-radius:12px;">{esc(p.get('country','?'))}</span>
      <span style="background:{tier_color}20;color:{tier_color};font-size:0.7rem;padding:2px 8px;border-radius:12px;font-weight:600;">{tier} ({p.get('probability','?')}%)</span>
      <span style="background:#ede9fe;color:#5b21b6;font-size:0.7rem;padding:2px 8px;border-radius:12px;font-weight:600;">score {p.get('total_score',0):.1f}</span>
    </div>
  </div>
  <div style="margin-top:6px;">{reasons_html}</div>
  <div style="margin-top:6px;">{news_links}</div>
</div>""", unsafe_allow_html=True)

            csv_rows = "merchant_id,mcc,country,probability,tier,total_score,reasons,matched_news_count\n"
            for p in priority_list:
                reasons_str = ' | '.join(p.get('all_reasons', [])).replace(',', ';')
                csv_rows += (f"{p.get('merchant_id','')},{p.get('mcc','')},{p.get('country','')},"
                            f"{p.get('probability','')},{p.get('tier','')},{p.get('total_score',0):.1f},"
                            f'"{reasons_str}",{len(p.get("matched_news",[]))}\n')
            st.download_button('⬇️ Экспортировать список в CSV', csv_rows,
                              file_name=f'priority_check_{datetime.now().strftime("%Y%m%d")}.csv',
                              mime='text/csv', key='adv_priority_csv')
            st.markdown('---')
        else:
            st.info('✅ Среди HIGH/MEDIUM новостей пока нет совпадений с вашими мерчантами по MCC/стране.')

    # ── ЛЕНТА НОВОСТЕЙ С ENTITY LINKING ───────────────────────────────────────
    st.markdown('#### 📰 Сигналы')
    st.markdown(
        "<p style='color:#5b7a9d;font-size:0.8rem;margin-top:-8px;'>"
        "По умолчанию показаны только ALERT — конкретные списки/решения с датой. "
        "RESEARCH (обзорная аналитика) скрыта, чтобы не создавать шум.</p>",
        unsafe_allow_html=True)

    fc1, fc2, fc3 = st.columns([2, 1, 1])
    with fc1:
        relevance_filter = st.multiselect(
            'Фильтр по релевантности:',
            ['HIGH', 'MEDIUM', 'LOW', 'NONE', 'UNRATED'],
            default=['HIGH', 'MEDIUM'],
            key='adv_relevance_filter'
        )
    with fc2:
        only_matches = st.checkbox('Только с совпадениями', value=has_client_data,
                                   key='adv_only_matches',
                                   help='Скрыть новости, которые не затрагивают ни одного вашего мерчанта')
    with fc3:
        show_research = st.checkbox('Показать RESEARCH', value=False,
                                    key='adv_show_research',
                                    help='Включить обзорные статьи/стратегии — обычно не actionable')

    rel_color = {'HIGH': '#b71c1c', 'MEDIUM': '#e65100', 'LOW': '#64748b',
                'NONE': '#94a3b8', 'UNRATED': '#7c3aed'}
    rel_bg = {'HIGH': '#fce4e4', 'MEDIUM': '#fff3e0', 'LOW': '#f1f5f9',
             'NONE': '#f1f5f9', 'UNRATED': '#f3e8ff'}

    def esc(s): return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    shown = [it for it in items if it.get('relevance', 'UNRATED') in relevance_filter]

    research_hidden_count = 0
    if not show_research:
        filtered = []
        for it in shown:
            if it.get('signal_type') == 'RESEARCH':
                research_hidden_count += 1
            else:
                filtered.append(it)
        shown = filtered

    no_match_count = 0
    if only_matches and has_client_data:
        filtered = []
        for it in shown:
            mm = it.get('matched_merchants')
            if mm and mm.get('has_match'):
                filtered.append(it)
            else:
                no_match_count += 1
        shown = filtered

    if research_hidden_count > 0:
        st.caption(f'ℹ️ Скрыто {research_hidden_count} обзорных (RESEARCH) элементов — включи "Показать RESEARCH" чтобы увидеть')

    if not shown:
        st.info('Нет элементов с выбранными фильтрами')

    for it in shown:
        rel = it.get('relevance', 'UNRATED')
        rc = rel_color.get(rel, '#64748b')
        rb = rel_bg.get(rel, '#f1f5f9')
        sig_type = it.get('signal_type', 'UNKNOWN')

        # ALERT/RESEARCH бейдж — главное визуальное разделение сигнала от шума
        sig_badge = (
            '<span style="background:#fee2e2;color:#991b1b;font-size:0.68rem;padding:2px 9px;'
            'border-radius:20px;font-weight:700;margin-right:6px;">🚨 ALERT</span>'
            if sig_type == 'ALERT' else
            '<span style="background:#f1f5f9;color:#64748b;font-size:0.68rem;padding:2px 9px;'
            'border-radius:20px;font-weight:600;margin-right:6px;">📄 RESEARCH</span>'
            if sig_type == 'RESEARCH' else ''
        )

        tag_html = ''
        for mcc in it.get('mcc_codes', []):
            tag_html += (f'<span style="background:#dbeafe;color:#1e40af;font-size:0.7rem;'
                        f'padding:2px 8px;border-radius:12px;margin:2px;">MCC {esc(mcc)}</span>')
        for c in it.get('countries', []):
            tag_html += (f'<span style="background:#fef3c7;color:#92400e;font-size:0.7rem;'
                        f'padding:2px 8px;border-radius:12px;margin:2px;">🌍 {esc(c)}</span>')
        for kw in it.get('risk_keywords', []):
            tag_html += (f'<span style="background:#f1f5f9;color:#475569;font-size:0.72rem;'
                        f'padding:2px 8px;border-radius:20px;margin:2px;">{esc(kw)}</span>')

        why = it.get('why_relevant', '')
        why_html = (
            f'<div style="font-size:0.79rem;color:#1e3a8a;background:#eff6ff;padding:8px 12px;'
            f'border-radius:8px;border-left:3px solid #3b82f6;margin-top:8px;">'
            f'<b>Почему касается:</b> {esc(why)}</div>'
        ) if why else ''

        what_if = it.get('what_if_ignored', '')
        what_if_html = (
            f'<div style="font-size:0.79rem;color:#7c2d12;background:#fff7ed;padding:8px 12px;'
            f'border-radius:8px;border-left:3px solid #ea580c;margin-top:6px;">'
            f'<b>⏰ Если не проверить:</b> {esc(what_if)}</div>'
        ) if what_if else ''

        # ── ENTITY LINKING БЛОК ────────────────────────────────────────────────
        mm = it.get('matched_merchants')
        impact_html = ''
        affected_ids = []
        if mm is not None and mm.get('has_match'):
            mcc_lines = ''.join([
                f'<div style="font-size:0.78rem;color:#7c2d12;">• MCC {esc(k)}: <b>{v}</b> мерчантов</div>'
                for k, v in mm.get('by_mcc', {}).items()
            ])
            country_lines = ''.join([
                f'<div style="font-size:0.78rem;color:#7c2d12;">• Страна {esc(k)}: <b>{v}</b> мерчантов</div>'
                for k, v in mm.get('by_country', {}).items()
            ])
            examples_html = ''
            for ex in mm.get('ranked_examples', [])[:3]:
                affected_ids.append(ex.get('merchant_id', ''))
                reasons_inline = ', '.join(ex.get('match_reasons', []))
                examples_html += (
                    f'<div style="font-size:0.76rem;color:#92400e;margin-left:8px;margin-top:4px;">'
                    f'→ <b>{esc(ex.get("merchant_id",""))}</b> '
                    f'({esc(ex.get("country","?"))}, {ex.get("probability","?")}%, {esc(ex.get("tier","?"))}) '
                    f'<span style="background:#fed7aa;color:#7c2d12;padding:1px 6px;border-radius:8px;font-size:0.7rem;">score {ex.get("score",0):.1f}</span>'
                    f'<div style="font-size:0.72rem;color:#a16207;margin-left:12px;">{esc(reasons_inline)}</div>'
                    f'</div>'
                )
            total = mm.get('total_count', 0)
            shown_count = min(3, len(mm.get('ranked_examples', [])))
            more_note = (f'<div style="font-size:0.72rem;color:#a16207;margin-top:4px;">'
                        f'+ ещё {total - shown_count} мерчантов с тем же MCC/страной (показаны топ-3 по score)</div>'
                        if total > shown_count else '')
            hot_warning = (
                f'<div style="font-size:0.78rem;color:#b71c1c;font-weight:600;margin-top:4px;">'
                f'⚠️ {mm["hot_count"]} из {total} уже HOT по вашей модели</div>'
                if mm.get('hot_count', 0) > 0 else ''
            )
            impact_html = f"""
  <div style="background:#fff7ed;border:1.5px solid #fdba74;border-radius:10px;padding:10px 14px;margin-top:10px;">
    <div style="font-size:0.82rem;font-weight:600;color:#9a3412;margin-bottom:4px;">
      🎯 Затрагивает {total} ваших мерчантов
    </div>
    {mcc_lines}{country_lines}
    {examples_html}
    {more_note}
    {hot_warning}
  </div>"""
        elif mm is not None and not mm.get('has_match', True):
            impact_html = (
                '<div style="font-size:0.76rem;color:#5b7a9d;margin-top:8px;">'
                '✅ Совпадений с вашими мерчантами не найдено</div>'
            )
        elif mm is None and (it.get('mcc_codes') or it.get('countries')) and not has_client_data:
            impact_html = (
                '<div style="font-size:0.76rem;color:#94a3b8;margin-top:8px;">'
                'ℹ️ Загрузи данные, чтобы увидеть, каких мерчантов это касается</div>'
            )

        st.markdown(f"""
<div class="intel-card" style="border-left:5px solid {rc};">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:6px;">
    <div style="flex:1;">
      {sig_badge}<a href="{esc(it.get('link',''))}" target="_blank" style="font-size:0.9rem;font-weight:600;color:#0d1f35;text-decoration:none;">
        {esc(it.get('title',''))}
      </a>
    </div>
    <span style="background:{rb};color:{rc};font-size:0.68rem;padding:2px 9px;border-radius:20px;font-weight:600;flex-shrink:0;">{rel}</span>
  </div>
  <div style="font-size:0.76rem;color:#5b7a9d;margin-bottom:6px;">
    📰 {esc(it.get('source_name',''))} &nbsp;|&nbsp; 🌍 {esc(it.get('region',''))}
  </div>
  <div style="font-size:0.83rem;color:#4a6080;line-height:1.6;">{esc(it.get('one_line_summary', it.get('title','')))}</div>
  <div style="margin-top:8px;">{tag_html}</div>
  {why_html}
  {what_if_html}
  {impact_html}
</div>""", unsafe_allow_html=True)

        # ── КНОПКИ ДЕЙСТВИЯ — видны только для ALERT с реальным совпадением ──────
        if sig_type == 'ALERT' and affected_ids:
            ac1, ac2, ac3 = st.columns(3)
            item_key = it.get('hash', str(hash(it.get('title', ''))))[:12]
            with ac1:
                alert_csv = "merchant_id,reason\n" + "\n".join(
                    [f"{mid}," + esc(it.get('one_line_summary',''))[:80] for mid in affected_ids]
                )
                st.download_button('📋 Экспорт затронутых ID', alert_csv,
                                  file_name=f'alert_{item_key}.csv', mime='text/csv',
                                  key=f'adv_export_{item_key}', use_container_width=True)
            with ac2:
                if st.button('✅ Отметить проверенным', key=f'adv_checked_{item_key}', use_container_width=True):
                    checked = st.session_state.get('adv_checked_items', set())
                    checked.add(item_key)
                    st.session_state.adv_checked_items = checked
                    st.success('Отмечено', icon='✅')
            with ac3:
                st.caption(f'Мерчанты: {", ".join(affected_ids[:3])}' +
                          (f' +{len(affected_ids)-3}' if len(affected_ids) > 3 else ''))

    if only_matches and no_match_count > 0:
        with st.expander(f'📭 Не затрагивает ваш портфель ({no_match_count})'):
            st.caption('Эти новости релевантны по теме, но не пересекаются с MCC/странами в вашей базе.')
            for it in items:
                if it.get('relevance', 'UNRATED') not in relevance_filter:
                    continue
                mm = it.get('matched_merchants')
                if mm and mm.get('has_match'):
                    continue
                st.write(f"• [{esc(it.get('title',''))}]({esc(it.get('link',''))})")




def _render_external_intelligence_tab():
    from ml.external_intelligence import (fetch_external_patterns,
                                           get_external_intel_summary,
                                           enrich_with_internal_data,
                                           get_api_key, save_api_key, has_api_key,
                                           test_api_connection, get_cache_age_info)

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0d3b8e,#1565c0,#00acc1);border-radius:14px;
                padding:20px 24px;margin-bottom:20px;box-shadow:0 4px 20px rgba(21,101,192,0.25);">
        <div style="color:white;font-size:1.05rem;font-weight:600;margin-bottom:4px;">
            🌐 Threat Intelligence & Hypothesis Generator
        </div>
        <div style="color:rgba(255,255,255,0.78);font-size:0.82rem;line-height:1.5;">
            Работает <b>независимо от загруженных данных</b> · Groq AI (бесплатно) анализирует мировые тенденции · Кэш 24ч
        </div>
    </div>""", unsafe_allow_html=True)

    # ── НАСТРОЙКА API-КЛЮЧА (Groq — БЕСПЛАТНО) ───────────────────────────────
    # Используем тот же ключ, что и AI-ассистент (вкладка "AI-ассистент").
    # Если ключ уже введён там — здесь он подхватится автоматически.
    if not has_api_key():
        st.markdown("""
        <div style="background:#fff8e1;border:1.5px solid #ffe082;border-radius:10px;
                    padding:14px 18px;margin-bottom:14px;font-size:0.84rem;color:#5d4037;">
            <b>⚡ Бесплатный AI-ключ для живых данных (Groq)</b><br>
            Без ключа показывается база знаний (6 паттернов / 3 угрозы / 3 гипотезы — статично).<br>
            С ключом — Claude... то есть Groq AI генерирует свежие паттерны при каждом запросе.<br><br>
            1. Зайди на <b>console.groq.com</b> → Sign Up (только email, без карты)<br>
            2. <b>API Keys</b> → <b>Create API Key</b> → скопируй (начинается с <code>gsk_...</code>)<br>
            3. Вставь ниже — <i>это тот же ключ, что используется в вкладке «AI-ассистент»,
            если ты его там уже вводил, он подхватится автоматически</i>
        </div>""", unsafe_allow_html=True)
        ec1, ec2 = st.columns([3, 1])
        with ec1:
            new_key = st.text_input('API ключ Groq (бесплатно):', type='password',
                                    placeholder='gsk_...', key='ext_api_key_input')
        with ec2:
            st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
            if st.button('💾 Сохранить ключ', key='save_ext_api_key', use_container_width=True):
                if new_key.strip():
                    save_api_key(new_key.strip())
                    st.success('✅ Сохранён, проверяю...')
                    st.rerun()
    else:
        with st.expander('🔑 API-ключ настроен (Groq, бесплатно) — нажми чтобы изменить или протестировать'):
            current_key = get_api_key()
            masked = current_key[:8] + '•' * 20 if len(current_key) > 8 else '•' * 20
            st.write(f'Текущий ключ: `{masked}`')
            tc1, tc2 = st.columns(2)
            with tc1:
                if st.button('🧪 Проверить ключ', key='test_api_key_btn', use_container_width=True):
                    with st.spinner('Проверяю...'):
                        ok, msg = test_api_connection(current_key)
                    if ok: st.success(msg)
                    else: st.error(msg)
            with tc2:
                new_key2 = st.text_input('Новый ключ:', type='password', key='change_ext_api_key')
                if st.button('💾 Обновить', key='update_ext_api_key', use_container_width=True):
                    if new_key2.strip():
                        save_api_key(new_key2.strip())
                        st.success('✅ Обновлено')
                        st.rerun()

    # Узнаём возраст кэша, чтобы показать честный таймер вместо непонятного
    # "обновить кэш / запросить AI" дубля кнопок, который путал пользователя
    cache_age_info = get_cache_age_info()

    col_a, col_b = st.columns([3, 1])
    with col_a:
        if cache_age_info['exists']:
            if cache_age_info['is_fresh']:
                st.markdown(
                    f"<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;"
                    f"padding:8px 14px;font-size:0.82rem;color:#14532d;'>"
                    f"✅ Кэш свежий (обновлён {cache_age_info['age_hours']:.1f}ч назад). "
                    f"Автообновление через {cache_age_info.get('hours_left', cache_age_info.get('next_refresh_hours', 0)):.1f}ч, "
                    f"или нажми «Запросить AI заново» для немедленного обновления.</div>",
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    "<div style='background:#fff8e1;border:1px solid #ffe082;border-radius:8px;"
                    "padding:8px 14px;font-size:0.82rem;color:#5d4037;'>"
                    "⏰ Кэш устарел (>24ч) — нажми «Запросить AI заново» чтобы получить свежие данные.</div>",
                    unsafe_allow_html=True)
    with col_b:
        force_btn = st.button('🤖 Запросить AI заново', key='ext_force', use_container_width=True,
                              type='primary',
                              help='Удаляет текущий кэш и делает НОВЫЙ запрос к Groq AI — '
                                   'результат гарантированно будет отличаться от текущего')

    # Загружаем данные
    if force_btn:
        # Удаляем кэш ДО запроса
        if os.path.exists('data/external_intel.json'):
            os.remove('data/external_intel.json')
        st.session_state.ext_intel = None

        status_placeholder = st.empty()
        def show_status(msg): status_placeholder.info(msg)

        with st.spinner('🤖 Запрашиваю Groq AI (бесплатно, занимает 5–15 сек)...'):
            result = fetch_external_patterns(force=True, show_status=show_status)

        status_placeholder.empty()

        if result.get('source') == 'groq_api':
            st.success(f'✅ Groq AI вернул НОВЫЕ данные: {len(result.get("patterns",[]))} паттернов, '
                       f'{len(result.get("threats",[]))} угроз, '
                       f'{len(result.get("hypotheses",[]))} гипотез')
        elif result.get('api_errors'):
            st.error(f'❌ Ошибка API — данные НЕ обновлены, показана база знаний.')
            with st.expander('🔍 Подробности ошибки (важно для диагностики)'):
                for err in result['api_errors']:
                    st.code(err, language=None)
        else:
            st.info('📚 Используются данные из встроенной базы знаний')

        st.session_state.ext_intel = result

    elif st.session_state.get('ext_intel') is None:
        with st.spinner('🌐 Загружаю данные...'):
            st.session_state.ext_intel = fetch_external_patterns(force=False)

    intel = st.session_state.get('ext_intel')
    if intel is None:
        st.warning('Нажми "Обновить кэш" для загрузки данных')
        return

    # Federated Learning — обогащаем паттерны если есть загруженные данные
    if st.session_state.get('df_agg') is not None:
        intel['patterns'] = enrich_with_internal_data(
            st.session_state.df_agg, intel.get('patterns', []))

    summary = get_external_intel_summary(intel)

    # KPI
    s1, s2, s3, s4 = st.columns(4)
    with s1: st.metric('🌍 Паттернов', summary['total_patterns'])
    with s2: st.metric('🚨 Угроз', summary['total_threats'])
    with s3: st.metric('🔮 Гипотез', summary['total_hypotheses'])
    with s4:
        src_label = '🤖 Groq AI' if summary['is_ai_generated'] else '📚 База знаний'
        fed_m = summary.get('federated_merchants', 0)
        st.metric('Источник', src_label, delta=f'FL: {fed_m:,} мерч.' if fed_m > 0 else None)

    st.markdown(
        f"<p style='color:#5b7a9d;font-size:0.78rem;margin-bottom:4px;'>"
        f"🕐 Обновлено: {summary['generated_at']} &nbsp;·&nbsp; "
        f"{'🤖 Данные от Groq AI (бесплатно)' if summary['is_ai_generated'] else '📚 База знаний · нажми «Запросить AI» для обновления'}"
        f"</p>", unsafe_allow_html=True
    )

    if summary.get('api_errors'):
        with st.expander('⚠️ Детали ошибок API'):
            for err in summary['api_errors']:
                st.write(f'• {err}')

    # Federated Learning info
    if summary.get('federated_merchants', 0) > 0:
        st.markdown(
            f"<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;"
            f"padding:8px 14px;margin-bottom:12px;font-size:0.82rem;color:#14532d;'>"
            f"🔗 <b>Federated Learning активен</b> — паттерны обогащены статистикой из "
            f"{summary['federated_merchants']:,} ваших мерчантов (данные не передаются наружу)</div>",
            unsafe_allow_html=True
        )

    # ── SUB-TABS ──────────────────────────────────────────────────────────────
    sub1, sub2, sub3 = st.tabs([
        f"🔍 Паттерны ({summary['total_patterns']})",
        f"🚨 Угрозы ({summary['total_threats']})",
        f"🔮 Гипотезы ({summary['total_hypotheses']})",
    ])

    risk_color = {'CRITICAL':'#b71c1c','HIGH':'#e65100','MEDIUM':'#f57f17'}
    risk_bg    = {'CRITICAL':'#fce4e4','HIGH':'#fff3e0','MEDIUM':'#fffde7'}
    risk_txt   = {'CRITICAL':'#8b0000','HIGH':'#8b3a00','MEDIUM':'#7a5500'}
    cat_emoji  = {'crypto':'₿','ecommerce':'🛍️','sanctions':'🚫','gaming':'🎰',
                  'food':'🍔','transport':'🚗','education':'📚','services':'💼'}
    def esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

    with sub1:
        st.markdown("#### 🔍 Актуальные паттерны скрытого бизнеса в мире")
        risk_filter = st.multiselect(
            'Фильтр по риску:', ['CRITICAL','HIGH','MEDIUM'],
            default=['CRITICAL','HIGH','MEDIUM'], key='ext_risk_filter')
        patterns_to_show = [p for p in intel.get('patterns',[]) if p.get('risk') in risk_filter]

        for p in patterns_to_show:
            r   = p.get('risk','MEDIUM')
            cat = p.get('category','services')
            rc  = risk_color.get(r,'#1976d2')
            rb  = risk_bg.get(r,'#e8f0fe')
            rt  = risk_txt.get(r,'#1565c0')
            emoji = cat_emoji.get(cat,'💼')
            novelty     = p.get('novelty_score', 0)
            novelty_bar = int(novelty * 10)
            novelty_color = '#7c3aed' if novelty > 0.85 else '#1565c0' if novelty > 0.70 else '#64748b'

            signals_html = ''.join([
                f'<span style="background:#f1f5f9;color:#475569;font-size:0.72rem;'
                f'padding:2px 8px;border-radius:20px;margin:2px;">{esc(s)}</span>'
                for s in p.get('behavioral_signals',[])])
            mcc_html = ' '.join([
                f'<code style="background:#dbeafe;color:#1e40af;padding:1px 6px;'
                f'border-radius:4px;font-size:0.72rem;">{esc(m)}</code>'
                for m in p.get('mcc_codes',[])])

            # Federated Learning: показываем совпадения в ваших данных
            fed_html = ''
            if p.get('internal_matches') is not None:
                im = p['internal_matches']
                ip = p.get('internal_match_pct', 0)
                ir = p.get('internal_avg_risk', 0)
                fed_color = '#b71c1c' if im > 50 else '#e65100' if im > 10 else '#14532d'
                fed_html = (
                    f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;'
                    f'padding:6px 10px;margin-top:8px;font-size:0.78rem;">'
                    f'🔗 <b style="color:{fed_color};">В ваших данных: {im} мерч. ({ip}%)</b>'
                    f'{f" · Ср. риск: {ir:.0f}%" if ir else ""}'
                    f'</div>'
                )

            st.markdown(f"""
<div class="intel-card" style="border-left:5px solid {rc};">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:10px;">
    <div style="font-size:0.95rem;font-weight:600;color:#0d1f35;line-height:1.3;flex:1;">{emoji} {esc(p.get('name',''))}</div>
    <div style="display:flex;gap:6px;flex-shrink:0;flex-wrap:wrap;">
      <span style="background:{rb};color:{rt};font-size:0.68rem;padding:2px 9px;border-radius:20px;font-weight:600;">{r}</span>
      <span style="background:#f1f5f9;color:#475569;font-size:0.68rem;padding:2px 9px;border-radius:20px;">{esc(p.get('region',''))}</span>
    </div>
  </div>
  <div style="font-size:0.83rem;color:#4a6080;line-height:1.6;margin-bottom:10px;">{esc(p.get('description',''))}</div>
  <div style="margin-bottom:8px;">{signals_html}</div>
  <div style="display:flex;gap:20px;margin-bottom:10px;font-size:0.76rem;color:#64748b;flex-wrap:wrap;">
    <span>MCC: {mcc_html}</span>
    <span>📅 с {p.get('first_seen_year','?')}</span>
    <span style="color:{novelty_color};">⭐ Новизна: {'█'*novelty_bar}{'░'*(10-novelty_bar)} {novelty:.0%}</span>
  </div>
  <div style="font-size:0.79rem;color:#1e3a8a;background:#eff6ff;padding:8px 12px;border-radius:8px;border-left:3px solid #3b82f6;margin-bottom:6px;">
    <b>🔍 Детекция:</b> {esc(p.get('detection_method',''))}
  </div>
  <div style="font-size:0.79rem;color:#14532d;background:#f0fdf4;padding:8px 12px;border-radius:8px;border-left:3px solid #22c55e;">
    <b>💡 Банку:</b> {esc(p.get('bank_recommendation',''))}
  </div>
  {fed_html}
</div>""", unsafe_allow_html=True)

    with sub2:
        st.markdown("#### 🚨 Актуальные угрозы для банков")
        for threat in intel.get('threats',[]):
            r  = threat.get('risk','MEDIUM')
            rc = risk_color.get(r,'#1976d2')
            rb = risk_bg.get(r,'#e8f0fe')
            rt = risk_txt.get(r,'#1565c0')
            emerging_badge = (
                '<span style="background:#fdf4ff;color:#7c3aed;font-size:0.68rem;'
                'padding:2px 8px;border-radius:20px;font-weight:600;margin-left:8px;">🆕 EMERGING</span>'
                if threat.get('emerging') else '')
            ind_html = ' '.join([
                f'<code style="background:#fee2e2;color:#991b1b;padding:1px 6px;'
                f'border-radius:4px;font-size:0.72rem;">{esc(i)}</code>'
                for i in threat.get('indicators',[])])
            st.markdown(f"""
<div class="intel-card" style="border-left:5px solid {rc};">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:10px;">
    <span style="font-size:0.95rem;font-weight:600;color:#0d1f35;">{esc(threat.get('name',''))}{emerging_badge}</span>
    <span style="background:{rb};color:{rt};font-size:0.68rem;padding:2px 9px;border-radius:20px;font-weight:600;flex-shrink:0;">{r}</span>
  </div>
  <div style="font-size:0.82rem;color:#4a6080;line-height:1.6;margin-bottom:8px;">{esc(threat.get('description',''))}</div>
  <div style="font-size:0.76rem;color:#5b7a9d;margin-bottom:8px;">
    📰 <b>Источник:</b> {esc(threat.get('source',''))} &nbsp;|&nbsp; 🌍 {esc(threat.get('region',''))} &nbsp;|&nbsp; 📅 {esc(threat.get('date_added',''))}
  </div>
  <div style="font-size:0.76rem;">🔍 <b>Индикаторы:</b> {ind_html}</div>
</div>""", unsafe_allow_html=True)

    with sub3:
        st.markdown("#### 🔮 Прогнозы: схемы будущего")
        st.markdown(
            "<p style='color:#5b7a9d;font-size:0.82rem;margin-top:-8px;margin-bottom:16px;'>"
            "⚠️ Гипотезы, не задокументированные случаи. Используй для превентивных мер.</p>",
            unsafe_allow_html=True)
        conf_color = {'HIGH':'#14532d','MEDIUM':'#7a5500','LOW':'#5b7a9d'}
        conf_bg    = {'HIGH':'#f0fdf4','MEDIUM':'#fffde7','LOW':'#f1f5f9'}
        for hyp in intel.get('hypotheses',[]):
            prob      = hyp.get('probability', 0.5)
            conf      = hyp.get('confidence','MEDIUM')
            try:
                prob_pct = int(float(prob) * 100)
            except (TypeError, ValueError):
                prob_pct = 50
            try:
                _ps = str(prob).replace("%","").strip()
                prob_bar = int(float(_ps) * 20) if _ps.replace(".","").isdigit() else 10
            except:
                prob_bar = 10
            trigger_html = ' '.join([
                f'<span style="background:#faf5ff;color:#6d28d9;font-size:0.72rem;'
                f'padding:2px 8px;border-radius:20px;">{esc(t)}</span>'
                for t in hyp.get('trigger_signals',[])])
            st.markdown(f"""
<div class="intel-card" style="border-left:5px solid #7c3aed;background:linear-gradient(to right,#faf5ff,#fff);">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;gap:10px;">
    <span style="font-size:0.95rem;font-weight:600;color:#4c1d95;line-height:1.3;flex:1;">🔮 {esc(hyp.get('name',''))}</span>
    <div style="display:flex;gap:6px;flex-shrink:0;">
      <span style="background:{conf_bg.get(conf,'#f1f5f9')};color:{conf_color.get(conf,'#475569')};font-size:0.68rem;padding:2px 9px;border-radius:20px;font-weight:600;">{conf}</span>
      <span style="background:#ede9fe;color:#5b21b6;font-size:0.68rem;padding:2px 9px;border-radius:20px;">{esc(hyp.get('timeframe',''))}</span>
    </div>
  </div>
  <div style="font-size:0.83rem;color:#4a6080;line-height:1.6;margin-bottom:10px;">{esc(hyp.get('description',''))}</div>
  <div style="margin-bottom:8px;">
    <span style="font-size:0.76rem;color:#5b7a9d;">Вероятность: </span>
    <span style="font-size:0.76rem;color:#7c3aed;font-weight:600;">{'█'*prob_bar}{'░'*(20-prob_bar)} {prob_pct}%</span>
  </div>
  <div style="margin-bottom:8px;">{trigger_html}</div>
  <div style="font-size:0.79rem;color:#1e3a8a;background:#eff6ff;padding:8px 12px;border-radius:8px;border-left:3px solid #3b82f6;">
    <b>🛡️ Банку сейчас:</b> {esc(hyp.get('prevention',''))}
  </div>
</div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT TAB
# ═══════════════════════════════════════════════════════════════════════════════
def _render_screening_tab(df_u, df_stats):
    """
    Вкладка «Скрининг»: обратный поиск — проверяем ВСЕХ мерчантов
    по санкционным спискам, FATF grey/black list и высокорисковым MCC.
    Плюс AI-семантический матчинг: новость vs профиль мерчанта без точного MCC.
    """
    from ml.sanctions_screener import screen_all_merchants, get_screening_summary, HIGH_RISK_MCC
    from ml.external_intelligence import get_api_key

    def esc(s): return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f,#1565c0);border-radius:14px;
                padding:20px 24px;margin-bottom:16px;box-shadow:0 4px 20px rgba(21,101,192,0.3);">
        <div style="color:white;font-size:1.05rem;font-weight:600;margin-bottom:4px;">
            🛡️ Скрининг мерчантов — обратный поиск по реестрам
        </div>
        <div style="color:rgba(255,255,255,0.82);font-size:0.82rem;line-height:1.5;">
            Проверяем ВСЕХ мерчантов по OpenSanctions · FATF Grey/Black List · Высокорисковым MCC<br>
            Не ждём новость — сами находим совпадения с реестрами раз в день
        </div>
    </div>""", unsafe_allow_html=True)

    df_agg = st.session_state.get('df_agg')
    if df_agg is None:
        st.info('💡 Загрузи базу мерчантов, чтобы запустить скрининг.')
        return

    col_a, col_b = st.columns([3, 1])
    with col_b:
        run_btn = st.button('🛡️ Запустить скрининг', type='primary',
                           key='screening_run_btn', use_container_width=True)
        force_btn = st.button('🔄 Принудительно (скачать новый список)',
                             key='screening_force_btn', use_container_width=True)

    result = st.session_state.get('screening_result')

    if run_btn or force_btn or result is None:
        with st.spinner(f'🛡️ Скрининг {len(df_agg):,} мерчантов по санкционным реестрам...'):
            result = screen_all_merchants(df_agg, force=force_btn)
            st.session_state.screening_result = result
            # АВТОТРИГГЕР: санкции/FATF Black List → автоуведомление
            try:
                from notifications import send_alerts_if_critical
                sc_patterns = []
                for h in result.get('sanctions_hits', []):
                    if h.get('confidence') == 'HIGH':
                        sc_patterns.append({'id': f"sanctions_{h['merchant_id']}", 'name': f"Санкционное совпадение: {h.get('match_name','?')}", 'risk': 'CRITICAL', 'matched_count': 1, 'type': 'screening'})
                for h in result.get('fatf_country_hits', []):
                    if h.get('risk_level') == 'BLACK_LIST':
                        sc_patterns.append({'id': f"fatf_{h['merchant_id']}", 'name': f"FATF Black List: {h.get('country_name','?')}", 'risk': 'CRITICAL', 'matched_count': 1, 'type': 'screening'})
                if sc_patterns:
                    auto_res = send_alerts_if_critical(sc_patterns, {'total': result.get('total_merchants',0), 'hot': 0, 'warm': 0})
                    if auto_res:
                        ok_ch = [k for k, v in auto_res.items() if 'OK' in str(v)]
                        if ok_ch: st.success(f'🔔 Автоуведомление о критичных совпадениях: {", ".join(ok_ch)}')
            except Exception: pass

    if result is None:
        return

    summary = get_screening_summary(result)

    if result.get('errors'):
        for err in result['errors']:
            st.warning(f'⚠️ {err}')

    # KPI-метрики
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        sc = summary['sanctions_hits']
        sc_high = summary['sanctions_high_confidence']
        st.metric('🚫 Санкционные совпадения',
                  f"{sc}",
                  delta=f"{sc_high} HIGH confidence" if sc_high else None)
    with m2:
        fc = summary['fatf_country_hits']
        fb = summary['fatf_black_list']
        st.metric('🌍 FATF Grey/Black List',
                  f"{fc}",
                  delta=f"{fb} BLACK LIST ⚠️" if fb else None)
    with m3:
        st.metric('⚠️ Высокорисковые MCC (CRITICAL)',
                  summary['high_risk_mcc_critical'])
    with m4:
        st.metric('🕐 Скрининг', summary['screened_at'])

    st.markdown(
        f"<p style='color:#5b7a9d;font-size:0.78rem;margin-bottom:14px;'>"
        f"Всего мерчантов проверено: {summary['total']:,} &nbsp;·&nbsp; "
        f"{'⚠️ Есть ошибки источников' if summary['has_errors'] else '✅ Все источники отработали'}"
        f"</p>", unsafe_allow_html=True)

    # ── РЕЗУЛЬТАТЫ ────────────────────────────────────────────────────────────
    sc_tab, fatf_tab, mcc_tab, sem_tab = st.tabs([
        f'🚫 Санкции ({len(result.get("sanctions_hits",[]))})',
        f'🌍 FATF ({len(result.get("fatf_country_hits",[]))})',
        f'⚠️ MCC ({len(result.get("high_risk_mcc_hits",[]))})',
        '🔍 AI-семантика',
    ])

    with sc_tab:
        hits = result.get('sanctions_hits', [])
        if not hits:
            st.success('✅ Совпадений с санкционными списками не найдено')
        else:
            conf_filter = st.multiselect('Фильтр по уверенности:',
                                        ['HIGH', 'MEDIUM', 'LOW'],
                                        default=['HIGH', 'MEDIUM'],
                                        key='sc_conf_filter')
            shown = [h for h in hits if h.get('confidence') in conf_filter]
            st.markdown(
                "<p style='color:#5b7a9d;font-size:0.8rem;'>"
                "⚠️ Все совпадения требуют ручной проверки — fuzzy match может давать "
                "ложные срабатывания. HIGH confidence = нормализованные названия совпали точно. "
                "MEDIUM/LOW = частичное совпадение, вероятность ошибки выше.</p>",
                unsafe_allow_html=True)
            for h in shown[:50]:
                conf = h.get('confidence', '?')
                conf_color = {'HIGH': '#b71c1c', 'MEDIUM': '#e65100', 'LOW': '#64748b'}.get(conf, '#64748b')
                conf_bg = {'HIGH': '#fce4e4', 'MEDIUM': '#fff3e0', 'LOW': '#f1f5f9'}.get(conf, '#f1f5f9')
                tier = h.get('tier', '?')
                tier_color = {'HOT': '#b71c1c', 'Warm': '#e65100', 'Low': '#1565c0'}.get(tier, '#64748b')
                st.markdown(f"""
<div style="background:#fff;border-radius:10px;padding:12px 16px;margin-bottom:8px;
     border-left:4px solid {conf_color};box-shadow:0 1px 4px rgba(0,0,0,0.05);">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span style="font-weight:600;color:#0d1f35;font-size:0.86rem;">{esc(h.get('merchant_id',''))}</span>
    <div style="display:flex;gap:6px;">
      <span style="background:{conf_bg};color:{conf_color};font-size:0.7rem;padding:2px 8px;border-radius:12px;font-weight:600;">{conf}</span>
      <span style="background:{tier_color}20;color:{tier_color};font-size:0.7rem;padding:2px 8px;border-radius:12px;">{tier} ({h.get('probability','?')}%)</span>
    </div>
  </div>
  <div style="font-size:0.8rem;color:#4a6080;margin-top:4px;">
    Совпадение: <b>{esc(h.get('match_name',''))}</b><br>
    Списки: <span style="font-size:0.76rem;">{esc(h.get('datasets',''))}</span>
  </div>
</div>""", unsafe_allow_html=True)
            if len(hits) > 50:
                st.caption(f'Показано 50 из {len(hits)} — скачай полный список через Экспорт')

    with fatf_tab:
        hits = result.get('fatf_country_hits', [])
        if not hits:
            st.success('✅ Мерчантов с транзакциями в FATF Grey/Black List странах не найдено')
        else:
            bl = [h for h in hits if h.get('risk_level') == 'BLACK_LIST']
            gl = [h for h in hits if h.get('risk_level') == 'GREY_LIST']
            if bl:
                st.error(f'🔴 {len(bl)} мерчантов связаны со странами из FATF BLACK LIST (КНДР, Иран, Мьянма) — '
                        f'требует немедленного уведомления регулятора')
                for h in bl[:20]:
                    st.write(f"• **{h['merchant_id']}** → {h['country_name']} ({h['country_iso']}) · {h.get('tier','?')} {h.get('probability','?')}%")
                st.markdown('---')
            if gl:
                st.warning(f'🟠 {len(gl)} мерчантов связаны со странами из FATF GREY LIST')
                for h in gl[:30]:
                    st.write(f"• **{h['merchant_id']}** → {h['country_name']} ({h['country_iso']}) · {h.get('tier','?')} {h.get('probability','?')}%")

    with mcc_tab:
        hits = result.get('high_risk_mcc_hits', [])
        if not hits:
            st.success('✅ Высокорисковых MCC среди мерчантов не найдено')
        else:
            risk_filter = st.multiselect('Фильтр по уровню риска:',
                                        ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'],
                                        default=['CRITICAL', 'HIGH'],
                                        key='mcc_risk_filter')
            shown = [h for h in hits if h.get('risk') in risk_filter]
            # Группируем по MCC для удобства
            by_mcc = {}
            for h in shown:
                mcc = h.get('mcc', '?')
                if mcc not in by_mcc:
                    by_mcc[mcc] = {'label': h.get('mcc_label',''), 'risk': h.get('risk',''), 'merchants': []}
                by_mcc[mcc]['merchants'].append(h)

            for mcc, info in sorted(by_mcc.items(), key=lambda x: {'CRITICAL':0,'HIGH':1,'MEDIUM':2,'LOW':3}.get(x[1]['risk'],4)):
                risk = info['risk']
                rc = {'CRITICAL':'#b71c1c','HIGH':'#e65100','MEDIUM':'#f57f17','LOW':'#64748b'}.get(risk,'#64748b')
                rb = {'CRITICAL':'#fce4e4','HIGH':'#fff3e0','MEDIUM':'#fffde7','LOW':'#f1f5f9'}.get(risk,'#f1f5f9')
                with st.expander(f"MCC {mcc} — {info['label']} | {len(info['merchants'])} мерчантов"):
                    for h in info['merchants'][:20]:
                        tier = h.get('tier','?')
                        tc = {'HOT':'#b71c1c','Warm':'#e65100','Low':'#1565c0'}.get(tier,'#64748b')
                        st.write(f"• **{h['merchant_id']}** ({h.get('country','?')}) "
                                f"<span style='color:{tc}'>{tier} {h.get('probability','?')}%</span>",
                                unsafe_allow_html=True)
                    if len(info['merchants']) > 20:
                        st.caption(f'+{len(info["merchants"])-20} ещё — скачай CSV через Экспорт')

    with sem_tab:
        _render_semantic_matching_ui(df_agg)

    # CSV-экспорт всех результатов скрининга
    st.markdown('---')
    if st.button('📋 Скачать полный отчёт скрининга (CSV)', key='screening_export_btn'):
        rows = ['Тип,merchant_id,Детали,Вероятность,Тир']
        for h in result.get('sanctions_hits', []):
            rows.append(f'SANCTIONS,{h["merchant_id"]},"{h["match_name"]} ({h["confidence"]})",'
                       f'{h.get("probability","")},{h.get("tier","")}')
        for h in result.get('fatf_country_hits', []):
            rows.append(f'FATF_{h["risk_level"]},{h["merchant_id"]},"{h["country_name"]}",'
                       f'{h.get("probability","")},{h.get("tier","")}')
        for h in result.get('high_risk_mcc_hits', []):
            rows.append(f'HIGH_RISK_MCC_{h["risk"]},{h["merchant_id"]},'
                       f'"MCC {h["mcc"]}: {h["mcc_label"]}",'
                       f'{h.get("probability","")},{h.get("tier","")}')
        csv_data = '\n'.join(rows)
        st.download_button('⬇️ Скачать CSV', csv_data,
                          file_name=f'screening_{datetime.now().strftime("%Y%m%d_%H%M")}.csv',
                          mime='text/csv', key='screening_csv_btn')


def _render_semantic_matching_ui(df_agg):
    """AI-семантический матчинг: новость vs профиль мерчанта без точного MCC."""
    from ml.semantic_matcher import run_semantic_matching
    from ml.external_intelligence import get_api_key
    from ml.ingestion_engine import load_last_digest

    def esc(s): return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    st.markdown("""
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
                padding:14px 18px;margin-bottom:14px;">
        <div style="font-size:0.9rem;font-weight:600;color:#0d1f35;margin-bottom:4px;">
            🔍 AI-семантический матчинг
        </div>
        <div style="font-size:0.82rem;color:#5b7a9d;line-height:1.5;">
            Сравниваем каждую новость с профилем мерчанта через AI — находим связи,
            которые точный MCC-матч пропускает.<br>
            <b>Двухэтапно:</b> сначала быстрый текстовый фильтр (бесплатно), затем
            AI только для топ-кандидатов (расход ~10-30 токен-запросов на сессию).
        </div>
    </div>""", unsafe_allow_html=True)

    digest = load_last_digest()
    if not digest or not digest.get('items'):
        st.info('📭 Нет собранных новостей — перейди в «Adversarial Intel» и нажми «Загрузить новое»')
        return

    items = digest.get('items', [])
    high_items = [it for it in items if it.get('relevance') in ('HIGH', 'MEDIUM')]
    st.write(f"**{len(high_items)}** HIGH/MEDIUM новостей доступно для матчинга (из {len(items)} всего)")

    api_key = get_api_key()
    if not api_key:
        st.warning('⚠️ AI-этап недоступен без Groq ключа — покажет только текстовый фильтр (шаг 1)')

    max_ai = st.slider('Сколько новостей прогнать через AI (расход токенов):',
                       min_value=1, max_value=min(10, len(high_items)),
                       value=min(3, len(high_items)),
                       key='sem_max_ai',
                       help='Каждая новость = ~1 запрос к Groq с батчем кандидатов')

    if st.button('🔍 Запустить семантический матчинг', type='primary', key='sem_run_btn'):
        with st.spinner('Анализирую... шаг 1 (текстовый фильтр) + шаг 2 (AI оценка)...'):
            sem_results = run_semantic_matching(items, df_agg, api_key,
                                               max_items_to_ai_score=max_ai)
            st.session_state.sem_results = sem_results

    sem_results = st.session_state.get('sem_results', {})
    if not sem_results:
        st.info('Нажми кнопку выше для запуска.')
        return

    st.markdown(f'**Найдено совпадений: {sum(len(v) for v in sem_results.values())} '
               f'по {len(sem_results)} новостям**')

    # Создаём обратный индекс: по новости из digest
    items_by_hash = {it.get('hash', str(hash(it.get('title','')))[:12]): it for it in items}

    for item_hash, matches in sem_results.items():
        if not matches:
            continue
        news_item = items_by_hash.get(item_hash, {})
        st.markdown(f"**📰 {esc(news_item.get('title', item_hash)[:80])}**")

        for m in matches[:5]:
            ai_score = m.get('ai_score')
            score_color = ('#b71c1c' if (ai_score or 0) >= 70
                          else '#e65100' if (ai_score or 0) >= 50
                          else '#64748b')
            score_label = (f'AI: {ai_score}/100' if ai_score is not None
                          else f'текст-score: {m.get("pre_score",0)}')
            reasoning = m.get('ai_reasoning', '') or ' | '.join(m.get('pre_reasons', []))
            tier = m.get('tier', '?')
            tc = {'HOT': '#b71c1c', 'Warm': '#e65100', 'Low': '#1565c0'}.get(tier, '#64748b')
            st.markdown(f"""
<div style="background:#fff;border-radius:8px;padding:10px 14px;margin-bottom:6px;
     border-left:3px solid {score_color};box-shadow:0 1px 3px rgba(0,0,0,0.04);">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span style="font-weight:600;font-size:0.84rem;color:#0d1f35;">{esc(m.get('merchant_id',''))}</span>
    <div style="display:flex;gap:6px;">
      <span style="background:{score_color}20;color:{score_color};font-size:0.72rem;padding:2px 8px;border-radius:12px;font-weight:600;">{score_label}</span>
      <span style="font-size:0.72rem;color:{tc};">MCC {esc(m.get('mcc',''))} · {esc(m.get('country',''))} · {tier} {m.get('probability','?')}%</span>
    </div>
  </div>
  <div style="font-size:0.78rem;color:#5b7a9d;margin-top:4px;">{esc(reasoning[:200])}</div>
</div>""", unsafe_allow_html=True)
        st.markdown('---')



def _render_telegram_osint_tab(df_u):
    from ml.telegram_monitor import monitor_channels, load_last_monitor_result, load_channel_config, save_channel_config
    from ml.entity_linker import link_items_to_merchants

    def esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

    st.markdown("""
    <div style="background:linear-gradient(135deg,#0a3d62,#1e3799,#0c2461);border-radius:14px;
                padding:20px 24px;margin-bottom:16px;box-shadow:0 4px 20px rgba(10,61,98,0.3);">
        <div style="color:white;font-size:1.05rem;font-weight:600;margin-bottom:4px;">
            📡 Telegram OSINT — мониторинг публичных каналов
        </div>
        <div style="color:rgba(255,255,255,0.82);font-size:0.82rem;line-height:1.5;">
            Парсинг через t.me/s/ · Без авторизации · Только публичный контент
        </div>
    </div>""", unsafe_allow_html=True)

    with st.expander('ℹ️ Как это работает и ограничения'):
        st.markdown("""
**Метод:** `t.me/s/USERNAME` — веб-preview Telegram для публичных каналов. Тот же HTML, что Google индексирует.
Работает ТОЛЬКО для каналов с @username и включённым preview. Закрытые группы недоступны без Telethon + авторизации.
**Ключевые слова для фильтрации:** обнал, отмыв, p2p, kaspi, usdt, крипто, схема, дроп и другие.
        """)

    channels = load_channel_config()
    with st.expander(f'⚙️ Настройка каналов ({len(channels)} шт.)'):
        for i, ch in enumerate(channels):
            c1, c2, c3, c4 = st.columns([2,3,1,1])
            with c1: channels[i]['username'] = st.text_input('Username', value=ch['username'], key=f'tg_u_{i}', label_visibility='collapsed')
            with c2: channels[i]['label'] = st.text_input('Описание', value=ch.get('label',''), key=f'tg_l_{i}', label_visibility='collapsed')
            with c3: channels[i]['region'] = st.text_input('Регион', value=ch.get('region','CIS'), key=f'tg_r_{i}', label_visibility='collapsed')
            with c4:
                if st.button('🗑️', key=f'tg_del_{i}'):
                    channels.pop(i); save_channel_config(channels); st.rerun()
        ca, cb = st.columns(2)
        with ca:
            if st.button('➕ Добавить канал', key='tg_add'):
                channels.append({'username':'','label':'Новый канал','region':'CIS'})
                save_channel_config(channels); st.rerun()
        with cb:
            if st.button('💾 Сохранить список', key='tg_save'):
                save_channel_config([c for c in channels if c.get('username')]); st.success('✅ Сохранено')

    _, col_btn = st.columns([3,1])
    with col_btn:
        run_btn = st.button('📡 Запустить мониторинг', type='primary', key='tg_run', use_container_width=True)

    if run_btn:
        active = [c for c in channels if c.get('username')]
        if not active:
            st.warning('Добавь хотя бы один канал')
        else:
            with st.spinner(f'Опрашиваю {len(active)} каналов...'):
                result = monitor_channels(active)
                st.session_state.tg_monitor_result = result

    result = st.session_state.get('tg_monitor_result') or load_last_monitor_result()
    if not result:
        st.info('📭 Нажми «Запустить мониторинг» для проверки каналов')
        return

    rel_msgs = result.get('relevant_messages', [])
    m1, m2, m3 = st.columns(3)
    with m1: st.metric('📡 Каналов', result.get('channels_checked',0))
    with m2: st.metric('💬 Сообщений', result.get('total_messages',0))
    with m3: st.metric('🚨 Релевантных', len(rel_msgs))
    st.caption(f"Проверено: {result.get('checked_at','')[:16]}")

    for err in result.get('errors', []):
        st.warning(f'⚠️ {err}')

    if not rel_msgs:
        st.success('✅ Релевантных упоминаний не найдено'); return

    df_agg = st.session_state.get('df_agg')
    if df_agg is not None:
        tg_items = []
        for m in rel_msgs:
            tl = m.get('text','').lower()
            mccs = ['6051','6099'] if any(k in tl for k in ['крипто','crypto','p2p','usdt','binance','kaspi']) else []
            countries = ['KZ'] if any(k in tl for k in ['казахстан','kz','kaspi']) else []
            tg_items.append({**m,'mcc_codes':mccs,'countries':countries,'title':m.get('text','')[:100],'link':'',
                            'source_name':m.get('channel_label',m.get('channel',''))})
        linked = link_items_to_merchants(tg_items, df_agg)
        matched = [it for it in linked if it.get('matched_merchants',{}) and it['matched_merchants'].get('has_match')]
        if matched:
            st.markdown(f"### 🎯 {len(matched)} сообщений связаны с вашими мерчантами")
            for it in matched[:10]:
                mm = it['matched_merchants']
                kw_html = ' '.join([f'<span style="background:#fee2e2;color:#991b1b;font-size:0.7rem;padding:2px 8px;border-radius:12px;">{esc(k)}</span>' for k in it.get('matched_keywords',[])])
                examples = ''.join([f'<div style="font-size:0.76rem;color:#92400e;">→ {esc(ex.get("merchant_id",""))} ({esc(ex.get("country","?"))}, {ex.get("probability","?")}%, {esc(ex.get("tier","?"))})</div>' for ex in mm.get('ranked_examples',[])[:3]])
                st.markdown(f"""
<div style="background:#fff7ed;border:1.5px solid #fdba74;border-radius:10px;padding:12px 16px;margin-bottom:10px;">
  <div style="font-size:0.78rem;color:#5b7a9d;">📢 {esc(it.get('channel_label',''))} · {esc(it.get('date','')[:10])}</div>
  <div style="font-size:0.84rem;line-height:1.5;margin:6px 0;">{esc(it.get('text','')[:300])}</div>
  <div style="margin-bottom:6px;">{kw_html}</div>
  <div style="background:#fff;border-radius:8px;padding:8px 12px;border-left:3px solid #f97316;">
    <b style="font-size:0.8rem;color:#9a3412;">🎯 Затрагивает {mm['total_count']} мерчантов</b>{examples}
  </div>
</div>""", unsafe_allow_html=True)
            st.markdown('---')

    st.markdown(f"### 💬 Все релевантные сообщения ({len(rel_msgs)})")
    for m in rel_msgs[:30]:
        kw_str = ', '.join(m.get('matched_keywords',[]))
        fwd = f" · ↩ из {esc(m['forwarded_from'])}" if m.get('forwarded_from') else ''
        st.markdown(f"""
<div class="intel-card" style="border-left:4px solid #1e3799;">
  <div style="font-size:0.76rem;color:#5b7a9d;">📢 {esc(m.get('channel_label',m.get('channel','')))} · {esc(m.get('date','')[:10])} · 👁 {esc(m.get('views',''))}{fwd}</div>
  <div style="font-size:0.84rem;line-height:1.5;">{esc(m.get('text','')[:400])}</div>
  <div style="margin-top:6px;font-size:0.74rem;color:#e65100;">🔑 {esc(kw_str)}</div>
</div>""", unsafe_allow_html=True)


def _render_roi_tab(df_stats):
    from ml.roi_calculator import calculate_roi, DEFAULT_ASSUMPTIONS

    def esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

    st.markdown("""
    <div style="background:linear-gradient(135deg,#1b4332,#2d6a4f,#40916c);border-radius:14px;
                padding:20px 24px;margin-bottom:16px;box-shadow:0 4px 20px rgba(27,67,50,0.3);">
        <div style="color:white;font-size:1.05rem;font-weight:600;margin-bottom:4px;">
            💰 ROI-калькулятор — финансовый бизнес-кейс для банка
        </div>
        <div style="color:rgba(255,255,255,0.82);font-size:0.82rem;">
            Конвертирует находки платформы в понятные банку финансовые исходы · Все параметры редактируемы
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("<div style='background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:10px 16px;font-size:0.82rem;color:#5d4037;margin-bottom:14px;'>⚠️ <b>Это оценка, не гарантия.</b> Замените параметры на реальные цифры банка для точного расчёта.</div>", unsafe_allow_html=True)

    with st.expander('⚙️ Параметры расчёта (редактируемые)'):
        c1, c2 = st.columns(2)
        with c1:
            fine = st.number_input('Средний штраф регулятора ($)', value=DEFAULT_ASSUMPTIONS['avg_regulatory_fine_usd'], step=1000, key='roi_fine')
            fine_prob = st.slider('Вероятность штрафа на необработанный HOT (% в год)', 1, 20, int(DEFAULT_ASSUMPTIONS['fine_probability_per_unchecked_hot']*100), key='roi_fine_prob')
            hourly = st.number_input('Стоимость часа комплаенс-офицера ($)', value=DEFAULT_ASSUMPTIONS['compliance_hourly_cost_usd'], step=5, key='roi_hourly')
        with c2:
            product_rev = st.number_input('Средний годовой доход с бизнес-продукта ($)', value=800, step=100, key='roi_rev')
            conv = st.slider('Конверсия HOT → бизнес-продукт (%)', 1, 40, 15, key='roi_conv')
            platform_cost = st.number_input('Годовая стоимость платформы ($)', value=DEFAULT_ASSUMPTIONS['platform_annual_cost_usd'], step=1000, key='roi_cost')

    assumptions = {
        'avg_regulatory_fine_usd': fine,
        'fine_probability_per_unchecked_hot': fine_prob / 100,
        'compliance_hourly_cost_usd': hourly,
        'manual_check_hours_per_merchant': DEFAULT_ASSUMPTIONS['manual_check_hours_per_merchant'],
        'reputation_incident_cost_usd': 50000,
        'reputation_incidents_per_year': 0.3,
        'platform_annual_cost_usd': platform_cost,
    }

    screening_summary = {}
    sr = st.session_state.get('screening_result')
    if sr:
        from ml.sanctions_screener import get_screening_summary
        screening_summary = get_screening_summary(sr)

    roi = calculate_roi(df_stats, screening_summary, assumptions)

    m1, m2, m3 = st.columns(3)
    with m1: st.metric('💎 Ценность/год', f"${roi['total_value_usd']:,.0f}", delta=f"ROI x{roi['roi_multiple']}")
    with m2: st.metric('📈 Чистый ROI', f"${roi['net_roi_usd']:,.0f}", delta=f"после вычета ${roi['platform_cost_usd']:,}/год")
    with m3: st.metric('⏱️ Окупаемость', f"{max(1,round(12/max(roi['roi_multiple'],0.1)))} мес." if roi['roi_multiple']>1 else 'Убыток')

    st.markdown('#### Откуда берётся ценность')
    colors = ['#b71c1c','#1565c0','#1b4332']
    for cat, color in zip(roi['categories'], colors):
        share = round(cat['value_usd']/max(roi['total_value_usd'],1)*100)
        st.markdown(f"""
<div style="background:#fff;border-radius:10px;padding:14px 18px;margin-bottom:10px;border-left:4px solid {color};box-shadow:0 1px 4px rgba(0,0,0,0.04);">
  <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
    <span style="font-weight:600;font-size:0.92rem;">{esc(cat['label'])}</span>
    <span style="font-size:1.1rem;font-weight:700;color:{color};">${cat['value_usd']:,.0f}/год</span>
  </div>
  <div style="background:#f1f5f9;border-radius:4px;height:6px;margin-bottom:8px;"><div style="background:{color};height:6px;border-radius:4px;width:{max(share,2)}%;"></div></div>
  <div style="font-size:0.78rem;color:#5b7a9d;">{esc(cat['formula'])}</div>
  <div style="font-size:0.77rem;color:#475569;margin-top:4px;">{esc(cat['detail'])}</div>
</div>""", unsafe_allow_html=True)
    st.caption(roi['disclaimer'])

    if st.button('📋 Скачать ROI-расчёт (TXT)', key='roi_export'):
        lines = ['HIDDEN BUSINESS DETECTOR — ROI-расчёт', '='*45,
                 f"Мерчантов: {df_stats.get('total',0):,} · HOT: {df_stats.get('hot',0)} · WARM: {df_stats.get('warm',0)}", '']
        for cat in roi['categories']:
            lines += [f"{cat['label']}: ${cat['value_usd']:,.0f}/год", f"  {cat['formula']}", f"  {cat['detail']}", '']
        lines += [f"ИТОГО: ${roi['total_value_usd']:,.0f}/год",
                 f"Стоимость платформы: ${roi['platform_cost_usd']:,}/год",
                 f"Чистый ROI: ${roi['net_roi_usd']:,.0f}/год (x{roi['roi_multiple']})", '', roi['disclaimer']]
        st.download_button('⬇️ Скачать TXT', '\n'.join(lines), file_name='HBD_ROI.txt', mime='text/plain', key='roi_txt')


def _render_cross_bank_tab(df_u):
    from ml.cross_bank_simulator import simulate_cross_bank_effect, get_consortium_roadmap

    def esc(s): return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

    st.markdown("""
    <div style="background:linear-gradient(135deg,#311b92,#4527a0,#512da8);border-radius:14px;
                padding:20px 24px;margin-bottom:16px;box-shadow:0 4px 20px rgba(49,27,146,0.3);">
        <div style="color:white;font-size:1.05rem;font-weight:600;margin-bottom:4px;">
            🌐 Кросс-банковая демонстрация — эффект объединения данных
        </div>
        <div style="color:rgba(255,255,255,0.82);font-size:0.82rem;">
            Симуляция на ваших данных · НЕ реальные данные других банков
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("<div style='background:#fce4e4;border:1.5px solid #ef9a9a;border-radius:10px;padding:12px 18px;margin-bottom:14px;font-size:0.82rem;color:#b71c1c;'><b>⚠️ СИМУЛЯЦИЯ — не реальные данные других банков.</b> Берём ваши данные, делим на N частей и показываем эффект объединения. Реальный консорциум — это Фаза 1 roadmap ниже.</div>", unsafe_allow_html=True)

    df_agg = st.session_state.get('df_agg')
    if df_agg is None:
        st.info('💡 Загрузи базу мерчантов для запуска симуляции'); return

    n_banks = st.slider('Количество виртуальных «банков-партнёров»:', 2, 5, 3, key='cb_n')
    if st.button('🌐 Запустить симуляцию', type='primary', key='cb_run'):
        with st.spinner('Симулирую...'):
            sim = simulate_cross_bank_effect(df_agg, n_virtual_banks=n_banks)
            st.session_state.cb_sim = sim

    sim = st.session_state.get('cb_sim')
    if sim:
        if 'error' in sim:
            st.warning(sim['error'])
        else:
            st.info(sim['explanation'])
            st.markdown('#### Что видит каждый банк по отдельности')
            cols = st.columns(len(sim['isolated_view']))
            for col, (bank_id, view) in zip(cols, sim['isolated_view'].items()):
                with col: st.metric(bank_id, f"{view['hot_count']} HOT / {view['total']}", delta=f"{view['visible_clusters']} кластеров")
            combined = sim['combined_view']
            st.markdown('#### При объединении всех')
            m1, m2, m3 = st.columns(3)
            with m1: st.metric('🔥 Всего HOT', combined['hot_count'])
            with m2: st.metric('🎯 Кластеров', combined['visible_clusters'], delta=f"+{combined['clusters_invisible_alone']} невидимы по отдельности")
            with m3: st.metric('📈 Доп. видимость', f"+{sim['pct_additional_clusters_visible']}%")
            if combined['example_hidden_clusters']:
                st.markdown('**Кластеры невидимые ни одному банку по отдельности:**')
                for c in combined['example_hidden_clusters']: st.write(f"• MCC {c['mcc']} · {c['country']}")
    else:
        st.info('Нажми «Запустить симуляцию» выше')

    st.markdown('#### 🗺️ Roadmap к реальному консорциуму')
    status_colors = {'done':'#14532d','requires_partnership':'#1565c0','requires_infrastructure':'#e65100','future':'#64748b'}
    status_labels = {'done':'✅ Готово','requires_partnership':'🤝 Нужны партнёры','requires_infrastructure':'🔧 Нужна инфраструктура','future':'🔮 Будущее'}
    for phase in get_consortium_roadmap():
        color = status_colors.get(phase['status'],'#64748b')
        label = status_labels.get(phase['status'],phase['status'])
        st.markdown(f"""
<div style="background:#fff;border-radius:10px;padding:12px 16px;margin-bottom:8px;border-left:4px solid {color};box-shadow:0 1px 3px rgba(0,0,0,0.04);">
  <div style="display:flex;justify-content:space-between;">
    <span style="font-weight:600;font-size:0.9rem;">{esc(phase['phase'])}</span>
    <span style="font-size:0.72rem;padding:2px 8px;border-radius:12px;background:{color}20;color:{color};font-weight:600;">{label}</span>
  </div>
  <div style="font-size:0.82rem;color:#5b7a9d;margin-top:4px;">{esc(phase['description'])}</div>
</div>""", unsafe_allow_html=True)


def _render_export_tab(df_u, patterns, df_stats):
    st.markdown('<div class="sec-h">📤 Экспорт отчётов для регулятора</div>', unsafe_allow_html=True)
    st.markdown(
        "<p style='color:#5b7a9d;font-size:0.83rem;'>"
        "Экспорт через HTML — работает без установки внешних библиотек "
        "(избегает проблем с PEP 668 / venv на macOS). Открой файл в браузере "
        "и нажми Ctrl+P → «Сохранить как PDF» для печатной версии.</p>",
        unsafe_allow_html=True)

    from html_report import generate_html_report, generate_csv_report

    screening_result = st.session_state.get('screening_result')
    ext_intel = st.session_state.get('ext_intel')

    cluster_summary = []
    try:
        from ml.merchant_profile import get_mcc_cluster_summary
        cluster_summary = get_mcc_cluster_summary(df_u)
    except Exception:
        pass

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div style="background:#fff;border-radius:12px;padding:20px;border:1px solid #d1dce8;margin-bottom:12px;">
          <div style="font-size:1rem;font-weight:600;color:#0d1f35;margin-bottom:8px;">📄 HTML-отчёт</div>
          <div style="font-size:0.83rem;color:#4a6080;margin-bottom:14px;">
            Полный отчёт: статистика, кластеры риска, паттерны, санкционный скрининг, FATF.<br>
            Откроется в браузере · печатается в PDF через Ctrl+P.
          </div>
        </div>""", unsafe_allow_html=True)

        if st.button('📄 Сгенерировать HTML-отчёт', type='primary', key='export_html_btn', use_container_width=True):
            with st.spinner('Генерирую отчёт...'):
                html = generate_html_report(
                    df_stats=df_stats,
                    patterns=patterns,
                    screening_result=screening_result,
                    ext_intel=ext_intel,
                    cluster_summary=cluster_summary,
                )
            st.download_button(
                label='⬇️ Скачать HTML-отчёт',
                data=html,
                file_name=f'HBD_Report_{datetime.now().strftime("%Y%m%d_%H%M")}.html',
                mime='text/html',
                key='html_download_btn'
            )
            st.success('✅ Готово. Открой файл в браузере для просмотра или печати в PDF.')

    with col2:
        st.markdown("""
        <div style="background:#fff;border-radius:12px;padding:20px;border:1px solid #d1dce8;margin-bottom:12px;">
          <div style="font-size:1rem;font-weight:600;color:#0d1f35;margin-bottom:8px;">📊 CSV-данные</div>
          <div style="font-size:0.83rem;color:#4a6080;margin-bottom:14px;">
            Сырые данные: статистика, паттерны, санкции, FATF — для импорта в Excel
            или внутренние системы.
          </div>
        </div>""", unsafe_allow_html=True)

        if st.button('📊 Сгенерировать CSV', type='primary', key='export_csv_btn', use_container_width=True):
            with st.spinner('Генерирую CSV...'):
                csv_data = generate_csv_report(df_stats, patterns, screening_result)
            st.download_button(
                label='⬇️ Скачать CSV',
                data=csv_data,
                file_name=f'HBD_Data_{datetime.now().strftime("%Y%m%d_%H%M")}.csv',
                mime='text/csv',
                key='csv_download_btn'
            )

    # Опционально: если reportlab/openpyxl всё же установлены — показываем доп. опцию
    with st.expander('⚙️ Альтернатива: PDF/Excel через Python-библиотеки (опционально)'):
        from report_generator import diagnose_environment, get_install_command, get_venv_setup_commands
        env = diagnose_environment()
        pdf_ok = env['libraries']['reportlab']['installed']
        xlsx_ok = env['libraries']['openpyxl']['installed']

        if pdf_ok and xlsx_ok:
            st.success('✅ reportlab и openpyxl установлены — можно использовать PDF/Excel напрямую')
            pc1, pc2 = st.columns(2)
            with pc1:
                if st.button('📄 PDF (reportlab)', key='export_pdf_btn_alt', use_container_width=True):
                    from report_generator import generate_pdf_report
                    pdf_bytes = generate_pdf_report(df_stats, patterns, ext_intel)
                    if pdf_bytes:
                        st.download_button('⬇️ Скачать PDF', pdf_bytes,
                                          file_name=f'HBD_{datetime.now().strftime("%Y%m%d")}.pdf',
                                          mime='application/pdf', key='pdf_dl_alt')
            with pc2:
                if st.button('📊 Excel (openpyxl)', key='export_excel_btn_alt', use_container_width=True):
                    from report_generator import generate_excel_report
                    xlsx_bytes = generate_excel_report(df_u, patterns, df_stats)
                    if xlsx_bytes:
                        st.download_button('⬇️ Скачать Excel', xlsx_bytes,
                                          file_name=f'HBD_{datetime.now().strftime("%Y%m%d")}.xlsx',
                                          mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                          key='xlsx_dl_alt')
        else:
            missing = [lib for lib, ok in [('reportlab', pdf_ok), ('openpyxl', xlsx_ok)] if not ok]
            st.info(f'Не установлены: {", ".join(missing)}. HTML-отчёт выше не требует установки — рекомендуем его.')
            if env.get('externally_managed'):
                st.caption('Обнаружена защита PEP 668 (Homebrew Python) — '
                          'команды pip install потребуют venv, см. ниже')
                for lib in missing:
                    st.code(get_venv_setup_commands([lib]), language='bash')




# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS TAB
# ═══════════════════════════════════════════════════════════════════════════════
def _render_notifications_tab(patterns, df_stats):
    from notifications import (load_config, save_config, send_alerts, send_test_alert,
                               load_log, test_telegram_chat, reset_dedup)

    st.markdown('<div class="sec-h">🔔 Webhook-уведомления</div>', unsafe_allow_html=True)
    st.markdown(
        "<p style='color:#5b7a9d;font-size:0.83rem;'>"
        "Автоматические алерты при обнаружении CRITICAL/HIGH паттернов. "
        "Поддерживаются: Telegram, Slack, Email.</p>", unsafe_allow_html=True)

    cfg = load_config()

    # ── ПЕРЕКЛЮЧАТЕЛЬ АВТООТПРАВКИ ───────────────────────────────────────────
    ac1, ac2 = st.columns([3, 1])
    with ac1:
        st.markdown(
            "<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;"
            "padding:10px 16px;font-size:0.83rem;color:#14532d;'>"
            "🔁 <b>Автоотправка:</b> при обнаружении CRITICAL-паттернов "
            "(после загрузки данных или пересчёта) уведомление уйдёт "
            "<b>автоматически</b>, без нажатия кнопок. Дедупликация — "
            "одни и те же паттерны не отправляются повторно.</div>",
            unsafe_allow_html=True)
    with ac2:
        auto_send = st.checkbox('Вкл. автоотправку', value=cfg.get('auto_send', True), key='auto_send_toggle')
        if auto_send != cfg.get('auto_send', True):
            cfg['auto_send'] = auto_send
            save_config(cfg)
            st.rerun()

    tab_tg, tab_sl, tab_em, tab_log = st.tabs(['📱 Telegram', '💬 Slack', '📧 Email', '📋 Лог'])

    with tab_tg:
        enabled = st.checkbox('Включить Telegram', value=cfg['telegram'].get('enabled', False), key='tg_enabled')

        st.markdown("""
        <div style="background:#e8f0fe;border-radius:10px;padding:14px 18px;font-size:0.83rem;color:#1565c0;margin-bottom:14px;">
          <b>📌 Шаг 1 — создай бота (один раз):</b><br>
          Открой @BotFather в Telegram → команда <code>/newbot</code> → следуй инструкциям →
          скопируй токен (формат <code>123456:ABC-DEF...</code>)
        </div>""", unsafe_allow_html=True)

        bot_token = st.text_input('Bot Token', value=cfg['telegram'].get('bot_token',''), type='password', key='tg_token')

        st.markdown('**📌 Шаг 2 — куда бот будет слать уведомления?**')
        destination = st.radio(
            'Выбери тип назначения:',
            ['👤 Мне в личку', '👥 В группу', '📢 В канал'],
            horizontal=True, key='tg_destination_type'
        )

        if destination == '👤 Мне в личку':
            st.markdown("""
            <div style="background:#fff8e1;border-radius:8px;padding:10px 14px;font-size:0.8rem;color:#5d4037;">
              <b>Для личных сообщений:</b><br>
              1. Найди своего бота в Telegram (по имени, которое дал при создании) → нажми <b>Start</b><br>
              2. Напиши боту любое сообщение (например "привет") — это ОБЯЗАТЕЛЬНО,
                 бот технически не может написать первым<br>
              3. Узнай свой User ID через бота <b>@userinfobot</b> — он пришлёт число типа <code>1004298825412</code><br>
              4. Вставь это число в поле Chat ID ниже (БЕЗ минуса)
            </div>""", unsafe_allow_html=True)
        elif destination == '👥 В группу':
            st.markdown("""
            <div style="background:#fff8e1;border-radius:8px;padding:10px 14px;font-size:0.8rem;color:#5d4037;">
              <b>Для группы:</b><br>
              1. Создай группу в Telegram (или используй существующую)<br>
              2. Добавь своего бота в группу как обычного участника (админ-права не обязательны
                 для отправки сообщений, но нужны, если хочешь закреплять/удалять)<br>
              3. Напиши в группе любое сообщение, упомянув бота, либо просто любое сообщение —
                 группа должна "познакомиться" с ботом<br>
              4. Узнай ID группы: добавь в неё бота <b>@RawDataBot</b> на секунду — он покажет "id": -100xxxxxxxxxx<br>
              5. Вставь это число В Chat ID <b>СО ЗНАКОМ МИНУС</b> (id групп всегда отрицательные, например <code>-1001234567890</code>)
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="background:#fff8e1;border-radius:8px;padding:10px 14px;font-size:0.8rem;color:#5d4037;">
              <b>Для канала:</b><br>
              1. Создай канал в Telegram (публичный или приватный)<br>
              2. Зайди в Настройки канала → Администраторы → Добавить администратора → выбери своего бота<br>
              3. Боту нужно минимум право "Публикация сообщений"<br>
              4. Узнай ID канала: перешли любое сообщение из канала боту <b>@RawDataBot</b> —
                 он покажет ID в формате -100xxxxxxxxxx<br>
              5. Вставь это число в Chat ID СО ЗНАКОМ МИНУС
            </div>""", unsafe_allow_html=True)

        chat_id = st.text_input('Chat ID', value=cfg['telegram'].get('chat_id',''), key='tg_chat',
                                 placeholder='1004298825412 (личка) или -1001234567890 (группа/канал)')

        tgc1, tgc2 = st.columns(2)
        with tgc1:
            if st.button('💾 Сохранить Telegram', key='save_tg', use_container_width=True):
                cfg['telegram'] = {'enabled': enabled, 'bot_token': bot_token, 'chat_id': chat_id}
                save_config(cfg)
                st.success('✅ Сохранено')
        with tgc2:
            if st.button('🧪 Проверить Telegram', key='test_tg_diag', use_container_width=True, type='primary'):
                if not bot_token.strip():
                    st.error('Сначала введи Bot Token')
                elif not chat_id.strip():
                    st.error('Сначала введи Chat ID')
                else:
                    with st.spinner('Проверяю токен, тип чата и пробую отправить...'):
                        ok, msg = test_telegram_chat(bot_token, chat_id)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)

    with tab_sl:
        sl_enabled = st.checkbox('Включить Slack', value=cfg['slack'].get('enabled', False), key='sl_enabled')
        webhook_url = st.text_input('Webhook URL', value=cfg['slack'].get('webhook_url',''), key='sl_webhook',
                                     help='Incoming Webhook URL из настроек Slack App')
        st.markdown("""
        <div style="background:#e8f0fe;border-radius:8px;padding:10px 14px;font-size:0.8rem;color:#1565c0;">
          <b>Как получить:</b><br>
          1. api.slack.com → Your Apps → Create New App<br>
          2. Incoming Webhooks → Add New Webhook → выбери канал<br>
          3. Скопируй Webhook URL
        </div>""", unsafe_allow_html=True)
        if st.button('💾 Сохранить Slack', key='save_sl'):
            cfg['slack'] = {'enabled': sl_enabled, 'webhook_url': webhook_url}
            save_config(cfg)
            st.success('✅ Сохранено')

    with tab_em:
        em_enabled = st.checkbox('Включить Email', value=cfg['email'].get('enabled', False), key='em_enabled')
        c1, c2 = st.columns(2)
        with c1:
            smtp_host = st.text_input('SMTP Host', value=cfg['email'].get('smtp_host',''), key='em_host',
                                       placeholder='smtp.gmail.com')
            smtp_user = st.text_input('SMTP User (от кого)', value=cfg['email'].get('smtp_user',''), key='em_user')
            smtp_pass = st.text_input('SMTP Password', value=cfg['email'].get('smtp_pass',''), type='password', key='em_pass')
        with c2:
            smtp_port = st.number_input('SMTP Port', value=cfg['email'].get('smtp_port', 587), key='em_port')
            to_email  = st.text_input('Кому (email)', value=cfg['email'].get('to_email',''), key='em_to')
        if st.button('💾 Сохранить Email', key='save_em'):
            cfg['email'] = {'enabled': em_enabled, 'smtp_host': smtp_host, 'smtp_port': int(smtp_port),
                            'smtp_user': smtp_user, 'smtp_pass': smtp_pass, 'to_email': to_email}
            save_config(cfg)
            st.success('✅ Сохранено')

    # Настройка минимального уровня риска
    st.markdown('---')
    c1, c2 = st.columns([2, 1])
    with c1:
        min_risk = st.selectbox('Минимальный риск для уведомления:',
                                ['CRITICAL', 'HIGH', 'MEDIUM'],
                                index=['CRITICAL','HIGH','MEDIUM'].index(cfg.get('min_risk','CRITICAL')),
                                key='min_risk_select')
    with c2:
        if st.button('💾 Сохранить', key='save_min_risk', use_container_width=True):
            cfg['min_risk'] = min_risk
            save_config(cfg)
            st.success('✅')

    # Кнопки тест/отправка
    st.markdown('---')
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        if st.button('🧪 Тестовое уведомление', key='test_notif_btn', use_container_width=True):
            with st.spinner('Отправляю тест...'):
                results = send_test_alert()
            for ch, res in results.items():
                if 'OK' in str(res):
                    st.success(f'✅ {ch}: отправлено')
                elif 'skipped' in ch:
                    st.info(f'ℹ️ {res}')
                else:
                    st.error(f'❌ {ch}: {res}')
    with bc3:
        if st.button('♻️ Сбросить дедупликацию', key='reset_dedup_btn', use_container_width=True,
                     help='Позволит повторно отправить уведомления о уже виденных паттернах'):
            reset_dedup()
            st.success('✅ История отправок очищена')
    with bc2:
        if st.button('🚨 Отправить сейчас', type='primary', key='send_now_btn', use_container_width=True):
            if patterns:
                with st.spinner('Отправляю...'):
                    results = send_alerts(patterns, df_stats)
                for ch, res in results.items():
                    if 'OK' in str(res):
                        st.success(f'✅ {ch}: отправлено')
                    elif 'skipped' in ch:
                        st.info(f'ℹ️ {res}')
                    else:
                        st.error(f'❌ {ch}: {res}')
            else:
                st.warning('Нет паттернов для отправки')

    with tab_log:
        log = load_log()
        if log:
            for entry in log[:20]:
                icon = '✅' if entry.get('status') == 'ok' else '❌'
                st.write(f"{icon} `{entry.get('timestamp','')[:16]}` **{entry.get('channel','')}** — {entry.get('message','')[:60]}")
                if entry.get('error'):
                    st.caption(f"   Ошибка: {entry['error']}")
        else:
            st.info('Лог пуст')


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════════
if 'df'         not in st.session_state: st.session_state.df         = None

with st.sidebar:
    _render_ai_sidebar()
    st.divider()
if 'df_agg'     not in st.session_state: st.session_state.df_agg     = None
if 'patterns'   not in st.session_state: st.session_state.patterns   = None
if 'ext_intel'  not in st.session_state: st.session_state.ext_intel  = None
if 'adv_digest'        not in st.session_state: st.session_state.adv_digest        = None
if 'screening_result'  not in st.session_state: st.session_state.screening_result  = None
if 'sem_results'       not in st.session_state: st.session_state.sem_results       = {}
if 'tg_monitor_result' not in st.session_state: st.session_state.tg_monitor_result = None
if 'cb_sim'            not in st.session_state: st.session_state.cb_sim            = None


# ═══════════════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="platform-header">
  <h1>Hidden Business Detector</h1>
  <p>AI-платформа для банков и платёжных систем · Cashless Avengers</p>
  <span class="platform-badge">🚀 ПРОЕКТ 2026 · BETA v2.2</span>
</div>""", unsafe_allow_html=True)

if st.session_state.df is not None:
    n_m = st.session_state.df['merchant_id'].nunique() if 'merchant_id' in st.session_state.df.columns else '?'
    st.info(f"📊 Данные из кэша: **{len(st.session_state.df):,}** записей · **{n_m}** мерчантов")


# ═══════════════════════════════════════════════════════════════════════════════
# ЗАГРУЗКА ДАННЫХ
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="sec-h">📁 Загрузка базы данных</div>', unsafe_allow_html=True)
mode = st.radio('Способ загрузки:', [
    '🌐 Загрузить файл через браузер',
    '💻 Указать путь к файлу на диске (для файлов > 1 ГБ)'
], horizontal=True, key='load_mode_radio')

df_loaded = None
should_process = False

if mode == '🌐 Загрузить файл через браузер':
    up = st.file_uploader('CSV или Excel', type=['csv','xlsx','xls'],
                           accept_multiple_files=True, label_visibility='collapsed', key='file_uploader_main')
    # КРИТИЧНЫЙ ФИКС: file_uploader остаётся непустым между rerun'ами Streamlit.
    # Без этой проверки данные пересчитывались бы на КАЖДОЕ нажатие любой кнопки.
    # should_reprocess() сравнивает хэш (имя+размер) с последним обработанным
    # набором файлов — пересчёт идёт ТОЛЬКО если файлы реально новые/изменились.
    if up and should_reprocess(up):
        should_process = True
        parts = []
        for f in up:
            try:
                if f.name.endswith('.csv'):
                    parts.append(pd.concat(pd.read_csv(f, chunksize=100_000), ignore_index=True))
                else:
                    parts.append(pd.read_excel(f))
            except Exception as e:
                st.error(f'❌ Ошибка {f.name}: {e}')
        if parts:
            df_loaded = pd.concat(parts, ignore_index=True)
        else:
            should_process = False
    elif up and not should_reprocess(up):
        # Файлы те же, что уже обработаны — ничего не делаем,
        # используем то, что уже лежит в session_state.df
        pass
else:
    fp = st.text_input('Путь к файлу:', placeholder='/Users/username/Desktop/export.csv', key='disk_path_input')
    if st.button('🚀 Загрузить с диска', type='primary', key='load_disk_btn') and fp.strip():
        path = fp.strip()
        if not os.path.exists(path):
            st.error(f'❌ Файл не найден: {path}')
        else:
            try:
                sz = os.path.getsize(path) / 1024**3
                with st.spinner(f'⏳ Читаю {sz:.2f} ГБ...'):
                    df_loaded = pd.read_parquet(path) if path.endswith('.parquet') else \
                                pd.concat(pd.read_csv(path, chunksize=500_000), ignore_index=True)
                st.success(f'✅ Прочитано {len(df_loaded):,} записей')
                should_process = True
            except Exception as e:
                st.error(f'❌ Ошибка: {e}')

if df_loaded is not None and should_process:
    df_raw, df_agg = process_and_score(df_loaded)
    # universal_trainer already sets probability and tier in df_agg
    # Map back to df_raw for compatibility (some modules still use df_raw)
    if 'probability' in df_agg.columns and 'merchant_id' in df_agg.columns:
        prob_map = df_agg.set_index('merchant_id')['probability'].to_dict()
        tier_map = df_agg.set_index('merchant_id')['tier'].astype(str).to_dict()
        mid_col_raw = next((c for c in ['merchant_id'] if c in df_raw.columns), df_raw.columns[0])
        df_raw['probability'] = df_raw[mid_col_raw].astype(str).map(prob_map).fillna(30.0)
        df_raw['tier'] = df_raw[mid_col_raw].astype(str).map(tier_map).fillna('Low')
    else:
        df_raw['probability'] = 30.0
        df_raw['tier'] = 'Low'
    if df_agg is not None and 'merchant_id' in df_raw.columns and 'merchant_id' in df_agg.columns:
        pm = df_raw.groupby('merchant_id')['probability'].mean().to_dict()
        df_agg['probability'] = df_agg['merchant_id'].map(pm).fillna(50)
    st.session_state.df    = df_raw
    st.session_state.df_agg = df_agg
    if mode == '🌐 Загрузить файл через браузер':
        mark_processed(up)
    with st.spinner('💾 Сохраняю кэш...'): save_df(df_raw)
    if df_agg is not None:
        with st.spinner(''): save_agg(df_agg)
    st.success(f'✅ Загружено {len(df_raw):,} записей')
    try:
        with st.spinner('🔍 Анализирую паттерны...'):
            pats = run_patterns(df_raw, df_agg, force=False)
            st.session_state.patterns = pats
        nd = [p for p in pats if p.get('type') == 'discovered']
        st.info(f'🎯 Схем: **{len(pats)}** ({len(nd)} новых)')

        # АВТО-ОТПРАВКА уведомлений — без участия пользователя.
        # send_alerts_if_critical сама проверяет: включены ли каналы,
        # есть ли CRITICAL, не отправляли ли уже именно эти паттерны раньше.
        from notifications import send_alerts_if_critical
        df_stats_auto = {
            'total': len(df_raw['merchant_id'].unique()) if 'merchant_id' in df_raw.columns else len(df_raw),
            'hot':   len(df_raw[df_raw['tier']=='HOT'])  if 'tier' in df_raw.columns else 0,
            'warm':  len(df_raw[df_raw['tier']=='Warm']) if 'tier' in df_raw.columns else 0,
        }
        auto_result = send_alerts_if_critical(pats, df_stats_auto)
        if auto_result:
            ok_channels = [k for k, v in auto_result.items() if 'OK' in str(v)]
            if ok_channels:
                st.success(f'🔔 Автоматически отправлены уведомления: {", ".join(ok_channels)}')
    except Exception as ex:
        st.error(f'❌ Паттерны: {ex}')


# ═══════════════════════════════════════════════════════════════════════════════
# ДАШБОРД
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.df is not None:
    df   = st.session_state.df
    dagg = st.session_state.df_agg
    cm   = {'HOT':'#ef5350','Warm':'#ff9800','Low':'#42a5f5'}
    mc_col = 'merchant_id' if 'merchant_id' in df.columns else df.columns[0]
    df_u   = df.drop_duplicates(subset=[mc_col]).copy()

    c1, c2, c3, c4 = st.columns(4)
    hot_count   = len(df_u[df_u['tier']=='HOT'])
    warm_count  = len(df_u[df_u['tier']=='Warm'])
    low_count   = len(df_u[df_u['tier']=='Low'])
    # ИСПРАВЛЕНО: "средняя вероятность по всей базе" усредняла HOT (96%) и LOW (~0%)
    # вместе — бессмысленная метрика (как средняя температура по больнице).
    # Заменено на медиану HOT-группы + количество выше порога 90%.
    hot_df       = df_u[df_u['tier']=='HOT']
    median_hot   = float(hot_df['probability'].median()) if len(hot_df) > 0 else 0
    above_90     = int((df_u['probability'] >= 90).sum())
    avg_prob     = df_u['probability'].mean()  # сохраняем для обратной совместимости df_stats
    with c1: st.metric('HOT LEAD',  f"{hot_count:,}",  delta=f"{hot_count/max(len(df_u),1)*100:.1f}%")
    with c2: st.metric('WARM LEAD', f"{warm_count:,}", delta=f"{warm_count/max(len(df_u),1)*100:.1f}%")
    with c3: st.metric('LOW',        f"{low_count:,}",  delta=f"{low_count/max(len(df_u),1)*100:.1f}%")
    with c4: st.metric('Выше 90% риска', f"{above_90:,}",
                       delta=f"медиана HOT: {median_hot:.1f}%" if hot_count > 0 else None)

    df_stats = {
        'total': len(df_u), 'hot': hot_count, 'warm': warm_count,
        'low': low_count,   'avg_prob': float(avg_prob),
        'median_hot': median_hot, 'above_90': above_90,
    }

    st.markdown('<div class="sec-h">Аналитика</div>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        'Обзор',
        'По категориям',
        'Паттерны',
        'Профиль клиента',
        'Внешняя разведка',
        'Скрининг',
        'Экспорт',
        'Уведомления',
    ])

    with tab1:
        cl, cr = st.columns(2)
        with cl:
            tc = df_u['tier'].value_counts().reset_index(); tc.columns = ['tier','count']
            fig = px.pie(tc, values='count', names='tier', hole=0.60, color='tier',
                         color_discrete_map=cm, title='Распределение мерчантов по риск-тирам')
            fig.update_traces(textposition='outside', textinfo='percent+label', textfont_size=12)
            fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                               font_color='#4a6080', showlegend=False, title_font_color='#1565c0',
                               title_font_size=14, margin=dict(t=50,b=10,l=10,r=10))
            st.plotly_chart(fig, use_container_width=True, key='pie_chart')
        with cr:
            fig2 = px.histogram(df_u, x='probability', nbins=40, color_discrete_sequence=['#1976d2'],
                                title='Распределение вероятностей (%)')
            fig2.add_vline(x=50, line_dash='dash', line_color='#ff9800', annotation_text='Warm')
            fig2.add_vline(x=75, line_dash='dash', line_color='#ef5350', annotation_text='HOT')
            fig2.update_layout(plot_bgcolor='#f0f4fa', paper_bgcolor='rgba(0,0,0,0)',
                                font_color='#4a6080', bargap=0.03, title_font_color='#1565c0',
                                title_font_size=14, xaxis=dict(gridcolor='#d1dce8'),
                                yaxis=dict(gridcolor='#d1dce8'), margin=dict(t=50,b=10,l=10,r=10))
            st.plotly_chart(fig2, use_container_width=True, key='hist_chart')

    with tab2:
        mcc_col = next((c for c in ['mcc','dominant_mcc'] if c in df.columns), None)
        if mcc_col:
            mc2 = df[df['tier']=='HOT'].groupby(mcc_col).size().reset_index(name='count')
            mc2 = mc2.sort_values('count', ascending=False).head(15)
            fig3 = px.bar(mc2, x='count', y=mc2[mcc_col].astype(str), orientation='h',
                          color='count', color_continuous_scale=['#90caf9','#ef5350'],
                          title='Топ-15 MCC кодов среди HOT LEAD')
            fig3.update_layout(plot_bgcolor='#f0f4fa', paper_bgcolor='rgba(0,0,0,0)',
                                font_color='#4a6080', coloraxis_showscale=False,
                                yaxis={'categoryorder':'total ascending'},
                                title_font_color='#1565c0', title_font_size=14,
                                xaxis=dict(gridcolor='#d1dce8'), margin=dict(t=50,b=10,l=10,r=10))
            st.plotly_chart(fig3, use_container_width=True, key='mcc_chart')
        else:
            st.info("Колонка 'mcc' не найдена")

    with tab3:
        h1, h2, h3 = st.columns([3,1,1])
        with h1:
            st.markdown('<div class="sec-h">Поведенческие схемы (по загруженным данным)</div>', unsafe_allow_html=True)
        with h2:
            if st.button('Обновить', key='pat_update_btn', use_container_width=True):
                try:
                    with st.spinner('Анализирую...'):
                        st.session_state.patterns = run_patterns(df, dagg, force=False)
                    st.rerun()
                except Exception as e: st.error(str(e))
        with h3:
            if st.button('Пересчитать', key='pat_force_btn', use_container_width=True):
                try:
                    for fp2 in ['data/pattern_memory.json','data/new_patterns.json']:
                        if os.path.exists(fp2): os.remove(fp2)
                    with st.spinner('Пересчёт...'):
                        st.session_state.patterns = run_patterns(df, dagg, force=True)
                    st.rerun()
                except Exception as e: st.error(str(e))

        patterns = st.session_state.patterns
        if patterns is None:
            try:
                with open('data/new_patterns.json', encoding='utf-8') as f:
                    patterns = json.load(f).get('patterns', [])
                    st.session_state.patterns = patterns
            except: patterns = []

        if patterns:
            known = [p for p in patterns if p.get('type') == 'known']
            disc  = [p for p in patterns if p.get('type') == 'discovered']
            if disc:
                st.markdown(f"#### Новые обнаруженные паттерны ({len(disc)} шт.)")
                for p in disc: render_pattern_card(p)
            if known:
                st.markdown('#### Известные схемы (обнаружены в данных)')
                for p in known: render_pattern_card(p)
        else:
            st.info("Нажми 'Обновить' для анализа паттернов.")

    with tab4:
        _render_client_profile_tab(df_u, df_stats)

    with tab5:
        sub_a, sub_b, sub_c = st.tabs(['AI-паттерны', 'Новости и угрозы', 'Telegram'])
        with sub_a:
            _render_external_intelligence_tab()
        with sub_b:
            _render_adversarial_intel_tab()
        with sub_c:
            _render_telegram_osint_tab(df_u)

    with tab6:
        _render_screening_tab(df_u, df_stats)

    with tab7:
        patterns_for_export = st.session_state.patterns or []
        _render_export_tab(df_u, patterns_for_export, df_stats)

    with tab8:
        patterns_for_notif = st.session_state.patterns or []
        _render_notifications_tab(patterns_for_notif, df_stats)

if st.session_state.df is None:
    st.markdown('<div class="sec-h">External Intelligence (доступно без данных)</div>', unsafe_allow_html=True)
    with st.expander('Открыть External Intelligence'):
        _render_external_intelligence_tab()

st.markdown("""
<div style="text-align:center;color:#8aaccc;font-size:0.73rem;margin-top:40px;padding:16px;border-top:1px solid #c5d8f0;">
    Hidden Business Detector v2.2 · Hidden Business Detector · Cashless Avengers 2026
</div>""", unsafe_allow_html=True)
