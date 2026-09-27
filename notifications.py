"""
notifications.py  v2
=====================
ИСПРАВЛЕНО:
  - Telegram теперь показывает ПОЛНОЕ тело ответа от Telegram API при ошибке
    (HTTP 400 почти всегда значит: неверный chat_id, или бот не может писать
    первым — пользователь должен сначала написать /start боту)
  - Добавлена функция test_telegram_chat() — диагностика конкретно chat_id
  - Автоотправка: send_alerts_if_critical() вызывается автоматически
    при обнаружении CRITICAL без участия пользователя
"""

import os
import json
import smtplib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

CONFIG_PATH    = 'data/notifications_config.json'
LOG_PATH       = 'data/notifications_log.json'
SENT_HASH_PATH = 'data/notifications_sent_hashes.json'  # чтобы не дублировать алерты


# ─── КОНФИГ ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        'telegram': {'enabled': False, 'bot_token': '', 'chat_id': ''},
        'slack':    {'enabled': False, 'webhook_url': ''},
        'email':    {'enabled': False, 'smtp_host': '', 'smtp_port': 587,
                     'smtp_user': '', 'smtp_pass': '', 'to_email': ''},
        'min_risk': 'CRITICAL',
        'auto_send': True,   # автоотправка при обнаружении (по умолчанию ВКЛ)
    }


