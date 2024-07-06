import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from flask import Flask, request, render_template
from requests_futures.sessions import FuturesSession
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from google.cloud import storage
import json
import os
import uuid
import requests
import copy
from datetime import datetime, timedelta, timezone
import threading
import time
import tempfile

app = Flask(__name__)

# Load environment variables from .env file
load_dotenv()

# Ensure a secure secret key is set for production
secret_key = os.environ.get('FLASK_SECRET_KEY')
if not secret_key and app.config['ENV'] == 'production':
    raise ValueError("No FLASK_SECRET_KEY set for Flask application")
app.secret_key = secret_key or 'default_secret_key'  # Use default for development

# Initialize Firebase Admin SDK
google_credentials_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
if not google_credentials_json:
    raise ValueError("No GOOGLE_CREDENTIALS_JSON set for Flask application")

# Write the credentials JSON to a temporary file
with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.json') as temp_file:
    temp_file.write(google_credentials_json)
    temp_cred_file_path = temp_file.name


# Set the environment variable to the path of the temporary file
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = temp_cred_file_path

# Initialize Firebase Admin SDK with the temporary credentials file
credentials = credentials.Certificate(temp_cred_file_path)
initialize_app(credentials)
db = firestore.client()


def generate_session_id(data):
    session_id = str(uuid.uuid4())

    # Split large data
    stats = data['stats']
    del data['stats']

    # Upload large data to GCS
    bucket_name = 'prep-mate-stats-bucket'
    filename = f'{session_id}_stats.json'
    data_url = upload_to_gcs(bucket_name, json.dumps(stats), filename)

    # Save reference to Firestore
    data['stats_url'] = data_url
    data['last_activity'] = datetime.now(timezone.utc).isoformat()

    db.collection('sessions').document(session_id).set(data)
    return session_id


def get_session_data(session_id):
    doc = db.collection('sessions').document(session_id).get()
    data = doc.to_dict() if doc.exists else None

    if data and 'stats_url' in data:
        response = requests.get(data['stats_url'])
        data['stats'] = response.json()

        # Update last activity timestamp
        db.collection('sessions').document(session_id).update({
            'last_activity': datetime.now(timezone.utc).isoformat()
        })

    return data


def upload_to_gcs(bucket_name, data, filename):
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(filename)
    blob.upload_from_string(data)
    return blob.public_url


# Cleanup Inactive Sessions Periodically
def cleanup_inactive_sessions(max_inactive_duration):
    while True:
        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(seconds=max_inactive_duration)

        sessions_ref = db.collection('sessions')
        inactive_sessions = sessions_ref.where('last_activity', '<', cutoff_time.isoformat()).stream()

        for session in inactive_sessions:
            session_id = session.id
            session_data = session.to_dict()

            # Delete the session document
            sessions_ref.document(session_id).delete()

            # Delete the corresponding stats file from GCS
            if 'stats_url' in session_data:
                filename = session_data['stats_url'].split('/')[-1]
                delete_from_gcs('prep-mate-stats-bucket', filename)

        time.sleep(max_inactive_duration)  # Wait for the specified duration before checking again


def delete_from_gcs(bucket_name, filename):
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(filename)
    blob.delete()


# Start the cleanup thread
max_inactive_duration = 3600  # 1 hour (you can change this value)
cleanup_thread = threading.Thread(target=cleanup_inactive_sessions, args=(max_inactive_duration,))
cleanup_thread.daemon = True
cleanup_thread.start()

# Register the function as a template global
app.jinja_env.globals.update(generate_session_id=generate_session_id)

# Initialize FuturesSession
futures_session = FuturesSession(executor=ThreadPoolExecutor(max_workers=10))

