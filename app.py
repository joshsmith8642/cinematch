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
    h1, h2, h3, p, div { font-family: 'Helvetica Neue', sans-serif; }
    
    /* Movie Card */
    .movie-card {
        position: relative; display: block; width: 100%; margin-bottom: 5px;
        border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s; aspect-ratio: 2/3;
    }
    .movie-card:hover { transform: scale(1.05); z-index: 10; }
    .movie-img { width: 100%; height: 100%; object-fit: cover; display: block; }

    /* Badges */
    .rating-badge {
        position: absolute; bottom: 5px; width: 28px; height: 28px;
        border-radius: 50%; background-color: rgba(8, 28, 34, 0.95);
        border: 2px solid #21d07a; color: white; font-weight: bold; font-size: 9px;
        display: flex; flex-direction: column; justify-content: center; align-items: center;
        z-index: 10; box-shadow: 0 2px 4px rgba(0,0,0,0.8);
    }
    .badge-left { left: 5px; border-color: #21d07a; }
    .badge-right { right: 5px; border-color: #01b4e4; }
    
    /* Streaming Logos */
    .stream-container {
        position: absolute; top: 5px; right: 5px; display: flex; flex-direction: column; gap: 2px; z-index: 12;
    }
    .stream-logo { width: 20px; height: 20px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.5); }
    .detail-stream-logo { width: 40px; height: 40px; border-radius: 6px; margin-right: 8px; }
    
    /* Buttons */
    div[data-testid="column"] button {
        padding: 0px !important; font-size: 10px !important;
        min-height: 24px !important; height: 24px !important; width: 100% !important;
    }
    
    /* NEW STATS CONTAINER */
    .stats-container {
        background-color: #121212;
        border-radius: 12px;
        padding: 20px;
        border: 1px solid #333;
        margin-bottom: 20px;
    }
    .stat-box {
        text-align: center;
        padding: 10px;
        border-right: 1px solid #333;
    }
    .stat-box:last-child { border-right: none; }
    .stat-value { font-size: 24px; font-weight: 800; color: #fff; }
    .stat-label { font-size: 11px; text-transform: uppercase; color: #888; margin-top: 5px; }
    .accent-green { color: #21d07a; }
    .accent-blue { color: #01b4e4; }
    
    /* Genre Header */
    .genre-header {
        font-size: 1.4rem; font-weight: 700; margin-top: 25px; margin-bottom: 10px;
        display: flex; align-items: center; border-bottom: 1px solid #333; padding-bottom: 5px;
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
def get_tmdb_genres(media_type="movie"):
    """Fetch genres for Movie or TV"""
    endpoint = "tv" if media_type == "tv" else "movie"
    url = f"https://api.themoviedb.org/3/genre/{endpoint}/list?api_key={TMDB_API_KEY}&language=en-US"
    data = requests.get(url).json()
    return {g['name']: g['id'] for g in data.get('genres', [])}

@st.cache_data
def get_genre_map_reversed(media_type="movie"):
    """Returns {id: 'Name'} map"""
    try:
        endpoint = "tv" if media_type == "tv" else "movie"
        url = f"https://api.themoviedb.org/3/genre/{endpoint}/list?api_key={TMDB_API_KEY}&language=en-US"
        data = requests.get(url).json()
        return {str(g['id']): g['name'] for g in data.get('genres', [])}
    except: return {}

@st.cache_data(ttl=3600)
def get_watch_providers(media_id, media_type="movie"):
    try:
        endpoint = "tv" if media_type == "tv" else "movie"
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

# --- ALGORITHM: GENRE ROWS ---
def get_genre_rows_data(genre_id, media_type, provider_ids=None, page=1, avoid_ids=None):
    """Fetch content for a specific genre row"""
    endpoint = "tv" if media_type == "tv" else "movie"
    base_url = f"https://api.themoviedb.org/3/discover/{endpoint}?api_key={TMDB_API_KEY}&language=en-US"
    
    # Sort by popularity + vote count to ensure quality suggestions
    params = f"&with_genres={genre_id}&sort_by=popularity.desc&vote_count.gte=200&page={page}"
    
    if provider_ids:
        p_str = "|".join([str(p) for p in provider_ids])
        params += f"&with_watch_providers={p_str}&watch_region=US"
        
    data = requests.get(base_url + params).json().get('results', [])
    
    # Anti-Bad Filter (Remove movies similar to bad ones if possible)
    # Simple ID exclusion for now
    filtered = []
    if avoid_ids:
        for m in data:
            if str(m['id']) not in avoid_ids:
                filtered.append(m)
        return filtered
        
    return data

def search_tmdb(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    return requests.get(url).json().get('results', [])

# --- HTML GENERATOR ---
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
    
    # 1. LOAD DATA
    history = get_watched_history()
    user_history = pd.DataFrame()
    if not history.empty:
        user_history = history[history['User'] == active_user]
    
    if 'hidden_synced' not in st.session_state:
        db_hidden = get_hidden_ids(active_user)
        st.session_state.hidden_movies.update(db_hidden)
        st.session_state.hidden_synced = True

    # 2. GLOBAL CONTROLS
    c_search, c_type, c_stream = st.columns([2, 1, 1])
    with c_search:
        search_query = st.text_input("Search", placeholder="Search Movies & TV...", label_visibility="collapsed")
    with c_type:
        # MASTER FILTER: TV vs MOVIE
        media_type_display = st.radio("Type", ["Movies", "TV Shows"], horizontal=True, label_visibility="collapsed")
        media_type = "movie" if media_type_display == "Movies" else "tv"
    with c_stream:
        with st.expander("Streaming", expanded=False):
            use_stream_filter = st.toggle("Filter")
            selected_providers = st.multiselect("Providers", list(PROVIDERS.keys()), default=["Netflix", "Max"], label_visibility="collapsed")
            prov_ids = [PROVIDERS[p] for p in selected_providers] if use_stream_filter else None

    # Filter History by Selected Type
    if not user_history.empty:
        user_history = user_history[user_history['Type'] == media_type]

    # 3. STATS DASHBOARD
    if not user_history.empty:
        chart_data = user_history.copy()
        chart_data['Rating'] = pd.to_numeric(chart_data['Rating'], errors='coerce')
        chart_data = chart_data.dropna(subset=['Rating'])
        
        avg_rating = chart_data['Rating'].mean()
        total_rated = len(chart_data)
        
        # --- ALTAIR HISTOGRAM (GRADIENT) ---
        base = alt.Chart(chart_data).encode(
            x=alt.X('Rating', bin=alt.Bin(step=5), title='Rating Distribution'),
            y=alt.Y('count()', title=None)
        )
        
        bars = base.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            color=alt.Color('Rating', scale=alt.Scale(scheme='redyellowgreen'), legend=None),
            tooltip=['count()']
        )
        
        rule = alt.Chart(pd.DataFrame({'mean': [avg_rating]})).mark_rule(color='white', strokeDash=[4, 4]).encode(x='mean')
        
        final_chart = (bars + rule).properties(height=100, background='transparent').configure_axis(
            labelColor='#888', titleColor='#888', gridColor='#333', domain=False
        ).configure_view(strokeWidth=0)

        # RENDER STATS
        with st.container():
            st.markdown('<div class="stats-container">', unsafe_allow_html=True)
            c_s1, c_s2, c_s3, c_chart = st.columns([1, 1, 1, 3])
            
            with c_s1:
                st.markdown(f"<div class='stat-box'><div class='stat-value accent-blue'>{total_rated}</div><div class='stat-label'>Rated</div></div>", unsafe_allow_html=True)
            
            # Find Top Genre
            g_map_rev = get_genre_map_reversed(media_type)
            all_g = []
            for g_str in user_history['Genres']:
                if g_str and g_str.lower() not in ['unknown', 'error']:
                    clean = str(g_str).replace('[', '').replace(']', '').replace("'", "")
                    parts = [x.strip() for x in clean.split(',')]
                    for p in parts: all_g.append(g_map_rev.get(p, p))
            top_genre = Counter(all_g).most_common(1)[0][0] if all_g else "-"
            
            with c_s2:
                st.markdown(f"<div class='stat-box'><div class='stat-value'>{top_genre}</div><div class='stat-label'>Top Genre</div></div>", unsafe_allow_html=True)
            
            with c_s3:
                st.markdown(f"<div class='stat-box'><div class='stat-value accent-green'>{avg_rating:.1f}</div><div class='stat-label'>Avg Score</div></div>", unsafe_allow_html=True)
                
            with c_chart:
                st.altair_chart(final_chart, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

    # --- DETAIL MODAL ---
    if st.session_state.view_movie_detail:
        m = st.session_state.view_movie_detail
        if st.button("← Back"):
            st.session_state.view_movie_detail = None
            st.rerun()
        
        c1, c2 = st.columns([1,3])
        with c1: st.image(f"https://image.tmdb.org/t/p/w400{m['poster_path']}", use_container_width=True)
        with c2:
            st.markdown(f"## {m.get('title', m.get('name'))}")
            
            if 'provider_logos' not in m: m['provider_logos'] = get_watch_providers(m['id'], media_type)
            if m['provider_logos']:
                logos = "".join([f'<img src="{l}" class="detail-stream-logo">' for l in m['provider_logos']])
                st.markdown(f"**Available on:**<br>{logos}", unsafe_allow_html=True)
            
            st.write(m.get('overview'))
            st.divider()
            user_rating = st.slider("Your Rating", 1, 100, 70)
            if st.button("✅ Save", type="primary"):
                title = m.get('title', m.get('name'))
                log_media(title, m['id'], m.get('genre_ids', []), {active_user: user_rating}, media_type, m['poster_path'])
                st.success("Logged!")
                st.session_state.hidden_movies.add(str(m['id']))
                hide_media_db(active_user, str(m['id']))
                st.session_state.view_movie_detail = None
                time.sleep(1)
                st.rerun()

    # --- SEARCH VIEW ---
    elif search_query:
        st.subheader("Results")
        results = search_tmdb(search_query)
        cols = st.columns(6)
        for i, item in enumerate(results):
            if not item.get('poster_path'): continue
            with cols[i % 6]:
                st.markdown(render_card(item['poster_path'], None), unsafe_allow_html=True)
                if st.button("Log", key=f"s_{item['id']}"):
                    st.session_state.view_movie_detail = item
                    st.rerun()

    # --- NETFLIX STYLE ROWS ---
    else:
        # Genre Filter
        g_map = get_tmdb_genres(media_type)
        sel_genres = st.multiselect("Filter Genres", list(g_map.keys()), placeholder="Showing Top Genres by Default")
        
        # Determine Genres to Show
        genres_to_show = []
        
        if sel_genres:
            # Explicit selection
            genres_to_show = sel_genres
        else:
            # Auto-rank based on user history
            g_map_rev = get_genre_map_reversed(media_type)
            genre_scores = {}
            if not user_history.empty:
                for _, row in user_history.iterrows():
                    try:
                        r = float(row['Rating'])
                        parts = str(row['Genres']).replace("'", "").replace("[","").replace("]","").split(',')
                        for p in parts:
                            name = g_map_rev.get(p.strip(), p.strip())
                            if name not in genre_scores: genre_scores[name] = []
                            genre_scores[name].append(r)
                    except: continue
            
            # Sort by Avg Rating
            ranked = sorted([(k, sum(v)/len(v)) for k,v in genre_scores.items()], key=lambda x: x[1], reverse=True)
            top_user_genres = [x[0] for x in ranked]
            
            # Backfill with defaults if < 5
            defaults = ["Action", "Comedy", "Sci-Fi", "Drama", "Thriller"] if media_type == "movie" else ["Drama", "Comedy", "Sci-Fi & Fantasy", "Animation", "Crime"]
            
            genres_to_show = top_user_genres
            for d in defaults:
                if d not in genres_to_show: genres_to_show.append(d)
            
            genres_to_show = genres_to_show[:5] # Cap at 5 rows

        # Identify Bad Movies for Anti-Filter
        avoid_ids = set()
        if not user_history.empty:
            bad_movies = user_history[pd.to_numeric(user_history['Rating'], errors='coerce') <= 50]
            avoid_ids = set(bad_movies['Movie_ID'].tolist())
            # Also add Hidden
            avoid_ids.update(st.session_state.hidden_movies)

        # RENDER ROWS
        for g_name in genres_to_show:
            g_id = g_map.get(g_name)
            if not g_id: continue
            
            st.markdown(f"<div class='genre-header'>{g_name}</div>", unsafe_allow_html=True)
            
            # Pagination
            page_key = f"{g_name}_{media_type}"
            if page_key not in st.session_state.genre_pages: st.session_state.genre_pages[page_key] = 1
            
            movies = get_genre_rows_data(g_id, media_type, prov_ids, st.session_state.genre_pages[page_key], avoid_ids)
            
            # Limit to 5
            movies = movies[:5]
            
            cols = st.columns([1,1,1,1,1, 0.5])
            
            for i, m in enumerate(movies):
                with cols[i]:
                    tmdb = int(m.get('vote_average', 0)*10)
                    logos = get_watch_providers(m['id'], media_type)
                    st.markdown(render_card(m['poster_path'], tmdb, None, logos), unsafe_allow_html=True)
                    
                    c1, c2, c3 = st.columns(3)
                    k = f"{g_name}_{m['id']}"
                    with c1: 
                        if st.button("Info", key=f"i_{k}"):
                            st.session_state.view_movie_detail = m
                            st.rerun()
                    with c2:
                        if st.button("Log", key=f"l_{k}"):
                            st.session_state.view_movie_detail = m
                            st.rerun()
                    with c3:
                        if st.button("Hide", key=f"h_{k}"):
                            st.session_state.hidden_movies.add(str(m['id']))
                            hide_media_db(active_user, str(m['id']))
                            st.rerun()
            
            with cols[5]:
                st.write("")
                st.write("")
                if st.button("➡️", key=f"n_{page_key}"):
                    st.session_state.genre_pages[page_key] += 1
                    st.rerun()

elif nav_choice == "Profile":
    st.header(f"Profile: {active_user}")
    history = get_watched_history()
    if not history.empty:
        user_history = history[history['User'] == active_user]
        st.dataframe(user_history)
