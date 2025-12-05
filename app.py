import streamlit as st
import pandas as pd
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime

# --- CONFIGURATION ---
TMDB_API_KEY = st.secrets["tmdb_api_key"]
SHEET_ID = st.secrets["sheet_id"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- HTML STYLES (For the Rating Rings & Badges) ---
def render_rating_ring(score, label="Score"):
    """Creates a TMDB-style colored ring"""
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
    """Generic fetcher"""
    try:
        service = get_google_sheet_client()
        result = service.values().get(spreadsheetId=SHEET_ID, range=range_name).execute()
        rows = result.get('values', [])
        return rows
    except Exception as e:
        return []

def get_users():
    """Fetch list of users from Tab 1"""
    rows = get_data("Users!A:B")
    if not rows or len(rows) < 2: return [] # No header or no data
    return [row[1] for row in rows[1:]] # Return names (Column B)

def add_user(name, favorite_genres, seed_movies):
    """Add a new user to the sheet"""
    service = get_google_sheet_client()
    # 1. Get next ID (simple count)
    current_users = get_users()
    new_id = len(current_users) + 1
    
    # 2. Prepare Row
    # Format: ID | Name | Genres | Seed_Movies (JSON-like string)
    row = [[new_id, name, ", ".join(favorite_genres), str(seed_movies)]]
    
    # 3. Append
    service.values().append(
        spreadsheetId=SHEET_ID, range="Users!A:D",
        valueInputOption="USER_ENTERED", body={'values': row}
    ).execute()
    st.cache_data.clear() # Clear cache so new user appears immediately

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

def get_watched_history():
    rows = get_data("Activity_Log!A:H")
    if len(rows) < 2: return pd.DataFrame()
    return pd.DataFrame(rows[1:], columns=["Date", "Title", "Movie_ID", "Genres", "User", "Rating", "Type", "Poster"])

def search_tmdb(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    return requests.get(url).json().get('results', [])

def get_tmdb_genres():
    url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=en-US"
    data = requests.get(url).json()
    return {g['name']: g['id'] for g in data.get('genres', [])}

# --- PAGE CONFIG ---
st.set_page_config(page_title="Cinematch", layout="wide", page_icon="🎬")

# --- APP FLOW CONTROL ---

# 1. Load Users
existing_users = get_users()

# 2. Check State: Are we onboarding?
if 'onboarding' not in st.session_state:
    st.session_state['onboarding'] = False

# IF NO USERS EXIST -> FORCE ONBOARDING
if not existing_users:
    st.session_state['onboarding'] = True

# UI: SIDEBAR
st.sidebar.title("🎬 Cinematch")

# If we have users, show selector
selected_users = []
if existing_users and not st.session_state['onboarding']:
    st.sidebar.markdown("### 👥 Who is watching?")
    # Add "Create New" to the list options
    options = existing_users + ["➕ Create New Profile"]
    selection = st.sidebar.multiselect("Select Profile(s)", options, default=[existing_users[0]])
    
    if "➕ Create New Profile" in selection:
        st.session_state['onboarding'] = True
        st.rerun()
    else:
        selected_users = selection

# --- VIEW: ONBOARDING / CREATE USER ---
if st.session_state['onboarding']:
    st.header("👋 Welcome to Cinematch")
    st.write("Let's create a profile to get better recommendations.")
    
    with st.form("new_user_form"):
        new_name = st.text_input("What is your name?")
        
        # Genre Selection
        genre_map = get_tmdb_genres()
        selected_genres = st.multiselect("Select 3 Genres you love", list(genre_map.keys()))
        
        # Seed Movies
        st.write("---")
        st.write("Pick 3 favorite movies to start your engine:")
        seed1 = st.text_input("Favorite Movie #1")
        seed2 = st.text_input("Favorite Movie #2")
        seed3 = st.text_input("Favorite Movie #3")
        
        submitted = st.form_submit_button("Create Profile")
        
        if submitted:
            if new_name and len(selected_genres) > 0:
                # In a real app, we'd search TMDB for the seed IDs here
                # For now, we just save the text to get you started
                seeds = [seed1, seed2, seed3]
                add_user(new_name, selected_genres, seeds)
                st.success(f"Profile created for {new_name}!")
                st.session_state['onboarding'] = False
                st.rerun()
            else:
                st.error("Please enter a name and at least one genre.")

# --- VIEW: MAIN APP ---
elif selected_users:
    
    # FETCH DATA ONCE
    history_df = get_watched_history()
    
    # TABS
    tab1, tab2 = st.tabs(["🏠 Discover & Stats", "🔎 Search & Log"])

    # --- TAB 1: DISCOVER & STATS ---
    with tab1:
        # --- SECTION: STATS CARD ---
        st.markdown("### 📊 Quick Stats")
        if not history_df.empty:
            # Filter history for selected users
            user_history = history_df[history_df['User'].isin(selected_users)]
            
            if not user_history.empty:
                s_col1, s_col2, s_col3 = st.columns(3)
                s_col1.metric("Movies Watched", len(user_history))
                
                # Convert ratings to numbers
                user_history['Rating'] = pd.to_numeric(user_history['Rating'], errors='coerce')
                avg_rating = user_history['Rating'].mean()
                s_col2.metric("Avg Rating", f"{int(avg_rating)}%")
                
                # Top Genre
                # (Simple string split for demo)
                all_genres =  ", ".join(user_history['Genres'].astype(str)).split(", ")
                if all_genres:
                    top_genre = max(set(all_genres), key=all_genres.count)
                    s_col3.metric("Top Genre", top_genre)
            else:
                st.info("No stats for this user combination yet.")
        else:
            st.info("Log your first movie to see stats!")
            
        st.divider()
        
        # --- SECTION: RECOMMENDATIONS ---
        st.header(f"Top Picks for: {', '.join(selected_users)}")
        
        # (Recommendation logic placeholder - assumes you have your previous logic here)
        # Displaying mock data to show the VISUAL style you asked for
        
        st.subheader("🆕 Fresh Finds (You haven't seen)")
        
        # Example of how to render the new card style
        # In real usage, you loop through `get_recommendations()` dataframe
        
        # MOCK LOOP
        cols = st.columns(4)
        mock_movies = [
            {"title": "Zootopia 2", "score": 77, "poster": "/7dFZJ2ZJJdcmkp05B9NWlqTJ5tq.jpg"},
            {"title": "Tron: Ares", "score": 65, "poster": "/mKPBd4Q4mSM9tJ6j8GfH7jV7tV.jpg"}
        ]
        
        for idx, movie in enumerate(mock_movies):
            with cols[idx]:
                if idx < 2: # Just showing 2 cols for the demo
                    st.image(f"https://image.tmdb.org/t/p/w500{movie['poster']}", use_container_width=True)
                    st.write(f"**{movie['title']}**")
                    # Render the HTML Ring
                    st.markdown(render_rating_ring(movie['score'], "TMDB"), unsafe_allow_html=True)


    # --- TAB 2: SEARCH & LOG ---
    with tab2:
        st.header("Search & Log")
        query = st.text_input("Search Title...", placeholder="e.g. The Hobbit")
        
        if query:
            results = search_tmdb(query)
            
            # GET IDs of movies user has ALREADY watched
            watched_ids = []
            if not history_df.empty:
                watched_ids = history_df['Movie_ID'].astype(str).tolist()

            for res in results:
                if res.get('media_type') not in ['movie', 'tv']: continue
                
                # Card Container
                with st.container():
                    st.write("---")
                    c1, c2 = st.columns([1, 4])
                    
                    # COLUMN 1: IMAGE
                    with c1:
                        poster_url = f"https://image.tmdb.org/t/p/w200{res.get('poster_path')}" if res.get('poster_path') else "https://via.placeholder.com/150"
                        st.image(poster_url)
                    
                    # COLUMN 2: DETAILS
                    with c2:
                        # Title Area
                        title_str = f"**{res.get('title', res.get('name'))}** ({res.get('release_date', res.get('first_air_date', ''))[:4]})"
                        st.markdown(f"### {title_str}")
                        
                        # Watched Badge Check
                        is_watched = str(res['id']) in watched_ids
                        tmdb_score = int(res.get('vote_average', 0) * 10) # Convert 7.4 to 74
                        
                        # Render Badges (Row of HTML)
                        badges_html = "<div style='display:flex; align-items:center; margin-bottom:10px;'>"
                        badges_html += render_rating_ring(tmdb_score, "TMDB Score")
                        if is_watched:
                            badges_html += render_watched_badge()
                        badges_html += "</div>"
                        
                        st.markdown(badges_html, unsafe_allow_html=True)
                        
                        st.write(res.get('overview', 'No overview available.'))
                        
                        # LOGGING EXPANDER
                        with st.expander("Rate & Log"):
                            user_ratings = {}
                            for u in selected_users:
                                # 1-100 Slider
                                user_ratings[u] = st.slider(f"{u}'s Rating", 1, 100, 70, key=f"{res['id']}_{u}")
                            
                            if st.button("LOG THIS", key=f"btn_{res['id']}"):
                                log_media(
                                    res.get('title', res.get('name')), 
                                    res['id'], 
                                    res.get('genre_ids', []),
                                    user_ratings, 
                                    res['media_type'],
                                    res.get('poster_path')
                                )
                                st.balloons()
                                st.success("Saved to Database!")
                                st.rerun()

else:
    # Fallback if somehow no users and logic fails
    st.warning("Please create a profile.")
