import streamlit as st
import pandas as pd
import cloudinary
import cloudinary.uploader
from PIL import Image
import requests
from io import BytesIO

# --- 1. CONFIGURATION ---
# Your permanent Cloudinary credentials
cloudinary.config(
    cloud_name = "djhyyziqe",
    api_key = "973845594791418",
    api_secret = "euyVjoIFQIad1_7MHScPdu9cpzk"
)

def process_and_upload(image_url, psku, suffix):
    """Downloads, resizes to 660x900, and uploads with a unique ID."""
    try:
        if pd.isna(image_url) or str(image_url).strip().lower() in ["", "nan", "none"]:
            return "No Link Provided"
            
        response = requests.get(image_url, timeout=15)
        response.raise_for_status()
        
        img = Image.open(BytesIO(response.content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        # Transformation to your specific dimensions
        img = img.resize((660, 900), Image.Resampling.LANCZOS)
        
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        
        # Uploading with unique ID based on SKU and Column Name
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
st.set_page_config(page_title="SKU Image Processor", layout="wide")

# Sidebar Instructions
with st.sidebar:
    st.header("📖 Instructions")
    st.markdown("""
    1. **Upload any Excel or CSV.** Headers do not need to be named anything specific.
    2. **Select the SKU Column:** This will be used to name the images.
    3. **Select Link Columns:** You can pick one or multiple columns that contain URLs.
    4. **Process:** The tool will resize all images to **660x900px**.
    5. **Download:** You will get an Excel file with two sheets: 
       * *Original Links* * *Resized Links*
    """)
    st.divider()
    st.info("The generated links are **permanent** and hosted on Cloudinary.")

st.title("🖼️ Professional SKU Image Resizer")

uploaded_file = st.file_uploader("Upload your product sheet", type=["csv", "xlsx"])

if uploaded_file:
    # Read file automatically regardless of format
    if uploaded_file.name.endswith('.csv'):
        df_original = pd.read_csv(uploaded_file)
    else:
        df_original = pd.read_excel(uploaded_file)
    
    st.success(f"File loaded! Found {len(df_original)} rows.")
    
    st.subheader("Map Your Columns")
    col1, col2 = st.columns(2)
    
    with col1:
        # User picks the ID column
        sku_col = st.selectbox("Select the column for PSKU / Barcode:", df_original.columns)
    
    with col2:
        # User picks one or more image columns
        url_cols = st.multiselect(
            "Select the column(s) that contain Image Links:", 
            [c for c in df_original.columns if c != sku_col]
        )

    if st.button("🚀 Process & Create Excel"):
        if not url_cols:
            st.error("Please select at least one column containing image links!")
        else:
            df_resized = df_original.copy()
            total_steps = len(df_original) * len(url_cols)
            step = 0
            progress_bar = st.progress(0)
            status = st.empty()
            
            for url_col in url_cols:
                new_links = []
                for i, row in df_original.iterrows():
                    current_sku = str(row[sku_col])
                    status.text(f"Processing {url_col} | SKU: {current_sku} ({step+1}/{total_steps})")
                    
                    # Process image
                    link = process_and_upload(row[url_col], current_sku, url_col)
                    new_links.append(link)
                    
                    step += 1
                    progress_bar.progress(step / total_steps)
                
                # Replace content in the resized dataframe
                df_resized[url_col] = new_links
            
            status.success("✅ Processing Complete!")
            
            # Create Excel with 2 Sheets
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_original.to_excel(writer, sheet_name='Original Links', index=False)
                df_resized.to_excel(writer, sheet_name='Resized Links', index=False)
            
            st.download_button(
                label="📥 Download Final Excel (2 Sheets)",
                data=output.getvalue(),
                file_name="processed_skus.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
