from argparse import ArgumentParser
import logging
import asyncio

from bot import Bot


LOGGING_LEVELS = (
    'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
)


parser = ArgumentParser()
parser.add_argument('--log-level', choices=LOGGING_LEVELS, default='INFO')
parser.add_argument('--admin', action='append', dest='admins')
parser.add_argument('token')


def setup_logging(opts):
    logging.basicConfig(
        level=opts.log_level,
        format='[%(asctime)s][%(levelname)s] %(message)s')


def main():
    opts = parser.parse_args()
    setup_logging(opts)
    logger = logging.getLogger(__name__)
    logger.info('Starting bot...')
    loop = asyncio.get_event_loop()
    bot = Bot(loop=loop, token=opts.token, logger=logger,
              admins=tuple(opts.admins))
    try:
        loop.run_until_complete(bot.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(bot.kill())
        loop.close()


if __name__ == '__main__':
    main()
