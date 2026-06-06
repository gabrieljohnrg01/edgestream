import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from library.models import Movie
from library.management.commands.conversion_utils import download_subtitles_with_subliminal, convert_external_subtitles_to_vtt, fuzzy_match_subtitles
import imageio_ffmpeg

class Command(BaseCommand):
    help = "Retroactively fetch missing subtitles for already converted movies."

    def handle(self, *args, **options):
        MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(settings.MEDIA_ROOT)))
        HLS_ROOT = Path(os.environ.get("HLS_ROOT", str(MEDIA_ROOT / "hls")))
        
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = "ffmpeg"
            
        movies = Movie.objects.filter(is_converted=True)
        count = 0
        
        for movie in movies:
            if not movie.file_path:
                continue
                
            infile = MEDIA_ROOT / str(movie.file_path).replace("/media/", "", 1)
            if not infile.exists():
                continue
                
            rel_path = Path(str(infile).replace(str(MEDIA_ROOT) + os.sep, ""))
            variant_root = HLS_ROOT / rel_path.with_suffix("")
            
            # Check if any .vtt files already exist in the variant root
            existing_vtts = list(variant_root.glob("*.vtt"))
            if existing_vtts:
                self.stdout.write(f"Skipping '{movie.title}' (already has subtitles)")
                continue
                
            self.stdout.write(f"Downloading subtitles for: {movie.title}...")
            
            # Download using the precise database title and year!
            download_subtitles_with_subliminal(infile, title=movie.title, year=movie.release_date.year if movie.release_date else None)
            
            # Find the downloaded file
            ext_subs = fuzzy_match_subtitles(infile, movie.title, movie.release_date.year if movie.release_date else None)
            
            if ext_subs:
                convert_external_subtitles_to_vtt(ffmpeg, ext_subs, variant_root)
                self.stdout.write(self.style.SUCCESS(f"Successfully downloaded and converted subtitles for '{movie.title}'!"))
                count += 1
            else:
                self.stdout.write(self.style.WARNING(f"Could not find subtitles online for '{movie.title}'."))
                
        self.stdout.write(self.style.SUCCESS(f"Finished! Downloaded new subtitles for {count} movies."))
