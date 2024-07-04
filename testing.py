import sys

import requests
import re
import pprint

api_url = "https://api.chess.com/pub/player/Hikaru/games/archives"

headers = {
    'User-Agent': 'Chess Prepper'
}

openings = {}

months = requests.get(api_url, headers=headers).json()

month_count = 0
for month in months['archives'][-12:]:
    games = requests.get(month, headers=headers).json()
    for game in games['games']:
        match = re.search(r"\[ECO \"(.*?)\"].*?\[ECOUrl \"(.*?)\"]", game['pgn'], re.DOTALL) if 'pgn' in game else None
        if match:
            eco = match.group(1)
            ecourl = match.group(2)
            opening_specific = ecourl[31:]
            opening_match = re.search(r"([a-zA-Z-]+)(?=$|\.|-\d)", opening_specific)
            opening = opening_match.group(1) if opening_match else 'unidentified'
            if eco in openings:
                if opening in openings[eco]:
                    openings[eco][opening] += 1
                else:
                    openings[eco][opening] = 1
            else:
                openings[eco] = {opening: 1}
    month_count += 1
    sys.stdout.write(f'\r{month_count}/96 months processed')
    sys.stdout.flush()

for eco_code, data in sorted(openings.items()):
    print(f'{eco_code}:')

    for opening_n, num_games in sorted(data.items()):
        print(f'   {opening_n} ({num_games})')
    print()