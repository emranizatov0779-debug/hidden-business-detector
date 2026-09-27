"""
ml/external_intelligence.py
============================
External Intelligence — паттерны скрытого бизнеса через Groq AI + Tavily поиск.
"""
import os
import json
import random
import string
import urllib.request
import urllib.error
from datetime import datetime

GROQ_URL   = 'https://api.groq.com/openai/v1/chat/completions'
GROQ_MODEL = 'qwen/qwen3.8-27b'
CACHE_PATH = 'data/external_intel.json'
CACHE_TTL_HOURS = 24

_SYS = (
    "You are a senior AML analyst specializing in Kazakhstan and CIS fintech. "
    "You generate structured intelligence about hidden business schemes. "
    "Always respond with valid JSON only, no markdown, no explanations outside JSON."
)


# ── API KEY ───────────────────────────────────────────────────────────────────

def get_api_key() -> str:
    try:
        import streamlit as _st
        k = _st.session_state.get('groq_api_key', '')
        if k:
            return k
    except Exception:
        pass
    env = os.environ.get('GROQ_API_KEY', '')
    if env:
        return env
    try:
        with open('data/groq_config.json', encoding='utf-8') as f:
            return json.load(f).get('api_key', '')
    except Exception:
        return ''


# ── GROQ API CALL ─────────────────────────────────────────────────────────────

def _call_api(prompt: str, system: str, api_key: str) -> tuple:
    if not api_key:
        return None, "Нет Groq API-ключа"
    try:
        payload = json.dumps({
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            "max_tokens": 1200,
            "temperature": 0.7,
        }).encode('utf-8')

        req = urllib.request.Request(
            GROQ_URL, data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if 'choices' in data and data['choices']:
                return data['choices'][0]['message']['content'], None
            return None, f"Пустой ответ: {json.dumps(data)[:100]}"

    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:300]
        if e.code == 401:
            return None, f"Неверный API-ключ Groq (HTTP 401): {body}"
        if e.code == 429:
            return None, f"Превышен лимит запросов (HTTP 429). Подожди минуту."
        return None, f"HTTP {e.code}: {body}"
    except urllib.error.URLError as e:
        return None, f"Сеть недоступна: {e.reason}"
    except Exception as e:
        return None, f"Ошибка: {type(e).__name__}: {e}"


def test_api_connection(api_key: str) -> tuple:
    text, err = _call_api('Say ["OK"]', 'Reply with JSON array only.', api_key)
    if text:
        return True, f"Ключ работает. Ответ: {text[:40]}"
    return False, f"{err}"


# ── CACHE ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        with open(CACHE_PATH, encoding='utf-8') as f:
            data = json.load(f)
        gen = data.get('generated_at', '')
        if gen:
            age = (datetime.now() - datetime.fromisoformat(gen)).total_seconds() / 3600
            if age < CACHE_TTL_HOURS:
                return data
    except Exception:
        pass
    return None


def _save_cache(data: dict):
    try:
        os.makedirs('data', exist_ok=True)
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_cache_age_info() -> dict:
    try:
        with open(CACHE_PATH, encoding='utf-8') as f:
            data = json.load(f)
        gen = data.get('generated_at', '')
        if gen:
            age_h = (datetime.now() - datetime.fromisoformat(gen)).total_seconds() / 3600
            return {
                'exists': True,
                'age_hours': round(age_h, 1),
                'is_fresh': age_h < CACHE_TTL_HOURS,
                'next_refresh_hours': max(0, round(CACHE_TTL_HOURS - age_h, 1)),
                'source': data.get('source', 'unknown'),
            }
    except Exception:
        pass
    return {'exists': False, 'age_hours': None, 'is_fresh': False, 'hours_left': 0, 'next_refresh_hours': 0}


# ── FALLBACK DATA ─────────────────────────────────────────────────────────────

