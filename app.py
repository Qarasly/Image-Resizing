import streamlit as st
import pandas as pd
import cloudinary
import cloudinary.uploader
from PIL import Image
import requests
from io import BytesIO

# --- 1. CONFIGURATION ---
# Your provided credentials
cloudinary.config(
    cloud_name = "djhyyziqe",
    api_key = "973845594791418",
    api_secret = "euyVjoIFQIad1_7MHScPdu9cpzk"
)

def process_and_upload(image_url, psku):
    """Downloads, resizes to 660x900, and uploads to Cloudinary."""
    try:
        # 1. Download
        response = requests.get(image_url, timeout=15)
        response.raise_for_status()
        
        # 2. Resize
        img = Image.open(BytesIO(response.content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        img = img.resize((660, 900), Image.Resampling.LANCZOS)
        
        # 3. Buffer
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        
        # 4. Upload (using PSKU as the filename)
        upload_result = cloudinary.uploader.upload(
            buf, 
            public_id = f"sku_{psku}",
            folder = "team_uploads",
            overwrite = True
        )
        
        return upload_result.get("secure_url")
    
    except Exception as e:
        return f"Error: {str(e)}"

# --- 2. USER INTERFACE ---
st.set_page_config(page_title="Image Resizer Tool", layout="wide")

st.title("🖼️ Team Image Resizer & Link Generator")
st.info("Upload your sheet. We'll resize images to 660x900 and provide permanent Cloudinary links.")

uploaded_file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])

if uploaded_file:
    # Read file
    df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
    
    st.subheader("Step 1: Map your columns")
    col1, col2 = st.columns(2)
    with col1:
        sku_col = st.selectbox("Which column is the PSKU?", df.columns)
    with col2:
        url_col = st.selectbox("Which column has the Image Links?", df.columns)

    if st.button("🚀 Process & Generate Permanent Links"):
        results = []
        bar = st.progress(0)
        status = st.empty()
        
        for i, row in df.iterrows():
            current_sku = str(row[sku_col])
            status.text(f"Processing SKU: {current_sku} ({i+1}/{len(df)})")
            
            new_link = process_and_upload(row[url_col], current_sku)
            results.append(new_link)
            
            bar.progress((i + 1) / len(df))
            
        df['Permanent_Resized_URL'] = results
        status.success("✅ Processing Complete!")
        
        st.subheader("Step 2: Download Results")
        st.dataframe(df[[sku_col, url_col, 'Permanent_Resized_URL']])
        
        csv_data = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Updated Sheet",
            data=csv_data,
            file_name="resized_images_list.csv",
            mime="text/csv"
        )