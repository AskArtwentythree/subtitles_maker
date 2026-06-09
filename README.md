# nutr_bot — контент-фабрика субтитров

Генерация reels/shorts-субтитров для коротких видео о фичах продукта.
Этап 1: тестируем провайдеров субтитров на локальных видео, выбираем лучший,
затем оборачиваем в Telegram-бота.

## Структура

```
providers/        # провайдеры субтитров с общим интерфейсом
  base.py         # SubtitleProvider / SubtitleOptions / SubtitleResult
  veed_fal.py     # VEED через fal.ai (veed/subtitles)
cli.py            # тест провайдеров на локальном файле
config.py         # ключи из .env
bot.py            # Telegram-бот: видео -> 3 варианта субтитров
samples/          # тестовые видео
output/           # результаты
```

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env         # впиши FAL_KEY и TELEGRAM_BOT_TOKEN
```

Ключ fal.ai: https://fal.ai/dashboard/keys
Токен бота: получить у @BotFather в Telegram.

## Запуск (тест субтитров)

```bash
# список доступных стилей
python cli.py --list-presets

# базовый прогон (язык определится автоматически)
python cli.py samples/feature.mp4

# с конкретным пресетом и языком
python cli.py samples/feature.mp4 --preset glass --language ru-RU
```

Результат сохраняется в `output/`.

## Провайдеры

| Провайдер | Модель | Что делает | Цена | Размер шрифта |
|-----------|--------|------------|------|---------------|
| `veed` | `veed/subtitles` (fal.ai) | видео → видео с вшитыми субтитрами, пресеты, тиры | от $0.10/мин (динам. пресеты — 2x) | нет (задаёт пресет) |
| `autosub` | `fal-ai/workflow-utilities/auto-subtitle` | караоке-субтитры с word-level подсветкой | $0.03/мин | да (`font_size`) |

### autosub: провайдер-специфичные параметры

Передаются через `--opt key=value` (можно несколько раз). Основные:

| Параметр | Значения | По умолчанию |
|----------|----------|--------------|
| `font_size` | int | 100 |
| `font_weight` | normal / bold / black | bold |
| `font_color` | white, black, red, ... (enum, не hex) | white |
| `highlight_color` | enum цветов | purple |
| `stroke_width` | int (пикс.) | 3 |
| `stroke_color` | enum | black |
| `background_color` | enum / none / transparent | none |
| `background_opacity` | 0.0–1.0 | — |
| `position` | top / center / bottom | bottom |
| `y_offset` | int | 75 |
| `words_per_subtitle` | 1 = по слову, 8–12 = предложения | 3 |
| `enable_animation` | true / false | true |

Пример:

```bash
python cli.py samples/features.MOV --provider autosub --language ru \
    --opt font_size=140 --opt font_color=white --opt stroke_width=4 \
    --opt highlight_color=yellow --opt words_per_subtitle=3
```

## Telegram-бот

Бот принимает озвученную запись экрана и присылает обратно **3 варианта** субтитров:

1. `autosub_hustle` — fal-ai/auto-subtitle, `font_size=50`, `words_per_subtitle=2`, обводка;
2. `shadeplay` — Veed, пресет `shadeplay`;
3. `hustle` — Veed, пресет `hustle`.

Запуск:

```bash
python bot.py
```

Затем напиши боту `/start` и пришли видео (mp4/mov) с голосом.

Настройки в `.env`:

| Переменная | Назначение |
|------------|------------|
| `TELEGRAM_BOT_TOKEN` | токен от @BotFather (обязательно) |
| `FAL_KEY` | ключ fal.ai (обязательно) |
| `DEFAULT_SUBTITLE_LANGUAGE` | язык распознавания, по умолчанию `ru-RU` (пусто = автоопределение Veed) |

⚠️ Ограничения Telegram Bot API: бот может **скачать** входной файл размером до **20 МБ**
и **отправить** результат до **50 МБ**. Для длинных роликов сжимай видео.

## Деплой на Railway

Бот работает на long polling, поэтому это обычный **worker** — веб-сервер и порт не нужны.
В репозитории уже лежат `Procfile`, `runtime.txt` и `railway.json`.

### Вариант A — через Railway CLI (без GitHub)

```bash
npm i -g @railway/cli
railway login
railway init            # создать новый проект
railway up              # собрать и задеплоить текущую папку
```

Затем задай переменные окружения (Variables):

```bash
railway variables --set FAL_KEY=xxx --set TELEGRAM_BOT_TOKEN=xxx
railway variables --set DEFAULT_SUBTITLE_LANGUAGE=ru-RU
```

### Вариант B — через GitHub

```bash
git init
git add .
git commit -m "nutr_bot: subtitle telegram bot"
git branch -M main
git remote add origin <твой-репозиторий>
git push -u origin main
```

Затем на railway.app: **New Project → Deploy from GitHub repo** → выбери репозиторий.
В разделе **Variables** добавь `FAL_KEY`, `TELEGRAM_BOT_TOKEN`, `DEFAULT_SUBTITLE_LANGUAGE`.

### Важно
- **`.env` не коммитится** (он в `.gitignore`) — ключи задаются только через Variables в Railway.
- Должен работать **только один** экземпляр бота (long polling). Если параллельно запустить
  бота локально и на Railway, Telegram вернёт ошибку `Conflict: terminated by other getUpdates`.
  Останови локальный `python bot.py` перед деплоем.
- Файловая система Railway эфемерна — это ок, временные видео всё равно удаляются после обработки.

Дальше: сравнить veed vs autosub, выбрать дефолт и (опционально) ветку CapCutAPI.
