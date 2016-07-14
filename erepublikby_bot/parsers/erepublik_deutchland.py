import aiohttp


BELARUS_ID = 83
CZECH_ID = 34


BATTLE_TYPE = 'war'

URL = (
    'https://www.erepublik-deutschland.de/api/listapi.php?'
    'p=battles&'
    'catk={ATTACKER}&'
    'cdef={DEFENDER}&'
    'cbtp={BATTLE_TYPE}&'
    'length=1&start=0&'
    'order%5B0%5D%5Bcolumn%5D=1&'
    'columns%5B1%5D%5Bdata%5D=finished_at&'
    'columns%5B1%5D%5Bname%5D=&'
    'columns%5B1%5D%5Bsearchable%5D=true&'
    'columns%5B1%5D%5Borderable%5D=true&'
    'columns%5B1%5D%5Bsearch%5D%5Bvalue%5D=&'
    'columns%5B1%5D%5Bsearch%5D%5Bregex%5D=false&'
    'columns%5B2%5D%5Bdata%5D=region_name&'
    'columns%5B2%5D%5Bname%5D=&'
    'columns%5B2%5D%5Bsearchable%5D=true&'
    'columns%5B2%5D%5Borderable%5D=true&'
    'columns%5B2%5D%5Bsearch%5D%5Bvalue%5D=&'
    'columns%5B2%5D%5Bsearch%5D%5Bregex%5D=false'
).format(
    ATTACKER=BELARUS_ID,
    DEFENDER=CZECH_ID,
    BATTLE_TYPE=BATTLE_TYPE
)


async def get_last_battle(loop):
    with aiohttp.ClientSession(loop=loop) as session:
        async with session.get(URL) as resp:
            data = await resp.json()
            return data['data'][0]
