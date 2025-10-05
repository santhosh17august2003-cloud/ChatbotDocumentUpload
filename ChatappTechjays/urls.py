from django.urls import path
from ChatappTechjays import views

urlpatterns = [
    path("chat/", views.chat, name="chat"),
    path("", views.signin, name="signin"),
    path("signup/", views.signup, name="signup"),
    path("signout/", views.signout, name="signout"),
    #path("profile/", views.profile, name="profile"),
    path("getvalue/", views.getvalue, name="getvalue"),
    #path("history/", views.chat_history, name="chat_history"),

    # Session management
    path('ajax_delete_session/', views.ajax_delete_session, name='ajax_delete_session'),
    path("load_session/<path:session_name>/", views.load_session, name="load_session"),
]
