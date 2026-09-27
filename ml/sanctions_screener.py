"""
ml/sanctions_screener.py  — Обратный скрининг по санкционным спискам
======================================================================
Пункт 5 из плана: "не ждать новость — проверять мерчантов по реестрам раз в день".

Что делает:
  Скачивает актуальный список санкций с OpenSanctions (бесплатно, без API-ключа,
  обновляется ежедневно) и проверяет ВСЕХ мерчантов клиента по нескольким слоям:
    1. Совпадение названия мерчанта с именем из санкционного списка (fuzzy match)
    2. Совпадение страны мерчанта со странами FATF grey/black list
    3. Совпадение MCC-кода с высокорисковыми MCC (статический список)

ЧЕСТНО про ограничения:
  - OpenSanctions бесплатен для НЕКОММЕРЧЕСКИХ пользователей. При продаже продукта
    банкам это коммерческое использование — нужна лицензия (платная) или API-ключ.
    Для текущего демо/MVP — бесплатный bulk download подходит.
  - Fuzzy match по названию даст false positives (совпадение "Алибаба" ≠ Alibaba Group).
    Все совпадения помечены флагом confidence: HIGH/MEDIUM/LOW, требующим ручной проверки.
  - Это НЕ заменяет полноценный AML-скрининг. Это "первый слой" для приоритизации.

Источники:
  - OpenSanctions Consolidated Sanctions (CSV): бесплатно без ключа, 88 санкционных списков
  - FATF High-Risk Jurisdictions (список стран grey/black list): скрапим страницу FATF
  - Высокорисковые MCC (статический список, основан на FATF, ACAMS и собственном анализе)
"""

import os
import re
import json
import hashlib
import urllib.request
from datetime import datetime, timedelta

# ─── ПУТИ ──────────────────────────────────────────────────────────────────────

SANCTIONS_CSV_PATH   = 'data/opensanctions_latest.csv'
FATF_COUNTRIES_PATH  = 'data/fatf_countries.json'
SCREENING_CACHE_PATH = 'data/sanctions_screening_results.json'
SCREENING_TTL_HOURS  = 24

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# ─── ВЫСОКОРИСКОВЫЕ MCC ────────────────────────────────────────────────────────
# Статический список, основан на:
# - FATF Guidance on Risk-Based Approach for Money or Value Transfer Services
# - ACAMS Money Laundering Risk Matrix
# - Паттернах, известных для СНГ-региона
HIGH_RISK_MCC = {
    '6051': {'label': 'Криптообмен / P2P-переводы', 'risk': 'CRITICAL'},
    '6099': {'label': 'Денежные переводы без банков', 'risk': 'CRITICAL'},
    '4829': {'label': 'Денежные переводы', 'risk': 'HIGH'},
    '7995': {'label': 'Казино / Гемблинг', 'risk': 'CRITICAL'},
    '7994': {'label': 'Игровые заведения', 'risk': 'HIGH'},
    '5912': {'label': 'Аптеки (риск нелицензированной фармы)', 'risk': 'HIGH'},
    '5122': {'label': 'Фармацевтические товары', 'risk': 'HIGH'},
    '6211': {'label': 'Ценные бумаги / брокерские услуги', 'risk': 'MEDIUM'},
    '6012': {'label': 'Финансовые услуги / займы', 'risk': 'MEDIUM'},
    '5999': {'label': 'Неклассифицированная розница (шумовой MCC)', 'risk': 'MEDIUM'},
    '7372': {'label': 'ПО / IT-услуги (риск нелицензированных P2P)', 'risk': 'LOW'},
    '0763': {'label': 'Сельхозкооперативы (риск схем через агро)', 'risk': 'MEDIUM'},
}

# ─── СКАЧИВАНИЕ ДАННЫХ ────────────────────────────────────────────────────────

def _fetch(url: str, timeout: int = 60) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f'[sanctions] fetch error {url}: {e}')
        return None


