from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("movies/", views.movies, name="movies"),
    path("series/", views.series, name="series"),
    path("series/<int:pk>/", views.series_detail, name="series_detail"),
    path("series/<int:series_pk>/season/<int:season_pk>/", views.season_detail, name="season_detail"),
    path("episode/<int:episode_pk>/", views.episode_playback, name="episode_playback"),
    path("movie/<int:pk>/", views.movie_detail, name="movie_detail"),
    path("movie/<int:pk>/play/", views.movie_playback, name="movie_playback"),

    path("search/", views.search, name="search"),
    path("account-select/", views.account_select, name="account_select"),
    path("queue/", views.queue_dashboard, name="queue_dashboard"),
    path("api/queue/", views.queue_status_api, name="queue_status_api"),
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("watchlist/", views.watchlist_view, name="watchlist"),
    path("ajax/watchlist/toggle/", views.api_toggle_watchlist, name="api_toggle_watchlist"),
    path("api/progress/update/", views.api_update_progress, name="api_update_progress"),
    path("api/queue/clear/", views.api_clear_queue, name="api_clear_queue"),
    path("api/profile/me/", views.api_my_profile, name="api_my_profile"),
    path("settings/", views.settings_view, name="settings"),
]