# Grouping openings by ECO and name
eco_details = {
    'A00': {
        'displayName': 'Uncommon Openings',
        'lines': {
            'Grob': ('Grob Opening', {
                'Grob-Gambit': ('Grob Gambit', None),
                'Other': ('Other', None)
            }),
            'Kings-F': ('King\'s Fianchetto Opening', {
                'Symmetrical': ('Symmetrical Variation', None),
                'Other': ('Other', None)
            }),
            'Polish': ('Polish Opening', {
                'Kuchark': ('Kucharkowski-Meybohm Gambit', None),
                'Other': ('Other', None)
            }),
            'Other': ('Other', None)
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
            'Other': ('Other', None)
        }
    },
    'A02-A03': {
        'displayName': 'Bird\'s Opening',
        'lines': {
            'Froms': ('From\'s Gambit', None),
            'Dutch': ('Dutch Variation', None),
            'Other': ('Other', None)
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
                'Other': ('Other', None)
            }),
            'Tennison': ('Tennison Gambit', None),
            'Sicilian': ('Sicilian Invitation', None),
            'Other': ('Other', None)
        }
    },
    'A07-A08': {
        'displayName': 'King\'s Indian Attack',
        'lines': {
            'Double': ('Double Fianchetto Variation', None),
            'French': ('French Variation', None),
            'Sicilian': ('Sicilian Variation', None),
            'Yugoslav': ('Yugoslav Variation', None),
            'Other': ('Other', None)
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
            'Reversed-S': ('Reversed Sicilian Variation', None),
            'Carls-B': ('Carls-Bremen System', None),
            'Mikenas': ('Mikenas-Carls Variation', None),
            'Symmetrical': ('Symmetrical Variation', None),
            'ning-Four-K': ('Four Knights Variation', None),
            'ning-Two-K': ('Two Knights Variation', None),
            'Other': ('Other', None)
        }
    },
    'd4': {
        'displayName': 'Uncommon d4 Openings',
        'lines': {
            'Englund': ('Englund Gambit', {
                'Decline': ('Declined', None),
                'Other': ('Other', None)
            }),
            'Modern-D': ('Modern Defense (1. d4)', {
                'Ptero': ('Pterodactyl Defense', None),
                'Averbak': ('Averbakh-Kotov Variation', None),
                'Other': ('Other', None)
            }),
            'English': ('English Defense', None),
            'Tartakower': ('Tartakower Variation', None),
            'Benoni': ('Benoni Defense', {
                'Old-B': ('Old Benoni Defense', None),
                'Modern': ('Modern Variation', None),
                'Other': ('Other', None)
            }),
            'Budapest': ('Budapest Gambit', None),
            'Benko': ('Benko Gambit', {
                'Decline': ('Declined', None),
                'Half': ('Half-Accepted', None),
                'Full': ('Fully-Accepted', None),
                'Other': ('Other', None)
            }),
            'Tromp': ('Trompowsky Attack', {
                'Classical': ('Classical Variation', None),
                'Poison': ('Poisoned-Pawn Variation', None),
                'Other': ('Other', None)
            }),
            'ti-Nimzo': ('Anti-Nimzo-Indian Variation', None),
            'Blumen': ('Blumenfeld Countergambit', None),
            'Torre': ('Torre Attack', None),
            'London': ('London System', {
                'Accel': ('Accelerated London System', {
                    'Steinitz': ('Steinitz Countergambit', None),
                    'Other': ('Other', None)
                }),
                'Indian': ('Indian Game Variation', None),
                'Other': ('Other', None)
            }),
            'Indian': ('Indian Game', {
                'East-I': ('East Indian Variation', None),
                'Old-I': ('Old Indian Defense', None),
                'Bogo-I': ('Bogo-Indian Defense', {
                    'Exchange': ('Exchange Variation', None),
                    'Grunfeld': ('Grunfeld Variation', None),
                    'Nimzo': ('Nimzowitsch Variation', None),
                    'Vitolins': ('Vitolins Variation', None),
                    'Wade-S': ('Wade-Smyslov Variation', None),
                    'Other': ('Other', None)
                }),
                'Polish': ('Polish Variation', None),
                'Spielmann': ('Spielmann Indian Variation', None),
                'Yusupov': ('Yusupov-Rubinstein System', None),
                'Accel': ('Accelerated Variation', None),
                'Knights': ('Knights Variation', None),
                'Other': ('Other', None)
            }),
            'Rossolimo': ('Rossolimo Variation', None),
            'Horwitz': ('Horwitz Defense', None),
            'Zuker': ('Zukertort Variation', None),
            'Chigorin': ('Chigorin Variation', None),
            'Levitsky': ('Levitsky Attack', None),
            'Stonewall': ('Stonewall Attack', None),
            'Blackmar': ('Blackmar Gambit', None),
            'Colle': ('Colle System', None),
            'Symmetrical': ('Symmetrical Variation', None),
            'Krause': ('Krause Variation', None),
            'Pseudo': ('Pseudo Catalan Variation', None),
            'Other': ('Other', None)
        }
    },
    'A80-A99': {
        'displayName': 'Dutch Defense',
        'lines': {
            'Fianchetto': ('Fianchetto Variation', {
                'Lenin': ('Leningrad Variation', None),
                'Other': ('Other', None)
            }),
            'Staunton': ('Staunton Gambit', {
                'Accept': ('Accepted', None),
                'Other': ('Other', None)
            }),
            'Lenin': ('Leningrad Variation', None),
            'Classic': ('Classical Variation', None),
            'Normal': ('Normal Variation', None),
            'Queen': ('Queen\'s Knight Variation', None),
            'Other': ('Other', None)
        }
    },
    'e4': {
        'displayName': 'Uncommon e4 Openings',
        'lines': {
            'Nimzo': ('Nimzowitsch Defense', {
                'Decline': ('Declined', None),
                'Kennedy': ('Kennedy Variation', None),
                'Scandi': ('Scandinavian Variation', None),
                'Other': ('Other', None)
            }),
            'Ponzi': ('Ponziani Opening', {
                'Jaenisch': ('Jaenisch Counterattack', None),
                'Steinitz': ('Steinitz Variation', None),
                'Counter': ('Ponziani Countergambit', None),
                'Spanish': ('Spanish Variation', None),
                'Kings-P': ('Weird Anti-Ponziani Lines', None),
                'Other': ('Other', None)
            }),
            'Owen': ('Owen\'s Defense', None),
            'Wayward': ('Wayward Queen Attack', None),
            'Center': ('Center Game', None),
            'Danish': ('Danish Gambit', None),
            'Kings-K': ('King\'s Knight Variation', None),
            'Other': ('Other', None)
        }
    },
    'B01': {
        'displayName': 'Scandinavian Defense',
        'lines': {
            'Mieses': ('Mieses-Kotrc Variation', {
                'Main-L': ('Main Line', None),
                'Gubinsky': ('Gubinsky-Melts Variation', None),
                'Other': ('Other', None)
            }),
            'Closed': ('Closed Variation', None),
            'Modern': ('Modern Variation', None),
            'Other': ('Other', None)
        }
    },
    'B02-B05': {
        'displayName': 'Alekhine\'s Defense',
        'lines': {
            'Two-P': ('Two Pawns Attack', {
                'Lasker': ('Lasker Variation', None),
                'Other': ('Other', None)
            }),
            'Scandi': ('Scandinavian Variation', None),
            'Four-P': ('Four Pawns Attack', None),
            'Modern': ('Modern Variation', None),
            'Normal': ('Normal Variation', None),
            'Other': ('Other', None)
        }
    },
    'B06': {
        'displayName': 'Modern Defense',
        'lines': {
            'Standard': ('Standard Line', {
                'Ptero': ('Pterodactyl Variation', None),
                'Two-K': ('Two Knights Variation', None),
                'Other': ('Other', None)
            }),
            'Ptero': ('Pterodactyl Variations', None),
            'Mongred': ('Mongredien Defense', None),
            'Three-P': ('Three Pawns Attack', None),
            'Gurgen': ('Gurgenidze Variation', None),
            'Bishop-A': ('Bishop Attack', None),
            'Other': ('Other', None)
        }
    },
    'B07-B09': {
        'displayName': 'Pirc Defense',
        'lines': {
            'Main': ('Main Line', {
                'Austrian': ('Austrian Attack', None),
                'Other': ('Other', None)
            }),
            'Geller': ('Geller System', None),
            'Classic': ('Classical Variations', None),
            'Czech': ('Czech Defense', None),
            'Other': ('Other', None)
        }
    },
    'B10-B19': {
        'displayName': 'Caro-Kann Defense',
        'lines': {
            'Accelerated-P': ('Accelerated Panov Attack', None),
            'Two-K': ('Two Knights Attack', {
                'Mindeno': ('Mindeno Variation', None),
                'Other': ('Other', None)
            }),
            'Advance': ('Advance Variation', {
                'Tal-': ('Tal Variation', None),
                'Botvin': ('Botvinnik-Carls Defense', None),
                'Short': ('Short Variation', None),
                'Van-': ('Van der Wiel Attack', None),
                'Bronst': ('Bronstein Variation', None),
                'Other': ('Other', None)
            }),
            'Exchange': ('Exchange Variation', None),
            'se-Panov': ('Panov Attack', None),
            'Gurgen': ('Gurgenidze System', None),
            'Main-L': ('Main Line', None),
            'Tartakower': ('Tartakower Variation', None),
            'stein-L': ('Bronstein-Larsen Variation', None),
            'Karpov': ('Karpov Variation', None),
            'Classic': ('Classical Variation', None),
            'Breyer': ('Breyer Variation', None),
            'Other': ('Other', None)
        }
    },
    'B20-B99': {
        'displayName': 'Sicilian Defense',
        'lines': {
            'Smith-Mor': ('Smith-Morra Gambit', {
                'Accept': ('Accepted', None),
                'Decline': ('Declined', {
                    'Center': ('Center Formation', None),
                    'Push': ('Push Variation', None),
                    'Other': ('Other', None)
                }),
                'Morphy': ('Morphy Gambit', None),
                'Other': ('Other', None)
            }),
            'Alapin': ('Alapin Variation', {
                'Delay': ('Delayed Alapin Variation', None),
                'Barmen': ('Barmen Defense', None),
                'Stoltz': ('Stoltz Attack', None),
                'Other': ('Other', None)
            }),
            'Closed-S': ('Closed Sicilian', {
                'Grand-P': ('Grand Prix Attack', None),
                'Magnus': ('Magnus Sicilian', None),
                'Traditional': ('Traditional Variation', None),
                'Fianchetto': ('Fianchetto Variation', None),
                'Other': ('Other', None)
            }),
            'Hyperaccel': ('Hyperaccelerated Dragon', None),
            'OKelly': ('O\'Kelly Variation', {
                'Maroczy': ('Maroczy Bind Variation', None),
                'Normal': ('Normal System', None),
                'Venice': ('Venice System', None),
                'Yerevan': ('Yerevan System', None),
                'Other': ('Other', None)
            }),
            'Open': ('Open Sicilian', {
                'Lowenth': ('Lowenthal Variation', None),
                'Pelikan': ('Pelikan and Sveshnikov Variations', None),
                'Accel': ('Accelerated Dragon', {
                    'Maroczy': ('Maroczy Bind Formation', None),
                    'Modern': ('Modern Variation', None),
                    'Other': ('Other', None)
                }),
                'en-Classic': ('Classical Variation', None),
                'n-Dragon': ('Dragon Variation', None),
                'Scheven': ('Scheveningen Variation', {
                    'Sozin': ('Sozin Attack', None),
                    'Other': ('Other', None)
                }),
                'Najdorf': ('Najdorf Variation', {
                    'Adam': ('Adam\'s Attack', None),
                    'English': ('English Attack', None),
                    'Freak': ('Freak Attack', None),
                    'Lipnit': ('Lipnitsky Attack', None),
                    'Opocensky': ('Opocensky Variation', None),
                    'Zagreb': ('Zagreb Variation', None),
                    'Other': ('Other', None)
                }),
                'Other': ('Other', None)
            }),
            'e-Kan': ('Kan Variation', {
                'Maroczy': ('Maroczy Bind Formation', None),
                'Modern': ('Modern Variation', None),
                'Knight': ('Knight Variation', None),
                'Other': ('Other', None)
            }),
            'Chekhover': ('Chekhover Variation', None),
            'Canal': ('Canal Attack', None),
            'Taimanov': ('Taimanov Variation', None),
            'Four-K': ('Four Knights Variation', None),
            'Nimzowitsch': ('Nimzowitsch Variation', None),
            'Nyezhmet': ('Nyezhmetdinov-Rossolimo Attack', None),
            'Snyder': ('Snyder Variation', None),
            'Staunton-Coch': ('Staunton-Cochrane Variation', None),
            'Bowdler': ('Bowdler Attack', None),
            'Lasker-D': ('Lasker-Dunne Atack', None),
            'Wing-G': ('Wing Gambit', None),
            'McDonn': ('McDonnell Attack', None),
            'Mengarini': ('Mengarini Variation', None),
            'Pin-V': ('Pin Variation', None),
            'Tartakower': ('Tartakower Variation', None),
            'Other': ('Other', None)
        }
    },
    'C00-C19': {
        'displayName': 'French Defense',
        'lines': {
            'Tarrasch': ('Tarrasch Variation', {
                'Open': ('Open Variation', None),
                'Close': ('Closed Variation', None),
                'Guimard': ('Guimard Defense', None),
                'Other': ('Other', None)
            }),
            'Classic': ('Classical Variation', {
                'Steinitz': ('Steinitz Variation', None),
                'MacCutch': ('MacCutcheon Variation', None),
                'Burn': ('Burn Variation', None),
                'Other': ('Other', None)
            }),
            'Winawer': ('Winawer Variation', {
                'Advance': ('Advance Variation', None),
                'Delay': ('Delayed Exchange Variation', None),
                'Alekhine': ('Alekhine-Maroczy Gambit', None),
                'Other': ('Other', None)
            }),
            'Advance': ('Advance Variation', {
                'Paulsen': ('Paulsen Attack', None),
                'Nimzo': ('Nimzowitsch System', None),
                'Wade': ('Wade Variation', None),
                'Other': ('Other', None)
            }),
            'e-Exchange': ('Exchange Variation', None),
            'Rubinstein': ('Rubinstein Variation', None),
            'Kings-I': ('King\'s Indian Attack', None),
            'Two-K': ('Two Knights Variation', None),
            'e-Normal': ('Normal Variation', None),
            'Queens-K': ('Queen\'s Knight Variation', None),
            'Other': ('Other', None)
        }
    },
    'C23-C29': {
        'displayName': 'Vienna Game',
        'lines': {
            'Max-L': ('Max Lange Defense', {
                'Steinitz': ('Steinitz Gambit', None),
                'Meitner': ('Meitner-Mieses Gambit', None),
                'Paulsen': ('Paulsen Variation', None),
                'nna-Gambit': ('Vienna Gambit', {
                    'Knight': ('Knight Variation', None),
                    'Other': ('Other', None)
                }),
                'Other': ('Other', None)
            }),
            'Falkbeer': ('Falkbeer Variation', {
                'Mieses': ('Mieses Variation', None),
                'Stanley': ('Stanley Variation', None),
                'nna-Gambit': ('Vienna Gambit', None),
                'Other': ('Other', None)
            }),
            'Main-L': ('Main Line', {
                'Paulsen': ('Paulsen Attack', None),
                'Other': ('Other', None)
            }),
            'Anderssen': ('Anderssen Defense', None),
            'Zhura': ('Zhuravlev Countergambit', None),
            'Bishops': ('Bishop\'s Opening', {
                'Berlin': ('Berlin Variation', {
                    'Spiel': ('Spielmann Attack', None),
                    'Vienna': ('Vienna Hybrid Variation', None),
                    'Other': ('Other', None)
                }),
                'Other': ('Other', None)
            }),
            'Other': ('Other', None)
        }
    },
    'C30-C39': {
        'displayName': 'King\'s Gambit',
        'lines': {
            'Traditional': ('Traditional Variation', None),
            'Bishops': ('Bishop\'s Gambit', None),
            'Kieser': ('Kieseritzky Gambit', None),
            'Decline': ('Declined', {
                'Classic': ('Classical Variation', None),
                'Queens-K': ('Queen\'s Knight Defense', None),
                'Falkbeer': ('Falkbeer Countergambit', None),
                'Other': ('Other', None)
            }),
            'Other': ('Other', None)
        }
    },
    'C40-C41': {
        'displayName': 'Philidor Defense',
        'lines': {
            'Exchange': ('Exchange Variation', None),
            'Hanham': ('Hanham Variation', None),
            'Nimzo': ('Nimzowitsch Variation', None),
            'Other': ('Other', None)
        }
    },
    'C42-C43': {
        'displayName': 'Petrov\'s Defense',
        'lines': {
            'Stafford': ('Stafford Gambit', None),
            'Classic': ('Classical Attack', {
                'Marshall': ('Marshall Variation', None),
                'Cozio': ('Cozio Attack', None),
                'Damiano': ('Damiano Variation', None),
                'Karklin': ('Karklins-Martinovsky Variation', None),
                'Millenni': ('Millennium Attack', None),
                'Nimzo': ('Nimzowitsch Attack', None),
                'Paulsen': ('Paulsen Attack', None),
                'Other': ('Other', None)
            }),
            'Three-K': ('Three Knights Game', None),
            'Steinitz': ('Steinitz Attack', None),
            'Urusov': ('Urusov Gambit', None),
            'Other': ('Other', None)
        }
    },
    'C45': {
        'displayName': 'Scotch Game',
        'lines': {
            'Classic': ('Classical Variation', {
                'Inter': ('Intermezzo Variation', None),
                'Potter': ('Potter Variation', None),
                'Other': ('Other', None)
            }),
            'Schmidt': ('Schmidt Variation', {
                'Mieses': ('Mieses Variation', None),
                'Tarta': ('Tartakower Variation', None),
                'Other': ('Other', None)
            }),
            'tch-Gambit': ('Scotch Gambit', None),
            'Other': ('Other', None)
        }
    },
    'C46': {
        'displayName': 'Three Knights Opening',
        'lines': {
            'Steinitz': ('Steinitz Defense', None),
            'Winawer': ('Winawer Defense', None),
            'Other': ('Other', None)
        }
    },
    'C47-C49': {
        'displayName': 'Four Knights Game',
        'lines': {
            'Gunsberg': ('Gunsberg Variation', None),
            'Italian': ('Italian Variation', None),
            'Scotch': ('Scotch Variation', None),
            'Spanish': ('Spanish Variation', {
                'Classic': ('Classical Variation', None),
                'Rubin': ('Rubinstein Countergambit', None),
                'Double': ('Double Spanish Variation', None),
                'Other': ('Other', None)
            }),
            'Other': ('Other', None)
        }
    },
    'C50-C59': {
        'displayName': 'Italian Game',
        'lines': {
            'Giuoco': ('Giuoco Piano Game', {
                'Pianissimo': ('Pianissimo Variation', {
                    'Four-K': ('Four Knights Variation', None),
                    'Other': ('Other', None)
                }),
                'Evans': ('Evans Gambit', {
                    'Bronstein': ('Bronstein Defense', None),
                    'Pierce': ('Pierce Defense', None),
                    'Anderssen': ('Anderssen Variation', None),
                    'Stone': ('Stone-Ware Variation', None),
                    'Slow': ('Slow Variation', None),
                    'Decline': ('Declined', None),
                    'Other': ('Other', None)
                }),
                'Center': ('Center Attack', None),
                'Main': ('Main Line', {
                    'Albin': ('Albin Gambit', None),
                    'Birds': ('Bird\'s Attack', None),
                    'Other': ('Other', None)
                }),
                'Other': ('Other', None)
            }),
            'Two-K': ('Two Knights Defense', None),
            'Knight-A': ('Fried Liver Attack', {
                'Polerio': ('Polerio Defense', None),
                'Fritz': ('Fritz Variation', None),
                'Other': ('Other', None)
            }),
            'Scotch': ('Scotch Transpositions', None),
            'Traxler': ('Traxler Counterattack', None),
            'Other': ('Other', None)
        }
    },
    'C60-C99': {
        'displayName': 'Ruy Lopez Opening',
        'lines': {
            'Berlin': ('Berlin Defense', {
                'Improved-S': ('Improved Steinitz Defense', {
                    'Hedge': ('Hedgehog Variation', None),
                    'Other': ('Other', None)
                }),
                'Rio-': ('Rio Gambit', None),
                'lHerm': ('l\'Hermet Variation', {
                    'Wall': ('Berlin Wall Defense', None),
                    'Showalter': ('Showalter Variation', None),
                    'Other': ('Other', None)
                }),
                'Bever': ('Beverwijk Variation', None),
                'Kaufmann': ('Kaufmann Variation', None),
                'Mortimer': ('Mortimer Variation', None),
                'Nyholm': ('Nyholm Attack', None),
                'Other': ('Other', None)
            }),
            'Morphy': ('Morphy Defense', {
                'Open-': ('Open Variation', None),
                'Close': ('Closed Variation', None),
                'Modern-S': ('Modern Steinitz Defense', None),
                'Anderssen': ('Anderssen Variation', None),
                'Anti-M': ('Anti-Marshall Variation', None),
                'Exchange': ('Exchange Variation', None),
                'Caro': ('Caro Variation', None),
                'Cozio': ('Cozio Defense', None),
                'Deferred-Cl': ('Deferred Classical Defense', None),
                'Deferred-Sc': ('Deferred Schliemann Defense', None),
                'Deferred-Fi': ('Deferred Fianchetto Defense', None),
                'Other': ('Other', None)
            }),
            'Old-Stein': ('Old Steinitz Defense', None),
            'Classic': ('Classical Defense', None),
            'Marshall': ('Marshall Attack', None),
            'Jaenisch': ('Schliemann Defense', None),
            'Cozio': ('Cozio Defense', None),
            'Fianchetto': ('Fianchetto Defense', None),
            'Other': ('Other', None)
        }
    },
    'D06-D69': {
        'displayName': 'Queen\'s Gambit',
        'lines': {
            'Accept': ('Accepted', {
                'Central': ('Central Variation', {
                    'Alekhine': ('Alekhine System', None),
                    'Greco': ('Greco Variation', None),
                    'Mcdonnell': ('Mcdonnell Defense', None),
                    'Modern': ('Modern Defense', None),
                    'Other': ('Other', None)
                }),
                'Old': ('Old Variation', None),
                'Alekhine': ('Alekhine Variation', None),
                'Showalter': ('Showalter Variation', None),
                'Classic': ('Classical Defense', None),
                'Other': ('Other', None)
            }),
            'Slav': ('Slav Defense', {
                'Modern': ('Modern Variation', {
                    'Quiet': ('Quiet Variation', None),
                    'Two-K': ('Two Knights Attack', None),
                    'Three-K': ('Three Knights Variation', None),
                    'Alapin': ('Alapin Variation', None),
                    'Triangle': ('Triangle System', None),
                    'Chameleon': ('Chameleon Variation', None),
                    'Suchting': ('Suchting Variation', None),
                    'Other': ('Other', None)
                }),
                'Semi-S': ('Semi-Slav Defense', None),
                'Exchange': ('Exchange Variation', None),
                'v-Gambit': ('Slav Gambit', None),
                'Other': ('Other', None)
            }),
            'Catalan': ('Catalan Opening', None),
            'Tarrasch': ('Tarrasch Defense', {
                'Semi-T': ('Semi-Tarrasch Defense', {
                    'Main': ('Main Line', None),
                    'Other': ('Other', None)
                }),
                'Two-K': ('Two Knights Variation', {
                    'Rubin': ('Rubinstein System', None),
                    'Other': ('Other', None)
                }),
                'Other': ('Other', None)
            }),
            'Decline': ('Declined', {
                'Queens-K': ('Queen\'s Knight Variation', None),
                'Three-K': ('Three Knights Variation', None),
                'Modern': ('Modern Variation', None),
                'Tradition': ('Traditional Variation', None),
                'Ragozin': ('Ragozin Defense', None),
                'Exchange': ('Exchange Variation', {
                    'Position': ('Positional Line', None),
                    'Other': ('Other', None)
                }),
                'Charou': ('Charousek Variation', None),
                'Janowski': ('Janowski Variation', None),
                'Albin': ('Albin Countergambit', None),
                'Austrian': ('Austrian Variation', None),
                'Marshall': ('Marshall Defense', None),
                'Baltic': ('Baltic Defense', None),
                'Chigorin': ('Chigorin Defense', None),
                'Other': ('Other', None)
            }),
            'Other': ('Other', None)
        }
    },
    'D70-D99': {
        'displayName': 'Grunfeld Defense',
        'lines': {
            'Exchange': ('Exchange Variation', {
                'Modern': ('Modern Variation', None),
                'Classic': ('Classical Variation', None),
                'Other': ('Other', None)
            }),
            'Three-K': ('Three Knights Variation', None),
            'Hungarian': ('Hungarian Attack', None),
            'Russian': ('Russian Variation', {
                'Prins': ('Prins Variation', None),
                'Other': ('Other', None)
            }),
            'Neo-G': ('Neo-Grunfeld Defense', None),
            'Anti-G': ('Anti-Grunfeld Defense', None),
            'Stockholm': ('Stockholm Variation', None),
            'Brinck': ('Brinckmann Attack', {
                'Capablanca': ('Capablanca Variation', None),
                'Other': ('Other', None)
            }),
            'Other': ('Other', None)
        }
    },
    'E00-E09': {
        'displayName': 'Catalan Opening',
        'lines': {
            'g-Open': ('Open Variation', {
                'Classic': ('Classical Variation', None),
                'Modern': ('Modern Variation', None),
                'Other': ('Other', None)
            }),
            'g-Close': ('Closed Variation', None),
            'East-I': ('East Indian Defense', None),
            'Other': ('Other', None)
        }
    },
    'E12-E19': {
        'displayName': 'Queen\'s Indian Defense',
        'lines': {
            'Kasparov': ('Kasparov Variation', None),
            'Spassky': ('Spassky System', None),
            'Fianchetto': ('Fianchetto Variation', {
                'Nimzo': ('Nimzowitsch Variation', None),
                'Capab': ('Capablanca Variation', None),
                'Classic': ('Classical Variation', None),
                'Tradition': ('Traditional Line', None),
                'Main-L': ('Main Line', None),
                'Other': ('Other', None)
            }),
            'Other': ('Other', None)
        }
    },
    'E20-E59': {
        'displayName': 'Nimzo-Indian Defense',
        'lines': {
            'Three-K': ('Three Knights Variation', None),
            'Spiel': ('Spielmann Variation', None),
            'Samisch': ('Samisch Variation', None),
            'Lenin': ('Leningrad Variation', None),
            'St-P': ('St. Petersburg Variation', {
                'Fischer': ('Fischer Variation', None),
                'Other': ('Other', None)
            }),
            'Reshev': ('Reshevsky Variation', None),
            'Bishop': ('Bishop Attack', {
                'Classic': ('Classical Defense', None),
                'Other': ('Other', None)
            }),
            'Hubner': ('Hubner Variation', {
                'red-Hub': ('Deferred Hubner Variation', None),
                'Other': ('Other', None)
            }),
            'Kmoch': ('Kmoch Variation', None),
            'Roman': ('Romanishin-Kasparov System', None),
            'Gligor': ('Gligoric System', None),
            'Normal': ('Normal Line', None),
            'Classic': ('Classical Variation', {
                'Keres': ('Keres Defense', None),
                'Zurich': ('Zurich Variaton', None),
                'Noa-': ('Noa Variation', None),
                'Berlin': ('Berlin Variation', None),
                'Other': ('Other', None)
            }),
            'Other': ('Other', None)
        }
    },
    'E60-E99': {
        'displayName': 'King\'s Indian Defense',
        'lines': {
            'Fianchetto': ('Fianchetto Variation', None),
            'Four-P': ('Four Pawns Attack', None),
            'Samisch': ('Samisch Variation', {
                'h-Gambit': ('Samisch Gambit', None),
                'Steiner': ('Steiner Attack', None),
                'Normal': ('Normal Defense', None),
                'Other': ('Other', None)
            }),
            'Smyslov': ('Smyslov Variation', None),
            'Kramer': ('Kramer Variation', None),
            'Makogo': ('Makogonov Variation', None),
            'Averbakh': ('Averbakh Variation', {
                'Semi-A': ('Semi-Averbakh Variation', None),
                'Benoni': ('Benoni Variation', None),
                'Other': ('Other', None)
            }),
            'Orthodox': ('Orthodox Variation', {
                'Exchange': ('Exchange Variation', None),
                'Other': ('Other', None)
            }),
            'Petros': ('Petrosian Variation', None),
            'Bayonet': ('Bayonet Attack', None),
            'Normal': ('Normal Variation', None),
            'Other': ('Other', None)
        }
    }
}


