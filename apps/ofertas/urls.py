from django.urls import path

from . import views

app_name = 'ofertas'

urlpatterns = [
    path('', views.home, name='home'),
    path('leve3/', views.leve3, name='leve3'),
]
