import json
import os
import tempfile

import fitz  # PyMuPDF for PDF fallback
import google.generativeai as genai
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from google.genai.errors import APIError
from langchain.document_loaders import (UnstructuredHTMLLoader,
                                        UnstructuredPDFLoader,
                                        UnstructuredWordDocumentLoader)

from .forms import SignInForm, SignupForm
from .models import Chat
# This file handles user views for the chat app

# ---------------- GEMINI CONFIG ---------------- #
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("⚠️ GEMINI_API_KEY not found in environment variables.")


# ---------------- RENAME SESSION ---------------- #
def rename_session(user, old_session_name, first_user_message):
    """Rename session using Gemini AI based on first user message."""
    try:
        count = Chat.objects.filter(user=user, session_name=old_session_name, sender="user").count()
        if count > 1:
            return old_session_name

        prompt = (
    f"Provide a short descriptive chat title (max 5 words, no quotes):\n"
    f"{first_user_message}"
)

        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.3, max_output_tokens=15)
        )
        if not response.candidates or not response.candidates[0].content.parts:
            raise ValueError("No title from Gemini")

        new_title = response.candidates[0].content.parts[0].text.strip().replace('"', '').replace("'", "")
        if new_title.lower().startswith("title:"):
            new_title = new_title[6:].strip()

        if not new_title:
            new_title = first_user_message[:30]

        # Ensure unique title
        existing = set(Chat.objects.filter(user=user).values_list('session_name', flat=True))
        counter, base = 2, new_title
        while new_title in existing:
            new_title = f"{base} ({counter})"
            counter += 1

        Chat.objects.filter(user=user, session_name=old_session_name).update(session_name=new_title)
        return new_title
    except Exception as e:
        print("[Rename Error]", e)
        return old_session_name