def save_config(cfg: dict):
    os.makedirs('data', exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _log_notification(channel: str, status: str, message: str, error: str = None):
    log = []
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, encoding='utf-8') as f:
                log = json.load(f)
        except Exception:
            pass
    log.insert(0, {
        'timestamp': datetime.now().isoformat(),
        'channel': channel, 'status': status,
        'message': message[:100], 'error': str(error) if error else None,
    })
    log = log[:50]
    os.makedirs('data', exist_ok=True)
    with open(LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def load_log() -> list:
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


# ─── ДЕДУПЛИКАЦИЯ АВТО-АЛЕРТОВ ────────────────────────────────────────────────

def _load_sent_hashes() -> set:
    if os.path.exists(SENT_HASH_PATH):
        try:
            with open(SENT_HASH_PATH, encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def _save_sent_hashes(hashes: set):
    os.makedirs('data', exist_ok=True)
    with open(SENT_HASH_PATH, 'w', encoding='utf-8') as f:
        json.dump(list(hashes)[-200:], f)  # храним последние 200


def test_telegram_chat(bot_token: str, chat_id: str) -> tuple[bool, str]:
    """
    Полная диагностика: проверяет токен бота, тип чата (личка/группа/канал),
    и пробует отправить сообщение — с понятными инструкциями под каждый случай.
    """
    if not bot_token or not bot_token.strip():
        return False, "❌ Bot Token не указан"
    if not chat_id or not chat_id.strip():
        return False, "❌ Chat ID не указан"

    chat_id = chat_id.strip()

    # Шаг 1: проверяем токен через getMe
    try:
        url = f'https://api.telegram.org/bot{bot_token.strip()}/getMe'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get('ok'):
                return False, f"❌ Bot Token невалиден: {result.get('description')}"
            bot_name = result['result'].get('username', '?')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return False, f"❌ Bot Token невалиден (HTTP {e.code}): {body[:200]}"
    except Exception as e:
        return False, f"❌ Не удалось проверить токен: {e}"

    # Шаг 2: пробуем узнать инфо о чате через getChat — это безопаснее,
    # чем сразу слать сообщение, и даёт понятную причину ошибки
    chat_type = None
    chat_title = None
    try:
        url = f'https://api.telegram.org/bot{bot_token.strip()}/getChat?chat_id={urllib.parse.quote(chat_id)}'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get('ok'):
                chat_type = result['result'].get('type')   # private | group | supergroup | channel
                chat_title = result['result'].get('title') or result['result'].get('username') or chat_id
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            desc = json.loads(body).get('description', body)
        except Exception:
            desc = body

        is_negative = chat_id.lstrip('-').isdigit() and chat_id.startswith('-')
        if 'chat not found' in desc.lower():
            if is_negative:
                hint = (f"\n\n💡 ID `{chat_id}` похож на ID группы/канала, но бот его не находит. "
                       f"ПРОВЕРЬ: бот @{bot_name} добавлен в эту группу/канал? "
                       f"Если это канал — бот должен быть админом канала.")
            else:
                hint = (f"\n\n💡 ID `{chat_id}` похож на личный User ID. Для личной переписки с ботом "
                       f"нужно: открыть @{bot_name} в Telegram → нажать Start (или написать что угодно) "
                       f"ОДИН РАЗ. После этого бот сможет писать тебе.")
            return False, f"❌ Чат не найден (HTTP {e.code}): {desc}{hint}"
        return False, f"❌ HTTP {e.code}: {desc}"
    except Exception as e:
        return False, f"❌ Не удалось получить инфо о чате: {e}"

    # Шаг 3: отправляем тестовое сообщение
    type_label = {
        'private': 'личный чат', 'group': 'группа',
        'supergroup': 'супергруппа', 'channel': 'канал'
    }.get(chat_type, chat_type or '?')

    ok, msg = send_telegram(bot_token, chat_id,
                            f'✅ Тест соединения с ботом @{bot_name} прошёл успешно!\n'
                            f'Тип чата: {type_label}' + (f' «{chat_title}»' if chat_title else ''))
    if ok:
        return True, (f"✅ Бот @{bot_name} подключен к {type_label} "
                      f"«{chat_title or chat_id}» — сообщение отправлено!")
    else:
        return False, f"✅ Чат найден ({type_label}), НО отправка не удалась: {msg}"


# ─── TELEGRAM (с полной диагностикой) ────────────────────────────────────────

def send_telegram(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """
    Returns (success, message). При ошибке message содержит ПОЛНОЕ тело ответа
    Telegram API, чтобы можно было понять точную причину (chat not found,
    bot was blocked, can't parse entities, etc.)
    """
    if not bot_token or not bot_token.strip():
        return False, "Bot Token пустой"
    if not chat_id or not chat_id.strip():
        return False, "Chat ID пустой"

    try:
        url = f'https://api.telegram.org/bot{bot_token.strip()}/sendMessage'
        payload = json.dumps({
            'chat_id': chat_id.strip(),
            'text': text,
            'parse_mode': 'HTML',
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get('ok'):
                return True, 'OK'
            return False, f"Telegram API: {result.get('description', 'Unknown error')}"
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            parsed = json.loads(body)
            desc = parsed.get('description', body)
        except Exception:
            desc = body
        # Расшифровка частых ошибок
        hint = ''
        if 'chat not found' in desc.lower():
            hint = (' → Chat ID неверный. Это должен быть ID чата КУДА бот пишет, '
                   'не твой личный ID. Напиши боту /start в личке, затем используй '
                   'свой User ID — Telegram должен показать "chat not found" только '
                   'если бот никогда не получал сообщений от этого chat_id.')
        elif 'bot was blocked' in desc.lower():
            hint = ' → Бот заблокирован пользователем. Разблокируй бота в Telegram.'
        elif 'unauthorized' in desc.lower():
            hint = ' → Bot Token неверный или отозван. Проверь токен у @BotFather.'
        return False, f"HTTP {e.code}: {desc}{hint}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ─── SLACK ───────────────────────────────────────────────────────────────────

def send_slack(webhook_url: str, text: str) -> tuple[bool, str]:
    if not webhook_url or not webhook_url.strip():
        return False, "Webhook URL пустой"
    try:
        payload = json.dumps({'text': text}).encode('utf-8')
        req = urllib.request.Request(webhook_url.strip(), data=payload,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return False, f"HTTP {e.code}: {body[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ─── EMAIL ───────────────────────────────────────────────────────────────────

def send_email(cfg: dict, subject: str, html_body: str) -> tuple[bool, str]:
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = cfg['smtp_user']
        msg['To']   = cfg['to_email']
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        with smtplib.SMTP(cfg['smtp_host'], int(cfg['smtp_port']), timeout=15) as server:
            server.ehlo(); server.starttls()
            server.login(cfg['smtp_user'], cfg['smtp_pass'])
            server.sendmail(cfg['smtp_user'], cfg['to_email'], msg.as_string())
        return True, 'OK'
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ─── ФОРМАТИРОВАНИЕ ───────────────────────────────────────────────────────────

def _format_pattern_alert(patterns: list, df_stats: dict = None) -> dict:
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    critical = [p for p in patterns if p.get('risk') == 'CRITICAL']
    high     = [p for p in patterns if p.get('risk') == 'HIGH']

    tg_lines = [f'🚨 <b>Hidden Business Detector</b> · {now}', '']
    if critical:
        tg_lines.append(f'🔴 <b>CRITICAL ({len(critical)})</b>')
        for p in critical[:5]:
            tg_lines.append(f'  • {p.get("name","?")} ({p.get("matched_count",0)} мерч.)')
    if high:
        tg_lines.append(f'🟠 <b>HIGH ({len(high)})</b>')
        for p in high[:3]:
            tg_lines.append(f'  • {p.get("name","?")}')
    if df_stats:
        tg_lines += ['', f'📊 Всего мерчантов: {df_stats.get("total",0):,}',
                     f'🔥 HOT: {df_stats.get("hot",0):,} | ⚡ WARM: {df_stats.get("warm",0):,}']
    telegram_text = '\n'.join(tg_lines)

    slack_text = (f'🚨 *Hidden Business Detector* · {now}\n'
                 f'🔴 CRITICAL: {len(critical)} | 🟠 HIGH: {len(high)}\n'
                 + '\n'.join([f'• {p.get("name")}' for p in (critical+high)[:5]]))

    rows = ''.join([
        f'<tr><td style="padding:6px 12px;border-bottom:1px solid #e2e8f0;">'
        f'<b style="color:{"#b71c1c" if p.get("risk")=="CRITICAL" else "#e65100"};">{p.get("risk")}</b></td>'
        f'<td style="padding:6px 12px;border-bottom:1px solid #e2e8f0;">{p.get("name","")}</td>'
        f'<td style="padding:6px 12px;border-bottom:1px solid #e2e8f0;">{p.get("matched_count",0)} мерч.</td></tr>'
        for p in patterns[:10]])
    email_html = f"""
    <div style="font-family:Inter,sans-serif;max-width:600px;">
      <div style="background:linear-gradient(135deg,#0d3b8e,#1565c0);padding:20px;border-radius:10px 10px 0 0;">
        <h2 style="color:white;margin:0;">🔍 Hidden Business Detector</h2>
        <p style="color:rgba(255,255,255,0.8);margin:4px 0 0;">Обнаружены паттерны риска · {now}</p>
      </div>
      <div style="background:#fff;padding:20px;border:1px solid #e2e8f0;border-radius:0 0 10px 10px;">
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="background:#f8fafc;">
            <th style="padding:8px 12px;text-align:left;font-size:0.8rem;color:#64748b;">РИСК</th>
            <th style="padding:8px 12px;text-align:left;font-size:0.8rem;color:#64748b;">ПАТТЕРН</th>
            <th style="padding:8px 12px;text-align:left;font-size:0.8rem;color:#64748b;">МЕРЧАНТЫ</th>
          </tr></thead><tbody>{rows}</tbody>
        </table>
      </div>
    </div>"""

    return {'telegram': telegram_text, 'slack': slack_text,
            'email_subject': f'⚠️ HBD Alert: {len(critical)} CRITICAL, {len(high)} HIGH · {now}',
            'email_html': email_html}


# ─── ОТПРАВКА (ручная, с кнопки) ─────────────────────────────────────────────

def send_alerts(patterns: list, df_stats: dict = None) -> dict:
    cfg = load_config()
    min_risk_order = {'MEDIUM':0,'HIGH':1,'CRITICAL':2}
    min_level = min_risk_order.get(cfg.get('min_risk','CRITICAL'), 2)
    filtered = [p for p in patterns if min_risk_order.get(p.get('risk','LOW'),-1) >= min_level]

    if not filtered:
        return {'skipped': 'Нет паттернов с достаточным уровнем риска'}

    msgs = _format_pattern_alert(filtered, df_stats)
    results = {}

    tg = cfg.get('telegram', {})
    if tg.get('enabled') and tg.get('bot_token') and tg.get('chat_id'):
        ok, err = send_telegram(tg['bot_token'], tg['chat_id'], msgs['telegram'])
        results['telegram'] = 'OK' if ok else f'Ошибка: {err}'
        _log_notification('telegram', 'ok' if ok else 'error', msgs['telegram'], None if ok else err)

    sl = cfg.get('slack', {})
    if sl.get('enabled') and sl.get('webhook_url'):
        ok, err = send_slack(sl['webhook_url'], msgs['slack'])
        results['slack'] = 'OK' if ok else f'Ошибка: {err}'
        _log_notification('slack', 'ok' if ok else 'error', msgs['slack'], None if ok else err)

    em = cfg.get('email', {})
    if em.get('enabled') and em.get('smtp_host') and em.get('to_email'):
        ok, err = send_email(em, msgs['email_subject'], msgs['email_html'])
        results['email'] = 'OK' if ok else f'Ошибка: {err}'
        _log_notification('email', 'ok' if ok else 'error', msgs['email_subject'], None if ok else err)

    if not results:
        results['skipped'] = 'Нет настроенных каналов'
    return results


# ─── АВТО-ОТПРАВКА (без участия пользователя) ────────────────────────────────

def send_alerts_if_critical(patterns: list, df_stats: dict = None) -> dict | None:
    """
    Вызывается АВТОМАТИЧЕСКИ после обнаружения паттернов (например, после
    загрузки данных или после пересчёта). Отправляет уведомления ТОЛЬКО если:
      1. auto_send включён в конфиге (по умолчанию True)
      2. Есть хотя бы 1 канал настроен и enabled
      3. Эти конкретные паттерны ещё не отправлялись (дедупликация по хэшу)

    Returns: dict результатов или None если отправка не требовалась/не настроена
    """
    cfg = load_config()
    if not cfg.get('auto_send', True):
        return None

    any_enabled = (cfg['telegram'].get('enabled') or
                  cfg['slack'].get('enabled') or
                  cfg['email'].get('enabled'))
    if not any_enabled:
        return None

    min_risk_order = {'MEDIUM':0,'HIGH':1,'CRITICAL':2}
    min_level = min_risk_order.get(cfg.get('min_risk','CRITICAL'), 2)
    critical_patterns = [p for p in patterns if min_risk_order.get(p.get('risk','LOW'),-1) >= min_level]

    if not critical_patterns:
        return None

    # Дедупликация: не слать повторно те же паттерны
    import hashlib
    sent_hashes = _load_sent_hashes()
    new_patterns = []
    new_hashes = set()
    for p in critical_patterns:
        h = hashlib.md5(f"{p.get('id','')}_{p.get('matched_count',0)}".encode()).hexdigest()[:12]
        if h not in sent_hashes:
            new_patterns.append(p)
            new_hashes.add(h)

    if not new_patterns:
        return None  # уже отправляли именно эти паттерны ранее

    results = send_alerts(new_patterns, df_stats)

    # Сохраняем хэши только если хоть что-то отправилось успешно
    if any('OK' in str(v) for v in results.values()):
        sent_hashes |= new_hashes
        _save_sent_hashes(sent_hashes)

    return results


def reset_dedup():
    """Сбрасывает историю отправленных алертов (для повторного тестирования)."""
    if os.path.exists(SENT_HASH_PATH):
        os.remove(SENT_HASH_PATH)


def send_test_alert(bot_token: str = None, chat_id: str = None) -> dict:
    test_pattern = [{'id':'test_001','name':'TEST: Тестовый паттерн','risk':'CRITICAL',
                     'matched_count':42,'type':'known'}]
    return send_alerts(test_pattern, {'total':2165,'hot':101,'warm':8})
