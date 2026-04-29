def get_direct_url(url):
    """Clean the URL and convert Google Drive sharing links to direct download links."""
    if pd.isna(url): return url
    
    # 1. CLEANING: Remove spaces, newlines, and hidden characters that cause 404s
    url = str(url).strip().replace('\n', '').replace('\r', '').replace('%0A', '')
    
    # 2. GOOGLE DRIVE CONVERSION
    if "drive.google.com" in url:
        # Regex to find the File ID regardless of what comes after it
        match = re.search(r"/d/([a-zA-Z0-9_-]{25,})", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url

@st.cache_data(show_spinner=False)
def cached_process_upload(image_url, psku, suffix):
    try:
        if pd.isna(image_url) or str(image_url).strip().lower() in ["", "nan", "none"]:
            return "No Link"
            
        direct_url = get_direct_url(image_url)
        
        # We use a user-agent header to mimic a browser, which helps with Drive downloads
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
        
        # Clean suffix to remove any illegal characters from column names
        clean_suffix = "".join(filter(str.isalnum, suffix))
        
        upload_result = cloudinary.uploader.upload(
            buf, 
            public_id = f"sku_{psku}_{clean_suffix}",
            folder = "team_uploads",
            overwrite = True
        )
        return upload_result.get("secure_url")
    except Exception as e:
        # If it still fails, return the error message so the user knows which link failed
        return f"Error: {str(e)}"
