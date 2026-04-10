# Дизайн разделения API и public URL для 3X-UI

## Цель

Разделить в приложении адрес 3X-UI для API-логина и служебных запросов от публичного адреса, который используется для построения subscription URL.

## Проблема

- Сейчас приложение использует один `XUI_BASE_URL` и для `/login`/`/panel/api/...`, и для `/sub/...`.
- В текущей инфраструктуре эти адреса различаются:
  - API и логин доступны по локальному адресу панели с `webBasePath`
  - публичная подписка доступна по внешнему адресу без `webBasePath`
- Из-за этого невозможно одновременно иметь рабочий логин в 3X-UI и корректные subscription URL.

## Решение

- Оставить `XUI_BASE_URL` как API base URL для обратной совместимости.
- Добавить новый optional config `XUI_PUBLIC_BASE_URL`.
- Все запросы клиента 3X-UI (`/login`, `/panel/api/...`) выполнять через API base URL.
- Все subscription URL строить через public base URL.
- Если `XUI_PUBLIC_BASE_URL` не задан, использовать `XUI_BASE_URL` как fallback.

## Изменения по компонентам

### Config

- `config.py` получает новое поле `xui_public_base_url: str`
- `.env.example` и документация получают новую переменную `XUI_PUBLIC_BASE_URL`

### XUI client

- `XUIClient` хранит:
  - `api_base_url`
  - `public_base_url`
- `_build_url()` продолжает строить только API URL
- `_build_subscription_url()` строит подписки от public base URL

### Обработчики и webapp

- Нормализация subscription URL должна использовать public base URL клиента, а не API base URL
- Остальная логика не меняется

## Обратная совместимость

- Старые конфиги продолжают работать без изменений, если `XUI_PUBLIC_BASE_URL` не задан
- В этом случае поведение останется прежним

## Проверка результата

- Бот успешно логинится в 3X-UI по API base URL
- Подписка строится по public base URL
- Ссылка подписки открывается в клиенте без `404`

## Ограничения

- Конфигурация должна задавать корректный `XUI_API`/`XUI_PUBLIC` split в `.env`
- Если публичный subscription endpoint не совпадает с `XUI_SUBSCRIPTION_PATH`, его нужно задавать отдельно как и раньше
