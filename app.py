import streamlit as st
import pandas as pd
import cloudinary
import cloudinary.uploader
from PIL import Image, ImageOps
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
    """Converts Google Drive sharing links to direct download links."""
    if "drive.google.com" in url:
        match = re.search(r"/d/([^/]+)", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

def resize_with_padding(img, target_size=(660, 900), background_color=(255, 255, 255)):
    """Resizes image to fit within target_size without cropping or stretching, adding padding."""
    # Get original dimensions
    img.thumbnail(target_size, Image.Resampling.LANCZOS)
    
    # Create a new white background canvas
    new_img = Image.new("RGB", target_size, background_color)
    
    # Center the resized image on the canvas
    # Use ( (canvas_width - img_width)//2, (canvas_height - img_height)//2 )
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
        response = requests.get(direct_url, timeout=15)
        response.raise_for_status()
        
        img = Image.open(BytesIO(response.content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        # Apply Padding Logic instead of Cropping
        img = resize_with_padding(img)
        
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
st.set_page_config(page_title="Pro SKU Resizer (Padded)", layout="wide")

st.title("🖼️ Pro SKU Resizer (No-Crop / No-Stretch)")
st.info("This version adds white padding to ensure the whole image fits perfectly in a 660x900 frame.")

uploaded_file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])

if uploaded_file:
    df_original = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
    
    col1, col2 = st.columns(2)
    with col1:
        sku_col = st.selectbox("SKU Column", df_original.columns)
    with col2:
        url_cols = st.multiselect("Image Link Columns", [c for c in df_original.columns if c != sku_col])

    if st.button("🚀 Process Batch") and url_cols:
        df_resized = df_original.copy()
        progress_bar = st.progress(0)
        status_msg = st.empty()
        
        total_tasks = len(df_original) * len(url_cols)
        current_task = 0
        
        for url_col in url_cols:
            new_links = []
            for i, row in df_original.iterrows():
                current_sku = str(row[sku_col])
                status_msg.markdown(f"**Processing:** `{current_sku}`")
                
                link = cached_process_upload(row[url_col], current_sku, url_col)
                new_links.append(link)
                
                current_task += 1
                progress_bar.progress(current_task / total_tasks)
            
            df_resized[url_col] = new_links

        status_msg.success("✅ Finished!")
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_original.to_excel(writer, sheet_name='Original Links', index=False)
            df_resized.to_excel(writer, sheet_name='Resized Links', index=False)
        
        st.download_button(
            label="📥 Download Results",
            data=output.getvalue(),
            file_name="resized_padded.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
