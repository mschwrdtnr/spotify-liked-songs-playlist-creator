from flask import Flask, redirect, request, session, url_for, render_template, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import os
import logging

load_dotenv()  # Load environment variables from .env file

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY')  # Use an environment variable for the secret key
app.config['SESSION_COOKIE_NAME'] = 'spotify-login-session'
app.config['SESSION_COOKIE_SECURE'] = True  # Ensure the cookie is only sent over HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # Session lifetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sp_oauth = SpotifyOAuth(
    client_id=os.getenv('SPOTIPY_CLIENT_ID'),
    client_secret=os.getenv('SPOTIPY_CLIENT_SECRET'),
    redirect_uri=os.getenv('SPOTIPY_REDIRECT_URI'),
    scope='user-library-read playlist-modify-public'
)

def get_all_liked_songs(sp):
    results = sp.current_user_saved_tracks(limit=50)
    total_songs = results['total']
    all_tracks = results['items']
    
    while len(all_tracks) < total_songs:
        results = sp.current_user_saved_tracks(limit=50, offset=len(all_tracks))
        all_tracks.extend(results['items'])
    
    # Sort tracks by added_at timestamp in reverse order (newest first)
    all_tracks.sort(key=lambda x: x['added_at'], reverse=True)
    
    return all_tracks

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login')
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    try:
        token_info = sp_oauth.get_access_token(code)
    except spotipy.exceptions.SpotifyOauthError as e:
        logger.error(f"Spotify OAuth error: {e}")
        return jsonify({'error': 'Authorization failed'}), 400

    session['token_info'] = token_info
    return redirect(url_for('home', logged_in='true'))

@app.route('/create_playlist', methods=['POST'])
def create_playlist():
    token_info = session.get('token_info', None)
    if not token_info:
        return jsonify({'error': 'Token info not found'}), 401

    try:
        sp = spotipy.Spotify(auth=token_info['access_token'], requests_timeout=10)
        user_id = sp.current_user()['id']

        # Fetch all liked songs and sort them by added_at timestamp in reverse order
        all_tracks = get_all_liked_songs(sp)
        track_ids = [item['track']['id'] for item in all_tracks]

        # Check if the playlist already exists
        playlists = sp.user_playlists(user_id)
        playlist = next((pl for pl in playlists['items'] if pl['name'] == "Liked Songs Playlist"), None)

        if playlist is None:
            # Create a new playlist
            playlist = sp.user_playlist_create(user_id, "Liked Songs Playlist", public=True)
            existing_tracks = []
        else:
            # Get existing track IDs
            existing_tracks = []
            results = sp.playlist_tracks(playlist['id'])
            while results:
                existing_tracks.extend([item['track']['id'] for item in results['items']])
                if results['next']:
                    results = sp.next(results)
                else:
                    results = None

        # Find new tracks to add (excluding already existing ones)
        new_tracks = [track for track in track_ids if track not in existing_tracks]
        num_added = len(new_tracks)

        # Add new songs to the playlist in batches of 100 (Spotify API limit)
        for i in range(len(new_tracks), 0, -100):
            sp.playlist_add_items(playlist['id'], new_tracks[max(0, i-100):i], position=0)

        # Remove tracks that are no longer liked
        tracks_to_remove = [track for track in existing_tracks if track not in track_ids]
        if tracks_to_remove:
            for i in range(0, len(tracks_to_remove), 100):
                sp.user_playlist_remove_all_occurrences_of_tracks(user_id, playlist['id'], tracks_to_remove[i:i+100])

        num_removed = len(tracks_to_remove)

        response_html = f"""
            <p>Playlist updated! {num_added} songs added, {num_removed} songs removed.</p>
            <a href='https://open.spotify.com/playlist/{playlist['id']}' class='spotify-link'>Open Playlist</a>
        """
        return jsonify({'html': response_html})

    except spotipy.exceptions.SpotifyException as e:
        logger.error(f"Spotify API error: {e}")
        return jsonify({'error': 'Failed to create or update playlist'}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

if __name__ == '__main__':
    app.run(debug=True)