def _get_fallback() -> dict:
    return {
        'patterns': [
            {'id': 'f1', 'name': 'P2P-криптообменник через Kaspi', 'description': 'Физлицо принимает оплату за USDT через Kaspi Pay от множества незнакомых лиц', 'risk': 'CRITICAL', 'region': 'KZ', 'mcc': ['6051', '6099'], 'signals': ['50+ уникальных карт/мес', 'суммы кратны курсу USDT', 'активность 24/7'], 'bank_action': 'Запросить источник средств, проверить лицензию', 'novelty_pct': 85},
            {'id': 'f2', 'name': 'Telegram-магазин без регистрации', 'description': 'Продажа товаров через Telegram-бот с оплатой на личную карту', 'risk': 'HIGH', 'region': 'KZ', 'mcc': ['5999'], 'signals': ['входящие от разных карт', 'суммы 499/999/2999', 'пики в выходные'], 'bank_action': 'Предложить бизнес-счет, проверить регистрацию ИП', 'novelty_pct': 80},
            {'id': 'f3', 'name': 'Обход санкций через КЗ', 'description': 'Российские компании используют физлиц в Казахстане для оплаты западных сервисов', 'risk': 'CRITICAL', 'region': 'KZ', 'mcc': ['5045', '7372'], 'signals': ['входящие из RU >500K тенге', 'исходящие в EU/US', 'несоответствие профилю'], 'bank_action': 'Запросить источник и назначение, уведомить ФМС', 'novelty_pct': 90},
            {'id': 'f4', 'name': 'Нелегальный букмекер', 'description': 'Прием ставок на личную карту для нелицензированных букмекеров', 'risk': 'CRITICAL', 'region': 'KZ', 'mcc': ['7995'], 'signals': ['всплески в дни матчей', 'округленные суммы', 'ночная активность'], 'bank_action': 'Блокировка и передача в службу безопасности', 'novelty_pct': 75},
            {'id': 'f5', 'name': 'Дропшиппинг без ИП', 'description': 'Выплаты от Wildberries/OZON на личную карту без регистрации', 'risk': 'HIGH', 'region': 'KZ', 'mcc': ['5999', '5065'], 'signals': ['регулярные выплаты от маркетплейса', 'нарастающие суммы', 'назначение: выплата продавцу'], 'bank_action': 'Предложить ИП и бизнес-счет', 'novelty_pct': 70},
            {'id': 'f6', 'name': 'AI-фриланс без регистрации', 'description': 'Продажа AI-контента через личные карты без ИП', 'risk': 'MEDIUM', 'region': 'CIS', 'mcc': ['7372'], 'signals': ['входящие SWIFT от Payoneer', 'нерегулярные суммы', 'клиенты из EU/US'], 'bank_action': 'Предложить счет для фрилансеров', 'novelty_pct': 65},
        ],
        'threats': [
            {'id': 't1', 'title': 'Рост P2P крипто-обменников', 'description': 'После ужесточения регулирования в РФ P2P-операторы переместились в KZ', 'severity': 'HIGH', 'region': 'KZ', 'action': 'Усилить мониторинг MCC 6051'},
            {'id': 't2', 'title': 'Telegram как канал теневых платежей', 'description': 'Telegram-боты используются для приема оплаты в обход кассы', 'severity': 'HIGH', 'region': 'KZ', 'action': 'Анализировать назначения входящих P2P-переводов'},
            {'id': 't3', 'title': 'Санкционные риски через физлиц', 'description': 'Физлица используются как транзитные звенья для обхода санкций', 'severity': 'CRITICAL', 'region': 'KZ', 'action': 'Проверять цепочки переводов KZ-EU'},
        ],
        'hypotheses': [
            {'id': 'h1', 'title': 'Рост AI-фриланса без ИП', 'rationale': 'Рост спроса на AI-контент создает новую категорию незарегистрированных фрилансеров', 'probability': 'HIGH', 'timeline': '3-6 мес'},
            {'id': 'h2', 'title': 'DeFi через личные карты', 'rationale': 'Интеграция DeFi с банковскими картами создаст новые схемы вывода', 'probability': 'MEDIUM', 'timeline': '6-12 мес'},
            {'id': 'h3', 'title': 'Маркетплейсы как канал отмывания', 'rationale': 'Фиктивные продажи на маркетплейсах для легализации доходов', 'probability': 'MEDIUM', 'timeline': '6-12 мес'},
        ],
        'source': 'fallback',
        'generated_at': datetime.now().isoformat(),
    }


