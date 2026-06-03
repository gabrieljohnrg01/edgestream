from rest_framework import serializers
from .models import Movie, Series, Season, Episode, WatchlistItem
from django.contrib.auth.models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'password']

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password']
        )
        return user

from library.views import get_hls_playlist_path

class MovieSerializer(serializers.ModelSerializer):
    hls_url = serializers.SerializerMethodField()
    genre_names = serializers.StringRelatedField(many=True, source='genres', read_only=True)
    
    class Meta:
        model = Movie
        fields = '__all__'
        
    def get_hls_url(self, obj):
        return get_hls_playlist_path(obj.file_path)

class EpisodeSerializer(serializers.ModelSerializer):
    hls_url = serializers.SerializerMethodField()

    class Meta:
        model = Episode
        fields = '__all__'

    def get_hls_url(self, obj):
        return get_hls_playlist_path(obj.file_path)

class SeasonSerializer(serializers.ModelSerializer):
    episodes = EpisodeSerializer(many=True, read_only=True)

    class Meta:
        model = Season
        fields = '__all__'

class SeriesSerializer(serializers.ModelSerializer):
    seasons = SeasonSerializer(many=True, read_only=True)
    genre_names = serializers.StringRelatedField(many=True, source='genres', read_only=True)

    class Meta:
        model = Series
        fields = '__all__'

class WatchlistItemSerializer(serializers.ModelSerializer):
    movie = MovieSerializer(read_only=True)
    series = SeriesSerializer(read_only=True)
    movie_id = serializers.PrimaryKeyRelatedField(queryset=Movie.objects.all(), source='movie', write_only=True, required=False)
    series_id = serializers.PrimaryKeyRelatedField(queryset=Series.objects.all(), source='series', write_only=True, required=False)

    class Meta:
        model = WatchlistItem
        fields = ['id', 'movie', 'series', 'movie_id', 'series_id', 'added_at']

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)
