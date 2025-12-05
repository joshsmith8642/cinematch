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
    /* Movie Card Container */
    .movie-card {
        position: relative;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        margin-bottom: 8px; /* Reduced bottom margin */
        transition: transform 0.2s;
        aspect-ratio: 2/3; /* Enforce poster aspect ratio */
    }
    .movie-card:hover {
        transform: scale(1.03);
        z-index: 10;
    }
    .movie-img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
        border-radius: 12px;
    }
    
    /* Rating Overlays */
    .rating-badge {
        position: absolute;
        bottom: 8px;
        width: 32px; /* Smaller badge */
        height: 32px;
        border-radius: 50%;
        background: rgba(8, 28, 34, 0.9);
        border: 2px solid #21d07a;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: bold;
        font-size: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.5);
        z-index: 2;
        flex-direction: column;
        line-height: 1;
    }
    
    /* Position specific badges */
    .badge-left {
        left: 8px;
    }
    .badge-right {
        right: 8px;
        border-color: #01b4e4; /* Blue for User */
    }
    
    .badge-label {
        font-size: 5px;
        text-transform: uppercase;
        margin-bottom: 1px;
        opacity: 0.8;
    }
    
    /* COMPACT BUTTONS CSS */
    div[data-testid="column"] button {
        width: 100%;
        padding: 0.1rem 0.1rem !important; /* Force tight padding */
        font-size: 0.75rem !important; /* Smaller text */
        height: auto !important;
        min-height: 0px !important;
    }
    /* Reduce gap between grid columns */
    div[data-testid="column"] {
        padding: 0 0.2rem; 
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
    
    # Genre ID to Name fix
    try:
        url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=en-US"
        data = requests.get(url).json()
        id_map = {g['id']: g['name'] for g in data.get('genres', [])}
    except: id_map = {}

    genre_str = ""
    if isinstance(genres, list) and len(genres) > 0:
        if isinstance(genres[0], dict):
            names = [g.get('name', '') for g in genres]
            genre_str = ", ".join(names)
        elif isinstance(genres[0], int):
            names = [id_map.get(g_id, str(g_id)) for g_id in genres]
            genre_str = ", ".join(names)
    else:
        genre_str = str(genres)

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

def get_popular_by_genre(genre_id):
    url = f"https://api.themoviedb.org/3/discover/movie?api_key={TMDB_API_KEY}&with_genres={genre_id}&sort_by=popularity.desc&vote_count.gte=500"
    return requests.get(url).json().get('results', [])[:12]

def search_tmdb(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    return requests.get(url).json().get('results', [])

def get_recommendations(watched_ids, media_type="movie", selected_genre_ids=None, page=1):
    endpoint = "tv" if media_type == "TV Shows" else "movie"
    base_url = f"https://api.themoviedb.org/3/discover/{endpoint}?api_key={TMDB_API_KEY}&language=en-US&sort_by=popularity.desc&vote_count.gte=200&page={page}"
    if selected_genre_ids:
        g_str = ",".join([str(g) for g in selected_genre_ids])
        base_url += f"&with_genres={g_str}"
    data = requests.get(base_url).json().get('results', [])
    if watched_ids:
        data = [m for m in data if str(m['id']) not in watched_ids]
    return data

# --- HTML CARD RENDERER (REWRITTEN) ---
def render_movie_card_html(poster_path, tmdb_score, user_score=None):
    """Generates the HTML for the image with overlaid ratings"""
    
    # 1. Colors
    tmdb_color = "#21d07a" # Green
    if tmdb_score < 70: tmdb_color = "#d2d531" # Yellow
    if tmdb_score < 40: tmdb_color = "#db2360" # Red
    
    poster_url = f"https://image.tmdb.org/t/p/w400{poster_path}" if poster_path else "https://via.placeholder.com/200x300"
    
    # 2. Build User Badge HTML (Right Side)
    user_badge_html = ""
    if user_score is not None and str(user_score).lower() != 'nan':
        user_badge_html = f"""
        <div class="rating-badge badge-right">
            <span class="badge-label">You</span>
            {int(float(user_score))}
        </div>
        """
    
    # 3. Build TMDB Badge HTML (Left Side)
    # Only show TMDB badge if score > 0
    tmdb_badge_html = ""
    if tmdb_score > 0:
        tmdb_badge_html = f"""
        <div class="rating-badge badge-left" style="border-color: {tmdb_color};">
            <span class="badge-label">TMDB</span>
            {tmdb_score}
        </div>
        """

    # 4. Final Clean HTML
    # Note: We use simple string concatenation to avoid f-string nesting errors
    html = f"""
    <div class="movie-card">
        <img src="{poster_url}" class="movie-img">
        {tmdb_badge_html}
        {user_badge_html}
    </div>
    """
    return html

# --- APP STARTUP ---
st.set_page_config(page_title="Cinematch", layout="wide", page_icon="🎬")

if 'page' not in st.session_state: st.session_state.page = "home"
if 'hidden_movies' not in st.session_state: st.session_state.hidden_movies = []
if 'view_movie_detail' not in st.session_state: st.session_state.view_movie_detail = None
if 'rec_page' not in st.session_state: st.session_state.rec_page = 1
if 'loaded_recs' not in st.session_state: st.session_state.loaded_recs = []

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

# --- MAIN PAGE: HOME ---
if nav_choice == "Home":
    
    # 1. SEARCH BAR
    search_query = st.text_input("🔍 Search...", placeholder="Movies, TV Shows...")

    # 2. DETAIL MODAL
    if st.session_state.view_movie_detail:
        m = st.session_state.view_movie_detail
        if st.button("← Back to Grid"):
            st.session_state.view_movie_detail = None
            st.rerun()
        
        c1, c2 = st.columns([1,3])
        with c1:
            st.image(f"https://image.tmdb.org/t/p/w400{m['poster_path']}", use_container_width=True)
        with c2:
            st.markdown(f"## {m['title']} ({m.get('release_date', '')[:4]})")
            st.write(m.get('overview'))
            st.divider()
            st.subheader("Rate & Log")
            user_rating = st.slider(f"{active_user}'s Rating", 1, 100, 70)
            if st.button("✅ Log to Database", type="primary"):
                log_media(m['title'], m['id'], m.get('genre_ids', []), {active_user: user_rating}, m['media_type'], m['poster_path'])
                st.success("Logged!")
                st.session_state.view_movie_detail = None
                time.sleep(1)
                st.rerun()

    # 3. MAIN GRID
    else:
        if search_query:
            st.subheader("Search Results")
            display_list = search_tmdb(search_query)
        else:
            # --- TOP CONTROLS ROW ---
            c_mode, c_type, c_sort, c_genre = st.columns([1.5, 1.5, 1.5, 3])
            
            with c_mode:
                view_mode = st.selectbox("View", ["Recommendations", "Rewatch"], label_visibility="collapsed")
            with c_type:
                media_type = st.selectbox("Type", ["Movies", "TV Shows"], label_visibility="collapsed")
            
            # --- SORTING LOGIC ---
            sort_options = []
            if view_mode == "Recommendations":
                sort_options = ["Popularity", "Highest Rated", "Newest"]
            else:
                sort_options = ["Date Watched", "Highest Rated"]
                
            with c_sort:
                sort_by = st.selectbox("Sort", sort_options, label_visibility="collapsed")

            with c_genre:
                g_map = get_tmdb_genres()
                sel_genres = st.multiselect("Genre", list(g_map.keys()), placeholder="All Genres", label_visibility="collapsed")
                sel_genre_ids = [g_map[name] for name in sel_genres]

            history = get_watched_history()
            
            # --- DATA FETCHING: REWATCH ---
            if view_mode == "Rewatch":
                if not history.empty:
                    my_history = history[history['User'] == active_user].copy()
                    display_list = []
                    
                    for _, row in my_history.iterrows():
                        if sel_genres and not any(g in row['Genres'] for g in sel_genres):
                            continue
                        
                        display_list.append({
                            "id": row['Movie_ID'],
                            "title": row['Title'],
                            "poster_path": row['Poster'],
                            "vote_average": 0, # TMDB score not stored in history, default to 0
                            "user_rating": float(row['Rating']),
                            "release_date": row['Date'], 
                            "media_type": row['Type']
                        })
                    
                    # Apply Sorting (Rewatch)
                    if sort_by == "Highest Rated":
                        display_list.sort(key=lambda x: x['user_rating'], reverse=True)
                    else: # Date Watched
                        display_list.sort(key=lambda x: x['release_date'], reverse=True)
                        
                else:
                    st.info("No history yet.")
                    display_list = []

            # --- DATA FETCHING: RECOMMENDATIONS ---
            else:
                watched_ids = history['Movie_ID'].astype(str).tolist() if not history.empty else []
                
                # Check Filters for Pagination Reset
                curr_filters = (media_type, tuple(sel_genre_ids), sort_by)
                if 'last_filters' not in st.session_state: st.session_state.last_filters = None
                
                if st.session_state.last_filters != curr_filters:
                    st.session_state.loaded_recs = []
                    st.session_state.rec_page = 1
                    st.session_state.last_filters = curr_filters
                
                if not st.session_state.loaded_recs:
                    new_data = get_recommendations(watched_ids, media_type, sel_genre_ids, page=1)
                    st.session_state.loaded_recs.extend(new_data)
                
                # Apply Sorting (Recs) - Note: API gives Popularity by default
                # We sort the current batch in memory for specific sorts
                raw_list = [m for m in st.session_state.loaded_recs if m['id'] not in st.session_state.hidden_movies]
                
                if sort_by == "Highest Rated":
                    display_list = sorted(raw_list, key=lambda x: x.get('vote_average', 0), reverse=True)
                elif sort_by == "Newest":
                    display_list = sorted(raw_list, key=lambda x: x.get('release_date', '0000'), reverse=True)
                else: # Popularity (Default order from API)
                    display_list = raw_list

        # --- GRID RENDERER ---
        GRID_COLS = 6
        for i in range(0, len(display_list), GRID_COLS):
            cols = st.columns(GRID_COLS)
            batch = display_list[i:i+GRID_COLS]
            for idx, item in enumerate(batch):
                with cols[idx]:
                    title = item.get('title', item.get('name'))
                    date = item.get('release_date', item.get('first_air_date', 'N/A'))[:4]
                    tmdb_score = int(item.get('vote_average', 0) * 10)
                    user_score = item.get('user_rating', None)
                    m_type = item.get('media_type', 'movie')
                    
                    # 1. HTML CARD
                    st.markdown(render_movie_card_html(item.get('poster_path'), tmdb_score, user_score), unsafe_allow_html=True)
                    
                    # 2. TITLE
                    if len(title) > 18: d_title = title[:16] + ".."
                    else: d_title = title
                    st.markdown(f"**{d_title}** <span style='color:gray; font-size:0.7em'>({date})</span>", unsafe_allow_html=True)
                    
                    # 3. COMPACT BUTTONS
                    b1, b2, b3 = st.columns(3, gap="small")
                    with b1:
                        if st.button("ℹ️", key=f"d_{item['id']}", help="Details"):
                            item['title'] = title
                            item['media_type'] = m_type
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b2:
                        if st.button("✅", key=f"w_{item['id']}", help="Log"):
                            item['title'] = title
                            item['media_type'] = m_type
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b3:
                        if st.button("🚫", key=f"h_{item['id']}", help="Hide"):
                            st.session_state.hidden_movies.append(item['id'])
                            st.rerun()

        if not search_query and view_mode == "Recommendations":
            st.write("")
            if st.button("Load More..."):
                st.session_state.rec_page += 1
                new_data = get_recommendations([], media_type, sel_genre_ids, page=st.session_state.rec_page)
                st.session_state.loaded_recs.extend(new_data)
                st.rerun()

elif nav_choice == "Profile":
    st.header(f"Profile: {active_user}")
    history = get_watched_history()
    if not history.empty:
        user_history = history[history['User'] == active_user]
        st.dataframe(user_history)
