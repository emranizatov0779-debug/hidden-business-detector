"""
ml/telegram_monitor.py — Мониторинг публичных Telegram-каналов через t.me/s/
"""
import os, re, json, hashlib, urllib.request, urllib.error
from datetime import datetime

TG_CACHE_PATH = 'data/telegram_monitor_cache.json'
TG_SEEN_PATH  = 'data/telegram_seen_hashes.json'
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

DEFAULT_CHANNELS = [
    {'username': 'durov', 'label': 'Pavel Durov (публичный, для теста)', 'region': 'Global'},
]

RISK_KEYWORDS = [
    'обнал','отмыв','дроп','дропер','p2p','каспи','kaspi','binance',
    'usdt','крипто','обмен','схема','вывод денег','нал','однодневк',
    'подстав','арбитраж','мошенн','фейк','пирамид','crypto','fraud',
    'money laundering','aml','sanctions',
]

def _fetch(username: str) -> str | None:
    url = f'https://t.me/s/{username.lstrip("@").strip()}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': _UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'[tg] {username}: {e}')
        return None

def _parse(html: str) -> tuple[list, bool]:
    if 'tgme_widget_message_wrap' not in html:
        return [], True
    messages = []
    blocks = re.findall(
        r'<div class="tgme_widget_message_wrap.*?(?=<div class="tgme_widget_message_wrap|\Z)',
        html, re.DOTALL)
    for block in blocks:
        id_m   = re.search(r'data-post="[\w]+/(\d+)"', block)
        text_m = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
        date_m = re.search(r'<time[^>]+datetime="([^"]+)"', block)
        views_m= re.search(r'tgme_widget_message_views">([\d.,KMkm]+)<', block)
        fwd_m  = re.search(r'tgme_widget_message_forwarded_from[^>]*>.*?<span[^>]*>([^<]+)</span>', block, re.DOTALL)
        text = ''
        if text_m:
            raw = re.sub(r'<br\s*/?>', '\n', text_m.group(1))
            text = re.sub(r'<[^>]+>', '', raw)
            text = (text.replace('&amp;','&').replace('&lt;','<').replace('&gt;','>').replace('&quot;','"').replace('&#39;',"'").strip())
        if text:
            messages.append({'msg_id': int(id_m.group(1)) if id_m else None,
                            'text': text, 'date': date_m.group(1) if date_m else '',
                            'views': views_m.group(1) if views_m else '0',
                            'forwarded_from': fwd_m.group(1).strip() if fwd_m else None})
    return messages, False

def filter_relevant(messages: list) -> list:
    out = []
    for m in messages:
        tl = m.get('text','').lower()
        kw = [k for k in RISK_KEYWORDS if k in tl]
        if kw:
            m2 = dict(m); m2['matched_keywords'] = kw; out.append(m2)
    return out

def _load_seen() -> set:
    if os.path.exists(TG_SEEN_PATH):
        try:
            with open(TG_SEEN_PATH, encoding='utf-8') as f: return set(json.load(f))
        except: pass
    return set()

def _save_seen(h: set):
    os.makedirs('data', exist_ok=True)
    with open(TG_SEEN_PATH, 'w', encoding='utf-8') as f: json.dump(list(h)[-1000:], f)

def monitor_channels(channels: list = None) -> dict:
    channels = channels or DEFAULT_CHANNELS
    result = {'channels_checked':0,'total_messages':0,'relevant_messages':[],'errors':[],'checked_at':datetime.now().isoformat()}
    seen = _load_seen(); new_h = set()
    for ch in channels:
        html = _fetch(ch['username'])
        result['channels_checked'] += 1
        if not html: result['errors'].append(f"{ch['username']}: не удалось загрузить"); continue
        msgs, disabled = _parse(html)
        if disabled: result['errors'].append(f"{ch['username']}: preview отключён"); continue
        result['total_messages'] += len(msgs)
        for m in filter_relevant(msgs):
            h = hashlib.md5(f"{ch['username']}_{m.get('msg_id')}_{m.get('text','')[:50]}".encode()).hexdigest()[:16]
            if h in seen: continue
            new_h.add(h); m['channel'] = ch['username']; m['channel_label'] = ch.get('label',ch['username'])
            m['region'] = ch.get('region','?'); m['hash'] = h
            result['relevant_messages'].append(m)
    seen |= new_h; _save_seen(seen)
    os.makedirs('data', exist_ok=True)
    with open(TG_CACHE_PATH,'w',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2,default=str)
    return result

def load_last_monitor_result() -> dict | None:
    if os.path.exists(TG_CACHE_PATH):
        try:
            with open(TG_CACHE_PATH,encoding='utf-8') as f: return json.load(f)
        except: pass
    return None

def load_channel_config() -> list:
    p = 'data/telegram_channels_config.json'
    if os.path.exists(p):
        try:
            with open(p,encoding='utf-8') as f: return json.load(f)
        except: pass
    return list(DEFAULT_CHANNELS)

def save_channel_config(ch: list):
    os.makedirs('data',exist_ok=True)
    with open('data/telegram_channels_config.json','w',encoding='utf-8') as f: json.dump(ch,f,ensure_ascii=False,indent=2)
