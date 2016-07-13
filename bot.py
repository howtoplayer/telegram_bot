import asyncio
import aiohttp


API_BASE_URL = 'https://api.telegram.org/bot{token}/{method}'
MAXIMUM_CONCURENT_REQUESTS = 50
REQUESTS_TIMEOUT = 10
LONG_POLLING_TIME = 60
HELLO_TEXT = """
Вас вітае бот [ERepublikByBot](https://telegram.me/erepublikby_bot)!
"""


class Bot:
    def __init__(self, loop, logger, token):
        self.logger = logger
        self.loop = loop
        self.token = token

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
            await self.get_bot_info()
        except Exception:
            self.logger.critical('Cant connect to telegram', exc_info=True)
            return

        self.pull_task = self.loop.create_task(self.pull_events())

        while self.running:
            if self.pending_tasks:
                done, pending = await asyncio.wait(
                    self.pending_tasks, return_when=asyncio.FIRST_COMPLETED)
                self.pending_tasks = pending
            else:
                await asyncio.sleep(0)

    async def pull_events(self):
        while self.running:
            self.logger.debug('Pull updates')
            events = await self.get(
                'getUpdates', offset=self.last_seen_update_id,
                timeout=LONG_POLLING_TIME, _short=False)

            self.logger.debug('Events getted %s', events)

            if events['ok'] and events['result']:
                for event in events['result']:
                    self.logger.debug('Process event %s', event)
                    task = None
                    if 'message' in event:
                        task = self.loop.create_task(
                            self.handle_message(event))
                    else:
                        self.logger.warning('Got unexpected event %s', event)

                    if task is not None:
                        self.pending_tasks.add(task)

                    self.last_seen_update_id = max(
                        self.last_seen_update_id, event['update_id'] + 1)

    async def handle_message(self, event):
        self.logger.debug('Got message %s', event)
        message = event['message']
        chat_id = message['chat']['id']
        text = message['text']

        if text == '/start':
            return await self.send_hello_text(chat_id)

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
                    return (await resp.json())

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
                    return (await resp.json())

    async def send_hello_text(self, chat_id):
        await self.post(
            'sendMessage', chat_id=chat_id, text=HELLO_TEXT,
            parse_mode='Markdown', disable_web_page_preview=True)
