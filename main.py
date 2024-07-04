import requests
import re

api_url = "https://api.chess.com/pub/player/TheWh1rlwind/games/archives"

headers = {
    'User-Agent': 'Chess Prepper'
}

months = requests.get(api_url, headers=headers).json()

opening_stats_w = {}
opening_stats_b = {}
numGames = 0

for month in months['archives'][-36:]:
    games = requests.get(month, headers=headers).json()
    for game in games['games']:
        match = re.search(r"\[ECO \"(.*?)\"].*?\[ECOUrl \"(.*?)\"]", game['pgn'], re.DOTALL)
        if match:
            eco = match.group(1)
            ecourl = match.group(2)
            opening_specific = ecourl[31:]      #includes specific move orders
            opening_match = re.search(r"([a-zA-Z-]+)(?=$|\.|-\d)", opening_specific)
            opening_general = opening_match.group(1) if opening_match else 'unidentified'       #specific move orders stripped
            #opening_general = re.search(r"(\D+)(?=$|-\d)", opening_specific)
            numGames += 1

            if game['white']['username'] == 'TheWh1rlwind':
                if eco in opening_stats_w:
                    opening_stats_w[eco]['total']['games'] += 1
                else:
                    opening_stats_w[eco] = {'total': {'games': 1, 'wins': 0}, 'urls': {}}

                if opening_general in opening_stats_w[eco]['urls']:
                    opening_stats_w[eco]['urls'][opening_general]['games'] += 1
                else:
                    opening_stats_w[eco]['urls'][opening_general] = {'games': 1, 'wins': 0}

                if game['white']['result'] == 'win':
                    opening_stats_w[eco]['total']['wins'] += 1
                    opening_stats_w[eco]['urls'][opening_general]['wins'] += 1
                else:
                    if game['black']['result'] != 'win':
                        opening_stats_w[eco]['urls'][opening_general]['wins'] += .5
            else:
                if eco in opening_stats_b:
                    opening_stats_b[eco]['total']['games'] += 1
                else:
                    opening_stats_b[eco] = {'total': {'games': 1, 'wins': 0}, 'urls': {}}

                if opening_general in opening_stats_b[eco]:
                    opening_stats_b[eco]['urls'][opening_general]['games'] += 1
                else:
                    opening_stats_b[eco]['urls'][opening_general] = {'games': 1, 'wins': 0}

                if game['black']['result'] == 'win':
                    opening_stats_b[eco]['total']['wins'] += 1
                    opening_stats_b[eco]['urls'][opening_general]['wins'] += 1
                else:
                    if game['white']['result'] != 'win':
                        opening_stats_b[eco]['urls'][opening_general]['wins'] += .5
        else:
            print("ECO tag not found - ", game['url'])

# Sort dictionary by win rate (value at index 1 / value at index 0)
# sorted_opening_stats_w = sorted(opening_stats_w.items(), key=lambda x: (x[1][0]))

sorted_ecos_w = sorted(opening_stats_w.items(), key=lambda x: x[1]['total']['games'], reverse=True)

sorted_opening_stats_w = {}
for eco_code, data in sorted_ecos_w:
    # Sort the URLs within each ECO code by win rate
    sorted_urls_w = sorted(data['urls'].items(),
                           key=lambda x: (x[1]['wins'] / x[1]['games']) if x[1]['games'] > 0 else 0,
                           reverse=True)

    # Reconstruct the structure with sorted URLs
    sorted_opening_stats_w[eco_code] = {
        'total': data['total'],
        'urls': {eco_url: stats for eco_url, stats in sorted_urls_w}
    }

sorted_ecos_b = sorted(opening_stats_b.items(), key=lambda x: x[1]['total']['games'], reverse=True)

sorted_opening_stats_b = {}
for eco_code, data in sorted_ecos_b:
    # Sort the URLs within each ECO code by win rate
    sorted_urls_b = sorted(data['urls'].items(),
                           key=lambda x: (x[1]['wins'] / x[1]['games']) if x[1]['games'] > 0 else 0,
                           reverse=True)

    # Reconstruct the structure with sorted URLs
    sorted_opening_stats_b[eco_code] = {
        'total': data['total'],
        'urls': {eco_url: stats for eco_url, stats in sorted_urls_b}
    }

print('Opening Statistics - White')
print('--------------------------')

for eco_code, data in sorted_opening_stats_w.items():
    total_games = data['total']['games']
    total_wins = data['total']['wins']
    # Calculate the total win rate, ensure not dividing by zero
    total_win_rate = (total_wins / total_games * 100)
    print(f'ECO: {eco_code}, Total Games: {total_games}, Total Wins: {total_wins}, Win Rate: {total_win_rate:.2f}%')

    for eco_url, stats in data['urls'].items():
        games = stats['games']
        wins = stats['wins']
        # Calculate the win rate for each URL, ensure not dividing by zero
        win_rate = (wins / games * 100)
        print(f'  URL: {eco_url}, Games: {games}, Wins: {wins}, Win Rate: {win_rate:.2f}%')
    print()

print('Opening Statistics - Black')
print('--------------------------')

for eco_code, data in sorted_opening_stats_b.items():
    total_games = data['total']['games']
    total_wins = data['total']['wins']
    # Calculate the total win rate, ensure not dividing by zero
    total_win_rate = (total_wins / total_games * 100)
    print(f'ECO: {eco_code}, Total Games: {total_games}, Total Wins: {total_wins}, Win Rate: {total_win_rate:.2f}%')

    for eco_url, stats in data['urls'].items():
        games = stats['games']
        wins = stats['wins']
        # Calculate the win rate for each URL, ensure not dividing by zero
        win_rate = (wins / games * 100)
        print(f'  URL: {eco_url}, Games: {games}, Wins: {wins}, Win Rate: {win_rate:.2f}%')
    print()

# # Print sorted dictionary
# print('Opening Statistics - White:')
# for code in sorted_opening_stats_w:
#     total_games = code['header'][0]
#     total_wins = code['header'][1]
#     print(f'{code}: {total_games} games, {total_wins} wins, Win rate: {total_wins / total_games:.2f}%')
#     for url, stats in code:
#         games, wins = stats
#         if games > 2:
#             print(f'{code}: {games} games, {wins} wins, Win rate: {wins / games:.2f}%')

# Sort dictionary by win rate (value at index 1 / value at index 0)
#sorted_opening_stats_b = sorted(opening_stats_b.items(), key=lambda x: (x[1][1] / x[1][0]))

# # Print sorted dictionary
# print('Opening Statistics - Black:')
# for code, stats in sorted_opening_stats_b:
#     games, wins = stats
#     if games > 2:
#         win_rate = (wins / games) * 100 if games != 0 else 0
#         print(f'{code}: {games} games, {wins} wins, Win rate: {win_rate:.2f}%')
