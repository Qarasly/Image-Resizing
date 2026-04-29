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
    """Converts Google Drive sharing links to direct download links."""
    if pd.isna(url): return url
    url = str(url).strip()
    if "drive.google.com" in url:
        match = re.search(r"/d/([^/]+)", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

def resize_with_padding(img, target_size=(660, 900), background_color=(255, 255, 255)):
    """Resizes image into 660x900 using white padding to prevent stretching or cropping."""
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
        response = requests.get(direct_url, timeout=15)
        response.raise_for_status()
        
        img = Image.open(BytesIO(response.content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
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
st.set_page_config(page_title="Bulk Image Resizing", layout="wide", page_icon="🖼️")

st.title("🖼️ Bulk Image Resizing")

# Instructions Section
with st.expander("📖 Instructions - How to use this tool", expanded=True):
    st.markdown("""
    1. **Upload File:** Upload your Excel (.xlsx) or CSV file containing SKU/Barcode and Image Links.
    2. **Map Columns:** * Select the column that identifies your product (e.g., **PSKU** or **Barcode**).
        * Select one or more columns that contain the **Original Image Links**.
    3. **Google Drive Links:** Ensure Google Drive links are set to **"Anyone with the link can view"**.
    4. **Process:** Click **Start Processing**. The tool adds white padding to keep your images proportional at **660x900px**.
    5. **Download:** Once finished, download the new Excel. The **'Resized Links'** sheet contains your permanent URLs.
    """)

st.divider()

uploaded_file = st.file_uploader("Upload your product sheet", type=["csv", "xlsx"])

if uploaded_file:
    # Load Data
    if uploaded_file.name.endswith('.csv'):
        df_original = pd.read_csv(uploaded_file)
    else:
        df_original = pd.read_excel(uploaded_file)
    
    st.success(f"File loaded successfully ({len(df_original)} rows found).")
    
    col1, col2 = st.columns(2)
    with col1:
        sku_col = st.selectbox("Select SKU / Barcode Column", df_original.columns)
    with col2:
        url_cols = st.multiselect("Select Image URL Column(s)", [c for c in df_original.columns if c != sku_col])

    if st.button("🚀 Start Processing") and url_cols:
        df_resized = df_original.copy()
        
        # Progress Tracking UI
        progress_container = st.container()
        with progress_container:
            st.write("### Processing Status")
            progress_bar = st.progress(0)
            status_text = st.empty()
            counter_display = st.empty()
        
        total_rows = len(df_original)
        total_cols = len(url_cols)
        total_tasks = total_rows * total_cols
        processed_count = 0
        
        for url_col in url_cols:
            new_links = []
            for i, row in df_original.iterrows():
                current_sku = str(row[sku_col])
                
                # Increment and update counter
                processed_count += 1
                percent = int((processed_count / total_tasks) * 100)
                
                status_text.markdown(f"**Current Task:** `{url_col}` | **Current SKU:** `{current_sku}`")
                counter_display.info(f"Processed {processed_count} of {total_tasks} images ({percent}%)")
                progress_bar.progress(processed_count / total_tasks)
                
                # Logic Execution
                link = cached_process_upload(row[url_col], current_sku, url_col)
                new_links.append(link)
            
            df_resized[url_col] = new_links

        status_text.success(f"✅ Successfully processed {total_tasks} images!")
        counter_display.empty()
        
        # Final Excel Generation
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_original.to_excel(writer, sheet_name='Original Links', index=False)
            df_resized.to_excel(writer, sheet_name='Resized Links', index=False)
        
        st.download_button(
            label="📥 Download Processed Excel File",
            data=output.getvalue(),
            file_name="Bulk_Resized_Images.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
