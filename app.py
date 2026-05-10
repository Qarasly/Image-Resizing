import streamlit as st
import pandas as pd
import cloudinary
import cloudinary.uploader
from PIL import Image, ImageOps, ImageStat
import requests
from io import BytesIO
import re

# --- 1. CONFIGURATION ---
cloudinary.config(
    cloud_name = "djhyyziqe",
    api_key = "973845594791418",
    api_secret = "euyVjoIFQIad1_7MHScPdu9cpzk"
)

def get_direct_url(url):
    """Clean the URL and convert Google Drive sharing links to direct download links."""
    if pd.isna(url): return url
    url = str(url).strip().replace('\n', '').replace('\r', '').replace('%0A', '')
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]{25,})", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

def detect_background_color(img):
    """Detects the average color at the edges of the image."""
    if img.mode != 'RGB':
        img = img.convert('RGB')
    w, h = img.size
    corners = [
        img.crop((0, 0, 5, 5)),           # Top-left
        img.crop((w-5, 0, w, 5)),         # Top-right
        img.crop((0, h-5, 5, h)),         # Bottom-left
        img.crop((w-5, h-5, w, h))        # Bottom-right
    ]
    r, g, b = 0, 0, 0
    for corner in corners:
        stat = ImageStat.Stat(corner)
        r += stat.mean[0]
        g += stat.mean[1]
        b += stat.mean[2]
    return (int(r/4), int(g/4), int(b/4))

def resize_with_choice(img, mode, target_size=(660, 900)):
    """Resizes image based on the user's selected background mode."""
    if mode == "Automatic":
        bg_color = detect_background_color(img)
    elif mode == "White":
        bg_color = (255, 255, 255)
    else:  # Black
        bg_color = (0, 0, 0)
    
    img.thumbnail(target_size, Image.Resampling.LANCZOS)
    new_img = Image.new("RGB", target_size, bg_color)
    paste_pos = (
        (target_size[0] - img.size[0]) // 2,
        (target_size[1] - img.size[1]) // 2
    )
    new_img.paste(img, paste_pos)
    return new_img

@st.cache_data(show_spinner=False)
def cached_process_upload(image_url, psku, suffix, bg_mode):
    try:
        if pd.isna(image_url) or str(image_url).strip().lower() in ["", "nan", "none"]:
            return "No Link"
            
        direct_url = get_direct_url(image_url)
        headers = {"User-Agent": "Mozilla/5.0"}
        
        response = requests.get(direct_url, headers=headers, timeout=20)
        response.raise_for_status()
        
        img = Image.open(BytesIO(response.content))
        
        # Process with the user's chosen color mode
        img = resize_with_choice(img, bg_mode)
        
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        
        clean_suffix = "".join(filter(str.isalnum, suffix))
        upload_result = cloudinary.uploader.upload(
            buf, 
            public_id = f"sku_{psku}_{clean_suffix}",
            folder = "team_uploads",
            overwrite = True
        )
        return upload_result.get("secure_url")
    except Exception as e:
        return f"Error: {str(e)}"

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Bulk Image Resizing", layout="wide", page_icon="🖼️")
st.title("🖼️ Bulk Image Resizing")

# Instructions
with st.expander("📖 Instructions", expanded=False):
    st.markdown("""
    1. **Upload** Excel/CSV.
    2. **Map Columns:** Choose SKU and Image URL columns.
    3. **Background Mode:** Select **Automatic** to match the photo, or **White/Black** to force a color.
    4. **Process:** Get permanent links in a new Excel file.
    """)

uploaded_file = st.file_uploader("Upload product sheet", type=["csv", "xlsx"])

if uploaded_file:
    df_original = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
    st.info(f"Loaded {len(df_original)} rows.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        sku_col = st.selectbox("SKU Column", df_original.columns)
    with col2:
        url_cols = st.multiselect("Image URL Column(s)", [c for c in df_original.columns if c != sku_col])
    with col3:
        bg_mode = st.selectbox("Background Fill Mode", ["Automatic", "White", "Black"])

    if st.button("🚀 Start Processing") and url_cols:
        # Clear cache
