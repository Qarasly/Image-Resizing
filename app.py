import streamlit as st
import pandas as pd
from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError
import requests
from io import BytesIO
import re
import zipfile
import base64
from rembg import remove
import json
import time
import os
import hashlib
from google import genai
import pillow_avif # Required for AVIF support

# --- 1. SECURE CONFIGURATION ---
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")

# --- HELPER FUNCTIONS ---
REQ_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8'
}

def get_direct_url(url):
    if pd.isna(url): return ""
    url = str(url).strip().replace('\n', '').replace('\r', '').replace('%0A', '')
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]{25,})", url)
        if match:
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url

def detect_background_color(img):
    if img.mode != 'RGB': img = img.convert('RGB')
    w, h = img.size
    corners = [img.crop((0,0,5,5)), img.crop((w-5,0,w,5)), img.crop((0,h-5,5,h)), img.crop((w-5,h-5,w,h))]
    r, g, b = 0, 0, 0
    for corner in corners:
        stat = ImageStat.Stat(corner)
        r += stat.mean[0]; g += stat.mean[1]; b += stat.mean[2]
    return (int(r/4), int(g/4), int(b/4))

def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

def process_image_pipeline(img, tw, th, final_color_rgb, bg_mode):
    if bg_mode: img = remove(img)
    curr_color = detect_background_color(img) if final_color_rgb == "AUTO" else final_color_rgb
    img.thumbnail((tw, th), Image.Resampling.LANCZOS)
    new_img = Image.new("RGB", (tw, th), curr_color)
    paste_pos = ((tw - img.size[0]) // 2, (th - img.size[1]) // 2)
    
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        new_img.paste(img, paste_pos, img)
    else:
        new_img.paste(img, paste_pos)
    return new_img

def upload_to_imgbb(img_buffer, psku, api_key):
    url = f"https://api.imgbb.com/1/upload?key={api_key}"
    b64_img = base64.b64encode(img_buffer.getvalue()).decode("utf-8")
    payload = {
        "image": b64_img,
        "name": str(psku)[:50] 
    }
    
    for attempt in range(5):
        res = requests.post(url, data=payload)
        if res.ok:
            return res.json()["data"]["url"]
            
        error_msg = res.text
        try: error_msg = res.json().get("error", {}).get("message", res.text)
        except: pass
        
        if "Rate limit" in error_msg or res.status_code in [429, 503, 400]:
            time.sleep(5 + (attempt * 5)) 
            continue
        else:
            raise Exception(f"ImgBB API Rejected: {error_msg}")
            
    raise Exception("ImgBB Rate Limit reached after multiple retries.")

def upload_to_cloudinary(img_buffer, psku, cloud_name, api_key, api_secret):
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    timestamp = str(int(time.time()))
    public_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(psku)[:50]) 
    
    sign_str = f"public_id={public_id}&timestamp={timestamp}{api_secret}"
    signature = hashlib.sha1(sign_str.encode('utf-8')).hexdigest()
    
    files = {'file': ('image.jpg', img_buffer.getvalue(), 'image/jpeg')}
    data = {
        'api_key': api_key,
        'timestamp': timestamp,
        'public_id': public_id,
        'signature': signature
    }
    
    res = requests.post(url, files=files, data=data)
    if res.ok:
        return res.json()["secure_url"]
    else:
        raise Exception(f"Cloudinary Error: {res.text}")

def generate_product_info(img):
    if not GEMINI_API_KEY: return {}
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = """
    Analyze this product image. Provide the following information in a valid JSON object:
    {
      "product_name": "A professional and catchy name for this product",
      "product_type": "The main category (e.g., Apparel, Electronics, Home Goods, Furniture)",
      "product_subtype": "The specific sub-category (e.g., V-Neck T-Shirt, Wireless Headphones, Sofa)",
      "description": "A compelling product description ready for an e-commerce website (2-3 sentences)."
    }
    Provide accurate information. Return ONLY the raw JSON object. Do not wrap it in markdown code blocks.
    """
    
    for attempt in range(3):
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=[img, prompt])
            raw = response.text.strip()
            backticks = chr(96) * 3
            if raw.startswith(backticks):
                raw = re.sub(r"^" + re.escape(backticks) + r"(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*" + re.escape(backticks) + r"$", "", raw)
            return json.loads(raw.strip())
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                if attempt < 2:
                    time.sleep(2 + attempt * 2)
                    continue
            return {"error": f"AI Error: {str(e)}"}
    return {"error": "AI Error: Server busy after multiple retries"}

# --- 2. UI LAYOUT ---
st.set_page_config(page_title="Catalog Studio", layout="wide")
st.title("🏭 Catalog Studio")

