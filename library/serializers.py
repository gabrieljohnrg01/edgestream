from rest_framework import serializers
from .models import Movie, Series, Season, Episode
from django.contrib.auth.models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

from library.views import get_hls_playlist_path

class MovieSerializer(serializers.ModelSerializer):
    hls_url = serializers.SerializerMethodField()
    
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

    class Meta:
        model = Series
        fields = '__all__'
