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
        display: inline-block;
        width: 100%;
        margin-bottom: 5px;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s;
    }
    .movie-card:hover {
        transform: scale(1.02);
        z-index: 5;
    }
    
    /* Poster Image */
    .movie-img {
        width: 100%;
        display: block;
        border-radius: 8px;
    }

    /* Rating Badges - Force High Visibility */
    .rating-badge {
        position: absolute;
        bottom: 5px;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background-color: #081c22;
        border: 2px solid #21d07a;
        color: white;
        font-family: sans-serif;
        font-weight: bold;
        font-size: 10px;
        display: flex;
        justify-content: center;
        align-items: center;
        z-index: 10; /* Force on top */
        box-shadow: 0 2px 4px rgba(0,0,0,0.8);
    }
    
    /* Positions */
    .badge-left {
        left: 5px;
        border-color: #21d07a;
    }
    .badge-right {
        right: 5px;
        border-color: #01b4e4;
    }
    
    /* Labels inside badges */
    .badge-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        line-height: 0.9;
    }
    .tiny-label {
        font-size: 5px;
        text-transform: uppercase;
        opacity: 0.8;
    }
    
    /* Buttons */
    div[data-testid="column"] button {
        padding: 0px 5px !important;
        font-size: 12px !important;
        min-height: 0px !important;
        height: 28px !important;
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
    
    # --- ROBUST GENRE FIX ---
    genre_str = "Unknown"
    try:
        if isinstance(genres, list) and len(genres) > 0:
            # Check if dict (API data) or int (Internal ID)
            if isinstance(genres[0], dict):
                genre_str = ", ".join([g.get('name', '') for g in genres])
            elif isinstance(genres[0], int):
                # Fetch Map if needed
                url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=en-US"
                data = requests.get(url).json()
                id_map = {g['id']: g['name'] for g in data.get('genres', [])}
                genre_str = ", ".join([id_map.get(g, str(g)) for g in genres])
        else:
            genre_str = str(genres)
    except Exception as e:
        genre_str = "Error"
    # -----------------------

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

def search_tmdb(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    return requests.get(url).json().get('results', [])

# --- HTML GENERATOR ---
def render_card(poster_path, tmdb_score, user_score=None):
    poster_url = f"https://image.tmdb.org/t/p/w400{poster_path}" if poster_path else "https://via.placeholder.com/200x300"
    
    # 1. TMDB Badge Logic
    tmdb_html = ""
    if tmdb_score is not None:
        color = "#21d07a" # Green
        if tmdb_score < 70: color = "#d2d531" # Yellow
        if tmdb_score < 40: color = "#db2360" # Red
        
        tmdb_html = f"""
        <div class="rating-badge badge-left" style="border-color: {color};">
            <div class="badge-content">
                <span class="tiny-label">TMDB</span>
                {tmdb_score}
            </div>
        </div>
        """
    
    # 2. User Badge Logic
    user_html = ""
    if user_score is not None and str(user_score) != 'nan':
        user_html = f"""
        <div class="rating-badge badge-right">
            <div class="badge-content">
                <span class="tiny-label">YOU</span>
                {int(float(user_score))}
            </div>
        </div>
        """

    # 3. Final HTML
    return f"""
    <div class="movie-card">
        <img src="{poster_url}" class="movie-img">
        {tmdb_html}
        {user_html}
    </div>
    """

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
            st.markdown(f"## {m['title']}")
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
                    for _, row in my_hist.iterrows():
                        if sel_genres and not any(g in row['Genres'] for g in sel_genres): continue
                        display_list.append({
                            "id": row['Movie_ID'], "title": row['Title'], "poster_path": row['Poster'],
                            "vote_average": 0, "user_rating": float(row['Rating']), "media_type": row['Type'], "date": row['Date']
                        })
                    
                    if sort_by == "Rating": display_list.sort(key=lambda x: x['user_rating'], reverse=True)
                    else: display_list.sort(key=lambda x: x['date'], reverse=True)
                else:
                    st.info("No history yet.")
                    display_list = []

            # 2. RECS DATA
            else:
                watched_ids = history['Movie_ID'].astype(str).tolist() if not history.empty else []
                # Cache Logic
                curr_filters = (media_type, tuple(sel_ids), sort_by)
                if 'last_filters' not in st.session_state: st.session_state.last_filters = None
                if st.session_state.last_filters != curr_filters:
                    st.session_state.loaded_recs = []
                    st.session_state.rec_page = 1
                    st.session_state.last_filters = curr_filters
                
                if not st.session_state.loaded_recs:
                    new_data = get_recommendations(watched_ids, media_type, sel_ids, page=1)
                    st.session_state.loaded_recs.extend(new_data)
                
                raw = [m for m in st.session_state.loaded_recs if m['id'] not in st.session_state.hidden_movies]
                
                if sort_by == "Rating": display_list = sorted(raw, key=lambda x: x.get('vote_average', 0), reverse=True)
                elif sort_by == "Newest": display_list = sorted(raw, key=lambda x: x.get('release_date', '0000'), reverse=True)
                else: display_list = raw

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
                    
                    # HTML Card
                    st.markdown(render_card(poster, tmdb, user), unsafe_allow_html=True)
                    
                    # Text Title
                    short_title = (title[:16] + "..") if len(title) > 18 else title
                    st.markdown(f"**{short_title}**")

                    # Text Buttons
                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button("Info", key=f"d_{item['id']}"):
                            item['title'] = title
                            item['media_type'] = m_type
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b2:
                        if st.button("Log", key=f"l_{item['id']}"):
                            item['title'] = title
                            item['media_type'] = m_type
                            st.session_state.view_movie_detail = item
                            st.rerun()
                    with b3:
                        if st.button("Hide", key=f"h_{item['id']}"):
                            st.session_state.hidden_movies.append(item['id'])
                            st.rerun()

        if not search_query and view_mode == "Recommendations":
            st.write("")
            if st.button("Load More..."):
                st.session_state.rec_page += 1
                new_data = get_recommendations([], media_type, sel_ids, page=st.session_state.rec_page)
                st.session_state.loaded_recs.extend(new_data)
                st.rerun()

elif nav_choice == "Profile":
    st.header(f"Profile: {active_user}")
    history = get_watched_history()
    if not history.empty:
        user_history = history[history['User'] == active_user]
        st.dataframe(user_history)
