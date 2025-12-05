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

# --- STYLING & HTML COMPONENTS ---
def render_header():
    """Custom Logo Header"""
    return """
    <div style="display: flex; align-items: center; margin-bottom: 20px;">
        <span style="font-size: 2.5rem;">🎬</span>
        <span style="font-size: 2rem; font-weight: 800; color: #E50914; letter-spacing: -1px; margin-left: 10px;">Cine</span>
        <span style="font-size: 2rem; font-weight: 800; color: #ffffff; letter-spacing: -1px;">Match</span>
    </div>
    """

def render_rating_ring(score, label="Score"):
    """TMDB-style colored ring"""
    if not score: return ""
    score = int(score)
    if score >= 70: color = "#21d07a" # Green
    elif score >= 40: color = "#d2d531" # Yellow
    else: color = "#db2360" # Red
    
    return f"""
    <div style="display: flex; align-items: center; margin-right: 10px;">
        <div style="position: relative; width: 35px; height: 35px; border-radius: 50%; background: #081c22; display: flex; align-items: center; justify-content: center; border: 3px solid {color};">
            <span style="color: white; font-weight: bold; font-size: 11px;">{score}<span style="font-size:7px;">%</span></span>
        </div>
    </div>
    """

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
    # 1. Fetch Genre Map once
    try:
        url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=en-US"
        data = requests.get(url).json()
        id_map = {g['id']: g['name'] for g in data.get('genres', [])}
    except: id_map = {}

    genre_str = ""
    # Check if genres is valid
    if isinstance(genres, list) and len(genres) > 0:
        # Check first item to see if it's Dict or Int
        first_item = genres[0]
        
        if isinstance(first_item, dict):
            # Format: [{'id': 28, 'name': 'Action'}]
            names = [g.get('name', '') for g in genres]
            genre_str = ", ".join(names)
            
        elif isinstance(first_item, int):
            # Format: [28, 12]
            names = [id_map.get(g_id, str(g_id)) for g_id in genres]
            genre_str = ", ".join(names)
            
    else:
        genre_str = str(genres)
    # -------------------------

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
    # Base URL changes based on media type
    endpoint = "tv" if media_type == "TV Shows" else "movie"
    
    base_url = f"https://api.themoviedb.org/3/discover/{endpoint}?api_key={TMDB_API_KEY}&language=en-US&sort_by=popularity.desc&vote_count.gte=200&page={page}"
    
    # Add Genre Filter
    if selected_genre_ids:
        # Join IDs with pipe (OR logic) or comma (AND logic). Let's use Comma (AND).
        g_str = ",".join([str(g) for g in selected_genre_ids])
        base_url += f"&with_genres={g_str}"

    data = requests.get(base_url).json().get('results', [])
    
    # Filter out watched
    if watched_ids:
        data = [m for m in data if str(m['id']) not in watched_ids]
    
    return data # Returns List of Dicts

# --- APP STARTUP ---
st.set_page_config(page_title="Cinematch", layout="wide", page_icon="🎬")

# Init Session State
if 'page' not in st.session_state: st.session_state.page = "home"
if 'onboarding_step' not in st.session_state: st.session_state.onboarding_step = 0
if 'new_user_data' not in st.session_state: st.session_state.new_user_data = {"name": "", "genres": [], "seeds": []}
if 'temp_genre_selection' not in st.session_state: st.session_state.temp_genre_selection = None
if 'view_movie_detail' not in st.session_state: st.session_state.view_movie_detail = None
if 'trigger_onboarding' not in st.session_state: st.session_state.trigger_onboarding = False
if 'rec_page' not in st.session_state: st.session_state.rec_page = 1
if 'loaded_recs' not in st.session_state: st.session_state.loaded_recs = []

# CSS Hacks for smaller tiles & nicer font
st.markdown("""
<style>
    div[data-testid="stImage"] img { border-radius: 10px; transition: transform 0.2s; }
    div[data-testid="stImage"] img:hover { transform: scale(1.05); }
    h1, h2, h3 { font-family: 'Helvetica Neue', sans-serif; }
</style>
""", unsafe_allow_html=True)

