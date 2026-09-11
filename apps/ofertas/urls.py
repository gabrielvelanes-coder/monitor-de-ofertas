from django.urls import path

from . import views

app_name = 'ofertas'

urlpatterns = [
    path('', views.home, name='home'),
    path('leve3/', views.leve3, name='leve3'),
    path('cestoes/', views.cestoes, name='cestoes'),
    path('supracorp/', views.supracorp, name='supracorp'),
    path('fabricante/<str:fabricante>/', views.impacto_fabricante, name='impacto_fabricante'),
    path('marketing/', views.marketing, name='marketing'),
]
