import streamlit as st
import pandas as pd
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime
import time
from streamlit_option_menu import option_menu
from collections import Counter
import altair as alt

# --- CONFIGURATION ---
TMDB_API_KEY = st.secrets["tmdb_api_key"]
SHEET_ID = st.secrets["sheet_id"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- STREAMING PROVIDER MAP (US) ---
PROVIDERS = {
    "Netflix": 8, "Disney+": 337, "Max": 1899, "Hulu": 15,
    "Amazon Prime": 9, "Apple TV+": 350, "Peacock": 384, "Paramount+": 531
}

# --- CSS STYLING ---
st.markdown("""
<style>
    /* Global Styles */
    h1, h2, h3 { font-family: 'Helvetica Neue', sans-serif; }
    
    /* Movie Card */
    .movie-card {
        position: relative;
        display: block;
        width: 100%;
        margin-bottom: 5px;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s;
        aspect-ratio: 2/3;
    }
    .movie-card:hover { transform: scale(1.02); z-index: 5; }
    .movie-img { width: 100%; height: 100%; object-fit: cover; display: block; }

    /* Rating Badges */
    .rating-badge {
        position: absolute; bottom: 5px; width: 28px; height: 28px;
        border-radius: 50%; background-color: rgba(8, 28, 34, 0.95);
        border: 2px solid #21d07a; color: white;
        font-family: sans-serif; font-weight: bold; font-size: 9px;
        display: flex; flex-direction: column; justify-content: center; align-items: center;
        z-index: 10; box-shadow: 0 2px 4px rgba(0,0,0,0.8); line-height: 1;
    }
    .badge-left { left: 5px; border-color: #21d07a; }
    .badge-right { right: 5px; border-color: #01b4e4; }
    
    /* Streaming Logos */
    .stream-container {
        position: absolute; top: 5px; right: 5px;
        display: flex; flex-direction: column; gap: 2px; z-index: 12;
    }
    .stream-logo { width: 20px; height: 20px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.5); }
    .detail-stream-logo { width: 40px; height: 40px; border-radius: 6px; margin-right: 8px; }
    
    /* Buttons */
    div[data-testid="column"] button {
        padding: 0px 0px !important; font-size: 10px !important;
        min-height: 24px !important; height: 24px !important; width: 100% !important;
    }
    div[data-testid="column"] { padding: 0 3px !important; }
    
    /* Stats Container */
    .stats-container {
        background-color: #1a1a1a;
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 20px;
        border: 1px solid #333;
    }
</style>
""", unsafe_allow_html=True)

# --- BACKEND FUNCTIONS ---

def get_google_sheet_client():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds).spreadsheets()

def get_data(range_name):
    try:
        service = get_google_sheet_client()
        result = service.values().get(spreadsheetId=SHEET_ID, range=range_name).execute()
        return result.get('values', [])
    except: return []

def get_users():
    rows = get_data("Users!A:B")
    if not rows or len(rows) < 2: return []
    return [row[1] for row in rows[1:]]

def add_user(name, favorite_genres, seed_movies):
    service = get_google_sheet_client()
    rows = get_data("Users!A:A")
    new_id = len(rows) if rows else 1
    row = [[new_id, name, ", ".join(favorite_genres), str(seed_movies)]]
    service.values().append(
        spreadsheetId=SHEET_ID, range="Users!A:D",
        valueInputOption="USER_ENTERED", body={'values': row}
    ).execute()

def log_media(title, movie_id, genres, users_ratings, media_type, poster_path):
    service = get_google_sheet_client()
    timestamp = datetime.now().strftime("%Y-%m-%d")
    
    # Genre Fix
    genre_str = "Unknown"
    try:
        if isinstance(genres, list) and len(genres) > 0:
            if isinstance(genres[0], dict):
                genre_str = ", ".join([g.get('name', '') for g in genres])
            elif isinstance(genres[0], int):
                genre_str = str(genres) 
        else: genre_str = str(genres)
    except: genre_str = "Error"

    new_rows = []
    for user, rating in users_ratings.items():
        new_rows.append([timestamp, title, str(movie_id), genre_str, user, str(rating), media_type, poster_path])
    
    service.values().append(
        spreadsheetId=SHEET_ID, range="Activity_Log!A:H",
        valueInputOption="USER_ENTERED", body={'values': new_rows}
    ).execute()
    st.toast(f"Logged {title}!")

def hide_media_db(user, movie_id):
    service = get_google_sheet_client()
    timestamp = datetime.now().strftime("%Y-%m-%d")
    row = [[user, str(movie_id), timestamp]]
    try:
        service.values().append(
            spreadsheetId=SHEET_ID, range="Hidden!A:C",
            valueInputOption="USER_ENTERED", body={'values': row}
        ).execute()
    except Exception as e: st.error(f"Could not save hide: {e}")