# --- USER GUIDE EXPANDER ---
with st.expander("📖 Quick Start Guide & How to Get API Keys"):
    st.markdown("""
    ### How to use this tool:
    **1. Secure your Workspace:** Always type your Name or Batch ID in Step 0. This creates a hidden backup. If your internet crashes mid-batch, you can type that exact name back in to download your recovered file!
    
    **2. Setup your Personal Cloud (Optional):** If you want the app to hand you an Excel sheet full of live image links, you must plug in your own free cloud storage keys. This bypasses global server rate limits.
    * **Option A: ImgBB (Easy but Strict Limits):** Go to [api.imgbb.com](https://api.imgbb.com/), create a free account, and copy your API Key.
    * **Option B: Cloudinary (Professional & Fast):** Go to [cloudinary.com](https://cloudinary.com/) and sign up for free. Go to your Dashboard -> *Product Environment Credentials*. Copy your **Cloud Name**, **API Key**, and **API Secret**.
    
    **3. Choose your Workflow:**
    * **Excel Links:** The full pipeline. Resizes images, optionally generates AI content, uploads to your cloud, and returns a finished Excel file.
    * **Modified Images (ZIP):** Bypasses the cloud entirely. Resizes/pads your images and gives you a downloaded ZIP file. Excellent for uploading directly into WordPress/Shopify!
    * **Original Raw Images (ZIP):** Pure downloader mode. Skips all AI and resizing. Just grabs the raw images from your links and names them by SKU. Perfect for bypassing strict website firewalls.
    
    **4. Upload & Run:** Drop your Excel sheet (or local image files) in Step 2, map your columns, and click Start!
    """)

# --- STEP 0: SECURE WORKSPACE & USER CLOUD KEYS ---
with st.container(border=True):
    st.markdown("### 🔐 Step 0: Workspace & Cloud Credentials")
    session_key = st.text_input("Workspace / User ID:", placeholder="e.g. JohnDoe or Batch_42", help="Creates a secure, isolated container for your progress backups.")

    if not session_key.strip():
        st.warning("⚠️ Please enter a Workspace ID above to unlock the tools.")
        st.stop()

    st.divider()
    st.markdown("#### ☁️ Personal Image Cloud (Optional)")
    st.write("To generate live Excel links, enter your personal cloud API keys. This ensures you never hit global rate limits.")
    cloud_provider = st.selectbox("Select Cloud Provider:", ["None (ZIP Outputs Only)", "ImgBB (Free)", "Cloudinary (Pro)"])
    
    user_imgbb_key = ""
    user_cloud_name = ""
    user_cloud_api = ""
    user_cloud_secret = ""
    
    if cloud_provider == "ImgBB (Free)":
        user_imgbb_key = st.text_input("ImgBB API Key:", type="password")
    elif cloud_provider == "Cloudinary (Pro)":
        c1, c2, c3 = st.columns(3)
        with c1: user_cloud_name = st.text_input("Cloud Name:")
        with c2: user_cloud_api = st.text_input("API Key:", type="password")
        with c3: user_cloud_secret = st.text_input("API Secret:", type="password")

safe_key = re.sub(r'[^a-zA-Z0-9_-]', '_', session_key.strip())
backup_filename = f"recovery_backup_{safe_key}.csv"

# --- EMERGENCY RECOVERY BLOCK (USER SPECIFIC) ---
if os.path.exists(backup_filename):
    st.error(f"⚠️ **Interrupted Session Detected for '{session_key}'!**")
    st.write("It looks like your previous run crashed. You can download your partially completed file below.")
    with open(backup_filename, "rb") as file:
        st.download_button(
            label=f"🚑 Download Emergency Backup ({session_key})",
            data=file,
            file_name=f"recovered_catalog_{safe_key}.csv",
            mime="text/csv"
        )
    st.divider()

# --- STEP 1: WORKFLOW SELECTION ---
st.markdown("### 🛠️ Step 1: Select Your Objective")

available_workflows = [
    "📦 Resize & Zip -> Modified Images", 
    "📥 Pure Downloader -> Original Raw Images (ZIP)"
]
# Only allow Excel Link mode if they provided Cloud keys
if cloud_provider != "None (ZIP Outputs Only)":
    available_workflows.insert(0, "📊 Resize & Upload -> Excel Links")

workflow = st.radio("What do you want to generate?", available_workflows, horizontal=True)

use_resizer = "Resize" in workflow
use_ai = False
ai_liability_accepted = False

