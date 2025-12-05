import streamlit as st
import pandas as pd
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime
import time

# --- CONFIGURATION ---
TMDB_API_KEY = st.secrets["tmdb_api_key"]
SHEET_ID = st.secrets["sheet_id"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- STYLING & HTML COMPONENTS ---
def render_rating_ring(score, label="Score"):
    """TMDB-style colored ring"""
    if not score: return ""
    score = int(score)
    if score >= 70: color = "#21d07a" # Green
    elif score >= 40: color = "#d2d531" # Yellow
    else: color = "#db2360" # Red
    
    return f"""
    <div style="display: flex; align-items: center; margin-right: 15px;">
        <div style="position: relative; width: 40px; height: 40px; border-radius: 50%; background: #081c22; display: flex; align-items: center; justify-content: center; border: 3px solid {color};">
            <span style="color: white; font-weight: bold; font-size: 14px;">{score}<span style="font-size:8px;">%</span></span>
        </div>
        <div style="margin-left: 8px; color: #fff; font-size: 0.8em; font-weight: bold;">{label}</div>
    </div>
    """

def render_watched_badge():
    return """
    <span style="background-color: #21d07a; color: #000; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.8em;">
        ✅ WATCHED
    </span>
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
    
    # Store seeds as simple string for now
    row = [[new_id, name, ", ".join(favorite_genres), str(seed_movies)]]
    
    service.values().append(
        spreadsheetId=SHEET_ID, range="Users!A:D",
        valueInputOption="USER_ENTERED", body={'values': row}
    ).execute()

def log_media(title, movie_id, genres, users_ratings, media_type, poster_path):
    service = get_google_sheet_client()
    timestamp = datetime.now().strftime("%Y-%m-%d")
    genre_str = ", ".join([g['name'] for g in genres]) if isinstance(genres, list) else str(genres)

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
    return requests.get(url).json().get('results', [])[:12] # Return top 12

def search_tmdb(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    return requests.get(url).json().get('results', [])

def get_recommendations(watched_ids, user_genres=None):
    # Simplified logic for demo (fetching popular)
    # In full version, use the seed/history logic we built before
    url = f"https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}&language=en-US&page=1"
    data = requests.get(url).json().get('results', [])
    
    # Filter out watched
    if watched_ids:
        data = [m for m in data if str(m['id']) not in watched_ids]
    
    return pd.DataFrame(data)

# --- APP STARTUP ---
st.set_page_config(page_title="Cinematch", layout="wide", page_icon="🎬")

# Session State Initialization
if 'page' not in st.session_state: st.session_state.page = "home"
if 'onboarding_step' not in st.session_state: st.session_state.onboarding_step = 0
if 'new_user_data' not in st.session_state: st.session_state.new_user_data = {"name": "", "genres": [], "seeds": []}
if 'temp_genre_selection' not in st.session_state: st.session_state.temp_genre_selection = None
if 'view_movie_detail' not in st.session_state: st.session_state.view_movie_detail = None

# Load Users
existing_users = get_users()

# --- ONBOARDING WIZARD ---
# Checks if we need to onboard (No users OR user clicked 'Create New')
if not existing_users or st.session_state.get('trigger_onboarding', False):
    st.empty() # Clear sidebar if possible
    
    step = st.session_state.onboarding_step
    user_data = st.session_state.new_user_data
    
    st.markdown("<h1 style='text-align: center;'>🍿 Welcome to Cinematch</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Let's build your taste profile.</p>", unsafe_allow_html=True)
    st.divider()

    # STEP 0: NAME
    if step == 0:
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            name = st.text_input("First, what should we call you?")
            if st.button("Start Setup"):
                if name:
                    st.session_state.new_user_data["name"] = name
                    st.session_state.onboarding_step = 1
                    st.rerun()

    # STEP 1, 3, 5: SELECT GENRE
    elif step in [1, 3, 5]:
        cycle_num = (step // 2) + 1 # 1, 2, or 3
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            st.subheader(f"Step {cycle_num}/3: Pick a Genre")
            genre_map = get_tmdb_genres()
            # Filter out already selected genres
            available_genres = [g for g in genre_map.keys() if g not in user_data["genres"]]
            selected_genre_name = st.selectbox("I'm in the mood for...", available_genres)
            
            if st.button(f"Show me {selected_genre_name} movies"):
                st.session_state.temp_genre_selection = (selected_genre_name, genre_map[selected_genre_name])
                st.session_state.onboarding_step += 1
                st.rerun()

    # STEP 2, 4, 6: SELECT MOVIES
    elif step in [2, 4, 6]:
        genre_name, genre_id = st.session_state.temp_genre_selection
        st.subheader(f"Select 3 favorites from: {genre_name}")
        
        movies = get_popular_by_genre(genre_id)
        
        # Grid Layout for selection
        selected_this_round = []
        cols = st.columns(4)
        
        # We use a form to capture checkboxes
        with st.form("movie_select_form"):
            for idx, m in enumerate(movies):
                col = cols[idx % 4]
                with col:
                    poster = f"https://image.tmdb.org/t/p/w200{m['poster_path']}"
                    st.image(poster, use_container_width=True)
                    if st.checkbox(m['title'], key=f"ob_{m['id']}"):
                        selected_this_round.append(m['title'])
            
            st.write("---")
            submit = st.form_submit_button("Next Step")
            
            if submit:
                if len(selected_this_round) >= 1: # Require at least 1, ideally 3
                    # Save Data
                    st.session_state.new_user_data["genres"].append(genre_name)
                    st.session_state.new_user_data["seeds"].extend(selected_this_round)
                    
                    # Advance
                    if step == 6: # Done
                        add_user(user_data["name"], user_data["genres"], user_data["seeds"])
                        st.session_state.trigger_onboarding = False
                        st.session_state.onboarding_step = 0
                        st.success("Profile Created!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.session_state.onboarding_step += 1
                        st.rerun()
                else:
                    st.error("Please select at least one movie.")

# --- MAIN APPLICATION (Post-Onboarding) ---
else:
    # SIDEBAR NAVIGATION
    st.sidebar.markdown("## 🎬 Cinematch")
    
    # User Selector
    current_users = existing_users + ["➕ Add Profile"]
    active_user = st.sidebar.selectbox("Watching Now:", current_users)
    
    if active_user == "➕ Add Profile":
        st.session_state.trigger_onboarding = True
        st.rerun()

    st.sidebar.markdown("---")
    
    # Navigation Menu
    nav_choice = st.sidebar.radio("Menu", ["🏠 Home", "👤 Profile", "⚙️ Settings"])
    
    # --- PAGE: HOME (Search + Recommendations) ---
    if nav_choice == "🏠 Home":
        
        # 1. SEARCH BAR (Integrated)
        search_query = st.text_input("🔍 Search movies or TV shows...", placeholder="Type 'The Matrix' or 'The Bear'...")
        
        # 2. DETAIL VIEW (If a movie is selected)
        if st.session_state.view_movie_detail:
            m = st.session_state.view_movie_detail
            if st.button("← Back to List"):
                st.session_state.view_movie_detail = None
                st.rerun()
                
            # Render Detail Card
            st.markdown(f"## {m['title']}")
            c1, c2 = st.columns([1,3])
            with c1:
                st.image(f"https://image.tmdb.org/t/p/w400{m['poster_path']}", use_container_width=True)
            with c2:
                st.markdown(f"**Released:** {m.get('release_date', 'N/A')}")
                st.write(m.get('overview'))
                
                # Badges
                score = int(m.get('vote_average', 0) * 10)
                st.markdown(render_rating_ring(score, "TMDB Score"), unsafe_allow_html=True)
                
                st.divider()
                st.subheader("Rate & Log")
                # Slider for Active User
                user_rating = st.slider(f"{active_user}'s Rating", 1, 100, 70)
                
                if st.button("✅ Log to Database"):
                    log_media(
                        m['title'], m['id'], m.get('genre_ids', []),
                        {active_user: user_rating}, m['media_type'], m['poster_path']
                    )
                    st.success("Logged!")
                    st.session_state.view_movie_detail = None # Close view
                    time.sleep(1)
                    st.rerun()

        # 3. MAIN GRID (Search Results OR Recommendations)
        else:
            if search_query:
                st.subheader(f"Results for '{search_query}'")
                results = search_tmdb(search_query)
            else:
                # Stats Header
                history = get_watched_history()
                user_count = len(history[history['User'] == active_user]) if not history.empty else 0
                st.markdown(f"#### 👋 Hi {active_user}, you've watched **{user_count}** movies.")
                
                st.subheader("Recommended for You")
                # Get Recs (excluding watched)
                watched_ids = history['Movie_ID'].astype(str).tolist() if not history.empty else []
                results_df = get_recommendations(watched_ids)
                results = results_df.to_dict('records')

            # Render Grid of Cards
            # We use batches of 4 columns
            for i in range(0, len(results), 4):
                cols = st.columns(4)
                batch = results[i:i+4]
                for idx, item in enumerate(batch):
                    with cols[idx]:
                        # Normalize keys (Search returns 'name' for TV, 'title' for movies)
                        title = item.get('title', item.get('name'))
                        poster = item.get('poster_path')
                        m_id = item.get('id')
                        media_type = item.get('media_type', 'movie')
                        
                        if poster:
                            st.image(f"https://image.tmdb.org/t/p/w300{poster}", use_container_width=True)
                        else:
                            st.markdown("⬛ No Image")
                        
                        st.markdown(f"**{title}**")
                        
                        # "Click to Log" Logic
                        # Streamlit buttons don't pass data well, so we use session state
                        if st.button("Log / Details", key=f"btn_{m_id}"):
                            # Standardize item structure for Detail View
                            item['title'] = title
                            item['media_type'] = media_type
                            st.session_state.view_movie_detail = item
                            st.rerun()

    # --- PAGE: PROFILE ---
    elif nav_choice == "👤 Profile":
        st.header(f"Profile: {active_user}")
        history = get_watched_history()
        if not history.empty:
            user_history = history[history['User'] == active_user]
            st.dataframe(user_history)
        else:
            st.info("No data available.")

    # --- PAGE: SETTINGS ---
    elif nav_choice == "⚙️ Settings":
        st.header("Settings")
        st.write("Coming soon: API Key management and Display Toggles.")
