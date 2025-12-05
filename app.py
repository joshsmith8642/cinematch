import streamlit as st
import pandas as pd
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime
import time
from streamlit_option_menu import option_menu

# --- CONFIGURATION ---
TMDB_API_KEY = st.secrets["tmdb_api_key"]
SHEET_ID = st.secrets["sheet_id"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

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
    
    /* Poster Image */
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
    
    /* Positions */
    .badge-left { left: 5px; border-color: #21d07a; }
    .badge-right { right: 5px; border-color: #01b4e4; }
    
    .badge-label {
        font-size: 5px;
        text-transform: uppercase;
        opacity: 0.8;
        margin-bottom: 1px;
    }
    
    /* Compact Buttons */
    div[data-testid="column"] button {
        padding: 0px 0px !important;
        font-size: 11px !important;
        min-height: 25px !important;
        height: 25px !important;
        width: 100% !important;
    }
    div[data-testid="column"] {
        padding: 0 2px !important;
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

def get_watched_history():
    rows = get_data("Activity_Log!A:H")
    if len(rows) < 2: return pd.DataFrame()
    return pd.DataFrame(rows[1:], columns=["Date", "Title", "Movie_ID", "Genres", "User", "Rating", "Type", "Poster"])

# --- TMDB FUNCTIONS ---
def get_tmdb_genres():
    url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=en-US"
    data = requests.get(url).json()
    return {g['name']: g['id'] for g in data.get('genres', [])}

def get_movie_details_live(movie_id, media_type="movie"):
    """Fetches fresh details (like current rating) for a specific ID"""
    try:
        endpoint = "tv" if media_type == "TV Shows" else "movie"
        url = f"https://api.themoviedb.org/3/{endpoint}/{movie_id}?api_key={TMDB_API_KEY}"
        return requests.get(url).json()
    except: return {}

def get_recommendations(watched_ids, media_type="movie", selected_genre_ids=None, page=1):
    endpoint = "tv" if media_type == "TV Shows" else "movie"
    base_url = f"https://api.themoviedb.org/3/discover/{endpoint}?api_key={TMDB_API_KEY}&language=en-US&sort_by=popularity.desc&vote_count.gte=200&page={page}"
    if selected_genre_ids:
        g_str = ",".join([str(g) for g in selected_genre_ids])
        base_url += f"&with_genres={g_str}"
    
    data = requests.get(base_url).json().get('results', [])
    
    # --- ROBUST FILTERING ---
    # Convert everything to strings to ensure matches work (550 vs "550")
    watched_set = set(str(x) for x in watched_ids)
    hidden_set = set(str(x) for x in st.session_state.hidden_movies)
    
    filtered_data = []
    for m in data:
        m_id = str(m['id'])
        if m_id not in watched_set and m_id not in hidden_set:
            filtered_data.append(m)
            
    return filtered_data

def search_tmdb(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    return requests.get(url).json().get('results', [])

# --- HTML GENERATOR ---
def render_card(poster_path, tmdb_score, user_score=None):
    poster_url = f"https://image.tmdb.org/t/p/w400{poster_path}" if poster_path else "https://via.placeholder.com/200x300"
    
    # 1. TMDB Badge
    tmdb_html = ""
    if tmdb_score is not None:
        color = "#21d07a" # Green
        if tmdb_score < 70: color = "#d2d531" # Yellow
        if tmdb_score < 40: color = "#db2360" # Red
        tmdb_html = f'<div class="rating-badge badge-left" style="border-color: {color};"><span class="badge-label">TMDB</span>{tmdb_score}</div>'
    
    # 2. User Badge
    user_html = ""
    if user_score is not None and str(user_score) != 'nan':
        user_html = f'<div class="rating-badge badge-right"><span class="badge-label">YOU</span>{int(float(user_score))}</div>'

    return f'<div class="movie-card"><img src="{poster_url}" class="movie-img">{tmdb_html}{user_html}</div>'

# --- APP STARTUP ---
st.set_page_config(page_title="Cinematch", layout="wide", page_icon="🎬")

if 'page' not in st.session_state: st.session_state.page = "home"
if 'hidden_movies' not in st.session_state: st.session_state.hidden_movies = []
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
    
    search_query = st.text_input("🔍 Search...", placeholder="Movies, TV Shows...")

    # --- DETAIL VIEW ---
    if st.session_state.view_movie_detail:
        m = st.session_state.view_movie_detail
        if st.button("← Back to Grid"):
            st.session_state.view_movie_detail = None
            st.rerun()
        
        c1, c2 = st.columns([1,3])
        with c1:
            st.image(f"https://image.tmdb.org/t/p/w400{m['poster_path']}", use_container_width=True)
        with c2:
            title_text = f"{m['title']}"
            if 'release_date' in m:
                title_text += f" ({m['release_date'][:4]})"
            st.markdown(f"## {title_text}")
            st.write(m.get('overview'))
            st.divider()
            st.subheader("Rate & Log")
            user_rating = st.slider(f"{active_user}'s Rating", 1, 100, 70)
            if st.button("✅ Log to Database", type="primary"):
                log_media(m['title'], m['id'], m.get('genre_ids', []), {active_user: user_rating}, m['media_type'], m['poster_path'])
                st.success("Logged!")
                # Add to local ignore list immediately so it vanishes from Recs
                st.session_state.hidden_movies.append(str(m['id'])) 
                st.session_state.view_movie_detail = None
                time.sleep(1)
                st.rerun()

    # --- GRID VIEW ---
    else:
        if search_query:
            st.subheader("Search Results")
            display_list = search_tmdb(search_query)
        else:
            # Filters
            c_mode, c_type, c_sort, c_genre = st.columns([1.5, 1.5, 1.5, 3])
            with c_mode: view_mode = st.selectbox("View", ["Recommendations", "Rewatch"], label_visibility="collapsed")
            with c_type: media_type = st.selectbox("Type", ["Movies", "TV Shows"], label_visibility="collapsed")
            
            sort_options = ["Popularity", "Rating", "Newest"] if view_mode == "Recommendations" else ["Date Watched", "Rating"]
            with c_sort: sort_by = st.selectbox("Sort", sort_options, label_visibility="collapsed")
            
            with c_genre:
                g_map = get_tmdb_genres()
                sel_genres = st.multiselect("Genre", list(g_map.keys()), placeholder="All Genres", label_visibility="collapsed")
                sel_ids = [g_map[name] for name in sel_genres]

            history = get_watched_history()
            
            # 1. REWATCH DATA
            if view_mode == "Rewatch":
                if not history.empty:
                    my_hist = history[history['User'] == active_user].copy()
                    display_list = []
                    
                    # NOTE: We now fetch live data for scores to fix the "0" bug
                    # This might be slightly slower but ensures accuracy
                    for _, row in my_hist.iterrows():
                        if sel_genres and not any(g in row['Genres'] for g in sel_genres): continue
                        
                        # Live Lookup
                        live_data = get_movie_details_live(row['Movie_ID'], row['Type'])
                        live_score = int(live_data.get('vote_average', 0) * 10)
                        
                        display_list.append({
                            "id": row['Movie_ID'], 
                            "title": row['Title'], 
                            "poster_path": row['Poster'],
                            "vote_average": live_score, # Fixed!
                            "user_rating": float(row['Rating']), 
                            "media_type": row['Type'], 
                            "date": row['Date'],
                            "release_date": live_data.get('release_date', live_data.get('first_air_date', ''))
                        })
                    
                    if sort_by == "Rating": display_list.sort(key=lambda x: x['user_rating'], reverse=True)
                    else: display_list.sort(key=lambda x: x['date'], reverse=True)
                else:
                    st.info("No history yet.")
                    display_list = []

            # 2. RECS DATA
            else:
                watched_ids = history['Movie_ID'].astype(str).tolist() if not history.empty else []
                
                # Reset Logic
                curr_filters = (media_type, tuple(sel_ids), sort_by)
                if 'last_filters' not in st.session_state: st.session_state.last_filters = None
                if st.session_state.last_filters != curr_filters:
                    st.session_state.loaded_recs = []
                    st.session_state.existing_ids = set() # Clear ID cache
                    st.session_state.rec_page = 1
                    st.session_state.last_filters = curr_filters
                
                # Load Page
                if not st.session_state.loaded_recs:
                    new_data = get_recommendations(watched_ids, media_type, sel_ids, page=1)
                    # Deduplicate before adding
                    for m in new_data:
                        if str(m['id']) not in st.session_state.existing_ids:
                            st.session_state.loaded_recs.append(m)
                            st.session_state.existing_ids.add(str(m['id']))
                
                display_list = st.session_state.loaded_recs
                
                # Sorting
                if sort_by == "Rating": display_list = sorted(display_list, key=lambda x: x.get('vote_average', 0), reverse=True)
                elif sort_by == "Newest": display_list = sorted(display_list, key=lambda x: x.get('release_date', '0000'), reverse=True)

        # RENDERER
        COLS = 6
        for i in range(0, len(display_list), COLS):
            cols = st.columns(COLS)
            batch = display_list[i:i+COLS]
            for idx, item in enumerate(batch):
                with cols[idx]:
                    # Values
                    title = item.get('title', item.get('name'))
                    tmdb = int(item.get('vote_average', 0) * 10)
                    user = item.get('user_rating', None)
                    m_type = item.get('media_type', 'movie')
                    poster = item.get('poster_path')
                    
                    # Fix: Add Year
                    raw_date = item.get('release_date', item.get('first_air_date', ''))
                    year = raw_date[:4] if raw_date else ""
                    
                    # HTML Card
                    st.markdown(render_card(poster, tmdb, user), unsafe_allow_html=True)
                    
                    # Text Title with Year
                    short_title = (title[:16] + "..") if len(title) > 18 else title
                    st.markdown(f"**{short_title}** <span style='font-size:0.8em; color:gray'>({year})</span>", unsafe_allow_html=True)

                    # Text Buttons
                    b1, b2, b3 = st.columns(3)
                    # Use unique keys by appending loop index "i" to avoid DuplicateKeyError
                    unique_key_suffix = f"{item['id']}_{i}_{idx}"
                    
                    with b1:
                        if st.button("Info", key=f"d_{unique_key_suffix}"):
                            item['title'] = title
                            item['media_type'] = m_type
                            item['release_date'] = raw_date # Ensure date passes to detail view
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b2:
                        if st.button("Log", key=f"l_{unique_key_suffix}"):
                            item['title'] = title
                            item['media_type'] = m_type
                            item['release_date'] = raw_date
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b3:
                        if st.button("Hide", key=f"h_{unique_key_suffix}"):
                            st.session_state.hidden_movies.append(str(item['id']))
                            st.rerun()

        if not search_query and view_mode == "Recommendations":
            st.write("")
            if st.button("Load More..."):
                st.session_state.rec_page += 1
                new_data = get_recommendations(watched_ids, media_type, sel_ids, page=st.session_state.rec_page)
                
                # Robust Deduplication
                count_new = 0
                for m in new_data:
                    if str(m['id']) not in st.session_state.existing_ids:
                        st.session_state.loaded_recs.append(m)
                        st.session_state.existing_ids.add(str(m['id']))
                        count_new += 1
                
                if count_new == 0:
                    st.toast("No more new movies found for this filter!")
                else:
                    st.rerun()

elif nav_choice == "Profile":
    st.header(f"Profile: {active_user}")
    history = get_watched_history()
    if not history.empty:
        user_history = history[history['User'] == active_user]
        st.dataframe(user_history)
