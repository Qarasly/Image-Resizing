import streamlit as st
import pandas as pd
import cloudinary
import cloudinary.uploader
from PIL import Image, ImageOps
import requests
from io import BytesIO
import re

# --- 1. CONFIGURATION ---
# Permanent Cloudinary Credentials
cloudinary.config(
    cloud_name = "djhyyziqe",
    api_key = "973845594791418",
    api_secret = "euyVjoIFQIad1_7MHScPdu9cpzk"
)

def get_direct_url(url):
    """Clean the URL and convert Google Drive sharing links to direct download links."""
    if pd.isna(url): return url
    
    # Remove spaces, newlines, and hidden characters (%0A)
    url = str(url).strip().replace('\n', '').replace('\r', '').replace('%0A', '')
    
    if "drive.google.com" in url:
        # Regex to find the File ID (long string of characters)
        match = re.search(r"/d/([a-zA-Z0-9_-]{25,})", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

def resize_with_padding(img, target_size=(660, 900), background_color=(255, 255, 255)):
    """Resizes image to 660x900 using white padding to avoid cropping or stretching."""
    img.thumbnail(target_size, Image.Resampling.LANCZOS)
    new_img = Image.new("RGB", target_size, background_color)
    paste_pos = (
        (target_size[0] - img.size[0]) // 2,
        (target_size[1] - img.size[1]) // 2
    )
    new_img.paste(img, paste_pos)
    return new_img

@st.cache_data(show_spinner=False)
def cached_process_upload(image_url, psku, suffix):
    try:
        if pd.isna(image_url) or str(image_url).strip().lower() in ["", "nan", "none"]:
            return "No Link"
            
        direct_url = get_direct_url(image_url)
        
        # Mimic browser headers to avoid being blocked by servers
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        response = requests.get(direct_url, headers=headers, timeout=20)
        response.raise_for_status()
        
        img = Image.open(BytesIO(response.content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        img = resize_with_padding(img)
        
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        
        # Clean suffix for safe filenames
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

# Sidebar for instructions
with st.sidebar:
    st.header("📖 How to use")
    st.markdown("""
    1. **Upload** your Excel or CSV.
    2. **Map** your SKU and Image columns.
    3. **Start Processing** to resize to 660x900.
    4. **Download** the 2-sheet Excel result.
    
    *Note: Google Drive links must be set to 'Anyone with link can view'.*
    """)

uploaded_file = st.file_uploader("Upload product sheet", type=["csv", "xlsx"])

if uploaded_file:
    if uploaded_file.name.endswith('.csv'):
        df_original = pd.read_csv(uploaded_file)
    else:
        df_original = pd.read_excel(uploaded_file)
    
    st.info(f"Loaded {len(df_original)} rows.")
    
    c1, c2 = st.columns(2)
    with c1:
        sku_col = st.selectbox("Select SKU Column", df_original.columns)
    with c2:
        url_cols = st.multiselect("Select Link Column(s)", [c for c in df_original.columns if c != sku_col])

    if st.button("🚀 Start Processing") and url_cols:
        df_resized = df_original.copy()
        
        # UI Progress elements
        prog_bar = st.progress(0)
        status_txt = st.empty()
        
        total_tasks = len(df_original) * len(url_cols)
        count = 0
        
        for url_col in url_cols:
            new_links = []
            for i, row in df_original.iterrows():
                current_sku = str(row[sku_col])
                count += 1
                
                # Update UI
                status_txt.markdown(f"**Processing {count}/{total_tasks}:** SKU `{current_sku}`")
                prog_bar.progress(count / total_tasks)
                
                # Process
                res = cached_process_upload(row[url_col], current_sku, url_col)
                new_links.append(res)
            
            df_resized[url_col] = new_links

        st.success("✅ Finished!")
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_original.to_excel(writer, sheet_name='Original Links', index=False)
            df_resized.to_excel(writer, sheet_name='Resized Links', index=False)
        
        st.download_button(
            label="📥 Download Result Excel",
            data=output.getvalue(),
            file_name="Bulk_Resized_Results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