def get_hidden_ids(user):
    rows = get_data("Hidden!A:B")
    if not rows: return set()
    return set([row[1] for row in rows if len(row) > 1 and row[0] == user])

def get_watched_history():
    rows = get_data("Activity_Log!A:H")
    if len(rows) < 2: return pd.DataFrame()
    return pd.DataFrame(rows[1:], columns=["Date", "Title", "Movie_ID", "Genres", "User", "Rating", "Type", "Poster"])

# --- TMDB FUNCTIONS ---
@st.cache_data
def get_tmdb_genres():
    url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=en-US"
    data = requests.get(url).json()
    return {g['name']: g['id'] for g in data.get('genres', [])}

@st.cache_data
def get_genre_map_reversed():
    """Returns {id: 'Name'} map"""
    try:
        url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=en-US"
        data = requests.get(url).json()
        return {str(g['id']): g['name'] for g in data.get('genres', [])}
    except: return {}

@st.cache_data(ttl=3600)
def get_watch_providers(media_id, media_type="movie"):
    try:
        endpoint = "tv" if media_type == "TV Shows" else "movie"
        url = f"https://api.themoviedb.org/3/{endpoint}/{media_id}/watch/providers?api_key={TMDB_API_KEY}"
        data = requests.get(url).json()
        providers = []
        seen = set()
        if 'results' in data and 'US' in data['results']:
            us = data['results']['US']
            if 'flatrate' in us:
                for p in us['flatrate']:
                    if p['provider_name'] not in seen and p.get('logo_path'):
                        providers.append(f"https://image.tmdb.org/t/p/w45{p['logo_path']}")
                        seen.add(p['provider_name'])
        return providers
    except: return []

# --- ALGORITHM: GET RECOMMENDATIONS BY GENRE ---
def get_genre_recommendations(genre_id, provider_ids=None, page=1, min_vote_count=200):
    """
    Fetches recommendations for a specific genre.
    Uses 'sort_by=vote_average.desc' combined with vote_count to surface quality.
    """
    base_url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&language=en-US"
    
    # Core Filters
    params = f"&with_genres={genre_id}&sort_by=popularity.desc&vote_count.gte={min_vote_count}&page={page}"
    
    if provider_ids:
        p_str = "|".join([str(p) for p in provider_ids])
        params += f"&with_watch_providers={p_str}&watch_region=US"
        
    data = requests.get(base_url + params).json().get('results', [])
    return data

