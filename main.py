import asyncio
import aiosqlite
import logging
import os
import json
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright, TimeoutError
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from pydantic import BaseModel, ValidationError
import html
from fake_useragent import UserAgent
from playwright_stealth import stealth_async

# Setup logging: console + rotating file
from logging.handlers import RotatingFileHandler
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
file_handler = RotatingFileHandler('app.log', maxBytes=5*1024*1024, backupCount=5)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

# User agent generator
ua = UserAgent()

# Env vars (from Docker)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
MAX_CONCURRENT = int(os.getenv('MAX_CONCURRENT', 5))
RATE_LIMIT_SECONDS = float(os.getenv('RATE_LIMIT_SECONDS', 2.0))

# Depuración
logging.info(f"TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID}")

# Validate required env vars
required_envs = ['TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID']
for env in required_envs:
    if not os.getenv(env):
        raise ValueError(f"Missing required environment variable: {env}")

# Pydantic model for config validation
class PageConfig(BaseModel):
    company: str
    url: str

# Load and validate config
try:
    with open('config.json', 'r') as f:
        raw_config = json.load(f)
    PAGES = [PageConfig(**item) for item in raw_config]
except (FileNotFoundError, json.JSONDecodeError, ValidationError) as e:
    raise ValueError(f"Invalid config.json: {e}")

# DB setup
DB_FILE = 'seen_jobs.db'

async def init_db():
    logging.info(f"Initializing database at {DB_FILE}")
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS seen_jobs (job_id TEXT PRIMARY KEY)''')
        await db.commit()
    logging.info("Database initialized successfully")

async def is_new_job(db, job_id):
    async with db.execute('SELECT 1 FROM seen_jobs WHERE job_id = ?', (job_id,)) as cursor:
        return await cursor.fetchone() is None

async def mark_as_seen(db, job_id):
    await db.execute('INSERT OR IGNORE INTO seen_jobs (job_id) VALUES (?)', (job_id,))
    await db.commit()

# Scrape single page (reuse browser, create new context/page)
async def scrape_page(page_data: PageConfig, db, bot, sem: asyncio.Semaphore, browser):
    company = page_data.company
    url = page_data.url
    logging.info(f"Scraping {company} at {url}")
    
    async with sem:
        context = None
        page = None
        try:
            user_agent = ua.random  # Generate random user agent
            context = await browser.new_context(user_agent=user_agent)
            page = await context.new_page()
            await stealth_async(page)
            
            for attempt in range(2):  # Retry x1
                try:
                    await page.goto(url, timeout=60000)
                    await page.wait_for_selector('.card-vacancy', timeout=30000)
                    
                    cards = await page.query_selector_all('a[href^="/jobs/get_vacancy/"] .card')
                    for card in cards:
                        title_elem = await card.query_selector('h4.name__vacancy')
                        location_elem = await card.query_selector('p.card-text:has(i.hr-Location-pin)')
                        time_elem = await card.query_selector('p.vacancy-time')
                        new_badge = await time_elem.query_selector('span.font-weight-bold.hrc-green.text-uppercase')
                        link = await card.evaluate('(el) => el.closest("a").href') if await card.evaluate('(el) => !!el.closest("a")') else None
                        
                        if not title_elem or not time_elem or not link:
                            continue
                        
                        title = await title_elem.inner_text()
                        location = await location_elem.inner_text() if location_elem else 'No especificada'
                        time_text = await time_elem.inner_text()
                        is_nuevo = new_badge and 'Nuevo' in await new_badge.inner_text()
                        job_id = link.split('/get_vacancy/')[-1] if '/get_vacancy/' in link else None
                        
                        if job_id and (is_nuevo or await is_new_job(db, job_id)):
                            thumbnail_url = None
                            img_elem = await card.query_selector('img')  # Adjust if needed
                            if img_elem:
                                thumbnail_url = await img_elem.get_attribute('src')
                            
                            message = f"NEW - {company}:\n{title.strip()}\nHace {time_text.strip().replace('Nuevo', '').strip()}\nUbicación: {location.strip()}\nLink: {link}"
                            message = html.escape(message)
                            
                            try:
                                if thumbnail_url:
                                    await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=thumbnail_url, caption=message, parse_mode=ParseMode.HTML)
                                else:
                                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode=ParseMode.HTML)
                            except TelegramError as te:
                                logging.error(f"Telegram error: {te}")
                            
                            await mark_as_seen(db, job_id)
                    
                    return True  # Success
                except TimeoutError as e:
                    logging.warning(f"Timeout on {url}, attempt {attempt+1}: {e}")
                    await asyncio.sleep(RATE_LIMIT_SECONDS)  # Simple rate limit after timeout
                except Exception as e:
                    logging.error(f"Error on {url}, attempt {attempt+1}: {e}")
            
            return False  # Failed after retries
        finally:
            if page:
                await page.close()
            if context:
                await context.close()

# Main loop
async def main():
    logging.info("Starting job scraper...")
    await init_db()
    bot = Bot(token=TELEGRAM_TOKEN)
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    
    async with async_playwright() as p:  # Global playwright for the whole script
        while True:
            start_time = datetime.now(timezone.utc)
            logging.info(f"Starting hourly scrape at {start_time}")
            
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])  # Single browser per cycle
            try:
                async with aiosqlite.connect(DB_FILE) as db:
                    failed_pages = []
                    tasks = []
                    
                    for page_data in PAGES:
                        tasks.append(scrape_page(page_data, db, bot, sem, browser))
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for i, res in enumerate(results):
                        if isinstance(res, Exception) or not res:
                            failed_pages.append(PAGES[i])
                    
                    # Retry failed: x2 with 5s pause
                    for retry_round in range(2):
                        if not failed_pages:
                            break
                        logging.info(f"Retrying {len(failed_pages)} failed pages, round {retry_round+1}")
                        new_failed = []
                        tasks = []
                        
                        for page_data in failed_pages:
                            tasks.append(scrape_page(page_data, db, bot, sem, browser))
                        
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        for i, res in enumerate(results):
                            if isinstance(res, Exception) or not res:
                                new_failed.append(failed_pages[i])
                        
                        failed_pages = new_failed
                        await asyncio.sleep(5)
                    
                    if failed_pages:
                        logging.warning(f"Final failed pages: {[p.company for p in failed_pages]}")
            finally:
                if browser:
                    await browser.close()
            
            end_time = datetime.now(timezone.utc)
            next_run = start_time + timedelta(hours=1)
            sleep_seconds = max(0, (next_run - end_time).total_seconds())
            logging.info(f"Scrape done at {end_time}. Sleeping {sleep_seconds:.2f}s until {next_run}")
            await asyncio.sleep(sleep_seconds)

if __name__ == '__main__':
    asyncio.run(main())