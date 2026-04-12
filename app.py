import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import google.generativeai as genai
import pandas as pd
import folium
from streamlit_folium import st_folium
from PIL import Image
import datetime
import uuid

# --- PAGE CONFIG ---
st.set_page_config(page_title="Nature SG", page_icon="🌿", layout="wide")

# --- DATA STRUCTURES (Mock locations for Singapore Parks) ---
SG_PARKS = {
    "Singapore Botanic Gardens": [1.3138, 103.8159],
    "MacRitchie Reservoir": [1.3411, 103.8217],
    "Bukit Timah Nature Reserve": [1.3486, 103.7770],
    "East Coast Park": [1.3007, 103.9122],
    "Sungei Buloh Wetland Reserve": [1.4468, 103.7303],
    "Pasir Ris Park": [1.3811, 103.9515],
    "Punggol Waterway Park": [1.4087, 103.9048],
    "Jurong Lake Gardens": [1.3364, 103.7288]
}

# --- INITIALIZATION ---
def init_services():
    # 1. Initialize Gemini
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    except KeyError:
        st.error("Gemini API key is missing. Please add GEMINI_API_KEY to .streamlit/secrets.toml")
        st.stop()

    # 2. Initialize Firebase
    try:
        if not firebase_admin._apps:
            # Reconstruct the service account dict from secrets
            firebase_cred_dict = {
                "type": st.secrets["firebase"]["type"],
                "project_id": st.secrets["firebase"]["project_id"],
                "private_key_id": st.secrets["firebase"]["private_key_id"],
                "private_key": st.secrets["firebase"]["private_key"].replace('\\n', '\n'),
                "client_email": st.secrets["firebase"]["client_email"],
                "client_id": st.secrets["firebase"]["client_id"],
                "auth_uri": st.secrets["firebase"]["auth_uri"],
                "token_uri": st.secrets["firebase"]["token_uri"],
                "auth_provider_x509_cert_url": st.secrets["firebase"]["auth_provider_x509_cert_url"],
                "client_x509_cert_url": st.secrets["firebase"]["client_x509_cert_url"],
                "universe_domain": st.secrets["firebase"]["universe_domain"],
            }
            cred = credentials.Certificate(firebase_cred_dict)
            firebase_admin.initialize_app(cred, {
                'databaseURL': st.secrets["firebase"]["databaseURL"]
            })
    except Exception as e:
        st.error(f"Firebase configuration issue: {e}")
        st.info("Ensure all firebase secrets (especially private_key and client_email) are properly pasted from your Firebase Service Account JSON into .streamlit/secrets.toml")
        st.stop()

init_services()

# --- HELPER FUNCTIONS ---
def identify_wildlife(image_data):
    """Calls Gemini Vision API to identify the content."""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest') # Flash is fast and supports vision
        prompt = """
        You are a wildlife expert specializing in the flora and fauna of Singapore.
        Look at this image and identify the primary subject. 
        Return the result EXACTLY in this format:
        Type: [Plant, Insect, or Animal]
        Name: [Common Name (Scientific Name)]
        Description: [1 short sentence describing it]
        """
        response = model.generate_content([prompt, image_data])
        return response.text
    except Exception as e:
        return f"Error: {e}"

def parse_identification(text):
    """Parses Gemini's structured response."""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    result = {"type": "Unknown", "name": "Unknown", "description": ""}
    for line in lines:
        if line.startswith("Type:"):
            result["type"] = line.replace("Type:", "").strip()
        elif line.startswith("Name:"):
            result["name"] = line.replace("Name:", "").strip()
        elif line.startswith("Description:"):
            result["description"] = line.replace("Description:", "").strip()
    return result

def fetch_sightings():
    """Fetches all sightings from Firebase Realtime Database."""
    ref = db.reference('sightings')
    data = ref.get()
    if data:
        # Convert nested dict to list of dicts
        records = []
        for key, val in data.items():
            val['id'] = key
            records.append(val)
        return pd.DataFrame(records)
    return pd.DataFrame()


# --- UI LAYOUT ---
st.title("🌿 Nature SG: Wildlife Identifier")
st.markdown("Discover and log the amazing plants, insects, and animals across Singapore's parks!")

tab1, tab2, tab3 = st.tabs(["📸 Identify & Log", "🗺️ Sightings Map", "📋 Recent Feed"])