def create_aliases(d):
    # Bird's Opening
    for num in range(2, 4):
        d[f'A0{num}'] = d['A02-A03']

    # Reti Opening
    for num in range(4, 7):
        d[f'A0{num}'] = d['A04-A06, A09']
    d['A09'] = d['A04-A06, A09']

    # King's Indian Attack
    for num in range(7, 9):
        d[f'A0{num}'] = d['A07-A08']

    # English Opening
    for num in range(10, 40):
        d[f'A{num}'] = d['A10-A39']

    # Uncommon Queen's Pawn
    # Unusual d4 Openings
    for num in range(40, 80):
        d[f'A{num}'] = d['d4']
    # Uncommon d4-d5 Openings
    for num in range(0, 6):
        d[f'D0{num}'] = d['d4']
    # Unusual d4-Nf6 Openings
    for num in range(10, 12):
        d[f'E{num}'] = d['d4']

    # Dutch Defense
    for num in range(80, 100):
        d[f'A{num}'] = d['A80-A99']

    # Alekhine's Defense
    for num in range(2, 6):
        d[f'B0{num}'] = d['B02-B05']

    # Pirc Defense
    for num in range(7, 10):
        d[f'B0{num}'] = d['B07-B09']

    # Caro-Kann Defense
    for num in range(10, 20):
        d[f'B{num}'] = d['B10-B19']

    # Sicilian Defense
    for num in range(20, 100):
        d[f'B{num}'] = d['B20-B99']

    # French Defense
    for num in range(0, 10):
        d[f'C0{num}'] = d['C00-C19']
    for num in range(10, 20):
        d[f'C{num}'] = d['C00-C19']

    # Uncommon King's Pawn Opening
    # Unusual e4 Openings
    d['B00'] = d['e4']
    # Uncommon e4-e5 Openings
    for num in range(20, 23):
        d[f'C{num}'] = d['e4']

    # Vienna Game
    for num in range(23, 30):
        d[f'C{num}'] = d['C23-C29']

    # King's Gambit
    for num in range(30, 40):
        d[f'C{num}'] = d['C30-C39']

    # Philidor Defense
    for num in range(40, 42):
        d[f'C{num}'] = d['C40-C41']

    # Petrov's Defense
    for num in range(42, 44):
        d[f'C{num}'] = d['C42-C43']

    # Four Knights Opening
    for num in range(47, 50):
        d[f'C{num}'] = d['C47-C49']

    # Italian Game
    for num in range(50, 60):
        d[f'C{num}'] = d['C50-C59']

    # Ruy Lopez Opening
    for num in range(60, 100):
        d[f'C{num}'] = d['C60-C99']

    # Queen's Gambit
    for num in range(6, 10):
        d[f'D0{num}'] = d['D06-D69']
    for num in range(10, 70):
        d[f'D{num}'] = d['D06-D69']

    # Grunfeld Defense
    for num in range(70, 100):
        d[f'D{num}'] = d['D70-D99']

    # Catalan Opening
    for num in range(0, 10):
        d[f'E0{num}'] = d['E00-E09']

    # Queen's Indian Defense
    for num in range(12, 20):
        d[f'E{num}'] = d['E12-E19']

    # Nimzo-Indian Defense
    for num in range(20, 60):
        d[f'E{num}'] = d['E20-E59']

    # King's Indian Defense
    for num in range(60, 99):
        d[f'E{num}'] = d['E60-E99']


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