def search_tmdb(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    return requests.get(url).json().get('results', [])

# --- HTML GENERATORS ---
def render_card(poster_path, tmdb_score, user_score=None, provider_logos=None):
    poster_url = f"https://image.tmdb.org/t/p/w400{poster_path}" if poster_path else "https://via.placeholder.com/200x300"
    
    tmdb_html = ""
    if tmdb_score is not None and tmdb_score > 0:
        color = "#21d07a" 
        if tmdb_score < 70: color = "#d2d531" 
        if tmdb_score < 40: color = "#db2360" 
        tmdb_html = f'<div class="rating-badge badge-left" style="border-color: {color};"><span class="badge-label">TMDB</span>{tmdb_score}</div>'
    
    user_html = ""
    if user_score is not None and str(user_score) != 'nan':
        user_html = f'<div class="rating-badge badge-right"><span class="badge-label">YOU</span>{int(float(user_score))}</div>'

    stream_html = ""
    if provider_logos:
        logos_str = "".join([f'<img src="{l}" class="stream-logo">' for l in provider_logos[:3]])
        stream_html = f'<div class="stream-container">{logos_str}</div>'

    return f'<div class="movie-card"><img src="{poster_url}" class="movie-img">{tmdb_html}{user_html}{stream_html}</div>'

# --- APP STARTUP ---
st.set_page_config(page_title="Cinematch", layout="wide", page_icon="🎬")

if 'page' not in st.session_state: st.session_state.page = "home"
if 'hidden_movies' not in st.session_state: st.session_state.hidden_movies = set()
if 'view_movie_detail' not in st.session_state: st.session_state.view_movie_detail = None
# We store pagination PER genre now
if 'genre_pages' not in st.session_state: st.session_state.genre_pages = {} 

existing_users = get_users()
if not existing_users:
    st.warning("Please create a profile.")
    st.stop()

# --- SIDEBAR ---
with st.sidebar:
    st.markdown("""
    <div style="display: flex; align-items: center; margin-bottom: 20px;">
        <span style="font-size: 2.5rem;">🎬</span>
        <span style="font-size: 2rem; font-weight: 800; color: #E50914; letter-spacing: -1px; margin-left: 10px;">Cine</span>
        <span style="font-size: 2rem; font-weight: 800; color: #ffffff; letter-spacing: -1px;">Match</span>
    </div>
    """, unsafe_allow_html=True)
    
    current_users = existing_users + ["➕ Add Profile"]
    active_user = st.selectbox("Watching Now:", current_users)
    st.markdown("---")
    nav_choice = option_menu("Menu", ["Home", "Profile", "Settings"], icons=['house-fill', 'person-circle', 'gear-fill'], menu_icon="cast", default_index=0, styles={"nav-link-selected": {"background-color": "#E50914"}})

# --- HOME PAGE ---
if nav_choice == "Home":
    
    # 1. LOAD DATA & SYNC
    history = get_watched_history()
    user_history = pd.DataFrame()
    if not history.empty:
        user_history = history[history['User'] == active_user]
    
    if 'hidden_synced' not in st.session_state:
        db_hidden = get_hidden_ids(active_user)
        st.session_state.hidden_movies.update(db_hidden)
        st.session_state.hidden_synced = True

    # 2. STATS & CHART (New Layout)
    if not user_history.empty:
        # Prepare Data for Chart
        chart_data = user_history.copy()
        chart_data['Rating'] = pd.to_numeric(chart_data['Rating'], errors='coerce')
        chart_data = chart_data.dropna(subset=['Rating'])
        
        # Calculate Stats
        avg_rating = chart_data['Rating'].mean()
        total_rated = len(chart_data)
        
        # --- ALTAIR DISTRIBUTION CHART ---
        chart = alt.Chart(chart_data).mark_bar(
            cornerRadiusTopLeft=3,
            cornerRadiusTopRight=3
        ).encode(
            x=alt.X('Rating', bin=alt.Bin(step=10), title='Rating (0-100)'),
            y=alt.Y('count()', title='Movies'),
            color=alt.value('#E50914'),
            tooltip=['count()']
        ).properties(
            height=150,
            background='transparent'
        ).configure_axis(
            labelColor='#aaa',
            titleColor='#aaa',
            gridColor='#333'
        ).configure_view(
            strokeWidth=0
        )
        
        # Mean Rule Line
        rule = alt.Chart(pd.DataFrame({'mean': [avg_rating]})).mark_rule(color='#21d07a', strokeDash=[4, 4]).encode(x='mean')
        final_chart = chart + rule

        # Render Stats Container
        with st.container():
            st.markdown('<div class="stats-container">', unsafe_allow_html=True)
            c_stat, c_chart = st.columns([1, 3])
            
            with c_stat:
                st.metric("Movies Rated", total_rated)
                st.metric("Avg Rating", f"{avg_rating:.1f}")
                st.caption(f"Benchmark: {avg_rating:.1f}")
            
            with c_chart:
                st.altair_chart(final_chart, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    else:
        st.info("Log movies to unlock your dashboard!")

    # 3. CONTROL BAR
    col_search, col_stream = st.columns([2, 1])
    with col_search:
        search_query = st.text_input("Search", placeholder="Search TMDB...", label_visibility="collapsed")
    with col_stream:
        with st.expander("📡 Services", expanded=False):
            use_stream_filter = st.toggle("Filter")
            selected_providers = st.multiselect("Providers", list(PROVIDERS.keys()), default=["Netflix", "Max"], label_visibility="collapsed")
            prov_ids = [PROVIDERS[p] for p in selected_providers] if use_stream_filter else None

    # --- DETAIL VIEW ---
    if st.session_state.view_movie_detail:
        m = st.session_state.view_movie_detail
        if st.button("← Back to Grid"):
            st.session_state.view_movie_detail = None
            st.rerun()
        
        c1, c2 = st.columns([1,3])
        with c1: st.image(f"https://image.tmdb.org/t/p/w400{m['poster_path']}", use_container_width=True)
        with c2:
            title_text = f"{m['title']}"
            if 'release_date' in m: title_text += f" ({m['release_date'][:4]})"
            st.markdown(f"## {title_text}")
            
            if 'provider_logos' not in m or not m['provider_logos']:
                m['provider_logos'] = get_watch_providers(m['id'], m['media_type'])
            
            if m['provider_logos']:
                st.write("**Streaming on:**")
                logo_html = "".join([f'<img src="{l}" class="detail-stream-logo">' for l in m['provider_logos']])
                st.markdown(logo_html, unsafe_allow_html=True)
                st.write("")
            
            st.write(m.get('overview'))
            st.divider()
            st.subheader("Rate & Log")
            user_rating = st.slider(f"{active_user}'s Rating", 1, 100, 70)
            if st.button("✅ Log to Database", type="primary"):
                log_media(m['title'], m['id'], m.get('genre_ids', []), {active_user: user_rating}, m['media_type'], m['poster_path'])
                st.success("Logged!")
                st.session_state.hidden_movies.add(str(m['id']))
                hide_media_db(active_user, str(m['id']))
                st.session_state.view_movie_detail = None
                time.sleep(1)
                st.rerun()

    # --- SEARCH VIEW ---
    elif search_query:
        st.subheader("Search Results")
        display_list = search_tmdb(search_query)
        COLS = 6
        for i in range(0, len(display_list), COLS):
            cols = st.columns(COLS)
            batch = display_list[i:i+COLS]
            for idx, item in enumerate(batch):
                with cols[idx]:
                    title = item.get('title', item.get('name'))
                    poster = item.get('poster_path')
                    if not poster: continue
                    
                    st.markdown(render_card(poster, None, None, None), unsafe_allow_html=True)
                    st.caption(f"**{title}**")
                    
                    if st.button("Log", key=f"s_{item['id']}"):
                        item['title'] = title
                        item['media_type'] = item.get('media_type', 'movie')
                        st.session_state.view_movie_detail = item
                        st.rerun()

    # --- RECOMMENDATION ROWS (NETFLIX STYLE) ---
    else:
        # 1. Analyze User Taste to Rank Genres
        g_map_rev = get_genre_map_reversed()
        genre_scores = {}
        
        if not user_history.empty:
            for _, row in user_history.iterrows():
                try:
                    rating = float(row['Rating'])
                    # Clean Genre String
                    g_str = str(row['Genres']).replace('[', '').replace(']', '').replace("'", "")
                    parts = [x.strip() for x in g_str.split(',')]
                    
                    for part in parts:
                        # Normalize to Name
                        g_name = g_map_rev.get(part, part)
                        if g_name not in genre_scores: genre_scores[g_name] = []
                        genre_scores[g_name].append(rating)
                except: continue
        
        # Calculate Avg per Genre
        ranked_genres = []
        for g, ratings in genre_scores.items():
            avg = sum(ratings) / len(ratings)
            ranked_genres.append((g, avg))
        
        # Sort by Rating Descending (User Preferences)
        ranked_genres.sort(key=lambda x: x[1], reverse=True)
        
        # Limit to Top 5 Genres for rows
        top_genres = [x[0] for x in ranked_genres[:5]]
        
        # Fallback if no history
        if not top_genres: top_genres = ["Action", "Comedy", "Sci-Fi", "Drama"]
        
        # RENDER ROWS
        g_map = get_tmdb_genres()
        
        for g_name in top_genres:
            g_id = g_map.get(g_name)
            if not g_id: continue
            
            st.markdown(f"### {g_name} <span style='font-size:0.6em; color:#21d07a'>({int(genre_scores.get(g_name, [0])[0] if g_name in genre_scores else 0)}% Match)</span>", unsafe_allow_html=True)
            
            # Pagination State
            if g_name not in st.session_state.genre_pages:
                st.session_state.genre_pages[g_name] = 1
                
            # Fetch Data
            # Note: We filter query by provider here!
            movies = get_genre_recommendations(g_id, prov_ids, page=st.session_state.genre_pages[g_name])
            
            # Filter Hidden/Watched
            watched_ids = set(str(x) for x in history['Movie_ID']) if not history.empty else set()
            hidden_ids = st.session_state.hidden_movies
            
            display_list = []
            for m in movies:
                if str(m['id']) not in watched_ids and str(m['id']) not in hidden_ids:
                    display_list.append(m)
            
            # Show top 5
            display_list = display_list[:5]
            
            cols = st.columns(6) # 5 Movies + 1 Next Button
            
            for idx, item in enumerate(display_list):
                with cols[idx]:
                    poster = item.get('poster_path')
                    tmdb = int(item.get('vote_average', 0) * 10)
                    
                    # Fetch Logos (Cached)
                    logos = get_watch_providers(item['id'])
                    
                    st.markdown(render_card(poster, tmdb, None, logos), unsafe_allow_html=True)
                    
                    # Buttons
                    b1, b2, b3 = st.columns(3)
                    key = f"{g_name}_{item['id']}"
                    with b1:
                        if st.button("Info", key=f"i_{key}"):
                            item['title'] = item.get('title')
                            item['media_type'] = 'movie'
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b2:
                        if st.button("Log", key=f"l_{key}"):
                            item['title'] = item.get('title')
                            item['media_type'] = 'movie'
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b3:
                        if st.button("Hide", key=f"h_{key}"):
                            st.session_state.hidden_movies.add(str(item['id']))
                            hide_media_db(active_user, str(item['id']))
                            st.rerun()
            
            # Next Button Column
            with cols[5]:
                st.write("")
                st.write("")
                st.write("")
                if st.button("➡️", key=f"next_{g_name}", help="Next Page"):
                    st.session_state.genre_pages[g_name] += 1
                    st.rerun()
            
            st.divider()

elif nav_choice == "Profile":
    st.header(f"Profile: {active_user}")
    history = get_watched_history()
    if not history.empty:
        user_history = history[history['User'] == active_user]
        st.dataframe(user_history)
