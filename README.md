# Job Alerts Scraper

Bot en Python que revisa cada hora los portales de empleo de una lista de empresas y avisa por **Telegram** cuando aparece una vacante nueva.

## Cómo funciona

1. Lee `config.json`: una lista de empresas con la URL de su portal de empleo.
2. Abre cada portal con **Playwright** (Chromium headless), hasta `MAX_CONCURRENT` a la vez, y lee las tarjetas de vacantes: título, ubicación, antigüedad y link.
3. Compara el identificador de cada vacante con una base **SQLite** (`seen_jobs.db`). Si es nueva, manda un mensaje al chat de Telegram, con la imagen si tiene, y la marca como vista.
4. Reintenta las páginas que fallaron y espera hasta el próximo ciclo.

Los selectores CSS están escritos para portales armados sobre la misma plataforma de reclutamiento (mismas clases en las tarjetas). Para otro tipo de portal hay que ajustarlos en `scrape_page`.

## Configuración

Copiá los ejemplos y completalos:

```bash
cp .env.example .env
cp config.example.json config.json
```

| Variable | Descripción | Por defecto |
| --- | --- | --- |
| `TELEGRAM_TOKEN` | Token del bot (se obtiene con @BotFather) | obligatoria |
| `TELEGRAM_CHAT_ID` | Chat o canal que recibe los avisos | obligatoria |
| `MAX_CONCURRENT` | Portales procesados en paralelo | `5` |
| `RATE_LIMIT_SECONDS` | Pausa tras un timeout | `2.0` |

`config.json` tiene este formato:

```json
[
  { "company": "Empresa Ejemplo", "url": "https://empresa-ejemplo.example.com/jobs" }
]
```

## Ejecutar

Con Docker:

```bash
docker build -t job-alerts-scraper .
docker run -d --name job-alerts --env-file .env job-alerts-scraper
```

`config.json` se copia a la imagen al construirla, así que tiene que existir antes del `docker build`. La base `seen_jobs.db` vive dentro del contenedor: si lo recreás sin montar un volumen, el bot vuelve a avisar de las vacantes que ya conocía.

Sin Docker (Python 3.12):

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

## Archivos

| Archivo | Función |
| --- | --- |
| `main.py` | Bucle principal, scraping, base de datos y avisos |
| `Dockerfile` | Imagen con Python 3.12 y Chromium, ejecuta como usuario sin privilegios |
| `config.example.json` | Ejemplo de lista de portales |
| `.env.example` | Ejemplo de variables de entorno |

## Notas

- `config.json`, `.env` y `seen_jobs.db` no se suben al repositorio (ver `.gitignore`).
- Mantené las pausas entre pedidos y revisá los términos de uso de cada portal.
- Proyecto personal: no tiene tests y no está pensado para producción.

## Créditos

Este proyecto se apoya en bibliotecas de código abierto, que no están incluidas:

- [Playwright para Python](https://playwright.dev/python/) (Microsoft, Apache-2.0)
- [playwright-stealth](https://github.com/Mattwmaster58/playwright_stealth) (MIT)
- [python-telegram-bot](https://python-telegram-bot.org) (LGPL-3.0)
- [fake-useragent](https://github.com/fake-useragent/fake-useragent) (Apache-2.0)
- [aiosqlite](https://github.com/omnilib/aiosqlite) y [Pydantic](https://github.com/pydantic/pydantic)

## Licencia

Código bajo [licencia MIT](LICENSE). © 2026 Nahuel Emiliano Diaz.