def process_games(d, username, num_months, time_classes):
    api_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    headers = {'User-Agent': 'Chess Prepper'}
    months = requests.get(api_url, headers=headers).json()

    if num_months is None:
        num_months = len(months['archives'])

    # Use FuturesSession for concurrent requests
    futures = []
    for month in months['archives'][-num_months:]:
        futures.append(futures_session.get(month, headers=headers))

    for future in as_completed(futures):
        response = future.result()
        games = response.json()
        with ThreadPoolExecutor(max_workers=10) as executor:
            game_futures = [executor.submit(update_stats, d, game, username, time_classes) for game in games['games']]
            for game_future in as_completed(game_futures):
                game_future.result()


def update_stats(d, game, username, time_classes):
    def update_line(d, game_id, game_data, line_name, win_inc):
        d['numGames'] += 1
        d['numWins'] += win_inc
        for line, value in d['lines'].items():
            if line in line_name:
                if 'lines' in d['lines'][line]:
                    update_line(d['lines'][line], game_id, game_data, line_name, win_inc)
                else:
                    d['lines'][line]['numGames'] += 1
                    d['lines'][line]['numWins'] += win_inc
                    if line_name in d['lines'][line]['urls']:
                        d['lines'][line]['urls'][line_name]['numGames'] += 1
                        d['lines'][line]['urls'][line_name]['numWins'] += win_inc
                        d['lines'][line]['urls'][line_name]['games'][game_id] = game_data
                    else:
                        d['lines'][line]['urls'][line_name] = {'numGames': 1, 'numWins': win_inc,
                                                               'games': {game_id: game_data}}
                return
        d['lines']['Other']['numGames'] += 1
        d['lines']['Other']['numWins'] += win_inc
        if line_name in d['lines']['Other']['urls']:
            d['lines']['Other']['urls'][line_name]['numGames'] += 1
            d['lines']['Other']['urls'][line_name]['numWins'] += win_inc
            d['lines']['Other']['urls'][line_name]['games'][game_id] = game_data
        else:
            d['lines']['Other']['urls'][line_name] = {'numGames': 1, 'numWins': win_inc, 'games': {game_id: game_data}}

    try:
        if game['rules'] == 'chess' and (len(time_classes) == 4 or game['time_class'] in time_classes):
            eco = None
            eco_url = None
            date = None
            for info in game['pgn'].split('\n'):
                if info.startswith('[ECO '):
                    eco = info.split('"')[1]
                elif info.startswith('[ECOUrl'):
                    eco_url = info.split('"')[1]
                elif info.startswith('[UTCD'):
                    date = info.split('"')[1]

            if eco and eco_url:
                opening_specific = eco_url[31:]
                game_data = {
                    'url': game['url'],
                    'time_class': game['time_class'],
                    'time_control': game['time_control'],
                    'white': game['white'],
                    'black': game['black'],
                    'date': date
                }
                game_id = game['url'].split('/')[-1]
                win_i = 0

                if game['white']['username'] == username:
                    if game['white']['result'] == 'win':
                        win_i = 1
                    elif game['black']['result'] != 'win':
                        win_i = .5
                    game_data['white']['win_inc'] = win_i
                    game_data['black']['win_inc'] = 1 - win_i
                    update_line(d['white'][eco], game_id, game_data, opening_specific, win_i)
                else:
                    if game['black']['result'] == 'win':
                        win_i = 1
                    elif game['white']['result'] != 'win':
                        win_i = .5
                    game_data['black']['win_inc'] = win_i
                    game_data['white']['win_inc'] = 1 - win_i
                    update_line(d['black'][eco], game_id, game_data, opening_specific, win_i)
    except KeyError:
        pass