# ── PARSE GROQ RESPONSE ───────────────────────────────────────────────────────

def _parse_groq_response(text: str) -> dict:
    """
    Парсит ответ Groq. Обрабатывает все варианты структуры:
    - {"patterns":[...],"threats":[...],"hypotheses":[...]}
    - [{"patterns":[...]}]
    - [{"id":"p1","name":...},...]  (массив паттернов напрямую)
    """
    import re

    if not text:
        return {}

    t = text.strip()
    result = {}

    # Вариант 1: массив снаружи
    if t.startswith('['):
        try:
            outer = json.loads(t)
            if isinstance(outer, list) and outer:
                first = outer[0]
                # Массив содержит объект с ключами
                if isinstance(first, dict) and first.get('patterns'):
                    return first
                # Массив паттернов напрямую
                if isinstance(first, dict) and first.get('name') and first.get('risk'):
                    return {'patterns': outer}
        except Exception:
            pass

    # Вариант 2: объект напрямую
    try:
        # Ищем JSON объект
        m = re.search(r'\{[\s\S]*\}', t)
        if m:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                if obj.get('patterns'):
                    result['patterns'] = obj['patterns']
                if obj.get('threats'):
                    result['threats'] = obj['threats']
                if obj.get('hypotheses'):
                    result['hypotheses'] = obj['hypotheses']
                # Одиночный паттерн
                if not result and obj.get('name') and obj.get('risk'):
                    result['patterns'] = [obj]
                if result:
                    return result
    except Exception:
        pass

    # Вариант 3: ищем все массивы
    try:
        arrays = re.findall(r'\[[\s\S]*?\]', t)
        for arr_str in arrays:
            try:
                arr = json.loads(arr_str)
                if not isinstance(arr, list) or not arr:
                    continue
                first = arr[0]
                if not isinstance(first, dict):
                    continue
                if first.get('name') and first.get('risk'):
                    result['patterns'] = arr
                elif first.get('title') and first.get('severity'):
                    result['threats'] = arr
                elif first.get('title') and first.get('probability'):
                    result['hypotheses'] = arr
            except Exception:
                continue
        if result:
            return result
    except Exception:
        pass

    return {}


# ── MAIN FUNCTION ─────────────────────────────────────────────────────────────

