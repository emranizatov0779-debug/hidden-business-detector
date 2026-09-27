"""
model_cache.py
==============
ИСПРАВЛЯЕТ: "после каждого действия модель долго переобучается заново"

КОРЕНЬ ПРОБЛЕМЫ:
  Streamlit держит file_uploader в session_state виджета. При любом действии
  (нажатии любой кнопки) весь скрипт перезапускается (rerun), и блок
  `if df_loaded is not None: ...` выполняется СНОВА, потому что `up`
  (результат file_uploader) остаётся непустым между rerun'ами — Streamlit
  не "забывает" загруженные файлы просто потому что где-то нажали кнопку.

РЕШЕНИЕ:
  Хэшируем содержимое загруженных файлов. Обучение/скоринг выполняется
  ТОЛЬКО если хэш изменился по сравнению с последним обработанным.
  Если хэш совпадает — берём уже посчитанный df из session_state,
  ничего заново не считаем.
"""

import hashlib
import streamlit as st


def compute_upload_hash(uploaded_files) -> str:
    """
    Считает хэш по именам + размерам загруженных файлов.
    Не читает весь файл повторно (дорого для больших CSV) — достаточно
    имени+размера чтобы понять "это те же самые файлы, что в прошлый раз".
    """
    if not uploaded_files:
        return ''
    parts = []
    for f in uploaded_files:
        # .size доступен у UploadedFile без перечитывания содержимого
        parts.append(f"{f.name}:{f.size}")
    combined = '|'.join(sorted(parts))
    return hashlib.md5(combined.encode()).hexdigest()


def should_reprocess(uploaded_files) -> bool:
    """
    True только если:
      - это первая загрузка (ничего не обработано раньше), ИЛИ
      - набор файлов реально изменился (новый файл, другой размер)
    """
    if not uploaded_files:
        return False

    new_hash = compute_upload_hash(uploaded_files)
    old_hash = st.session_state.get('_last_upload_hash', None)

    if new_hash != old_hash:
        st.session_state['_last_upload_hash'] = new_hash
        return True
    return False


def mark_processed(uploaded_files):
    """Явно отметить текущий набор файлов как уже обработанный."""
    st.session_state['_last_upload_hash'] = compute_upload_hash(uploaded_files)


def reset_processed_marker():
    """Сбросить маркер — следующая загрузка форсированно переобучит модель."""
    if '_last_upload_hash' in st.session_state:
        del st.session_state['_last_upload_hash']
