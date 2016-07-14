import asyncio
import traceback
from functools import partial
import datetime

import aiohttp
import pytz

from erepublikby_bot.parsers.erepublik_deutchland import get_last_battle


MINSK_ZONE = pytz.timezone('Europe/Minsk')


API_BASE_URL = 'https://api.telegram.org/bot{token}/{method}'
MAXIMUM_CONCURENT_REQUESTS = 50
REQUESTS_TIMEOUT = 10
LONG_POLLING_TIME = 300
HELLO_TEXT = """\
Вас вітае бот [{first_name}](https://telegram.me/{username})!

Даступныя каманды:
/rw - Пакзвае, калі будзе наступнае пераможнае паўстанне.\
"""
RW_TEXT = """\
Наступнае пераможнае паўстаньне можна падтрымаць у {region} (Беларусь) \
{time} (±3 хвіліны). Для гэтага вам трэба знаходзіцца ў пазначаным \
рэгіёне і націснуць кнопку падтрымкі на галоўнай старонцы гульні.

http://prntscr.com/bsot4o\
"""
RETRIES = 5


def convert_erepublik_time_to_belarus_time(time):
    return time + datetime.timedelta(hours=10)


class BadResponseError(Exception):
    pass


class Bot:
    def __init__(self, loop, logger, token, admins=tuple()):
        self.logger = logger
        self.loop = loop
        self.token = token
        self.admins = admins

        self.running = False
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.semaphore = asyncio.Semaphore(
            MAXIMUM_CONCURENT_REQUESTS, loop=self.loop)
        self.last_seen_update_id = 0
        self.pull_task = None
        self.pending_tasks = set()

    async def run(self):
        if self.running:
            raise Exception('Already started')

        self.running = True

        try:
            bot_info = await self.get_bot_info()
        except Exception:
            self.logger.critical('Cant connect to telegram', exc_info=True)
            return

        self.bot_info = bot_info

        retry = 0

        while self.running:
            self.pull_task = self.loop.create_task(self.pull_events())
            try:
                await self.pull_task
            except asyncio.TimeoutError:  # Try again if timeout error received
                pass
            except Exception:  # Shutdown otherwise
                self.on_task_done(self.pull_task)
                retry += 1
                if retry == RETRIES:
                    raise
                await asyncio.sleep(2 ** retry)

    def on_task_done(self, task, payload=None):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            self.logger.error(
                'An error occured %s', str(payload), exc_info=True)
            self.spawn_task(
                self.send_to_admins, traceback.format_exc(), payload)

        try:
            self.pending_tasks.remove(task)
        except KeyError:
            pass

    def spawn_task(self, coro, *args, **kwargs):
        task = self.loop.create_task(coro(*args, **kwargs))
        self.pending_tasks.add(task)
        task.add_done_callback(partial(
            self.on_task_done, payload=(coro.__name__, args, kwargs)))

    async def send_to_admins(self, tb, additional):
        async def send_exception():
            await self.post('sendMessage', chat_id=admin, text=tb)
            await self.post('sendMessage', chat_id=admin, text=str(additional))

        tasks = set()
        for admin in self.admins:
            tasks.add(send_exception())
        await asyncio.wait(tasks, loop=self.loop)

    async def pull_events(self):
        while self.running:
            self.logger.debug('Pull updates')
            events = await self.get(
                'getUpdates', offset=self.last_seen_update_id,
                timeout=LONG_POLLING_TIME, _short=False)

            self.logger.debug('Events getted %s', events)

            for event in events:
                self.logger.debug('Process event %s', event)
                if 'message' in event:
                    self.spawn_task(self.handle_message, event)
                else:
                    self.logger.warning('Got unexpected event %s', event)

                self.last_seen_update_id = max(
                    self.last_seen_update_id, event['update_id'] + 1)

    def clean_command(self, text):
        cmd, *args = text.split()
        if '@' in cmd:
            cmd, name, *garbage = cmd.split('@')
            if garbage:
                return None

            if name != self.bot_info['username']:
                return None

        return cmd, args

    async def handle_message(self, event):
        self.logger.debug('Got message %s', event)
        message = event['message']
        chat_id = message['chat']['id']
        message_id = message['message_id']
        text = message['text']

        if text[0] != '/':
            return await self.handle_regular_message(event)

        cmd, args = self.clean_command(text)

        if cmd == '/start' or cmd == '/help':
            return await self.send_hello_text(chat_id)
        elif cmd == '/rw':
            return await self.send_rw_data(chat_id, message_id)
        else:
            self.logger.warning('Unsupported command %s (%s)', cmd, event)

    async def handle_regular_message(self, event):
        self.logger.debug('Regular message %s', event['message']['text'])

    async def kill(self):
        self.logger.info('Atempt to graceful shutdown...')
        need_to_wait = []

        if self.pull_task is not None:
            self.pull_task.cancel()
            need_to_wait.append(self.pull_task)

        if self.pending_tasks:
            for task in self.pending_tasks:
                if not task.done():
                    task.cancel()
                    need_to_wait.append(task)

        self.session.close()

        if need_to_wait:
            await asyncio.wait(need_to_wait, loop=self.loop)

        self.running = False
        self.logger.info('Bot stopped...')

    async def get_bot_info(self):
        self.logger.info('Testing token...')
        bot_info = await self.get('getMe')
        self.logger.info(bot_info)
        return bot_info

    async def get(self, method, *, _short=True, **kwargs):
        url = API_BASE_URL.format(token=self.token, method=method)
        masked_url = API_BASE_URL.format(token='*****', method=method)
        self.logger.debug(
            'Making GET request on url %s with params %s',
            masked_url, kwargs)
        timeout = REQUESTS_TIMEOUT if _short else LONG_POLLING_TIME

        async with self.semaphore:
            with aiohttp.Timeout(timeout, loop=self.loop):
                async with self.session.get(url, params=kwargs) as resp:
                    json = await resp.json()
                    if not json or not json.get('ok', False):
                        raise BadResponseError(
                            'Telegram server returns bad response %s' % json)
                    return json['result']

    async def post(self, method, *, _short=True, **kwargs):
        url = API_BASE_URL.format(token=self.token, method=method)
        masked_url = API_BASE_URL.format(token='*****', method=method)
        self.logger.debug(
            'Making POST request on url %s with data %s',
            masked_url, kwargs)
        timeout = REQUESTS_TIMEOUT if _short else LONG_POLLING_TIME

        async with self.semaphore:
            with aiohttp.Timeout(timeout, loop=self.loop):
                async with self.session.post(url, data=kwargs) as resp:
                    json = await resp.json()
                    if not json or not json.get('ok', False):
                        raise BadResponseError(
                            'Telegram server returns bad response %s' % json)
                    return json['result']

    async def send_hello_text(self, chat_id):
        await self.post(
            'sendMessage', chat_id=chat_id,
            text=HELLO_TEXT.format(**self.bot_info),
            parse_mode='Markdown', disable_web_page_preview=True)

    async def send_rw_data(self, chat_id, msg_id):
        self.logger.info(
            'Request last battle info from erepublik-deutchland.de')
        last_battle = await get_last_battle(loop=self.loop)
        self.logger.debug('Info about last battle fetched %s', last_battle)

        region = last_battle['region_name']
        finished_at = last_battle['finished_at']
        finished_at = datetime.datetime.strptime(
            finished_at, '%Y-%m-%d %H:%M:%S')
        next_battle_at = finished_at + datetime.timedelta(days=1)
        next_battle_at_belarus = convert_erepublik_time_to_belarus_time(
            next_battle_at)
        now = datetime.datetime.utcnow()
        now = now.replace(tzinfo=pytz.UTC)
        now = now.astimezone(MINSK_ZONE)
        day = None
        if now.day == next_battle_at_belarus.day:
            day = 'сёньня'
        elif next_battle_at_belarus.day - now.day == 1:
            day = 'заўтра'
        if day is None:
            raise Exception('Not today and not tommorow. %s' % last_battle)
        next_battle_time_str = next_battle_at_belarus.strftime('%H:%M')
        time = '{} пасьля {}'.format(day, next_battle_time_str)

        await self.post(
            'sendMessage', chat_id=chat_id,
            text=RW_TEXT.format(region=region, time=time),
            reply_to_message_id=msg_id,
            parse_mode='Markdown', disable_web_page_preview=False)