if use_resizer:
    with st.container(border=True):
        st.subheader("⚙️ Processing Options")
        s1, s2 = st.columns(2)
        with s1:
            target_w = st.number_input("Width (px)", min_value=10, value=660)
            target_h = st.number_input("Height (px)", min_value=10, value=900)
            bg_mode = st.toggle("AI Background Removal (rembg)", value=False)
        with s2:
            color_type = st.radio("Canvas Fill Style:", ["Standard White", "Automatic (Match Image)", "Custom Color"], horizontal=True)
            if color_type == "Custom Color": 
                final_color_rgb = hex_to_rgb(st.color_picker("Pick color", "#FFFFFF"))
            elif color_type == "Standard White": 
                final_color_rgb = (255, 255, 255)
            else: 
                final_color_rgb = "AUTO"
        
        st.divider()
        use_ai = st.toggle("🤖 Enable AI Content Generation (Name, Type, Description)")
        if use_ai:
            st.warning("⚠️ **Mandatory AI Liability Disclaimer**")
            ai_liability_accepted = st.checkbox("I acknowledge that AI models may produce inaccurate text and our team will verify the outputs.")

st.divider()

# --- STEP 2: UPLOAD DATA ---
st.markdown("### 📂 Step 2: Upload Target Data")
input_mode = st.selectbox("Input Source", ["Links (Excel/CSV Sheet)", "Local Image Files"])

smart_skip = False
if input_mode == "Links (Excel/CSV Sheet)" and "Excel Links" in workflow:
    smart_skip = st.toggle("⏭️ Smart Resume (Skip processed items)", value=True, help="Ignores rows that already have a Resized Link.")

data_to_process = []
df_original = None

if input_mode == "Links (Excel/CSV Sheet)":
    uploaded_file = st.file_uploader("Upload Product Target Sheet", type=["csv", "xlsx"])
    if uploaded_file:
        df_original = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
        c1, c2 = st.columns(2)
        with c1: sku_col = st.selectbox("Select Target SKU Column", df_original.columns)
        with c2: url_cols = st.multiselect("Select Target URL Column(s)", [c for c in df_original.columns if c != sku_col])
            
        if url_cols:
            for idx, row in df_original.iterrows():
                for col in url_cols:
                    if pd.isna(row[col]) or str(row[col]).strip().lower() == 'nan' or str(row[col]).strip() == "":
                        continue
                        
                    if smart_skip and "Resized Link" in df_original.columns:
                        existing_link = str(df_original.at[idx, "Resized Link"]).strip()
                        if existing_link.startswith("http"): continue 
                    
                    data_to_process.append({"sku": str(row[sku_col]).strip(), "content": row[col], "col_name": col, "row_idx": idx, "type": "url"})
else:
    # UPDATED: Now fully supports jfif, avif, webp, jpeg, png, and jpg!
    uploaded_imgs = st.file_uploader("Upload Target Images", type=["jpg", "jpeg", "jfif", "png", "webp", "avif"], accept_multiple_files=True)
    if uploaded_imgs:
        for img_file in uploaded_imgs:
            data_to_process.append({"sku": img_file.name.rsplit('.', 1)[0].strip(), "content": Image.open(img_file), "col_name": "file", "type": "file"})

