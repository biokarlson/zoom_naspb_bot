# Zoom bot

Реализовано по ТЗ: заявки (FSM), проверка занятости (бот + Яндекс Календарь), одобрение/отклонение,
создание встреч в Zoom (PMI, type 2/3) и событий в календаре, отмена (по запросу и админом),
списки «Мои встречи» / «Все встречи», шаблон инструкции и {extra_text}, подключение Zoom и CalDAV из бота.

## Запуск
1. Python 3.10+, `pip install -r requirements.txt`
2. Переменные окружения — см. `.env.example` (ключ: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
3. В `config.py` вписать `ADMIN_IDS`
4. `python main.py`
5. В боте: /start → Управление → «Подключить Zoom» и «Подключить календарь»

## Структура
- `bot/handlers/` — start, request (FSM), review (одобрить/отклонить/проверить), meetings (списки, карточки, отмена), admin_settings
- `services/` — zoom, caldav_client, availability, recurrence, approval, cancellation, templating, series
- `db/` — модели и репозиторий (SQLite)
- `web/oauth.py` — /zoom/callback

## Важно
- Не проверено на реальных Zoom и Яндекс CalDAV: первый прогон делайте на тестовых данных.
- Заявки/отмены обрабатываются защищённо от двойных нажатий (атомарная смена статуса + блокировка в процессе).
- «Все встречи» показывает статусы: на рассмотрении, одобрена, отмена запрошена.
- Состояние OAuth и FSM хранится в памяти: после перезапуска бота диалоги сбрасываются.