# --- TAB 1: IDENTIFY & LOG ---
with tab1:
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Capture Image")
        # Let user choose camera or file upload
        input_method = st.radio("Select input method:", ["Camera", "Upload File"], horizontal=True)
        img_file_buffer = None
        
        if input_method == "Camera":
            img_file_buffer = st.camera_input("Take a picture")
        else:
            img_file_buffer = st.file_uploader("Upload an image", type=["jpg", "jpeg", "png"])
            
        st.subheader("Location")
        selected_park = st.selectbox("Where are you?", list(SG_PARKS.keys()))
        
    with col2:
        st.subheader("Identification Result")
        if img_file_buffer is not None:
            # Display image
            img = Image.open(img_file_buffer)
            st.image(img, use_container_width=True, caption="Your Image")
            
            if st.button("Identify Wildlife", type="primary"):
                with st.spinner("Analyzing image with Gemini AI..."):
                    # Call Gemini
                    response_text = identify_wildlife(img)
                    if "Error:" not in response_text:
                        parsed = parse_identification(response_text)
                        
                        # Show result
                        st.success("Identification Complete!")
                        st.metric(label="Type", value=parsed["type"])
                        st.markdown(f"**Name:** {parsed['name']}")
                        st.markdown(f"**Notes:** {parsed['description']}")
                        
                        # Save to Firebase
                        with st.spinner("Saving to database..."):
                            ref = db.reference('sightings')
                            record = {
                                "timestamp": datetime.datetime.now().isoformat(),
                                "park": selected_park,
                                "latitude": SG_PARKS[selected_park][0],
                                "longitude": SG_PARKS[selected_park][1],
                                "type": parsed["type"],
                                "name": parsed["name"],
                                "description": parsed["description"]
                            }
                            ref.push(record)
                        st.balloons()
                        st.info("Successfully recorded to Firebase!")
                    else:
                        st.error(response_text)
        else:
            st.info("Capture or upload an image to start.")


# --- TAB 2: SIGHTINGS MAP ---
with tab2:
    st.subheader("Wildlife Distribution Map")
    
    df = fetch_sightings()
    
    if not df.empty:
        # Filter options
        filter_type = st.multiselect("Filter by Type:", options=df['type'].unique(), default=df['type'].unique())
        filtered_df = df[df['type'].isin(filter_type)]
        
        if not filtered_df.empty:
            st.markdown(f"Showing **{len(filtered_df)}** recorded sightings.")
            
            # Count per park
            park_counts = filtered_df['park'].value_counts().reset_index()
            park_counts.columns = ['park', 'count']
            
            st.dataframe(park_counts, hide_index=True)

            # Create Folium Map
            # Center on Singapore
            sg_map = folium.Map(location=[1.3521, 103.8198], zoom_start=11)
            
            colors = {"Plant": "green", "Insect": "orange", "Animal": "red", "Unknown": "gray"}
            
            for idx, row in filtered_df.iterrows():
                # Format Popup
                popup_html = f"<b>{row['name']}</b><br>Type: {row['type']}<br>Date: {row['timestamp'][:10]}"
                
                folium.Marker(
                    location=[row['latitude'], row['longitude']],
                    popup=folium.Popup(popup_html, max_width=250),
                    tooltip=row['name'],
                    icon=folium.Icon(color=colors.get(row['type'], 'blue'), icon='info-sign')
                ).add_to(sg_map)

            # Render map in Streamlit
            st_folium(sg_map, width=800, height=500, returned_objects=[])
        else:
            st.warning("No sightings match the selected filters.")
    else:
        st.info("No sightings recorded yet. Go out and explore!")


# --- TAB 3: RECENT FEED ---
with tab3:
    st.subheader("Recent Feed")
    df = fetch_sightings()
    if not df.empty:
        # Sort by timestamp descending
        df = df.sort_values(by='timestamp', ascending=False)
        for idx, row in df.iterrows():
            with st.container():
                col_a, col_b = st.columns([1, 4])
                with col_a:
                    icon = "🌿" if row['type'] == 'Plant' else "🐞" if row['type'] == 'Insect' else "🦊"
                    st.markdown(f"### {icon}")
                with col_b:
                    st.markdown(f"**{row['name']}** at {row['park']}")
                    st.caption(f"{row['type']} | {row['timestamp'][:16].replace('T', ' ')}")
                    if 'description' in row and row['description']:
                        st.markdown(f"> {row['description']}")
                st.divider()
    else:
        st.info("No recent sightings.")