# ---------------- AUTH ---------------- #
"""Handle user signup form submission and user creation."""
def signup(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            full_name = form.cleaned_data['full_name']
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            username = email
            if User.objects.filter(username=username).exists():
                messages.error(request, "Email already registered!")
                return redirect('signup')
            User.objects.create_user(username=username, email=email, password=password, first_name=full_name)
            messages.success(request, "Account created successfully! Please Sign In.")
            return redirect('signin')
    else:
        form = SignupForm()
    return render(request, 'Chatapp/signup.html', {'form': form})


def signin(request):
    if request.method == "POST":
        form = SignInForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = authenticate(request, username=email, password=password)
            if user:
                login(request, user)
                return redirect('chat')
            messages.error(request, "Invalid email or password!")
            return redirect('signin')
    else:
        form = SignInForm()
    return render(request, 'Chatapp/signin.html', {'form': form})


def signout(request):
    logout(request)
    messages.success(request, "Logged out successfully!")
    return redirect('signin')


# ---------------- MAIN CHAT ---------------- #
@login_required(login_url='signin')
def chat(request):
    """Display chat page and handle new chat creation."""
    if request.method == "POST":
        i = 1
        new_session_name = f"Chat {i}"
        while Chat.objects.filter(user=request.user, session_name=new_session_name).exists():
            i += 1
            new_session_name = f"Chat {i}"

        request.session['current_session'] = new_session_name
        Chat.objects.create(
            user=request.user,
            session_name=new_session_name,
            message="👋 Hello! How can I assist you today?",
            sender="bot"
        )

    session_name = request.session.get('current_session')
    if not session_name:
        session_name = "Chat 1"
        if not Chat.objects.filter(user=request.user, session_name=session_name).exists():
            Chat.objects.create(
                user=request.user,
                session_name=session_name,
                message="👋 Hello! How can I assist you today?",
                sender="bot"
            )
        request.session['current_session'] = session_name

    chats = Chat.objects.filter(user=request.user, session_name=session_name).order_by("timestamp")
    sessions = (
        Chat.objects.filter(user=request.user)
        .exclude(session_name__isnull=True)
        .exclude(session_name="")
        .values_list('session_name', flat=True)
        .distinct()
        .order_by('-timestamp')
    )

    return render(request, 'Chatapp/chat.html', {
        "chats": chats,
        "session_name": session_name,
        "sessions": sessions
    })


# ---------------- GEMINI RESPONSE ---------------- #
def get_gemini_response(prompt):
    try:
        if not GEMINI_API_KEY:
            return "Bot: API key not configured."
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        if not response.candidates or not response.candidates[0].content.parts:
            return "Bot: Could not generate a valid response."
        return response.candidates[0].content.parts[0].text.strip()
    except APIError:
        return "Bot: API connection error."
    except Exception as e:
        return f"Bot: Error - {e}"


# ---------------- FILE UPLOAD + MESSAGE ---------------- #
# pylint: disable=too-many-locals,too-many-branches,too-many-statements
@csrf_exempt
@login_required
def getvalue(request):
    """Handles user messages and file uploads."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    session_name = request.session.get('current_session') or "Chat 1"
    message, uploaded_file = "", None
    if request.content_type.startswith("multipart/form-data"):
        message = request.POST.get("message", "").strip()
        uploaded_file = request.FILES.get("doc_file")
    else:
        import json

        try:
            data = json.loads(request.body)
            message = data.get("message", "").strip()
        except json.JSONDecodeError:
            return JsonResponse({"reply": "Invalid JSON"})

    if not message and not uploaded_file:
        return JsonResponse({"reply": "Please type a message or upload a file!"})

    context_text, old_session_name = "", session_name
    is_first_user_message = (
        session_name.startswith("Chat ")
        and Chat.objects.filter(user=request.user, session_name=session_name, sender="user").count() == 0
        and message
    )

    # ---------- FILE PROCESSING ----------
    if uploaded_file:
        temp_file_path = ""
        try:
            suffix = os.path.splitext(uploaded_file.name)[1] or ".tmp"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                for chunk in uploaded_file.chunks():
                    tmp.write(chunk)
                temp_file_path = tmp.name

            file_text = ""

            if uploaded_file.name.lower().endswith(".docx"):
                loader = UnstructuredWordDocumentLoader(temp_file_path)
                docs = loader.load()
                file_text = "\n".join([d.page_content for d in docs])

            elif uploaded_file.name.lower().endswith((".html", ".htm")):
                loader = UnstructuredHTMLLoader(temp_file_path)
                docs = loader.load()
                file_text = "\n".join([d.page_content for d in docs])

            elif uploaded_file.name.lower().endswith(".pdf"):
                try:
                    loader = UnstructuredPDFLoader(temp_file_path)
                    docs = loader.load()
                    file_text = "\n".join([d.page_content for d in docs])
                except Exception as e:
                    print(f"[UnstructuredPDFLoader failed] {e}")
                    try:
                        with fitz.open(temp_file_path) as pdf_doc:
                            pages = [p.get_text("text") for p in pdf_doc]
                        file_text = "\n".join(pages)
                    except Exception as inner:
                        print(f"[PyMuPDF fallback failed] {inner}")
                        file_text = "⚠️ Unable to extract readable text from PDF."

            else:
                file_text = f"📄 Uploaded file: {uploaded_file.name} (unsupported type)"

            # Save extracted text
            if file_text.strip():
                Chat.objects.create(user=request.user, message=f"📄 Uploaded: {uploaded_file.name}", sender="document", session_name=session_name)
                Chat.objects.create(user=request.user, message=file_text, sender="document", session_name=session_name)
                context_text = file_text
            else:
                Chat.objects.create(user=request.user, message=f"📄 Uploaded: {uploaded_file.name} (no readable text found)", sender="document", session_name=session_name)
                context_text = f"User uploaded a file named {uploaded_file.name}, but no readable text was found."

        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    # ---------- USER MESSAGE ----------
    if message:
        Chat.objects.create(user=request.user, message=message, sender="user", session_name=session_name)

    # Rename session on first message
    if is_first_user_message:
        new_title = rename_session(request.user, old_session_name, message)
        request.session['current_session'] = new_title
        session_name = new_title

    # ---------- GEMINI BOT RESPONSE ----------
    prompt = f"{context_text}\n\nUser: {message}" if context_text else message
    bot_reply = get_gemini_response(prompt)
    Chat.objects.create(user=request.user, message=bot_reply, sender="bot", session_name=session_name)

    return JsonResponse({"reply": bot_reply, "session_name": session_name})


# ---------------- LOAD SESSION ---------------- #
@login_required
def load_session(request, session_name):
    chats = Chat.objects.filter(user=request.user, session_name=session_name).order_by("timestamp")
    data = [{"sender": c.sender, "message": c.message} for c in chats]
    request.session['current_session'] = session_name
    return JsonResponse({"chats": data, "session_name": session_name})


# ---------------- DELETE SESSION ---------------- #
@login_required
@csrf_exempt
def ajax_delete_session(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            session_name = data.get("session_name", "")
            if not session_name:
                return JsonResponse({"deleted": False, "error": "No session name"}, status=400)
            Chat.objects.filter(user=request.user, session_name=session_name).delete()
            if request.session.get('current_session') == session_name:
                request.session['current_session'] = None
            return JsonResponse({"deleted": True})
        except Exception as _:
            return JsonResponse(
    {"error": "An unexpected error occurred. Please try again later."}
)

    return JsonResponse({"deleted": False, "error": "Invalid request"}, status=400)

