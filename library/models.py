from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Movie(models.Model):
    title = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512, unique=True)
    tmdb_id = models.IntegerField()
    description = models.TextField(blank=True)
    poster_url = models.URLField(blank=True)
    release_date = models.DateField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    date_added = models.DateTimeField(default=timezone.now)
    watch_count = models.IntegerField(default=0)
    last_watch_reset = models.DateTimeField(default=timezone.now)
    is_converted = models.BooleanField(default=False)
    genres = models.ManyToManyField(Genre, blank=True)

    class Meta:
        ordering = ["-date_added"]

    def __str__(self):
        return self.title

    @property
    def duration_display(self):
        if not self.duration:
            return "Unknown duration"
        total_seconds = int(self.duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m {seconds}s"


class Series(models.Model):
    title = models.CharField(max_length=255, unique=True)
    tmdb_id = models.IntegerField()
    description = models.TextField(blank=True)
    poster_url = models.URLField(blank=True)
    release_date = models.DateField(null=True, blank=True)
    date_added = models.DateTimeField(default=timezone.now)
    watch_count = models.IntegerField(default=0)
    last_watch_reset = models.DateTimeField(default=timezone.now)
    genres = models.ManyToManyField(Genre, blank=True)

    class Meta:
        ordering = ["-date_added"]

    def __str__(self):
        return self.title


class Season(models.Model):
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name="seasons")
    season_number = models.IntegerField()
    poster_url = models.URLField(blank=True)

    class Meta:
        ordering = ["season_number"]
        unique_together = ("series", "season_number")

    def __str__(self):
        return f"{self.series.title} - Season {self.season_number}"


class Episode(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="episodes")
    episode_number = models.IntegerField()
    title = models.CharField(max_length=255, blank=True)
    file_path = models.CharField(max_length=512, unique=True)
    description = models.TextField(blank=True)
    still_url = models.URLField(blank=True)
    is_converted = models.BooleanField(default=False)

    class Meta:
        ordering = ["episode_number"]
        unique_together = ("season", "episode_number")

    def __str__(self):
        return f"{self.season} - E{self.episode_number}: {self.title or 'Untitled'}"


class ConversionTask(models.Model):
    STATUS_QUEUED = "QUEUED"
    STATUS_PROCESSING = "PROCESSING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    file_path = models.CharField(max_length=512)
    movie = models.ForeignKey('Movie', null=True, blank=True, on_delete=models.CASCADE, related_name='conversion_tasks')
    episode = models.ForeignKey('Episode', null=True, blank=True, on_delete=models.CASCADE, related_name='conversion_tasks')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    progress = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["file_path"]),
        ]

    @property
    def file_name(self):
        import os
        return os.path.basename(self.file_path)

    def __str__(self):
        return f"{self.file_path} ({self.status})"


# Keep MediaItem for backwards compatibility during transition
class MediaItem(models.Model):
    MEDIA_TYPE_MOVIE = "MOVIE"
    MEDIA_TYPE_SERIES = "SERIES"
    MEDIA_TYPE_CHOICES = [
        (MEDIA_TYPE_MOVIE, "Movie"),
        (MEDIA_TYPE_SERIES, "Series"),
    ]

    title = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512, unique=True)
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES)
    tmdb_id = models.IntegerField()
    description = models.TextField(blank=True)
    poster_url = models.URLField(blank=True)
    release_date = models.DateField(null=True, blank=True)
    date_added = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-date_added"]

    def __str__(self):
        return f"{self.title} ({self.media_type})"

class WatchlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="watchlist")
    movie = models.ForeignKey('Movie', null=True, blank=True, on_delete=models.CASCADE)
    series = models.ForeignKey('Series', null=True, blank=True, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-added_at"]

    def __str__(self):
        if self.movie:
            return f"{self.user.username} - {self.movie.title}"
        if self.series:
            return f"{self.user.username} - {self.series.title}"
        return f"{self.user.username} - WatchlistItem"

class PlaybackProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="progress")
    movie = models.ForeignKey('Movie', null=True, blank=True, on_delete=models.CASCADE)
    episode = models.ForeignKey('Episode', null=True, blank=True, on_delete=models.CASCADE)
    timestamp = models.IntegerField(default=0)  # current playback time in seconds
    last_watched = models.DateTimeField(auto_now=True)
    is_finished = models.BooleanField(default=False)

    class Meta:
        unique_together = (("user", "movie"), ("user", "episode"))

    def __str__(self):
        if self.movie:
            return f"{self.user.username} - {self.movie.title} ({self.timestamp}s)"
        if self.episode:
            return f"{self.user.username} - {self.episode.title} ({self.timestamp}s)"
        return f"{self.user.username} - Progress"