@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')


@app.route('/process_games', methods=['POST'])
def process_games_api():
    username = request.form['username']
    color = request.form['color']
    all_games = request.form.get('allGames') == 'on'
    time_classes = request.form.getlist('time-classes')
    num_months = None

    headers = {'User-Agent': 'Chess Prepper'}
    profile_api_url = f"https://api.chess.com/pub/player/{username}"
    profile_info = requests.get(profile_api_url, headers=headers).json()

    if 'code' in profile_info and profile_info['code'] == 0:
        return f"User \"{username}\" not found.", 404

    stats_api_url = f"https://api.chess.com/pub/player/{username}/stats"
    stats_info = requests.get(stats_api_url, headers=headers).json()
    rating_info = {}

    if not all_games:
        time_frame = request.form['num-months']
        months_or_years = request.form['monthsOrYears']
        if months_or_years == 'months':
            num_months = int(time_frame)
        else:
            num_months = int(time_frame) * 12
        if int(time_frame) == 1:
            time_frame_str = f"last {months_or_years[:-1]}"
        else:
            time_frame_str = f"last {time_frame} {months_or_years}"
    else:
        time_frame_str = 'all games'

    if color == 'white':
        not_color = 'black'
    else:
        not_color = 'white'

    if not time_classes:
        time_classes = ['bullet', 'blitz', 'rapid', 'daily']

    for time_class in time_classes:
        chess_time_class = stats_info.get(f"chess_{time_class}", {})
        last_rating = chess_time_class.get('last', {}).get('rating', 'N/A')
        best_rating = chess_time_class.get('best', {}).get('rating', 'N/A')

        rating_info[time_class] = {
            'current': last_rating if last_rating != 'N/A' else 'N/A',
            'peak': best_rating if best_rating != 'N/A' else 'N/A'
        }

    player_info = {'display_name': profile_info['url'][29:], 'color': color, 'not_color': not_color,
                   'ratings': rating_info, 'time_frame': time_frame_str}

    # Initialize the opening stats dictionary
    opening_stats_w = {eco: create_eco_dict(details['displayName'], details['lines']) for eco, details in
                       eco_details.items()}
    create_aliases(opening_stats_w)
    opening_stats_b = copy.deepcopy(opening_stats_w)

    opening_stats = {'white': opening_stats_w, 'black': opening_stats_b}

    # Process games and update stats
    process_games(opening_stats, username, num_months, time_classes)

    # Prettify stats and store them in Firestore
    stats = {
        'white': prettify_stats(opening_stats['white']),
        'black': prettify_stats(opening_stats['black'])
    }

    session_id = generate_session_id({
        'player_info': player_info,
        'stats': stats
    })

    if stats:
        return render_template('process_games.html', stats=stats[color], playerinfo=player_info, gamesort='checked',
                               winsort='', asc='', desc='checked', session_id=session_id, str=str)
    else:
        return "No stats available", 400


