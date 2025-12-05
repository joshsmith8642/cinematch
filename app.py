import streamlit as st
import pandas as pd
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime
import time
from streamlit_option_menu import option_menu
from collections import Counter

# --- CONFIGURATION ---
TMDB_API_KEY = st.secrets["tmdb_api_key"]
SHEET_ID = st.secrets["sheet_id"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- STREAMING PROVIDER MAP (US Region) ---
PROVIDERS = {
    "Netflix": 8, "Disney+": 337, "Max": 1899, "Hulu": 15,
    "Amazon Prime": 9, "Apple TV+": 350, "Peacock": 384, "Paramount+": 531
}

# --- CSS STYLING ---
st.markdown("""
<style>
    /* Card Container */
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
    .movie-card:hover {
        transform: scale(1.02);
        z-index: 5;
    }
    .movie-img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }

    /* Rating Badges */
    .rating-badge {
        position: absolute;
        bottom: 5px;
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background-color: rgba(8, 28, 34, 0.95);
        border: 2px solid #21d07a;
        color: white;
        font-family: sans-serif;
        font-weight: bold;
        font-size: 11px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        z-index: 10;
        box-shadow: 0 2px 4px rgba(0,0,0,0.8);
        line-height: 1;
    }
    .badge-left { left: 5px; border-color: #21d07a; }
    .badge-right { right: 5px; border-color: #01b4e4; }
    .badge-label { font-size: 5px; text-transform: uppercase; opacity: 0.8; margin-bottom: 1px; }
    
    /* Streaming Logos */
    .stream-container {
        position: absolute;
        top: 5px;
        right: 5px;
        display: flex;
        flex-direction: column;
        gap: 4px;
        z-index: 12;
    }
    .stream-logo {
        width: 24px;
        height: 24px;
        border-radius: 4px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.5);
    }
    
    /* Compact Buttons */
    div[data-testid="column"] button {
        padding: 0px 0px !important;
        font-size: 11px !important;
        min-height: 25px !important;
        height: 25px !important;
        width: 100% !important;
    }
    div[data-testid="column"] { padding: 0 2px !important; }
    
    /* STATS CARDS CSS (COMPACT) */
    .stat-card {
        background: linear-gradient(135deg, #1e1e1e 0%, #2a2a2a 100%);
        border-radius: 10px;
        padding: 10px; /* Reduced padding */
        text-align: center;
        border: 1px solid #333;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .stat-val { font-size: 22px; font-weight: 800; color: #fff; margin: 0; line-height: 1.2; }
    .stat-label { font-size: 10px; text-transform: uppercase; color: #aaa; letter-spacing: 0.5px; margin-top: 4px; }
    .stat-accent-1 { color: #E50914; }
    .stat-accent-2 { color: #21d07a; }
    .stat-accent-3 { color: #01b4e4; }

    /* COMPLEX SCORE CARD */
    .score-card-grid {
        display: flex;
        justify-content: space-around;
        align-items: center;
        padding: 5px 0;
    }
    .score-item {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 0 4px;
    }
    .border-x { border-left: 1px solid #444; border-right: 1px solid #444; }
    .score-val { font-size: 18px; font-weight: 800; line-height: 1; }
    .score-label { font-size: 8px; text-transform: uppercase; color: #aaa; margin-top: 2px; }
    .score-title {
        font-size: 8px; color: #888; margin-top: 3px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 70px;
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
        else:
            genre_str = str(genres)
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

def get_movie_details_live(movie_id, media_type="movie"):
    try:
        endpoint = "tv" if media_type == "TV Shows" else "movie"
        url = f"https://api.themoviedb.org/3/{endpoint}/{movie_id}?api_key={TMDB_API_KEY}"
        return requests.get(url).json()
    except: return {}

@st.cache_data(ttl=3600) # Cache for 1 hour to improve performance
def get_watch_providers(media_id, media_type="movie"):
    """Fetches streaming provider logos for US flatrate"""
    try:
        endpoint = "tv" if media_type == "TV Shows" else "movie"
        url = f"https://api.themoviedb.org/3/{endpoint}/{media_id}/watch/providers?api_key={TMDB_API_KEY}"
        data = requests.get(url).json()
        
        providers = []
        if 'results' in data and 'US' in data['results']:
            us_data = data['results']['US']
            if 'flatrate' in us_data:
                for p in us_data['flatrate']:
                    if p.get('logo_path'):
                        providers.append(f"https://image.tmdb.org/t/p/w45{p['logo_path']}")
        return providers
    except:
        return []

def get_recommendations(watched_ids, media_type="movie", selected_genre_ids=None, provider_ids=None, page=1):
    endpoint = "tv" if media_type == "TV Shows" else "movie"
    base_url = f"https://api.themoviedb.org/3/discover/{endpoint}?api_key={TMDB_API_KEY}&language=en-US&sort_by=popularity.desc&vote_count.gte=200&page={page}"
    if selected_genre_ids:
        g_str = ",".join([str(g) for g in selected_genre_ids])
        base_url += f"&with_genres={g_str}"
    if provider_ids:
        p_str = "|".join([str(p) for p in provider_ids])
        base_url += f"&with_watch_providers={p_str}&watch_region=US"
    
    data = requests.get(base_url).json().get('results', [])
    return data

def search_tmdb(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    return requests.get(url).json().get('results', [])

# --- HTML GENERATORS ---
def render_card(poster_path, tmdb_score, user_score=None, provider_logos=None):
    poster_url = f"https://image.tmdb.org/t/p/w400{poster_path}" if poster_path else "https://via.placeholder.com/200x300"
    
    # Ratings
    tmdb_html = ""
    if tmdb_score is not None and tmdb_score > 0:
        color = "#21d07a" 
        if tmdb_score < 70: color = "#d2d531" 
        if tmdb_score < 40: color = "#db2360" 
        tmdb_html = f'<div class="rating-badge badge-left" style="border-color: {color};"><span class="badge-label">TMDB</span>{tmdb_score}</div>'
    
    user_html = ""
    if user_score is not None and str(user_score) != 'nan':
        user_html = f'<div class="rating-badge badge-right"><span class="badge-label">YOU</span>{int(float(user_score))}</div>'

    # Streaming Logos
    stream_html = ""
    if provider_logos:
        logos_str = ""
        for logo_url in provider_logos:
            logos_str += f'<img src="{logo_url}" class="stream-logo">'
        stream_html = f'<div class="stream-container">{logos_str}</div>'

    return f'<div class="movie-card"><img src="{poster_url}" class="movie-img">{tmdb_html}{user_html}{stream_html}</div>'

def render_simple_stat_card(label, value, accent_class):
    return f"""<div class="stat-card"><div class="stat-val {accent_class}">{value}</div><div class="stat-label">{label}</div></div>"""

def render_complex_stat_card(best_val, best_title, avg_val, worst_val, worst_title):
    return f"""
    <div class="stat-card score-card-grid">
        <div class="score-item">
            <div class="score-val stat-accent-2">{best_val}</div>
            <div class="score-label">BEST</div>
            <div class="score-title">{best_title}</div>
        </div>
        <div class="score-item border-x">
            <div class="score-val stat-accent-3">{avg_val}</div>
            <div class="score-label">AVG</div>
        </div>
        <div class="score-item">
            <div class="score-val stat-accent-1">{worst_val}</div>
            <div class="score-label">WORST</div>
            <div class="score-title">{worst_title}</div>
        </div>
    </div>
    """

# --- APP STARTUP ---
st.set_page_config(page_title="Cinematch", layout="wide", page_icon="🎬")

# Init Session
if 'page' not in st.session_state: st.session_state.page = "home"
if 'hidden_movies' not in st.session_state: st.session_state.hidden_movies = set()
if 'view_movie_detail' not in st.session_state: st.session_state.view_movie_detail = None
if 'rec_page' not in st.session_state: st.session_state.rec_page = 1
if 'loaded_recs' not in st.session_state: st.session_state.loaded_recs = []
if 'existing_ids' not in st.session_state: st.session_state.existing_ids = set()

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

    # 2. STATS DASHBOARD (Compact & Fixed)
    if not user_history.empty:
        # Calculations
        total = len(user_history)
        
        genre_map_rev = get_genre_map_reversed()
        all_genres_names = []
        for g_str in user_history['Genres']:
            if g_str and g_str.lower() not in ['unknown', 'error']:
                ids = [x.strip() for x in str(g_str).split(',')]
                for g_id in ids:
                    all_genres_names.append(genre_map_rev.get(g_id, g_id))
        top_genre = Counter(all_genres_names).most_common(1)[0][0] if all_genres_names else "N/A"
        
        # Scores
        try:
            df_scores = user_history.copy()
            df_scores['Rating'] = pd.to_numeric(df_scores['Rating'], errors='coerce').fillna(0)
            avg_val = f"{df_scores['Rating'].mean():.1f}"
            
            best_row = df_scores.loc[df_scores['Rating'].idxmax()]
            best_val = int(best_row['Rating'])
            best_title = best_row['Title']
            
            worst_row = df_scores.loc[df_scores['Rating'].idxmin()]
            worst_val = int(worst_row['Rating'])
            worst_title = worst_row['Title']
        except:
             avg_val, best_val, best_title, worst_val, worst_title = ("-", 0, "", 0, "")

        # Render
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(render_simple_stat_card("Movies Rated", total, "stat-accent-1"), unsafe_allow_html=True)
        with c2: st.markdown(render_simple_stat_card("Top Genre", top_genre, "stat-accent-2"), unsafe_allow_html=True)
        with c3: st.markdown(render_complex_stat_card(best_val, best_title, avg_val, worst_val, worst_title), unsafe_allow_html=True)
    else:
        st.info("Log movies to unlock your dashboard!")

    st.write("---")

    # 3. CONTROL BAR
    col_search, col_stream = st.columns([2, 1])
    with col_search:
        st.write("Filter & Search")
        search_query = st.text_input("Search", placeholder="Movies, TV Shows...", label_visibility="collapsed")
    with col_stream:
        st.write("Streaming Services")
        with st.expander("Select Your Services", expanded=False):
            use_stream_filter = st.toggle("Filter Results")
            selected_providers = st.multiselect("Providers", list(PROVIDERS.keys()), default=["Netflix", "Max"], label_visibility="collapsed")
            
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

    # --- GRID VIEW ---
    else:
        if search_query:
            st.subheader("Search Results")
            display_list = search_tmdb(search_query)
            # Note: No streaming logos on search results to keep it fast
            processed_list = []
            for item in display_list:
                 item['provider_logos'] = None 
                 processed_list.append(item)
            display_list = processed_list

        else:
            # Sub-Filters
            c_mode, c_type, c_sort, c_genre = st.columns([1.5, 1.5, 1.5, 3])
            with c_mode: view_mode = st.selectbox("View", ["Recommendations", "Rewatch"], label_visibility="collapsed")
            with c_type: media_type = st.selectbox("Type", ["Movies", "TV Shows"], label_visibility="collapsed")
            sort_options = ["Popularity", "Rating", "Newest"] if view_mode == "Recommendations" else ["Date Watched", "Rating"]
            with c_sort: sort_by = st.selectbox("Sort", sort_options, label_visibility="collapsed")
            with c_genre:
                g_map = get_tmdb_genres()
                sel_genres = st.multiselect("Genre", list(g_map.keys()), placeholder="All Genres", label_visibility="collapsed")
                sel_ids = [g_map[name] for name in sel_genres]
            
            # REWATCH
            if view_mode == "Rewatch":
                if not user_history.empty:
                    my_hist = user_history.copy()
                    display_list = []
                    target_type = "movie" if media_type == "Movies" else "tv"
                    
                    for _, row in my_hist.iterrows():
                        if row['Type'] != target_type: continue
                        if sel_genres and not any(g in row['Genres'] for g in sel_genres): continue
                        
                        live_data = get_movie_details_live(row['Movie_ID'], row['Type'])
                        # Get Providers for Rewatch too
                        prov_logos = get_watch_providers(row['Movie_ID'], row['Type'])

                        display_list.append({
                            "id": row['Movie_ID'], "title": row['Title'], "poster_path": row['Poster'],
                            "vote_average": live_data.get('vote_average', 0), 
                            "user_rating": float(row['Rating']), 
                            "media_type": row['Type'], "date": row['Date'],
                            "release_date": live_data.get('release_date', live_data.get('first_air_date', '')),
                            "provider_logos": prov_logos
                        })
                    
                    if sort_by == "Rating": display_list.sort(key=lambda x: x['user_rating'], reverse=True)
                    else: display_list.sort(key=lambda x: x['date'], reverse=True)
                else:
                    st.info("No history yet.")
                    display_list = []

            # RECOMMENDATIONS
            else:
                watched_ids = history['Movie_ID'].astype(str).tolist() if not history.empty else []
                prov_ids = [PROVIDERS[p] for p in selected_providers] if use_stream_filter else None

                # Reset Logic
                curr_filters = (media_type, tuple(sel_ids), sort_by, tuple(prov_ids) if prov_ids else None)
                if 'last_filters' not in st.session_state: st.session_state.last_filters = None
                if st.session_state.last_filters != curr_filters:
                    st.session_state.loaded_recs = []
                    st.session_state.existing_ids = set() 
                    st.session_state.rec_page = 1
                    st.session_state.last_filters = curr_filters
                
                if not st.session_state.loaded_recs:
                    new_data = get_recommendations(watched_ids, media_type, sel_ids, prov_ids, page=1)
                    for m in new_data:
                        if str(m['id']) not in st.session_state.existing_ids:
                            # FETCH PROVIDERS LIVE and cache
                            m['provider_logos'] = get_watch_providers(m['id'], media_type)
                            st.session_state.loaded_recs.append(m)
                            st.session_state.existing_ids.add(str(m['id']))
                
                # Filter Hidden
                display_list = [m for m in st.session_state.loaded_recs if str(m['id']) not in st.session_state.hidden_movies]
                
                if sort_by == "Rating": display_list = sorted(display_list, key=lambda x: x.get('vote_average', 0), reverse=True)
                elif sort_by == "Newest": display_list = sorted(display_list, key=lambda x: x.get('release_date', '0000'), reverse=True)

        # RENDERER
        COLS = 6
        for i in range(0, len(display_list), COLS):
            cols = st.columns(COLS)
            batch = display_list[i:i+COLS]
            for idx, item in enumerate(batch):
                with cols[idx]:
                    title = item.get('title', item.get('name'))
                    raw_score = item.get('vote_average', 0)
                    tmdb = int(raw_score * 10)
                    user = item.get('user_rating', None)
                    m_type = item.get('media_type', 'movie')
                    poster = item.get('poster_path')
                    raw_date = item.get('release_date', item.get('first_air_date', ''))
                    year = raw_date[:4] if raw_date else ""
                    logos = item.get('provider_logos')
                    
                    st.markdown(render_card(poster, tmdb, user, logos), unsafe_allow_html=True)
                    
                    short_title = (title[:16] + "..") if len(title) > 18 else title
                    st.markdown(f"**{short_title}** <span style='font-size:0.8em; color:gray'>({year})</span>", unsafe_allow_html=True)

                    b1, b2, b3 = st.columns(3)
                    key_suffix = f"{item['id']}_{i}_{idx}"
                    
                    with b1:
                        if st.button("Info", key=f"d_{key_suffix}"):
                            item['title'] = title
                            item['media_type'] = m_type
                            item['release_date'] = raw_date 
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b2:
                        if st.button("Log", key=f"l_{key_suffix}"):
                            item['title'] = title
                            item['media_type'] = m_type
                            item['release_date'] = raw_date
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b3:
                        if st.button("Hide", key=f"h_{key_suffix}"):
                            st.session_state.hidden_movies.add(str(item['id']))
                            hide_media_db(active_user, str(item['id']))
                            st.rerun()

        if not search_query and view_mode == "Recommendations":
            st.write("")
            if st.button("Load More..."):
                st.session_state.rec_page += 1
                prov_ids = [PROVIDERS[p] for p in selected_providers] if use_stream_filter else None
                new_data = get_recommendations(watched_ids, media_type, sel_ids, prov_ids, page=st.session_state.rec_page)
                
                count = 0
                for m in new_data:
                    if str(m['id']) not in st.session_state.existing_ids:
                        # Fetch providers for new batch
                        m['provider_logos'] = get_watch_providers(m['id'], media_type)
                        st.session_state.loaded_recs.append(m)
                        st.session_state.existing_ids.add(str(m['id']))
                        count += 1
                if count == 0: st.toast("No more movies found!")
                else: st.rerun()

elif nav_choice == "Profile":
    st.header(f"Profile: {active_user}")
    history = get_watched_history()
    if not history.empty:
        user_history = history[history['User'] == active_user]
        st.dataframe(user_history)
