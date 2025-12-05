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

# --- ADVANCED CSS (The "Overlay" Magic) ---
st.markdown("""
<style>
    /* Card Container */
    .movie-card {
        position: relative;
        border-radius: 10px;
        overflow: hidden;
        transition: transform 0.2s;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        margin-bottom: 8px;
    }
    .movie-card:hover {
        transform: scale(1.02);
    }
    
    /* The Poster Image */
    .movie-img {
        width: 100%;
        display: block;
        border-radius: 10px;
    }

    /* Rating Badge Container (Bottom Left overlap) */
    .rating-container {
        position: absolute;
        bottom: 5px;
        left: 5px;
        display: flex;
        gap: 5px;
    }

    /* The Ring Itself */
    .rating-ring {
        position: relative;
        width: 38px;
        height: 38px;
        background-color: #081c22;
        border-radius: 50%;
        display: flex;
        justify-content: center;
        align-items: center;
        border: 2px solid #21d07a; /* Default Green */
        box-shadow: 0 0 4px rgba(0,0,0,0.5);
    }
    
    .rating-text {
        color: white;
        font-family: 'Arial', sans-serif;
        font-weight: bold;
        font-size: 13px;
    }
    
    .rating-sub {
        font-size: 7px;
        vertical-align: top;
    }

    /* User Rating (Blue Ring) */
    .user-ring {
        border-color: #01b4e4 !important;
    }
    
    /* Action Buttons (Streamlit Overrides) */
    div[data-testid="stHorizontalBlock"] button {
        padding: 0px 10px;
        font-size: 1.2rem;
        border: none;
        background: transparent;
    }
    div[data-testid="stHorizontalBlock"] button:hover {
        background: rgba(255,255,255,0.1);
        color: #E50914;
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

# --- HTML CARD RENDERER ---
def render_movie_card_html(poster_path, tmdb_score, user_score=None):
    """Generates the HTML for the image with overlaid ratings"""
    
    # Logic for TMDB Color
    tmdb_color = "#21d07a" # Green
    if tmdb_score < 70: tmdb_color = "#d2d531" # Yellow
    if tmdb_score < 40: tmdb_color = "#db2360" # Red
    
    poster_url = f"https://image.tmdb.org/t/p/w400{poster_path}" if poster_path else "https://via.placeholder.com/200x300"
    
    html = f"""
    <div class="movie-card">
        <img src="{poster_url}" class="movie-img">
        <div class="rating-container">
            <div class="rating-ring" style="border-color: {tmdb_color};" title="TMDB Rating">
                <span class="rating-text">{tmdb_score}<span class="rating-sub">%</span></span>
            </div>
    """
    
    # Add User Rating Ring if it exists
    if user_score:
        html += f"""
            <div class="rating-ring user-ring" title="Your Rating">
                <span class="rating-text">{int(user_score)}<span class="rating-sub">%</span></span>
            </div>
        """
        
    html += """
        </div>
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

# --- ONBOARDING (Simplified for this snippet, same as before) ---
existing_users = get_users()
if not existing_users:
    # (Keeping your existing onboarding logic here effectively)
    st.warning("Please create a profile using the previous code logic (omitted here to fit the UI update).")
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

    # 2. DETAIL MODAL (Replaces Grid)
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
            # --- SLICERS & FILTERS ---
            c_slice, c_filter = st.columns([2, 1])
            with c_slice:
                view_mode = st.radio("View Mode", ["Recommendations", "Rewatch"], horizontal=True, label_visibility="collapsed")
            with c_filter:
                media_type = st.radio("Type", ["Movies", "TV Shows"], horizontal=True, label_visibility="collapsed")

            history = get_watched_history()
            
            # --- LOGIC: REWATCH ---
            if view_mode == "Rewatch":
                if not history.empty:
                    # Filter by User
                    my_history = history[history['User'] == active_user]
                    # Convert to list of dicts for the renderer
                    display_list = []
                    for _, row in my_history.iterrows():
                        display_list.append({
                            "id": row['Movie_ID'],
                            "title": row['Title'],
                            "poster_path": row['Poster'],
                            "vote_average": 0, # We don't have TMDB score stored in log, maybe skip
                            "user_rating": row['Rating'],
                            "release_date": row['Date'], # Using watch date as placeholder
                            "media_type": row['Type']
                        })
                    display_list.reverse() # Newest first
                else:
                    st.info("No history yet.")
                    display_list = []

            # --- LOGIC: RECOMMENDATIONS ---
            else:
                watched_ids = history['Movie_ID'].astype(str).tolist() if not history.empty else []
                # Check Filters
                if 'last_filters' not in st.session_state: st.session_state.last_filters = None
                curr_filters = (media_type)
                if st.session_state.last_filters != curr_filters:
                    st.session_state.loaded_recs = []
                    st.session_state.rec_page = 1
                    st.session_state.last_filters = curr_filters
                
                if not st.session_state.loaded_recs:
                    new_data = get_recommendations(watched_ids, media_type, page=1)
                    st.session_state.loaded_recs.extend(new_data)
                
                # Filter out Hidden
                display_list = [m for m in st.session_state.loaded_recs if m['id'] not in st.session_state.hidden_movies]

        # --- GRID RENDERER ---
        GRID_COLS = 6
        for i in range(0, len(display_list), GRID_COLS):
            cols = st.columns(GRID_COLS)
            batch = display_list[i:i+GRID_COLS]
            for idx, item in enumerate(batch):
                with cols[idx]:
                    # DATA PREP
                    title = item.get('title', item.get('name'))
                    date = item.get('release_date', item.get('first_air_date', 'N/A'))[:4]
                    tmdb_score = int(item.get('vote_average', 0) * 10)
                    user_score = item.get('user_rating', None)
                    m_type = item.get('media_type', 'movie')
                    
                    # 1. HTML CARD (Image + Overlays)
                    st.markdown(render_movie_card_html(item.get('poster_path'), tmdb_score, user_score), unsafe_allow_html=True)
                    
                    # 2. TITLE
                    if len(title) > 20: d_title = title[:18] + "..."
                    else: d_title = title
                    st.markdown(f"**{d_title}** <span style='color:gray; font-size:0.8em'>({date})</span>", unsafe_allow_html=True)
                    
                    # 3. BUTTONS (Action Bar)
                    b_col1, b_col2, b_col3 = st.columns(3)
                    
                    # Details
                    with b_col1:
                        if st.button("ℹ️", key=f"d_{item['id']}", help="Details"):
                            item['title'] = title
                            item['media_type'] = m_type
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    
                    # Watch (Log)
                    with b_col2:
                        if st.button("✅", key=f"w_{item['id']}", help="Log as Watched"):
                            item['title'] = title
                            item['media_type'] = m_type
                            st.session_state.view_movie_detail = item
                            st.rerun()
                            
                    # Hide
                    with b_col3:
                        if st.button("🚫", key=f"h_{item['id']}", help="Not Interested"):
                            st.session_state.hidden_movies.append(item['id'])
                            st.rerun()

        # LOAD MORE
        if not search_query and view_mode == "Recommendations":
            st.write("")
            if st.button("Load More..."):
                st.session_state.rec_page += 1
                new_data = get_recommendations([], media_type, page=st.session_state.rec_page)
                st.session_state.loaded_recs.extend(new_data)
                st.rerun()

elif nav_choice == "Profile":
    st.header(f"Profile: {active_user}")
    history = get_watched_history()
    if not history.empty:
        user_history = history[history['User'] == active_user]
        st.dataframe(user_history)
