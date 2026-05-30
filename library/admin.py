from django.contrib import admin
from .models import Movie, Series, Season, Episode, MediaItem

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ("title", "release_date", "date_added")
    search_fields = ("title",)

@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ("title", "release_date", "date_added")
    search_fields = ("title",)

@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("series", "season_number")
    search_fields = ("series__title",)

@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("season", "episode_number", "title")
    search_fields = ("season__series__title", "title")

@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    list_display = ("title", "media_type", "release_date", "date_added")
    search_fields = ("title",)
    list_filter = ("media_type",)