@app.route('/sort_openings', methods=['POST'])
def sort_openings_api():
    def recursive_sort(lines):
        for line in lines:
            if 'sub_lines' in line and line['sub_lines']:
                line['sub_lines'].sort(key=lambda x: x[metric], reverse=direction)
                recursive_sort(line['sub_lines'])

    session_id = request.form['session_id']
    data = get_session_data(session_id)

    if not data:
        return "No stats to sort", 400

    metric = request.form['metric']
    direction = request.form['direction'] == 'True'
    color = data['player_info']['color']
    stats = data['stats'][color]
    stats.sort(key=lambda x: x[metric], reverse=direction)

    recursive_sort(stats)

    gamesort = 'checked' if metric == 'num_games' else ''
    winsort = 'checked' if metric == 'win_rate' else ''
    asc = 'checked' if not direction else ''
    desc = 'checked' if direction else ''

    return render_template('process_games.html', stats=stats, playerinfo=data['player_info'], gamesort=gamesort,
                           winsort=winsort, asc=asc, desc=desc, session_id=session_id, str=str)


@app.route('/swap_colors', methods=['POST'])
def swap_colors_api():
    session_id = request.form['session_id']
    data = get_session_data(session_id)

    if not data:
        return "No stats to swap", 400

    old_color = data['player_info']['color']
    new_color = data['player_info']['not_color']

    data['player_info']['color'] = new_color
    data['player_info']['not_color'] = old_color

    db.collection('sessions').document(session_id).update({
        'player_info.color': new_color,
        'player_info.not_color': old_color
    })

    return render_template('process_games.html', stats=data['stats'][new_color], playerinfo=data['player_info'],
                           gamesort='checked', winsort='', asc='', desc='checked', session_id=session_id, str=str)


