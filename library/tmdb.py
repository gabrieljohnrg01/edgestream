import json
import os
import re
import urllib.parse
import urllib.request

from django.utils import timezone

# If you want to override the TMDB key in production, set TMDB_API_KEY in the environment.
TMDB_API_KEY = os.environ.get(
    "TMDB_API_KEY",
    "fc5229ddcee9e96a1be1b8f8535063a3",
)
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

TMDB_GENRES = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Science Fiction",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
    10759: "Action & Adventure",
    10762: "Kids",
    10763: "News",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap",
    10767: "Talk",
    10768: "War & Politics"
}

def get_genre_names(genre_ids):
    if not genre_ids:
        return []
    return [TMDB_GENRES.get(gid) for gid in genre_ids if gid in TMDB_GENRES]
def clean_title(filename):
    try:
        from guessit import guessit
        guess = guessit(filename)
        title = guess.get("title")
        if title:
            return title
    except ImportError:
        pass
        
    title = os.path.splitext(filename)[0]
    
    # Remove season/episode info (S01E01 patterns)
    title = re.sub(r"[Ss]\d{1,2}[Ee]\d{1,2}", "", title)
    
    # Remove bracketed content and parenthetical content
    title = re.sub(r"\[.*?\]", " ", title)
    title = re.sub(r"\(.*?\)", " ", title)
    
    # Replace common separators with space
    title = title.replace(".", " ").replace("_", " ").replace("-", " ")
    
    # Remove year patterns
    title = re.sub(r"\b(19|20)\d{2}\b", "", title)
    
    # Remove common quality/release tags
    quality_tags = r"\b(1080p|720p|480p|4k|hd|uhd|bluray|bdrip|web|webrip|hdtv|h264|h265|x264|x265|aac|dts|ac3|yts|rarbg|etrg|vost|elite|avi)\b"
    title = re.sub(quality_tags, "", title, flags=re.IGNORECASE)
    
    # Remove any remaining special chars
    title = re.sub(r"[^\w\s]", "", title)
    
    # Clean up whitespace
    return " ".join(title.split()).strip()


def extract_title_year(filename):
    try:
        from guessit import guessit
        guess = guessit(filename)
        title = guess.get("title")
        year = guess.get("year")
        if not title:
            title = clean_title(filename)
        return title, year
    except ImportError:
        cleaned = os.path.splitext(filename)[0]
        year_match = re.search(r"\b(19|20)\d{2}\b", cleaned)
        year = int(year_match.group(0)) if year_match else None
        title = clean_title(filename)
        return title, year


def normalize_title_for_match(title):
    return re.sub(r"[^a-z0-9]", "", title.lower().strip())


def fetch_tmdb_metadata(title, media_type, year=None):
    if not title or TMDB_API_KEY.startswith("<"):
        return None

    endpoint = "search/movie" if media_type == "MOVIE" else "search/tv"
    params = {"api_key": TMDB_API_KEY, "query": title}
    if media_type == "MOVIE" and year:
        params["year"] = year
    query = urllib.parse.urlencode(params)
    url = f"https://api.themoviedb.org/3/{endpoint}?{query}"

    with urllib.request.urlopen(url, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))

    results = data.get("results", [])
    if not results:
        return None

    field_name = "title" if media_type == "MOVIE" else "name"
    normalized_target = normalize_title_for_match(title)

    exact_matches = [
        result
        for result in results
        if normalize_title_for_match(result.get(field_name, "")) == normalized_target
    ]
    if exact_matches:
        return exact_matches[0]

    contains_matches = [
        result
        for result in results
        if normalized_target in normalize_title_for_match(result.get(field_name, ""))
    ]
    if contains_matches:
        return contains_matches[0]

    return results[0]


def parse_date(value):
    if not value:
        return None
    try:
        return timezone.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def fetch_season_details(tmdb_id, season_num):
    """Fetch season details from TMDB including poster_path."""
    if TMDB_API_KEY.startswith("<"):
        return None
    
    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_num}?api_key={TMDB_API_KEY}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data
    except Exception:
        return None


def fetch_episode_details(tmdb_id, season_num, episode_num):
    """Fetch episode details from TMDB including overview and still_path."""
    if TMDB_API_KEY.startswith("<"):
        return None
    
    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_num}/episode/{episode_num}?api_key={TMDB_API_KEY}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data
    except Exception:
        return None


def download_tmdb_image(url, subfolder="posters"):
    if not url:
        return ""
    if url.startswith("/media/"):
        return url
        
    import os
    import urllib.request
    from urllib.parse import urlparse
    from django.conf import settings
    
    media_root = os.environ.get("MEDIA_ROOT", str(settings.MEDIA_ROOT))
    folder_path = os.path.join(media_root, subfolder)
    os.makedirs(folder_path, exist_ok=True)
    
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        return ""
        
    file_path = os.path.join(folder_path, filename)
    
    if os.path.exists(file_path):
        return f"/media/{subfolder}/{filename}"
        
    try:
        urllib.request.urlretrieve(url, file_path)
        return f"/media/{subfolder}/{filename}"
    except Exception as e:
        print(f"Error downloading image {url}: {e}")
        return url
