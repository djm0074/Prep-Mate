import requests
import re
import sys


def create_line_dict(display_name, sub_lines=None):
    line_dict = {
        'displayName': display_name,
        'numGames': 0,
        'numWins': 0,
        'urls': {}
    }
    if sub_lines:
        line_dict['lines'] = {sub_line: create_line_dict(sub_line_name, sub_sub_lines)
                              for sub_line, (sub_line_name, sub_sub_lines) in sub_lines.items()}
    return line_dict


def create_eco_dict(display_name, lines):
    return {
        'displayName': display_name,
        'numGames': 0,
        'numWins': 0,
        'urls': {},
        'lines': {line: create_line_dict(line_name, sub_lines) for line, (line_name, sub_lines) in lines.items()}
    }


def process_games(d, username, num_months):
    api_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    headers = {'User-Agent': 'Chess Prepper'}
    months = requests.get(api_url, headers=headers).json()
    month_count = 0

    for month in months['archives'][-num_months:]:
        games = requests.get(month, headers=headers).json()
        for game in games['games']:
            match = re.search(r"\[ECO \"(.*?)\"].*?\[ECOUrl \"(.*?)\"]", game['pgn'], re.DOTALL)
            if match:
                eco = match.group(1)
                if eco in d:
                    d[eco]['numGames'] += 1
                    ecourl = match.group(2)
                    opening_specific = ecourl[31:]
                    opening_match = re.search(r"([a-zA-Z-]+)(?=$|\.|-\d)", opening_specific)
                    opening = opening_match.group(1) if opening_match else 'unidentified'
                    update_stats(d[eco]['lines'], opening)
        month_count += 1
        sys.stdout.write(f'\r{month_count}/{num_months} months processed')
        sys.stdout.flush()
    print()


def update_stats(d_lines, url):
    for line, value in d_lines.items():
        if line in url:
            d_lines[line]['numGames'] += 1
            if 'lines' in d_lines[line]:
                update_stats(d_lines[line]['lines'], url)
            else:
                if url in d_lines[line]['urls']:
                    d_lines[line]['urls'][url]['numGames'] += 1
                else:
                    d_lines[line]['urls'][url] = {'numGames': 1}

            return
    d_lines['Other']['numGames'] += 1
    if url in d_lines['Other']['urls']:
        d_lines['Other']['urls'][url]['numGames'] += 1
    else:
        d_lines['Other']['urls'][url] = {'numGames': 1}


def print_stats(d, indent=0, printed=set()):
    if id(d) in printed:
        return
    printed.add(id(d))

    if 'displayName' in d and 'numGames' in d and 'numWins' in d:
        display_name = d['displayName']
        num_games = d['numGames']
        num_wins = d['numWins']
        win_rate = (num_wins / num_games * 100) if num_games > 0 else 0
        print(
            '    ' * indent + f"{display_name} ({num_games} Games Played, {num_wins} Wins, {win_rate:.2f}% Win Rate):")

    # Recursively print nested dictionaries, skipping the stats keys
    for key, value in d.items():
        if isinstance(value, dict) and key not in ['displayName', 'numGames', 'numWins', 'urls']:
            print_stats(value, indent + 1)


def create_aliases(d):
    # Bird's Opening
    for num in range(2, 4):
        d[f'A0{num}'] = d['A02-A03']

    # Reti Opening
    for num in range(4, 7):
        d[f'A0{num}'] = d['A04-A06, A09']
    d[f'A09'] = d['A04-A06, A09']

    # King's Indian Attack
    for num in range(7, 9):
        d[f'A0{num}'] = d['A07-A08']

    # English Opening
    for num in range(10, 40):
        d[f'A{num}'] = d['A10-A39']


# Example definitions with nested sub-lines
eco_details = {
    'A00': {
        'displayName': 'Uncommon Openings',
        'lines': {
            'Grob': ('Grob Opening', {
                'Grob-Gambit': ('Grob Gambit', None),
                'Other': ('Other Grob Variations', None)
            }),
            'Kings-F': ('King\'s Fianchetto Opening', None),
            'Polish': ('Polish Opening', {
                'Kuchark': ('Kucharkowski-Meybohm Gambit', None),
                'Other': ('Other Polish Variations', None)
            }),
            'Other': ('Other Uncommon Openings', None)
        }
    },
    'A01': {
        'displayName': 'Nimzowitsch-Larsen Attack',
        'lines': {
            'Classical': ('Classical Variation', None),
            'English': ('English Variation', None),
            'Indian': ('Indian Variation', None),
            'Modern': ('Modern Variation', None),
            'Symmetrical': ('Symmetrical Variation', None),
            'Other': ('Other Nimzo-Larsen Variations', None)
        }
    },
    'A02-A03': {
        'displayName': 'Bird\'s Opening',
        'lines': {
            'Froms': ('From\'s Gambit', None),
            'Dutch': ('Dutch Variation', None),
            'Other': ('Other Bird Variations', None)
        }
    },
    'A04-A06, A09': {
        'displayName': 'Reti Opening',
        'lines': {
            'Dutch': ('Dutch Variation', None),
            'Kingside': ('Kingside Fianchetto Variation', None),
            'Queenside': ('Queenside Fianchetto Variation', None),
            'Quiet': ('Quiet System', None),
            'Nimzo': ('Nimzo-Larsen Variations', None),
            'Kings-Indian': ('King\'s Indian Attack Variations', None),
            'Reti-Gambit': ('Reti Gambit', {
                'Accept': ('Accepted', None),
                'Decline': ('Declined', None),
                'Other': ('Other Reti Gambit Variations', None)
            }),
            'Other': ('Other Reti Variations', None)
        }
    },
    'A07-A08': {
        'displayName': 'King\'s Indian Attack',
        'lines': {
            'Double': ('Double Fianchetto Variation', None),
            'French': ('French Variation', None),
            'Sicilian': ('Sicilian Variation', None),
            'Yugoslav': ('Yugoslav Variation', None),
            'Other': ('Other Variations', None)
        }
    },
    'A10-A39': {
        'displayName': 'English Opening',
        'lines': {
            'Great-S': ('Great Snake Variation', None),
            'Caro': ('Caro-Kann Defensive System', None),
            'Anglo-Indian': ('Anglo-Indian Variation', None),
            'Anglo-Scandi': ('Anglo-Scandinavian Variation', None),
            'Agincourt': ('Agincourt Defense', None),
            'Kings-Eng': ('King\'s English Variation', None),
            'Reversed-S': ('Reversed Sicilian Variation', {
                'Taimanov': ('Taimanov Variation', None),
                'Three-K': ('Three Knights System', None),
                'Closed': ('Closed', None),
                'Other': ('Other Reversed Sicilian Variations', None)
            }),
            'Carls-B': ('Carls-Bremen System', None),
            'Four-K': ('Four Knights Variation', None),
            'Symmetrical': ('Symmetrical Variation', None),
            'Other': ('Other Variations', None)
        }
    },
}

# Initialize the opening stats dictionary
opening_stats = {eco: create_eco_dict(details['displayName'], details['lines']) for eco, details in eco_details.items()}

create_aliases(opening_stats)

process_games(opening_stats, 'Hikaru', 36)

# Assuming `opening_stats` is your dictionary containing all the opening statistics:
print_stats(opening_stats)