existing_users = get_users()

# --- ONBOARDING WIZARD (Same as before) ---
if not existing_users or st.session_state.trigger_onboarding:
    st.empty()
    step = st.session_state.onboarding_step
    user_data = st.session_state.new_user_data
    st.markdown("<h1 style='text-align: center;'>🍿 Welcome to Cinematch</h1>", unsafe_allow_html=True)
    st.divider()

    if step == 0:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            name = st.text_input("First, what should we call you?")
            if st.button("Start Setup"):
                if name:
                    st.session_state.new_user_data["name"] = name
                    st.session_state.onboarding_step = 1
                    st.rerun()
    elif step in [1, 3, 5]:
        c1, c2, c3 = st.columns([1,2,1])
        with c2:
            st.subheader(f"Step {(step//2)+1}/3: Pick a Genre")
            genre_map = get_tmdb_genres()
            avail = [g for g in genre_map.keys() if g not in user_data["genres"]]
            sel = st.selectbox("I'm in the mood for...", avail)
            if st.button(f"Show {sel}"):
                st.session_state.temp_genre_selection = (sel, genre_map[sel])
                st.session_state.onboarding_step += 1
                st.rerun()
    elif step in [2, 4, 6]:
        g_name, g_id = st.session_state.temp_genre_selection
        st.subheader(f"Select favorites: {g_name}")
        movies = get_popular_by_genre(g_id)
        sel_rnd = []
        cols = st.columns(6) # Smaller tiles in onboarding too
        with st.form("movie_select"):
            for idx, m in enumerate(movies):
                with cols[idx % 6]:
                    poster = f"https://image.tmdb.org/t/p/w200{m['poster_path']}"
                    st.image(poster, use_container_width=True)
                    if st.checkbox(m['title'], key=f"ob_{m['id']}"): sel_rnd.append(m['title'])
            st.write("---")
            if st.form_submit_button("Next"):
                if len(sel_rnd) >= 1:
                    st.session_state.new_user_data["genres"].append(g_name)
                    st.session_state.new_user_data["seeds"].extend(sel_rnd)
                    if step == 6:
                        add_user(user_data["name"], user_data["genres"], user_data["seeds"])
                        st.session_state.trigger_onboarding = False
                        st.session_state.onboarding_step = 0
                        st.rerun()
                    else:
                        st.session_state.onboarding_step += 1
                        st.rerun()