@app.route('/opening_details')
def opening_details():
    current_session_id = request.args.get('current_session_id', None)
    session_info = get_session_data(current_session_id)

    if not session_info or 'stats' not in session_info:
        return "Session expired or invalid", 400

    variation = session_info['stats']
    path = request.args.get('path', None)
    keys = path.split('.')
    for key in keys:
        if key.isdigit():
            key = int(key)  # Convert to integer if the key is an index
        variation = variation[key]

    parent = request.args.get('parent', '')

    for line in variation['variations'].values():
        line['games'] = dict(
            sorted(line['games'].items(), key=lambda item: datetime.strptime(item[1]['date'], '%Y.%m.%d'),
                   reverse=True))

    return render_template('opening_details.html', variation=variation, parent=parent, playerinfo=session_info['player_info'])


def prettify_stats(stats_dict):
    def recursive_build(details):
        num_games = details['numGames']
        num_wins = details['numWins']
        win_rate = int(round((num_wins / num_games * 100), 0)) if num_games > 0 else 0  # Calculate and round win rate

        # Calculate win rate for each variation
        variations = {
            key: {
                'numGames': value['numGames'],
                'numWins': value['numWins'],
                'winRate': int(round((value['numWins'] / value['numGames'] * 100), 0)) if value['numGames'] > 0 else 0,
                'games': value['games']
            }
            for key, value in details.get('urls', {}).items()
        }

        result = {
            'display_name': details['displayName'],
            'num_games': num_games,
            'win_rate': win_rate,  # Store win rate as an integer
            'variations': variations,
            'sub_lines': []
        }

        if 'lines' in details:
            for key, sub_details in details['lines'].items():
                if sub_details and sub_details['numGames'] > 0:  # Ensuring there is data to process
                    result['sub_lines'].append(recursive_build(sub_details))

        result['sub_lines'].sort(key=lambda x: x['num_games'], reverse=True)

        return result

    def move_opening(new_eco_name, old_eco, old_name):
        stats_dict[new_eco_name] = stats_dict[old_eco]['lines'][old_name]
        del stats_dict[old_eco]['lines'][old_name]
        stats_dict[old_eco]['numGames'] -= stats_dict[new_eco_name]['numGames']
        stats_dict[old_eco]['numWins'] -= stats_dict[new_eco_name]['numWins']

    move_opening('london', 'd4', 'London')
    move_opening('indian', 'd4', 'Indian')
    move_opening('benoni', 'd4', 'Benoni')
    move_opening('trompowsky', 'd4', 'Tromp')

    move_opening('nimzo-def', 'e4', 'Nimzo')
    move_opening('ponziani', 'e4', 'Ponzi')

    move_opening('grob', 'A00', 'Grob')
    move_opening('kings-fianchetto', 'A00', 'Kings-F')
    move_opening('polish', 'A00', 'Polish')

    results = []
    seen = set()
    for eco_code, details in stats_dict.items():
        if details['displayName'] not in seen and details['numGames'] > 0:
            results.append(recursive_build(details))
            seen.add(details['displayName'])

    results.sort(key=lambda x: x['num_games'], reverse=True)

    return results


if __name__ == '__main__':
    app.run(debug=False)
