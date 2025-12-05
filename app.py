import streamlit as st
import pandas as pd
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime

# --- CONFIGURATION ---
# These will pull from the secrets you set up later
TMDB_API_KEY = st.secrets["tmdb_api_key"]
SHEET_ID = st.secrets["sheet_id"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- BACKEND FUNCTIONS ---

def get_google_sheet_client():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()

def get_watched_data():
    """Fetch the log from Google Sheets"""
    try:
        service = get_google_sheet_client()
        sheet = service.values().get(spreadsheetId=SHEET_ID, range="Activity_Log!A:G").execute()
        rows = sheet.get("values", [])
        if len(rows) < 2: return pd.DataFrame(columns=["Date", "Title", "Movie_ID", "Genres", "User", "Rating", "Type"])
        return pd.DataFrame(rows[1:], columns=rows[0])
    except:
        return pd.DataFrame(columns=["Date", "Title", "Movie_ID", "Genres", "User", "Rating", "Type"])

def log_media(title, movie_id, genres, users_ratings, media_type):
    """Write new rows to Google Sheets"""
    service = get_google_sheet_client()
    timestamp = datetime.now().strftime("%Y-%m-%d")
    
    # TMDB gives genres as a list of dictionaries, we need a string
    genre_str = ", ".join([g['name'] for g in genres]) if isinstance(genres, list) else str(genres)

    new_rows = []
    for user, rating in users_ratings.items():
        new_rows.append([timestamp, title, str(movie_id), genre_str, user, str(rating), media_type])
    
    body = {'values': new_rows}
    service.values().append(
        spreadsheetId=SHEET_ID, range="Activity_Log!A:G",
        valueInputOption="USER_ENTERED", body=body
    ).execute()

def search_tmdb(query):
    url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    return requests.get(url).json().get('results', [])

def get_watch_providers(media_id, media_type='movie'):
    url = f"https://api.themoviedb.org/3/{media_type}/{media_id}/watch/providers?api_key={TMDB_API_KEY}"
    data = requests.get(url).json()
    if 'US' in data.get('results', {}):
        providers = data['results']['US']
        flatrate = [p['provider_name'] for p in providers.get('flatrate', [])]
        free = [p['provider_name'] for p in providers.get('free', [])]
        return flatrate, free
    return [], []

def get_recommendations(watched_ids, user_genres):
    recs = []
    # If no history, use generic popular movies
    if not watched_ids:
        url = f"https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}"
        return pd.DataFrame(requests.get(url).json().get('results', []))

    # Fetch Recs based on last 3 watched
    for m_id in watched_ids[-3:]:
        url = f"https://api.themoviedb.org/3/movie/{m_id}/recommendations?api_key={TMDB_API_KEY}"
        data = requests.get(url).json().get('results', [])
        recs.extend(data)
    
    df = pd.DataFrame(recs).drop_duplicates(subset='id')
    
    # Scoring Logic
    def score(row):
        base = row.get('vote_average', 5)
        bonus = 1.5 if any(g_id in user_genres for g_id in row.get('genre_ids', [])) else 0
        return base + bonus

    if not df.empty:
        df['cine_score'] = df.apply(score, axis=1)
        df = df.sort_values(by='cine_score', ascending=False)
    
    return df

# --- UI LAYOUT ---
st.set_page_config(page_title="Cinematch", layout="wide", page_icon="🎬")

# Sidebar
st.sidebar.title("🎬 Cinematch")
st.sidebar.markdown("### Who is watching?")
users = ["Me", "Wife", "Guest"]
selected_users = st.sidebar.multiselect("Select Profile(s)", users, default=["Me"])

if not selected_users:
    st.warning("Please select a viewer profile.")
    st.stop()

tab1, tab2, tab3 = st.tabs(["🏠 Discover", "📝 Search & Log", "📊 Stats"])

# --- TAB 1: DISCOVER ---
with tab1:
    st.header(f"Top Picks for: {', '.join(selected_users)}")
    
    # Filters
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        mood = st.selectbox("Mood / Genre", ["All", "Action", "Comedy", "Drama", "Sci-Fi", "Horror", "Romance"])
    with col_f2:
        media_filter = st.radio("Type", ["Movies", "TV Shows"], horizontal=True)

    # Fetch History
    history_df = get_watched_data()
    
    # 1. NEW RECOMMENDATIONS
    st.subheader("🆕 Fresh Finds (You haven't seen)")
    # (Mock logic - in real usage, we filter out IDs from history_df)
    watched_ids = history_df['Movie_ID'].tolist() if not history_df.empty else []
    recs_df = get_recommendations(watched_ids, []) # Passing empty genres for simplicity in v1
    
    if not recs_df.empty:
        # Filter out watched
        recs_df = recs_df[~recs_df['id'].astype(str).isin(watched_ids)]
        
        cols = st.columns(4)
        for idx, row in enumerate(recs_df.head(4).itertuples()):
            with cols[idx]:
                poster = f"https://image.tmdb.org/t/p/w500{row.poster_path}" if row.poster_path else "https://via.placeholder.com/200x300"
                st.image(poster, use_container_width=True)
                st.markdown(f"**{row.title}** ({row.vote_average}/10)")
                flat, free = get_watch_providers(row.id)
                if flat: st.caption(f"📺 {', '.join(flat[:2])}")
                if free: st.caption(f"🆓 {', '.join(free[:2])}")
    
    # 2. REWATCH RECOMMENDATIONS
    st.subheader("🔁 Comfort Rewatches")
    if not history_df.empty:
        # Simple logic: Show high rated movies from history
        history_df['Rating'] = pd.to_numeric(history_df['Rating'])
        favorites = history_df[history_df['Rating'] >= 8].sample(min(len(history_df), 4))
        if not favorites.empty:
            cols = st.columns(4)
            for idx, row in enumerate(favorites.itertuples()):
                with cols[idx]:
                    st.info(f"{row.Title}")
                    st.caption(f"Rated: {row.Rating}/10")

# --- TAB 2: LOG ---
with tab2:
    st.header("Log a Movie or Show")
    query = st.text_input("Search Title...")
    if query:
        results = search_tmdb(query)
        for res in results:
            if res.get('media_type') not in ['movie', 'tv']: continue
            
            with st.expander(f"{res.get('title', res.get('name'))} ({res.get('release_date', res.get('first_air_date', ''))[:4]})"):
                c1, c2 = st.columns([1,3])
                with c1:
                    poster = f"https://image.tmdb.org/t/p/w200{res.get('poster_path')}" if res.get('poster_path') else ""
                    if poster: st.image(poster)
                with c2:
                    st.write(res.get('overview'))
                    # Rating Sliders
                    user_ratings = {}
                    st.write("---")
                    for u in selected_users:
                        user_ratings[u] = st.slider(f"{u}'s Rating", 1, 10, 7, key=f"{res['id']}_{u}")
                    
                    if st.button("LOG THIS", key=f"btn_{res['id']}"):
                        log_media(
                            res.get('title', res.get('name')), 
                            res['id'], 
                            res.get('genre_ids', []), # Note: This needs mapping, passing raw IDs for now
                            user_ratings, 
                            res['media_type']
                        )
                        st.balloons()
                        st.success("Saved to Database!")

# --- TAB 3: STATS ---
with tab3:
    st.header("Your Data")
    df = get_watched_data()
    if not df.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Logs", len(df))
        # Calculate Avg Rating
        df['Rating'] = pd.to_numeric(df['Rating'])
        avg_score = df['Rating'].mean()
        col2.metric("Average Score", f"{avg_score:.1f}/10")
        
        st.dataframe(df)
    else:
        st.info("No data yet! Go to the Search tab to log your first movie.")