# --- MAIN APP ---
else:
    # --- SIDEBAR ---
    with st.sidebar:
        st.markdown(render_header(), unsafe_allow_html=True)
        
        # User Selector
        current_users = existing_users + ["➕ Add Profile"]
        active_user = st.selectbox("Watching Now:", current_users)
        if active_user == "➕ Add Profile":
            st.session_state.trigger_onboarding = True
            st.rerun()
        
        st.markdown("---")
        
        # PRO NAVIGATION
        nav_choice = option_menu(
            "Menu",
            ["Home", "Profile", "Settings"],
            icons=['house-fill', 'person-circle', 'gear-fill'],
            menu_icon="cast",
            default_index=0,
            styles={
                "nav-link-selected": {"background-color": "#E50914"},
            }
        )

    # --- PAGE: HOME ---
    if nav_choice == "Home":
        # SEARCH
        search_query = st.text_input("🔍 Search...", placeholder="Movies, TV Shows...")
        
        # DETAIL VIEW
        if st.session_state.view_movie_detail:
            m = st.session_state.view_movie_detail
            if st.button("← Back"):
                st.session_state.view_movie_detail = None
                st.rerun()
            
            st.markdown(f"## {m['title']}")
            c1, c2 = st.columns([1,3])
            with c1:
                st.image(f"https://image.tmdb.org/t/p/w400{m['poster_path']}", use_container_width=True)
            with c2:
                st.write(m.get('overview'))
                score = int(m.get('vote_average', 0) * 10)
                st.markdown(render_rating_ring(score, "TMDB Score"), unsafe_allow_html=True)
                st.divider()
                st.subheader("Rate & Log")
                user_rating = st.slider(f"{active_user}'s Rating", 1, 100, 70)
                if st.button("✅ Log to Database"):
                    log_media(m['title'], m['id'], m.get('genre_ids', []),
                              {active_user: user_rating}, m['media_type'], m['poster_path'])
                    st.success("Logged!")
                    st.session_state.view_movie_detail = None
                    time.sleep(1)
                    st.rerun()

        # MAIN GRID
        else:
            if search_query:
                st.subheader("Search Results")
                results = search_tmdb(search_query)
                display_list = results
            else:
                # --- FILTERS ---
                c_f1, c_f2 = st.columns([3, 1])
                with c_f1:
                    # Genre Filter
                    g_map = get_tmdb_genres()
                    sel_genres = st.multiselect("Filter Genres", list(g_map.keys()))
                    sel_genre_ids = [g_map[name] for name in sel_genres]
                with c_f2:
                    # Type Filter
                    media_type = st.radio("Type", ["Movies", "TV Shows"], horizontal=True, label_visibility="collapsed")
                
                # RECS LOGIC (Pagination)
                history = get_watched_history()
                watched_ids = history['Movie_ID'].astype(str).tolist() if not history.empty else []
                
                # Fetch Logic
                # If filters changed, reset pagination
                current_filters = (media_type, tuple(sel_genre_ids))
                if 'last_filters' not in st.session_state: st.session_state.last_filters = current_filters
                
                if st.session_state.last_filters != current_filters:
                    st.session_state.loaded_recs = [] # Clear cache
                    st.session_state.rec_page = 1
                    st.session_state.last_filters = current_filters
                
                # If cache empty, fetch page 1
                if not st.session_state.loaded_recs:
                    new_data = get_recommendations(watched_ids, media_type, sel_genre_ids, page=1)
                    st.session_state.loaded_recs.extend(new_data)

                display_list = st.session_state.loaded_recs

            # RENDER GRID (6 Columns)
            GRID_COLS = 6
            for i in range(0, len(display_list), GRID_COLS):
                cols = st.columns(GRID_COLS)
                batch = display_list[i:i+GRID_COLS]
                for idx, item in enumerate(batch):
                    with cols[idx]:
                        title = item.get('title', item.get('name'))
                        poster = item.get('poster_path')
                        m_id = item.get('id')
                        m_type = item.get('media_type', 'movie') # Search gives specific, discover implies generic
                        if not search_query: m_type = "movie" if media_type == "Movies" else "tv"

                        if poster:
                            st.image(f"https://image.tmdb.org/t/p/w200{poster}", use_container_width=True)
                        else:
                            st.markdown("⬛ No Image")
                        
                        # Truncate long titles
                        if len(title) > 20: display_title = title[:18] + "..."
                        else: display_title = title
                        
                        st.caption(f"**{display_title}**")
                        
                        if st.button("Details", key=f"btn_{m_id}"):
                            item['title'] = title
                            item['media_type'] = m_type
                            st.session_state.view_movie_detail = item
                            st.rerun()
            
            # LOAD MORE BUTTON (Only for Recs)
            if not search_query:
                st.write("")
                _, c_load, _ = st.columns([2,1,2])
                with c_load:
                    if st.button("Load More Movies..."):
                        st.session_state.rec_page += 1
                        new_data = get_recommendations(watched_ids, media_type, sel_genre_ids, page=st.session_state.rec_page)
                        st.session_state.loaded_recs.extend(new_data)
                        st.rerun()

    # --- PAGE: PROFILE ---
    elif nav_choice == "Profile":
        st.header(f"Profile: {active_user}")
        history = get_watched_history()
        if not history.empty:
            user_history = history[history['User'] == active_user]
            st.dataframe(user_history)
        else: st.info("No data available.")

    # --- PAGE: SETTINGS ---
    elif nav_choice == "Settings":
        st.header("Settings")
        st.write("Settings coming soon.")