def download_opensanctions(force: bool = False) -> tuple[str | None, str | None]:
    """
    Скачивает CSV-файл OpenSanctions Consolidated Sanctions (бесплатно без ключа).
    Кэширует локально на 24ч чтобы не качать 50 MB при каждом запросе.

    Returns: (path, error_message)
    """
    # CSV-формат: легче парсить, меньше размер чем полный JSON
    # targets.simple.csv содержит: id, caption, schema, countries, topics, datasets, aliases
    url = 'https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv'

    if not force and os.path.exists(SANCTIONS_CSV_PATH):
        age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(SANCTIONS_CSV_PATH))
        if age < timedelta(hours=SCREENING_TTL_HOURS):
            return SANCTIONS_CSV_PATH, None

    data = _fetch(url, timeout=90)
    if not data:
        return None, (
            f"Не удалось скачать список OpenSanctions ({url}). "
            f"Проверь интернет-соединение. "
            f"Если проблема повторяется — OpenSanctions могли изменить URL "
            f"(актуальные URL: opensanctions.org/docs/bulk/)"
        )

    os.makedirs('data', exist_ok=True)
    with open(SANCTIONS_CSV_PATH, 'wb') as f:
        f.write(data)
    return SANCTIONS_CSV_PATH, None


def _load_sanctions_index() -> dict:
    """
    Загружает CSV в памяти как словарь {lower_name → [record, ...]}.
    Файл ~5-10 MB, индекс строится один раз за сессию.
    """
    if not os.path.exists(SANCTIONS_CSV_PATH):
        return {}
    try:
        import csv
        index = {}
        with open(SANCTIONS_CSV_PATH, encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                caption = row.get('caption', '').strip()
                if not caption:
                    continue
                key = caption.lower()
                if key not in index:
                    index[key] = []
                index[key].append(row)
                # Добавляем алиасы
                for alias in row.get('aliases', '').split(';'):
                    alias = alias.strip().lower()
                    if alias and alias != key:
                        if alias not in index:
                            index[alias] = []
                        index[alias].append(row)
        return index
    except Exception as e:
        print(f'[sanctions] index build error: {e}')
        return {}


# ─── FUZZY MATCHING ───────────────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """Нормализуем для сравнения: нижний регистр, убираем юрформы и спецсимволы."""
    if not name:
        return ''
    n = name.lower().strip()
    # Убираем распространённые юридические суффиксы
    for suffix in [' llc', ' ltd', ' inc', ' corp', ' gmbh', ' ооо', ' ао', ' тоо',
                   ' зао', ' оао', ' со', ' ип', ' тов', ' пао']:
        n = n.replace(suffix, '')
    # Убираем специальные символы, оставляем буквы, цифры, пробелы
    n = re.sub(r'[^\w\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def _match_confidence(merchant_name: str, sanctions_key: str) -> str | None:
    """
    Returns: 'HIGH' / 'MEDIUM' / 'LOW' / None
    Уровни уверенности явно определены, чтобы аналитик понимал,
    сколько ручного труда нужно при данном уровне.
    """
    mn = _normalize_name(merchant_name)
    sk = _normalize_name(sanctions_key)

    if not mn or not sk:
        return None

    # Точное совпадение после нормализации — ВЫСОКАЯ уверенность
    if mn == sk:
        return 'HIGH'

    # Одна строка содержит другую (например "КриптоПэй" vs "ООО КриптоПэй Казахстан")
    if len(mn) >= 5 and len(sk) >= 5:
        if mn in sk or sk in mn:
            return 'HIGH'

    # Токенное совпадение: считаем общие слова-токены
    mn_tokens = set(mn.split()) - {'the', 'a', 'an', 'of', 'and', 'or', 'в', 'и', 'с', 'для'}
    sk_tokens = set(sk.split()) - {'the', 'a', 'an', 'of', 'and', 'or', 'в', 'и', 'с', 'для'}

    if len(mn_tokens) == 0 or len(sk_tokens) == 0:
        return None

    common = mn_tokens & sk_tokens
    overlap = len(common) / max(len(mn_tokens), len(sk_tokens))

    if overlap >= 0.8:
        return 'MEDIUM'
    if overlap >= 0.5 and len(common) >= 2:
        return 'LOW'

    return None


# ─── FATF GREY/BLACK LIST ─────────────────────────────────────────────────────

# Статический список FATF High-Risk Jurisdictions (Grey + Black list) по состоянию на 2024-2025
# Обновляется вручную ~2 раза в год или через парсинг страницы FATF.
# Страны в Black List (наивысший риск) помечены отдельно.
FATF_GREY_LIST = {
    'MM': 'Myanmar', 'KP': 'North Korea', 'IR': 'Iran',  # Black list
    'BF': 'Burkina Faso', 'CM': 'Cameroon', 'CG': 'Congo', 'HT': 'Haiti',
    'CI': "Cote d'Ivoire", 'KE': 'Kenya', 'ML': 'Mali', 'MZ': 'Mozambique',
    'NG': 'Nigeria', 'PH': 'Philippines', 'ZA': 'South Africa', 'SS': 'South Sudan',
    'SY': 'Syria', 'TZ': 'Tanzania', 'VN': 'Vietnam', 'YE': 'Yemen',
    'UG': 'Uganda', 'BJ': 'Benin', 'TT': 'Trinidad and Tobago',
    'KH': 'Cambodia',  # Часто упоминается в схемах для СНГ
}
FATF_BLACK_LIST = {'KP', 'IR', 'MM'}  # Максимальный риск — требуют немедленного алерта

# Ещё нет в текущем FATF Grey List, но часто упоминаются в регуляторных предупреждениях
# для банков Казахстана/СНГ:
ELEVATED_RISK_COUNTRIES = {
    'AF': 'Afghanistan', 'LY': 'Libya', 'SO': 'Somalia', 'VE': 'Venezuela',
}


# ─── СКРИНИНГ МЕРЧАНТОВ ───────────────────────────────────────────────────────

def screen_all_merchants(df_agg, force: bool = False) -> dict:
    """
    Главная функция: проверяет ВСЕХ мерчантов по трём слоям.

    Returns: dict с ключами:
      - 'screened_at': timestamp
      - 'total_merchants': int
      - 'sanctions_hits': [{merchant_id, match_type, match_name, confidence, record}, ...]
      - 'fatf_country_hits': [{merchant_id, country_iso, country_name, risk_level}, ...]
      - 'high_risk_mcc_hits': [{merchant_id, mcc, mcc_label, risk}, ...]
      - 'errors': [str, ...]
    """
    if df_agg is None or len(df_agg) == 0:
        return {'screened_at': datetime.now().isoformat(), 'total_merchants': 0,
                'sanctions_hits': [], 'fatf_country_hits': [], 'high_risk_mcc_hits': [],
                'errors': ['Нет данных мерчантов для скрининга']}

    # Проверяем кэш
    if not force and os.path.exists(SCREENING_CACHE_PATH):
        try:
            with open(SCREENING_CACHE_PATH, encoding='utf-8') as f:
                cached = json.load(f)
            cached_time = datetime.fromisoformat(cached.get('screened_at', '2000-01-01'))
            if datetime.now() - cached_time < timedelta(hours=SCREENING_TTL_HOURS):
                return cached
        except Exception:
            pass

    result = {
        'screened_at': datetime.now().isoformat(),
        'total_merchants': int(len(df_agg)),
        'sanctions_hits': [],
        'fatf_country_hits': [],
        'high_risk_mcc_hits': [],
        'errors': [],
    }

    # Определяем нужные колонки
    id_col      = next((c for c in ['merchant_id'] if c in df_agg.columns), df_agg.columns[0])
    name_col    = next((c for c in ['merchant_name', 'name', 'business_name'] if c in df_agg.columns), None)
    country_col = next((c for c in ['dominant_country', 'country'] if c in df_agg.columns), None)
    mcc_col     = next((c for c in ['dominant_mcc', 'mcc'] if c in df_agg.columns), None)
    prob_col    = 'probability' if 'probability' in df_agg.columns else None
    tier_col    = 'tier' if 'tier' in df_agg.columns else None

    # ── СЛОЙ 1: Санкционный скрининг по названию ──────────────────────────────
    if name_col:
        csv_path, err = download_opensanctions(force=force)
        if err:
            result['errors'].append(f'Санкционный скрининг недоступен: {err}')
        else:
            sanctions_index = _load_sanctions_index()
            if sanctions_index:
                for _, row in df_agg.iterrows():
                    merchant_name = str(row.get(name_col, '')).strip()
                    if not merchant_name or merchant_name in ('?', 'nan', 'None'):
                        continue
                    # Проверяем по всем ключам индекса
                    mn_normalized = _normalize_name(merchant_name)
                    for key, records in sanctions_index.items():
                        confidence = _match_confidence(merchant_name, key)
                        if confidence:
                            for rec in records:
                                result['sanctions_hits'].append({
                                    'merchant_id': str(row.get(id_col, '?')),
                                    'merchant_name': merchant_name,
                                    'match_name': rec.get('caption', key),
                                    'confidence': confidence,
                                    'countries_in_list': rec.get('countries', ''),
                                    'datasets': rec.get('datasets', ''),
                                    'probability': float(row.get(prob_col, 0)) if prob_col else None,
                                    'tier': str(row.get(tier_col, '?')) if tier_col else None,
                                })
                            break  # нашли хотя бы одно совпадение для этого ключа
            else:
                result['errors'].append('Санкционный индекс пустой — возможно, файл не скачался корректно')
    else:
        result['errors'].append(
            "Нет колонки с названием мерчанта (merchant_name / name / business_name) — "
            "санкционный скрининг по имени пропущен. "
            "Скрининг по стране и MCC всё равно выполнен."
        )

    # ── СЛОЙ 2: Страна мерчанта в FATF grey/black list ────────────────────────
    if country_col:
        iso_to_names = {
            'KZ': ['kazakhstan', 'kz'], 'RU': ['russia', 'ru'], 'UZ': ['uzbekistan', 'uz'],
            'AE': ['uae', 'united arab emirates', 'ae'], 'KH': ['cambodia', 'kh'],
            'CN': ['china', 'cn'], 'BY': ['belarus', 'by'], 'KG': ['kyrgyzstan', 'kg'],
            'MM': ['myanmar', 'burma', 'mm'], 'KP': ['north korea', 'kp'],
            'IR': ['iran', 'ir'], 'VN': ['vietnam', 'vn'], 'PH': ['philippines', 'ph'],
            'NG': ['nigeria', 'ng'], 'KE': ['kenya', 'ke'], 'YE': ['yemen', 'ye'],
            'SY': ['syria', 'sy'], 'HT': ['haiti', 'ht'], 'SS': ['south sudan', 'ss'],
            'TZ': ['tanzania', 'tz'], 'ML': ['mali', 'ml'], 'BF': ['burkina faso', 'bf'],
        }
        name_to_iso = {}
        for iso, names in iso_to_names.items():
            for n in names:
                name_to_iso[n] = iso

        for _, row in df_agg.iterrows():
            country_val = str(row.get(country_col, '')).lower().strip()
            if not country_val or country_val in ('?', 'nan', 'none', ''):
                continue
            iso = name_to_iso.get(country_val) or (country_val.upper() if len(country_val) == 2 else None)
            if not iso:
                continue
            if iso in FATF_GREY_LIST:
                risk_level = 'BLACK_LIST' if iso in FATF_BLACK_LIST else 'GREY_LIST'
                result['fatf_country_hits'].append({
                    'merchant_id': str(row.get(id_col, '?')),
                    'country_iso': iso,
                    'country_name': FATF_GREY_LIST[iso],
                    'risk_level': risk_level,
                    'probability': float(row.get(prob_col, 0)) if prob_col else None,
                    'tier': str(row.get(tier_col, '?')) if tier_col else None,
                })

    # ── СЛОЙ 3: Высокорисковые MCC ───────────────────────────────────────────
    if mcc_col:
        for _, row in df_agg.iterrows():
            mcc_val = str(row.get(mcc_col, '')).strip()
            if mcc_val in HIGH_RISK_MCC:
                mcc_info = HIGH_RISK_MCC[mcc_val]
                result['high_risk_mcc_hits'].append({
                    'merchant_id': str(row.get(id_col, '?')),
                    'mcc': mcc_val,
                    'mcc_label': mcc_info['label'],
                    'risk': mcc_info['risk'],
                    'probability': float(row.get(prob_col, 0)) if prob_col else None,
                    'tier': str(row.get(tier_col, '?')) if tier_col else None,
                    'country': str(row.get(country_col, '?')) if country_col else None,
                })

    # Сортируем hits по вероятности убывающей (наиболее рискованные сверху)
    for key in ('sanctions_hits', 'fatf_country_hits', 'high_risk_mcc_hits'):
        result[key].sort(key=lambda x: -(x.get('probability') or 0))

    # Сохраняем кэш
    os.makedirs('data', exist_ok=True)
    with open(SCREENING_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    return result


def get_screening_summary(result: dict) -> dict:
    """Краткая статистика для отображения в хедере."""
    return {
        'total': result.get('total_merchants', 0),
        'sanctions_hits': len(result.get('sanctions_hits', [])),
        'sanctions_high_confidence': sum(
            1 for h in result.get('sanctions_hits', []) if h.get('confidence') == 'HIGH'
        ),
        'fatf_country_hits': len(result.get('fatf_country_hits', [])),
        'fatf_black_list': sum(
            1 for h in result.get('fatf_country_hits', []) if h.get('risk_level') == 'BLACK_LIST'
        ),
        'high_risk_mcc_critical': sum(
            1 for h in result.get('high_risk_mcc_hits', []) if h.get('risk') == 'CRITICAL'
        ),
        'screened_at': result.get('screened_at', '')[:16],
        'has_errors': bool(result.get('errors')),
    }
