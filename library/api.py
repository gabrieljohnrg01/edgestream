from rest_framework import viewsets, generics, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from .models import Movie, Series, Season, Episode
from .serializers import MovieSerializer, SeriesSerializer, SeasonSerializer, EpisodeSerializer, UserRegistrationSerializer

class RegisterUserAPIView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=status.HTTP_201_CREATED)


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
