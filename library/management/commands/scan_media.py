import os
import re
import subprocess
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from library.models import Movie, Series, Season, Episode, ConversionTask, Genre
from library.tmdb import (
    TMDB_IMAGE_BASE,
    clean_title,
    extract_title_year,
    fetch_tmdb_metadata,
    download_tmdb_image,
    fetch_season_details,
    fetch_episode_details,
    parse_date,
    get_genre_names,
)

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", str(settings.MEDIA_ROOT))
MEDIA_FOLDERS = {
    "movies": os.path.join(MEDIA_ROOT, "movies"),
    "series": os.path.join(MEDIA_ROOT, "series"),
}

HLS_ROOT = Path(os.environ.get("HLS_ROOT", str(Path(MEDIA_ROOT) / "hls")))


def has_hls_playlist(file_path):
    if not file_path.startswith("/media/"):
        return False
    rel_path = Path(file_path[len("/media/"):])
    hls_dir = HLS_ROOT / rel_path.with_suffix("")
    playlist_name = rel_path.with_suffix("").name + ".m3u8"
    return (hls_dir / playlist_name).exists()


def get_media_duration(path):
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        seconds = float(result.stdout.strip())
        return timezone.timedelta(seconds=seconds)
    except Exception:
        return None


def extract_season_episode(filename, filepath=""):
    season = None
    episode = None
    
    # 1. Try to extract Season from folder path (e.g. ".../Season 1/...")
    match_folder = re.search(r"Season\s+(\d+)", filepath, re.IGNORECASE)
    if match_folder:
        season = int(match_folder.group(1))

    # 2. Use guessit for filename
    try:
        from guessit import guessit
        guess = guessit(filename)
        guess_season = guess.get("season")
        guess_episode = guess.get("episode")
        
        if isinstance(guess_episode, list):
            guess_episode = guess_episode[0]
            
        if season is None and guess_season is not None:
            season = int(guess_season)
        if guess_episode is not None:
            episode = int(guess_episode)
    except ImportError:
        pass

    # 3. Regex fallback for standard S01E01 format
    if season is None or episode is None:
        match_regex = re.search(r"[Ss](\d{1,2})[Ee](\d{1,2})", filename)
        if match_regex:
            if season is None:
                season = int(match_regex.group(1))
            if episode is None:
                episode = int(match_regex.group(2))
                
    # 4. Fallback for absolute episode formats like " - 050 - "
    if episode is None:
        match_abs = re.search(r"-\s*(\d{2,4})\s*-", filename)
        if match_abs:
            episode = int(match_abs.group(1))

    return season, episode


