from django.urls import path
from ChatappTechjays import views

urlpatterns = [
	path("chat/", views.chat, name="chat"),
	path("signin/", views.signin, name="signin"),
	path("signup/", views.signup, name="signup"),
    path("signout/", views.signout, name="signout"),
    path('profile/', views.profile, name='profile'),
    path('getvalue/', views.getvalue, name='getvalue'),
    
    
] 