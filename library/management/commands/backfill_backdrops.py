import time
from django.core.management.base import BaseCommand
from library.models import Movie, Series
from library.tmdb import fetch_tmdb_metadata, TMDB_IMAGE_BASE

class Command(BaseCommand):
    help = "Backfill backdrop_url for existing movies and series"

    def handle(self, *args, **options):
        self.stdout.write("Backfilling backdrops for Movies...")
        for movie in Movie.objects.filter(backdrop_url=""):
            metadata = fetch_tmdb_metadata(movie.title, "MOVIE")
            if metadata and metadata.get("backdrop_path"):
                backdrop_url = f"{TMDB_IMAGE_BASE}{metadata['backdrop_path']}"
                movie.backdrop_url = backdrop_url
                movie.save(update_fields=["backdrop_url"])
                self.stdout.write(self.style.SUCCESS(f"Added backdrop to {movie.title}"))
            time.sleep(0.5)

        self.stdout.write("Backfilling backdrops for Series...")
        for series in Series.objects.filter(backdrop_url=""):
            metadata = fetch_tmdb_metadata(series.title, "SERIES")
            if metadata and metadata.get("backdrop_path"):
                backdrop_url = f"{TMDB_IMAGE_BASE}{metadata['backdrop_path']}"
                series.backdrop_url = backdrop_url
                series.save(update_fields=["backdrop_url"])
                self.stdout.write(self.style.SUCCESS(f"Added backdrop to {series.title}"))
            time.sleep(0.5)
            
        self.stdout.write(self.style.SUCCESS("Backdrop backfill complete!"))