class Command(BaseCommand):
    help = "Scan local media folders and index movies and series."

    def handle(self, *args, **options):
        self.scan_movies()
        self.scan_series()
        self.scan_hls_series()

    def scan_movies(self):
        movies_dir = MEDIA_FOLDERS["movies"]
        if not os.path.isdir(movies_dir):
            self.stdout.write(self.style.WARNING(f"Skipping {movies_dir}: directory does not exist."))
            return

        for root, _, files in os.walk(movies_dir):
            for filename in sorted(files):
                if not filename.lower().endswith((".mp4", ".avi", ".mkv", ".m4v")):
                    continue

                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, MEDIA_ROOT).replace(os.sep, "/")
                file_path = f"/media/{rel_path}"

                parent_dir = os.path.basename(root)
                if parent_dir and parent_dir.lower() != 'movies':
                    title_source = parent_dir
                else:
                    title_source = filename

                title_guess, year_guess = extract_title_year(title_source)
                metadata = fetch_tmdb_metadata(title_guess, "MOVIE", year_guess)
                if not metadata:
                    self.stdout.write(self.style.WARNING(f"No TMDB metadata for '{filename}'."))
                    continue

                poster_path = metadata.get("poster_path") or ""
                poster_url = download_tmdb_image(f"{TMDB_IMAGE_BASE}{poster_path}", "posters") if poster_path else ""
                backdrop_path = metadata.get("backdrop_path") or ""
                backdrop_url = download_tmdb_image(f"{TMDB_IMAGE_BASE}{backdrop_path}", "backdrops") if backdrop_path else ""
                description = metadata.get("overview", "")
                release_date = parse_date(metadata.get("release_date"))
                tmdb_id = metadata.get("id") or 0
                duration = get_media_duration(full_path)

                movie, created = Movie.objects.update_or_create(
                    file_path=file_path,
                    defaults={
                        "title": title_guess or filename,
                        "tmdb_id": tmdb_id,
                        "description": description,
                        "poster_url": poster_url,
                        "backdrop_url": backdrop_url,
                        "release_date": release_date,
                        "duration": duration,
                        "date_added": timezone.now(),
                        "is_converted": has_hls_playlist(file_path),
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Added MOVIE: {title_guess}"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"Updated MOVIE: {title_guess}"))

                genre_ids = metadata.get("genre_ids", [])
                genre_names = get_genre_names(genre_ids)
                if genre_names:
                    genres = []
                    for g_name in genre_names:
                        g, _ = Genre.objects.get_or_create(name=g_name)
                        genres.append(g)
                    movie.genres.set(genres)

                if not movie.is_converted and not ConversionTask.objects.filter(file_path=file_path, status__in=[ConversionTask.STATUS_QUEUED, ConversionTask.STATUS_PROCESSING]).exists():
                    ConversionTask.objects.create(
                        file_path=file_path,
                        movie=movie,
                        status=ConversionTask.STATUS_QUEUED,
                    )

    def scan_series(self):
        series_dir = MEDIA_FOLDERS["series"]
        if not os.path.isdir(series_dir):
            self.stdout.write(self.style.WARNING(f"Skipping {series_dir}: directory does not exist."))
            return

        series_metadata_cache = {}

        for root, _, files in os.walk(series_dir):
            # Extract series folder name from path
            rel_path = os.path.relpath(root, series_dir)
            parts = rel_path.split(os.sep)
            series_folder_name = parts[0] if parts and parts[0] != "." else ""
            for filename in sorted(files):
                if not filename.lower().endswith((".mp4", ".avi", ".mkv", ".m4v")):
                    continue

                full_path = os.path.join(root, filename)
                season_num, episode_num = extract_season_episode(filename, full_path)
                if season_num is None or episode_num is None:
                    self.stdout.write(self.style.WARNING(f"Could not parse S/E from '{filename}'."))
                    continue
                rel_path = os.path.relpath(full_path, MEDIA_ROOT).replace(os.sep, "/")
                file_path = f"/media/{rel_path}"

                if Episode.objects.filter(file_path=file_path).exists():
                    continue

                title_guess = clean_title(series_folder_name if series_folder_name else filename)
                
                if title_guess in series_metadata_cache:
                    metadata = series_metadata_cache[title_guess]
                else:
                    self.stdout.write(f"DEBUG: Requesting TMDB for series title: '{title_guess}'")
                    metadata = fetch_tmdb_metadata(title_guess, "SERIES")
                    
                    # If failed, fallback to filename
                    if not metadata and series_folder_name:
                        fallback_guess = clean_title(filename)
                        self.stdout.write(f"DEBUG: Requesting TMDB for fallback filename title: '{fallback_guess}'")
                        metadata = fetch_tmdb_metadata(fallback_guess, "SERIES")
                        
                    series_metadata_cache[title_guess] = metadata

                if not metadata:
                    self.stdout.write(self.style.WARNING(f"No TMDB metadata for '{filename}'. (Guessed titles: '{title_guess}', Fallback: '{clean_title(filename) if series_folder_name else 'none'}')"))
                    continue

                series_title = metadata.get("name") or title_guess
                tmdb_id = metadata.get("id") or 0
                series, created = Series.objects.update_or_create(
                    title=series_title,
                    defaults={
                        "tmdb_id": tmdb_id,
                        "description": metadata.get("overview", ""),
                        "poster_url": download_tmdb_image(f"{TMDB_IMAGE_BASE}{metadata.get('poster_path')}", "posters") if metadata.get("poster_path") else "",
                        "backdrop_url": download_tmdb_image(f"{TMDB_IMAGE_BASE}{metadata.get('backdrop_path')}", "backdrops") if metadata.get("backdrop_path") else "",
                        "release_date": parse_date(metadata.get("first_air_date")),
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Added SERIES: {series_title}"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"Updated SERIES: {series_title}"))

                genre_ids = metadata.get("genre_ids", [])
                genre_names = get_genre_names(genre_ids)
                if genre_names:
                    genres = []
                    for g_name in genre_names:
                        g, _ = Genre.objects.get_or_create(name=g_name)
                        genres.append(g)
                    series.genres.set(genres)

                # Fetch season details for poster
                season_details = fetch_season_details(tmdb_id, season_num)
                season_poster = ""
                if season_details and season_details.get("poster_path"):
                    season_poster = download_tmdb_image(f"{TMDB_IMAGE_BASE}{season_details.get('poster_path')}", "posters")

                season, _ = Season.objects.update_or_create(
                    series=series,
                    season_number=season_num,
                    defaults={"poster_url": season_poster},
                )

                if season_poster and season.poster_url != season_poster:
                    season.poster_url = season_poster
                    season.save(update_fields=["poster_url"])

                # Fetch episode details
                episode_details = fetch_episode_details(tmdb_id, season_num, episode_num)
                ep_title = episode_details.get("name", "") if episode_details else ""
                ep_description = episode_details.get("overview", "") if episode_details else ""
                ep_still = ""
                if episode_details and episode_details.get("still_path"):
                    ep_still = download_tmdb_image(f"{TMDB_IMAGE_BASE}{episode_details.get('still_path')}", "stills")

                episode, created = Episode.objects.update_or_create(
                    season=season,
                    episode_number=episode_num,
                    defaults={
                        "file_path": file_path,
                        "title": ep_title,
                        "description": ep_description,
                        "still_url": ep_still,
                        "is_converted": has_hls_playlist(file_path),
                    },
                )

                if created:
                    self.stdout.write(
                        self.style.SUCCESS(f"Added {series_title} S{season_num:02d}E{episode_num:02d}: {ep_title}")
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(f"Updated {series_title} S{season_num:02d}E{episode_num:02d}: {ep_title}")
                    )

                if not episode.is_converted and not ConversionTask.objects.filter(file_path=file_path, status__in=[ConversionTask.STATUS_QUEUED, ConversionTask.STATUS_PROCESSING]).exists():
                    ConversionTask.objects.create(
                        file_path=file_path,
                        episode=episode,
                        status=ConversionTask.STATUS_QUEUED,
                    )

    def scan_hls_movies(self):
        movies_hls_dir = os.path.join(HLS_ROOT, "movies")
        if not os.path.isdir(movies_hls_dir):
            return

        for root, dirs, files in os.walk(movies_hls_dir):
            m3u8_files = [f for f in files if f.endswith(".m3u8")]
            if not m3u8_files:
                continue
                
            master_playlist = None
            for m3u8 in m3u8_files:
                try:
                    content = open(os.path.join(root, m3u8), "r", encoding="utf-8").read()
                    if "EXT-X-STREAM-INF" in content:
                        master_playlist = m3u8
                        break
                except Exception:
                    pass
                    
            if not master_playlist:
                master_playlist = m3u8_files[0]

            rel_path = os.path.relpath(root, movies_hls_dir)
            parts = rel_path.split(os.sep)
            
            if not parts:
                continue

            title_source = parts[0]
            file_path = f"/media/movies/{rel_path.replace(os.sep, '/')}.mkv"

            if Movie.objects.filter(file_path=file_path).exists():
                continue

            title_guess, year_guess = extract_title_year(title_source)
            metadata = fetch_tmdb_metadata(title_guess, "MOVIE", year_guess)
            if not metadata:
                self.stdout.write(self.style.WARNING(f"No TMDB metadata for HLS movie '{title_source}'."))
                continue

            poster_path = metadata.get("poster_path") or ""
            poster_url = download_tmdb_image(f"{TMDB_IMAGE_BASE}{poster_path}", "posters") if poster_path else ""
            backdrop_path = metadata.get("backdrop_path") or ""
            backdrop_url = download_tmdb_image(f"{TMDB_IMAGE_BASE}{backdrop_path}", "backdrops") if backdrop_path else ""
            description = metadata.get("overview", "")
            release_date = parse_date(metadata.get("release_date"))
            tmdb_id = metadata.get("id") or 0

            movie, created = Movie.objects.update_or_create(
                file_path=file_path,
                defaults={
                    "title": metadata.get("title") or title_guess,
                    "tmdb_id": tmdb_id,
                    "description": description,
                    "poster_url": poster_url,
                    "backdrop_url": backdrop_url,
                    "release_date": release_date,
                    "duration": None,
                    "is_converted": True,
                },
            )

            genre_ids = metadata.get("genre_ids", [])
            genre_names = get_genre_names(genre_ids)
            if genre_names:
                genres = []
                for g_name in genre_names:
                    g, _ = Genre.objects.get_or_create(name=g_name)
                    genres.append(g)
                movie.genres.set(genres)

            self.stdout.write(self.style.SUCCESS(f"{'Added' if created else 'Updated'} HLS MOVIE: {movie.title}"))

    def scan_hls_series(self):
        series_hls_dir = os.path.join(HLS_ROOT, "series")
        if not os.path.isdir(series_hls_dir):
            return

        series_metadata_cache = {}

        for root, dirs, files in os.walk(series_hls_dir):
            m3u8_files = [f for f in files if f.endswith(".m3u8")]
            if not m3u8_files:
                continue
                
            master_playlist = None
            for m3u8 in m3u8_files:
                try:
                    content = open(os.path.join(root, m3u8), "r", encoding="utf-8").read()
                    if "EXT-X-STREAM-INF" in content:
                        master_playlist = m3u8
                        break
                except Exception:
                    pass
                    
            if not master_playlist:
                master_playlist = m3u8_files[0]

            rel_path = os.path.relpath(root, series_hls_dir)
            parts = rel_path.split(os.sep)
            
            # Must be exactly Series / Season / Episode folder depth
            if len(parts) != 3:
                continue
                
            series_folder_name = parts[0]
            
            # Only focus on Fullmetal Alchemist for now!
            if "Fullmetal Alchemist" not in series_folder_name:
                continue
            filename_without_ext = parts[-1]
            filename = f"{filename_without_ext}.mkv"
            
            full_path = os.path.join(root, filename)
            season_num, episode_num = extract_season_episode(filename, full_path)
            
            if season_num is None or episode_num is None:
                self.stdout.write(self.style.WARNING(f"Could not parse S/E from HLS folder '{rel_path}'."))
                continue

            file_path = f"/media/series/{rel_path.replace(os.sep, '/')}.mkv"

            if Episode.objects.filter(file_path=file_path).exists():
                continue

            title_guess = clean_title(series_folder_name)
            
            if title_guess in series_metadata_cache:
                metadata = series_metadata_cache[title_guess]
            else:
                self.stdout.write(f"DEBUG: Requesting TMDB for HLS series title: '{title_guess}'")
                metadata = fetch_tmdb_metadata(title_guess, "SERIES")
                series_metadata_cache[title_guess] = metadata

            if not metadata:
                self.stdout.write(self.style.WARNING(f"No TMDB metadata for HLS series '{series_folder_name}'."))
                continue

            series_title = metadata.get("name") or title_guess
            tmdb_id = metadata.get("id") or 0
            series, created = Series.objects.update_or_create(
                title=series_title,
                defaults={
                    "tmdb_id": tmdb_id,
                    "description": metadata.get("overview", ""),
                    "poster_url": download_tmdb_image(f"{TMDB_IMAGE_BASE}{metadata.get('poster_path')}", "posters") if metadata.get("poster_path") else "",
                    "backdrop_url": download_tmdb_image(f"{TMDB_IMAGE_BASE}{metadata.get('backdrop_path')}", "backdrops") if metadata.get("backdrop_path") else "",
                    "release_date": parse_date(metadata.get("first_air_date")),
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Added SERIES: {series_title}"))

            season_obj, _ = Season.objects.get_or_create(series=series, season_number=season_num)
            
            episode_details = fetch_episode_details(tmdb_id, season_num, episode_num)
            ep_title = ""
            ep_description = ""
            ep_still = ""
            if episode_details:
                ep_title = episode_details.get("name", "")
                ep_description = episode_details.get("overview", "")
                still_path = episode_details.get("still_path")
                if still_path:
                    ep_still = download_tmdb_image(f"{TMDB_IMAGE_BASE}{still_path}", "stills")

            Episode.objects.create(
                season=season_obj,
                episode_number=episode_num,
                title=ep_title,
                file_path=file_path,
                description=ep_description,
                still_url=ep_still,
                is_converted=True,
            )
            self.stdout.write(self.style.SUCCESS(f"Added HLS Episode: {series_title} S{season_num:02d}E{episode_num:02d}"))