# --- EXECUTION ENGINE ---
if st.button("🚀 Start Production Loop") and data_to_process:
    # Security Checks
    if use_ai and not ai_liability_accepted:
        st.error("🚨 Execution Blocked: You must read and check the AI Liability Disclaimer box to use content features.")
        st.stop()
        
    if "Excel Links" in workflow:
        if cloud_provider == "ImgBB (Free)" and not user_imgbb_key:
            st.error("🚨 Please enter your ImgBB API Key in Step 0.")
            st.stop()
        elif cloud_provider == "Cloudinary (Pro)" and (not user_cloud_name or not user_cloud_api or not user_cloud_secret):
            st.error("🚨 Please enter all 3 Cloudinary keys in Step 0.")
            st.stop()
        
    pb = st.progress(0)
    st_txt = st.empty()
    total = len(data_to_process)
    
    # -------------------------------------------------------------------------
    # PIPELINE 1: RESIZE & UPLOAD TO EXCEL (USER CLOUD)
    # -------------------------------------------------------------------------
    if "Excel Links" in workflow:
        results_df = df_original.copy() if input_mode == "Links (Excel/CSV Sheet)" else pd.DataFrame(columns=["psku"])
            
        for i, item in enumerate(data_to_process):
            st_txt.text(f"Processing Loop {i+1}/{total}: {item['sku']}")
            target_idx = i if input_mode == "Local Image Files" else item['row_idx']
            
            try:
                if item['type'] == "url":
                    link_val = str(item['content']).strip()
                    if not link_val.startswith("http"): raise ValueError(f"Skipped: Invalid URL ('{link_val}')")
                    
                    resp = requests.get(get_direct_url(link_val), headers=REQ_HEADERS, timeout=15)
                    resp.raise_for_status()
                    try:
                        raw_img = Image.open(BytesIO(resp.content))
                    except UnidentifiedImageError:
                        raise ValueError("Not a valid image file (blocked by firewall or 404 error).")
                else:
                    raw_img = item['content']

                proc_img = process_image_pipeline(raw_img, target_w, target_h, final_color_rgb, bg_mode)
                buf = BytesIO()
                proc_img.save(buf, format="JPEG", quality=90)
                buf.seek(0)
                
                # UPLOAD TO USER'S SELECTED CLOUD
                if cloud_provider == "ImgBB (Free)":
                    res_link = upload_to_imgbb(buf, item['sku'], user_imgbb_key)
                elif cloud_provider == "Cloudinary (Pro)":
                    res_link = upload_to_cloudinary(buf, item['sku'], user_cloud_name, user_cloud_api, user_cloud_secret)
                
                if input_mode == "Local Image Files": results_df.at[target_idx, "psku"] = item['sku']
                results_df.at[target_idx, "Resized Link"] = res_link
                
                if use_ai and GEMINI_API_KEY:
                    st_txt.text(f"🤖 Gemini analyzing product {i+1}/{total}: {item['sku']}")
                    ai_outputs = generate_product_info(proc_img)
                    results_df.at[target_idx, "Generated Name"] = ai_outputs.get("product_name", "")
                    results_df.at[target_idx, "Generated Type"] = ai_outputs.get("product_type", "")
                    results_df.at[target_idx, "Generated Subtype"] = ai_outputs.get("product_subtype", "")
                    results_df.at[target_idx, "Generated Description"] = ai_outputs.get("description", "")
                    if "error" in ai_outputs: results_df.at[target_idx, "AI Diagnostics"] = ai_outputs.get("error")
            
            except Exception as e: 
                results_df.at[target_idx, "Resized Link"] = f"Error: {str(e)}"
            
            results_df.to_csv(backup_filename, index=False)
            time.sleep(1.0) # Standard limit safety pause
            pb.progress((i + 1) / total)

        if os.path.exists(backup_filename): os.remove(backup_filename)
        st.success("✅ Automation completed successfully!")
        out_excel = BytesIO()
        with pd.ExcelWriter(out_excel, engine='openpyxl') as writer:
            results_df.to_excel(writer, index=False)
        st.download_button("📥 Download Final Results", out_excel.getvalue(), f"Completed_Catalog_{safe_key}.xlsx")

    # -------------------------------------------------------------------------
    # PIPELINE 2: RESIZE & ZIP IMAGES
    # -------------------------------------------------------------------------
    elif "Modified Images" in workflow:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_f:
            for i, item in enumerate(data_to_process):
                st_txt.text(f"Processing & Zipping {i+1}/{total}: {item['sku']}")
                try:
                    if item['type'] == "url":
                        link_val = str(item['content']).strip()
                        if not link_val.startswith("http"): raise ValueError("Invalid URL")
                        resp = requests.get(get_direct_url(link_val), headers=REQ_HEADERS, timeout=15)
                        raw_img = Image.open(BytesIO(resp.content))
                    else:
                        raw_img = item['content']
                    
                    proc_img = process_image_pipeline(raw_img, target_w, target_h, final_color_rgb, bg_mode)
                    img_buf = BytesIO()
                    proc_img.save(img_buf, format="JPEG", quality=90)
                    zip_f.writestr(f"{item['sku']}.jpg", img_buf.getvalue())
                    
                    if use_ai and GEMINI_API_KEY:
                        ai_outputs = generate_product_info(proc_img)
                        zip_f.writestr(f"{item['sku']}_metadata.json", json.dumps(ai_outputs, indent=4))
                except Exception: pass
                time.sleep(0.5)
                pb.progress((i + 1) / total)
        st.success("✅ ZIP Generated!")
        st.download_button("📥 Download Resized Images ZIP", zip_buffer.getvalue(), f"Resized_Images_{safe_key}.zip")

    # -------------------------------------------------------------------------
    # PIPELINE 3: PURE RAW DOWNLOADER
    # -------------------------------------------------------------------------
    elif "Original Raw Images" in workflow:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_f:
            for i, item in enumerate(data_to_process):
                st_txt.text(f"Downloading {i+1}/{total}: {item['sku']}")
                try:
                    if item['type'] == "url":
                        link_val = str(item['content']).strip()
                        if link_val.startswith("http"):
                            resp = requests.get(get_direct_url(link_val), headers=REQ_HEADERS, timeout=15)
                            resp.raise_for_status()
                            zip_f.writestr(f"{item['sku']}.jpg", resp.content)
                    else:
                        img_buf = BytesIO()
                        item['content'].save(img_buf, format="JPEG", quality=100)
                        zip_f.writestr(f"{item['sku']}.jpg", img_buf.getvalue())
                except Exception: pass
                time.sleep(0.5) 
                pb.progress((i + 1) / total)
                
        st.success("✅ Bulk Download & Rename Complete!")
        st.download_button("📥 Download Original Images ZIP", zip_buffer.getvalue(), f"Original_Raw_Images_{safe_key}.zip")
