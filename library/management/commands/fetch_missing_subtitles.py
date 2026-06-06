import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from library.models import Movie, Episode
from library.management.commands.conversion_utils import download_subtitles_with_subliminal, convert_external_subtitles_to_vtt, fuzzy_match_subtitles
import imageio_ffmpeg

class Command(BaseCommand):
    help = "Retroactively fetch missing subtitles for already converted movies and episodes."

    def process_item(self, item, item_type, MEDIA_ROOT, HLS_ROOT, ffmpeg):
        if not item.file_path:
            self.stdout.write(f"DEBUG: '{item.title}' has no file_path.")
            return 0
            
        # Robust path resolution
        raw_path = str(item.file_path)
        if raw_path.startswith('/media/'):
            raw_path = raw_path[7:]
        elif raw_path.startswith('media/'):
            raw_path = raw_path[6:]
        elif raw_path.startswith('\\media\\'):
            raw_path = raw_path[7:]
        elif raw_path.startswith('media\\'):
            raw_path = raw_path[6:]
            
        infile = MEDIA_ROOT / raw_path
        if not infile.exists():
            self.stdout.write(f"DEBUG: '{item.title}' skipped because file doesn't exist at: {infile}")
            return 0
            
        rel_path = Path(raw_path)
        variant_root = HLS_ROOT / rel_path.with_suffix("")
        
        # Check if any .vtt files already exist in the variant root
        existing_vtts = list(variant_root.glob("*.vtt"))
        if existing_vtts:
            self.stdout.write(f"Skipping '{item.title}' (already has subtitles)")
            return 0
            
        self.stdout.write(f"Downloading subtitles for {item_type}: {item.title}...")
        
        # Download using the precise database title and year
        if item_type == 'Movie':
            year = item.release_date.year if getattr(item, 'release_date', None) else None
            download_subtitles_with_subliminal(infile, title=item.title, year=year)
            ext_subs = fuzzy_match_subtitles(infile, item.title, year)
        else:
            # Episode: use series title for better matching
            series_title = item.season.series.title
            year = item.season.series.release_date.year if getattr(item.season.series, 'release_date', None) else None
            # Subliminal often prefers series title + season/episode numbers rather than episode title alone
            download_subtitles_with_subliminal(infile, title=series_title, year=year)
            ext_subs = fuzzy_match_subtitles(infile, series_title, year)
        
        if ext_subs:
            convert_external_subtitles_to_vtt(ffmpeg, ext_subs, variant_root)
            self.stdout.write(self.style.SUCCESS(f"Successfully downloaded and converted subtitles for '{item.title}'!"))
            return 1
        else:
            self.stdout.write(self.style.WARNING(f"Could not find subtitles online for '{item.title}'."))
            return 0

    def handle(self, *args, **options):
        MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(settings.MEDIA_ROOT)))
        HLS_ROOT = Path(os.environ.get("HLS_ROOT", str(MEDIA_ROOT / "hls")))
        
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = "ffmpeg"
            
        count = 0
        
        # Process Movies
        movies = Movie.objects.filter(is_converted=True)
        for movie in movies:
            count += self.process_item(movie, 'Movie', MEDIA_ROOT, HLS_ROOT, ffmpeg)
            
        # Process Episodes
        episodes = Episode.objects.filter(is_converted=True)
        for episode in episodes:
            count += self.process_item(episode, 'Episode', MEDIA_ROOT, HLS_ROOT, ffmpeg)
                
        self.stdout.write(self.style.SUCCESS(f"Finished! Downloaded new subtitles for {count} media items."))