def fetch_external_patterns(force: bool = False, show_status=None) -> dict:
    if not force:
        cached = _load_cache()
        if cached:
            return cached

    if force and os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)

    api_key = get_api_key()
    today   = datetime.now().strftime('%Y-%m-%d')
    nonce   = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    errors  = []

    def _log(msg):
        if show_status:
            show_status(msg)

    result = _get_fallback()

    if not api_key:
        result['api_errors'] = ['Нет Groq API-ключа. Введи ключ на console.groq.com']
        result['generated_at'] = datetime.now().isoformat()
        _save_cache(result)
        return result

    # Tavily поиск (если есть ключ)
    web_context = ""
    try:
        from ml.tavily_search import get_tavily_key, get_kazakhstan_aml_context
        tv_key = get_tavily_key()
        if tv_key:
            _log('Ищу актуальные данные в интернете (Tavily)...')
            web_context = get_kazakhstan_aml_context(tv_key)
    except Exception:
        pass

    _log('Запрашиваю Groq AI...')

    prompt = (
        f"Date: {today}. ID: {nonce}.\n"
        + (web_context + "\n\n" if web_context else "")
        + "Return ONLY valid JSON (no markdown). Structure:\n"
        + '{"patterns":[{"id":"p1","name":"<name>","description":"<desc under 80 chars>","risk":"CRITICAL","region":"KZ","mcc":["6051"],"signals":["s1","s2"],"bank_action":"<action>","novelty_pct":85},{"id":"p2",...},{"id":"p3",...}],'
        + '"threats":[{"id":"t1","title":"<title>","description":"<desc>","severity":"HIGH","region":"KZ","action":"<action>"},{"id":"t2",...}],'
        + '"hypotheses":[{"id":"h1","title":"<title>","rationale":"<rationale>","probability":"MEDIUM","timeline":"6-12 мес"},{"id":"h2",...}]}\n'
        + "Focus: Kazakhstan 2025-2026 AML. Real MCC codes. Short strings."
    )

    text, err = _call_api(prompt, _SYS, api_key)

    if text:
        parsed = _parse_groq_response(text)
        if parsed.get('patterns'):
            result['patterns']   = parsed['patterns']
            result['source']     = 'groq_api'
        if parsed.get('threats'):
            result['threats']    = parsed['threats']
        if parsed.get('hypotheses'):
            result['hypotheses'] = parsed['hypotheses']
        if result['source'] != 'groq_api':
            errors.append(f'Parse failed. Keys found: {list(parsed.keys())}. Text: {text[:100]}')
    else:
        errors.append(f'API: {err}')

    result['generated_at'] = datetime.now().isoformat()
    result['api_errors']   = errors if errors else None
    _save_cache(result)
    return result


# ── SUPPORTING FUNCTIONS ──────────────────────────────────────────────────────

def load_federated_stats() -> dict:
    try:
        with open('data/federated_stats.json', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def enrich_with_internal_data(df_agg, patterns: list) -> list:
    if df_agg is None or df_agg.empty:
        return patterns
    enriched = []
    for p in patterns:
        p = dict(p)
        try:
            mccs = p.get('mcc', [])
            if isinstance(mccs, str):
                mccs = [mccs]
            mcc_col = 'dominant_mcc' if 'dominant_mcc' in df_agg.columns else None
            if mcc_col and mccs:
                matches = df_agg[df_agg[mcc_col].astype(str).isin([str(m) for m in mccs])]
                hot = int((matches['tier'] == 'HOT').sum()) if 'tier' in matches.columns else 0
                total = len(matches)
                p['internal_matches'] = total
                p['internal_hot'] = hot
                p['match_rate_pct'] = round(total / max(len(df_agg), 1) * 100, 1)
            else:
                p['internal_matches'] = 0
                p['internal_hot'] = 0
                p['match_rate_pct'] = 0
        except Exception:
            p['internal_matches'] = 0
            p['internal_hot'] = 0
            p['match_rate_pct'] = 0
        enriched.append(p)
    return enriched


def get_external_intel_summary(data: dict) -> dict:
    fed = load_federated_stats()
    return {
        'total_patterns':      len(data.get('patterns', [])),
        'total_threats':       len(data.get('threats', [])),
        'total_hypotheses':    len(data.get('hypotheses', [])),
        'critical_count':      sum(1 for p in data.get('patterns', []) + data.get('threats', [])
                                   if p.get('risk') == 'CRITICAL' or p.get('severity') == 'CRITICAL'),
        'source':              data.get('source', 'unknown'),
        'generated_at':        data.get('generated_at', '')[:16],
        'is_ai_generated':     data.get('source') in ('groq_api', 'groq_api_partial'),
        'api_errors':          data.get('api_errors'),
        'federated_merchants': fed.get('total_merchants', 0),
    }


def save_api_key(api_key: str):
    os.makedirs('data', exist_ok=True)
    with open('data/groq_config.json', 'w', encoding='utf-8') as f:
        json.dump({'api_key': api_key}, f)


def has_api_key() -> bool:
    return bool(get_api_key())
