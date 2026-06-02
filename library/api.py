from rest_framework import viewsets, generics
from rest_framework.permissions import AllowAny
from .models import Movie, Series, Season, Episode
from .serializers import MovieSerializer, SeriesSerializer, SeasonSerializer, EpisodeSerializer, UserRegistrationSerializer

class RegisterUserAPIView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]


class MovieViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Movie.objects.filter(is_converted=True)
    serializer_class = MovieSerializer

class SeriesViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Series.objects.all()
    serializer_class = SeriesSerializer

class SeasonViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Season.objects.all()
    serializer_class = SeasonSerializer

class EpisodeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Episode.objects.filter(is_converted=True)
    serializer_class = EpisodeSerializer
