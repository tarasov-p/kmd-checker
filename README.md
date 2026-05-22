# kmd-checker

Простой stateless веб-сервис, который проверяет чертёж КМД (металлоконструкции)
на 2 типа ошибок из 23 — **путаница в артикулах** и **оформление чертежей**.
Конструктивные вопросы (прочность, концентраторы, катет шва) бот не судит — помечает как
требующие ручной проверки.

- Загружаем **PDF / DWG / DXF** через drag-and-drop.
- Бот рендерит страницы, парсит факты, прогоняет 8 правил и финальный LLM-judge.
- Возвращает один из вердиктов:
  - `no_issues` — ошибок не найдено;
  - `errors_found` — ошибки + список findings;
  - `manual_review_required` — нужна ручная проверка;
  - `not_a_drawing` — это не похоже на чертёж;
  - `unsupported_format` — формат / размер не поддерживаются.

**История не сохраняется** — никаких БД, очередей и кэшей: только память процесса и
`tempfile.TemporaryDirectory()` на время одной проверки.

## Архитектура (одностраничная)

```
браузер ──multipart──> FastAPI (uvicorn workers=1)
   │                       │
   │  SSE /stream          ├── tempfile.TemporaryDirectory()
   │ <─────────────────────┤   ├── original.pdf|dwg|dxf
   │                       │   └── pages/page_*.png
   │                       │
   │                       └── asyncio.Task(run_pipeline):
   │                            DWG → DXF (libredwg)
   │                            DXF → PDF (ezdxf + matplotlib)
   │                            render PDF (PyMuPDF 220 DPI)
   │                            pre-check  (gemini-3.1-pro-preview)
   │                            extract    (gemini-3.1-pro-preview)
   │                            rules      (8 правил)
   │                            judge      (claude-opus-4-7 → fallback gpt-5.5)
   │                            merge + verdict
   │                            session.status = "done"
```

## Зависимости

- Python 3.12+
- `libredwg-bin` в системе (для DWG; в Docker уже стоит).
- OpenRouter API key.

## Быстрый старт (Docker)

```bash
git clone git@github.com:tarasov-p/kmd-checker.git
cd kmd-checker
cp .env.example .env
$EDITOR .env   # вставить OPENROUTER_API_KEY
docker compose up --build
open http://localhost:8080
```

## Локально без Docker (uv)

```bash
# 1. зависимости
uv sync --group dev

# 2. DWG-конвертер (только если планируете грузить DWG)
brew install libredwg          # macOS
# или: apt-get install libredwg-bin

# 3. ключ
export OPENROUTER_API_KEY=sk-or-v1-...

# 4. сервер
uv run kmd-checker server --reload
# или прямой проход без HTTP:
uv run kmd-checker check examples/example.pdf

# тесты
uv run pytest -q
```

## API

| метод | путь | назначение |
|---|---|---|
| `GET`  | `/` | drag-and-drop UI |
| `GET`  | `/ping` | health |
| `POST` | `/api/v1/kmd/check` | загрузить файл (multipart `file`), вернёт `{session_id}` |
| `GET`  | `/api/v1/kmd/check/{session_id}` | состояние |
| `GET`  | `/api/v1/kmd/check/{session_id}/stream` | SSE-стрим с heartbeat |
| `GET`  | `/api/v1/kmd/check/{session_id}/pages/{i}.png` | превью страницы |

POST поддерживает query-параметр `?force=1` — пропустить пре-чек «это чертёж?».

## Что покрывает

8 синхронных правил (без токенов):

- `filename_title_mismatch` — имя файла vs обозначение в штампе.
- `part_code_mismatch` — код в основной надписи vs дублирующие штампы.
- `left_right_mismatch` — левая/правая в разных местах чертежа.
- `revision_index_mismatch` — хвост артикула после последнего разделителя.
- `material_mismatch` — AISI 304 / 430 в filename vs штамп.
- `missing_title_block_field` — нет материала/масштаба/общего числа листов.
- `drawing_designation_mismatch_between_sheets` — разное обозначение на листах.
- `specification_fastener_class_missing` *(experimental)* — крепёж без класса прочности
  при наличии требования в ТТ.

Дальше vision-LLM (`claude-opus-4-7`) с строгим JSON-промптом, fallback на `gpt-5.5`
с `reasoning_effort=xhigh` (graceful degrade на `high` при невалидном enum).

## Тесты

```bash
uv run pytest -q
```

Юниты:
- `tests/test_article_parser.py` — нормализация и токенизация на 5 реальных артикулах
  (`IB190x142.6Z345-l`, `SM43х113х60.4Z345-r`, `ADS.W50.168x81a84.15`, `M50/5.12.10E`,
  `0,5В/Пло-13х20/2490Е`).
- `tests/test_rules_engine.py` — 7 правил + experimental на синтетических `ExtractedFacts`.

## Ограничения

- **Stateless** — повторная загрузка того же файла = повторная оплата токенов
  (~$0.20-0.30 за чек на `claude-opus-4-7` vision + extract).
- VM/контейнер reboot во время проверки → сессия теряется, юзер видит `error`.
- Максимум 50 страниц и 100 МБ на один файл.
- `libredwg` ест DWG 2000-2018. XREF, цветные слои нестандартного DXF могут падать —
  тогда UI говорит «экспортируйте PDF из CAD».

## Лицензия

MIT.
