from django.contrib.auth.models import User
from django.db import models


class Chat(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session_name = models.CharField(max_length=100, default="")  # NEW: session grouping
    message = models.TextField()
    sender = models.CharField(
        max_length=10,
        choices=[('user', 'User'), ('bot', 'Bot'), ('document', 'Document')]
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.session_name} - {self.user.username} - {self.sender}: {self.message[:20]}"
