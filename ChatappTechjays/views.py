from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from .forms import SignupForm, SignInForm
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json, os, tempfile

from .models import Chat
from django.db import transaction # <-- ADDED IMPORT

# Gemini API
import google.generativeai as genai
from google.genai.errors import APIError
from langchain.document_loaders import UnstructuredWordDocumentLoader, UnstructuredPDFLoader, UnstructuredHTMLLoader

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("⚠️ GEMINI_API_KEY not found in environment variables.")


# ---------------- UTILITY: RENAME SESSION ---------------- #
def rename_session(user, old_session_name, first_user_message):
    """
    Rename a chat session to a meaningful name using Gemini AI based on the first user message.
    Only rename if the session has exactly 1 user message (the first).
    """
    try:
        # Check if the session already has more than one user message
        message_count = Chat.objects.filter(user=user, session_name=old_session_name, sender="user").count()
        if message_count > 1:
            return old_session_name

        prompt = (
            f"Based on the following first message, provide a very concise and informative chat title "
            f"(maximum 5 words). Do not include quotation marks or prefixes like 'Title:'. Just return the title:\n"
            f"{first_user_message}"
        )

        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=15
            )
        )

        # Check if response has usable content
        if not response.candidates or not response.candidates[0].content.parts:
            raise ValueError("No content returned from Gemini.")

        new_title = response.candidates[0].content.parts[0].text.strip()

        # Clean up title
        new_title = new_title.replace('"', '').replace("'", "")
        if new_title.lower().startswith("title:"):
            new_title = new_title[6:].strip()

        # Fallback if Gemini is too brief
        if not new_title or len(new_title.split()) < 2:
            new_title = first_user_message[:30].strip().capitalize()
            if len(new_title) > 30:
                new_title = new_title[:27] + "..."

        # Truncate if too long
        if len(new_title) > 50:
            new_title = new_title[:47] + "..."

        # Ensure unique title for this user
        existing_titles = set(Chat.objects.filter(user=user).values_list('session_name', flat=True))
        if new_title in existing_titles:
            base_title = new_title
            counter = 2
            while f"{base_title} ({counter})" in existing_titles:
                counter += 1
            new_title = f"{base_title} ({counter})"

        # Update session name
        Chat.objects.filter(user=user, session_name=old_session_name).update(session_name=new_title)

        return new_title

    except Exception as e:
        print(f"[Rename Session Error] {e}")
        return old_session_name  # Fallback to old name if anything fails


# ---------------- AUTH ---------------- #
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
            username = email
            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user)
                return redirect('chat')
            else:
                messages.error(request, "Invalid email or password!")
                return redirect('signin')
    else:
        form = SignInForm()
    return render(request, 'Chatapp/signin.html', {'form': form})


def signout(request):
    logout(request)
    messages.success(request, "Logged out successfully!")
    return redirect('signin')


# ---------------- MAIN CHAT (RECTIFIED) ---------------- #
@login_required(login_url='signin')
def chat(request):
    """Display chat page and handle new chat creation"""
    
    # --- New Session Logic ---
    if request.method == "POST":
        # Find the next available "Chat X" name to use as a temporary placeholder
        i = 1
        new_session_name = f"Chat {i}"
        while Chat.objects.filter(user=request.user, session_name=new_session_name).exists():
            i += 1
            new_session_name = f"Chat {i}"
        
        request.session['current_session'] = new_session_name

        # Initial bot message is created *only* when a user clicks 'New Chat'
        Chat.objects.create(
            user=request.user,
            session_name=new_session_name,
            message="Hello! How can I assist you today?",
            sender="bot"
        )
        return redirect('chat')

    # --- Load Session Logic (RECTIFIED) ---
    session_name = request.GET.get('session') or request.session.get('current_session') or None
    
    # 1. If no session is active (first visit or after deleting), try to load the most recent one.
    if not session_name:
        most_recent_session = Chat.objects.filter(user=request.user).exclude(session_name__isnull=True).exclude(session_name="").order_by('-timestamp').values_list('session_name', flat=True).first()
        
        if most_recent_session:
            session_name = most_recent_session
        else:
            # 2. If no history exists at all, use "Chat 1" as the default start name
            session_name = "Chat 1"
            # Ensure the "Chat 1" session is initialized with the bot message only if it doesn't exist.
            if not Chat.objects.filter(user=request.user, session_name=session_name).exists():
                 Chat.objects.create(
                     user=request.user,
                     session_name=session_name,
                     message="Hello! How can I assist you today?",
                     sender="bot"
                 )
    
    # 3. Handle the case where the saved session name (current_session) is an old temporary name ("Chat X")
    # that has been renamed. We need to fall back to the most recent actual session name.
    elif session_name.startswith("Chat ") and not Chat.objects.filter(user=request.user, session_name=session_name).exists():
        most_recent_session = Chat.objects.filter(user=request.user).exclude(session_name__isnull=True).exclude(session_name="").order_by('-timestamp').values_list('session_name', flat=True).first()
        if most_recent_session:
             session_name = most_recent_session
        
    request.session['current_session'] = session_name

    chats = Chat.objects.filter(user=request.user, session_name=session_name).order_by("timestamp")
    
    # Exclude None and empty string session names for sidebar history
    sessions = Chat.objects.filter(user=request.user).exclude(session_name__isnull=True).exclude(session_name="").values_list('session_name', flat=True).distinct().order_by('-timestamp')

    return render(request, 'Chatapp/chat.html', {
        "chats": chats,
        "session_name": session_name,
        "sessions": sessions
    })


@login_required
def profile(request):
    return render(request, 'Chatapp/profile.html')


# ---------------- GEMINI RESPONSE ---------------- #
def get_gemini_response(prompt):
    try:
        if not GEMINI_API_KEY:
            return "Bot: API key not configured."
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt, generation_config=genai.GenerationConfig(temperature=0.7, max_output_tokens=10000))
        return response.text.strip() if response.candidates and response.candidates[0].content.parts else "Bot: Could not generate a valid response."
    except APIError:
        return "Bot: API connection error."
    except Exception as e:
        return f"Bot: Error - {e}"


# ---------------- FILE UPLOAD + MESSAGE ---------------- #
@csrf_exempt
@login_required
def getvalue(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    message, uploaded_file = "", None
    # Use the session name from the Django session, falling back to 'Chat 1'
    session_name = request.session.get('current_session') or "Chat 1" 

    if request.content_type.startswith("multipart/form-data"):
        message = request.POST.get("message", "").strip()
        uploaded_file = request.FILES.get("doc_file")
    else:
        try:
            data = json.loads(request.body)
            message = data.get("message", "").strip()
        except json.JSONDecodeError:
            return JsonResponse({"reply": "Invalid JSON."})

    if not message and not uploaded_file:
        return JsonResponse({"reply": "Please type a message or upload a file!"})

    context_text = ""
    is_first_user_message = False
    old_session_name = session_name 

    # Check if this is the very first user message in a new temporary session
    if session_name.startswith("Chat ") and Chat.objects.filter(user=request.user, session_name=session_name, sender="user").count() == 0 and message:
        is_first_user_message = True

    # Save uploaded file text if any (omitted for brevity, assume this is correct)
    if uploaded_file:
        temp_file_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=uploaded_file.name) as tmp:
                for chunk in uploaded_file.chunks():
                    tmp.write(chunk)
                temp_file_path = tmp.name

            if uploaded_file.name.endswith(".docx"):
                loader = UnstructuredWordDocumentLoader(temp_file_path)
            elif uploaded_file.name.endswith(".pdf"):
                loader = UnstructuredPDFLoader(temp_file_path)
            elif uploaded_file.name.endswith((".html", ".htm")):
                loader = UnstructuredHTMLLoader(temp_file_path)
            else:
                loader = None

            if loader:
                documents = loader.load()
                file_text = "\n".join([doc.page_content for doc in documents])
                # Store the extracted text as a 'document' sender message
                Chat.objects.create(user=request.user, message=file_text, sender="document", session_name=session_name)
                context_text = file_text
            else:
                # Store a placeholder if content couldn't be extracted
                Chat.objects.create(user=request.user, message=f"📄 Uploaded file: {uploaded_file.name}", sender="document", session_name=session_name)
                context_text = f"User uploaded a file named {uploaded_file.name}, content not extracted."
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
    
    # Save user message if any
    if message:
        Chat.objects.create(user=request.user, message=message, sender="user", session_name=session_name)

    # Rename session if it's the first user message
    if is_first_user_message:
        # Pass the original "Chat X" name to the rename function
        new_title = rename_session(request.user, old_session_name, message)
        
        # Update session variables with the new, descriptive name
        request.session['current_session'] = new_title
        session_name = new_title # Update session_name for the bot response saving

    # Prepare prompt for Gemini AI bot response
    final_prompt = f"You are an AI assistant. Context from document:\n{context_text}\n\nUser asks: {message}" if context_text else message
    bot_reply = get_gemini_response(final_prompt)
    Chat.objects.create(user=request.user, message=bot_reply, sender="bot", session_name=session_name)

    return JsonResponse({"reply": bot_reply, "session_name": session_name})


# ---------------- AJAX: LOAD SESSION ---------------- #
@login_required
def load_session(request, session_name):
    """Return full old chat history as JSON"""
    chats = Chat.objects.filter(user=request.user, session_name=session_name).order_by("timestamp")
    data = [{"sender": c.sender, "message": c.message} for c in chats]
    request.session['current_session'] = session_name
    return JsonResponse({"chats": data, "session_name": session_name})


# ---------------- AJAX: DELETE SESSION ---------------- #
@login_required
@csrf_exempt
def ajax_delete_session(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            session_name = data.get("session_name", "").strip()

            # Delete all chats with empty session name if requested
            if session_name.lower() == "empty": 
                Chat.objects.filter(user=request.user, session_name__isnull=True).delete()
                Chat.objects.filter(user=request.user, session_name="").delete()
                if not request.session.get('current_session'):
                    request.session['current_session'] = None
                return JsonResponse({"deleted": True, "session_name": "empty"})

            # Normal deletion
            if not session_name:
                return JsonResponse({"deleted": False, "error": "No session name provided"}, status=400)

            Chat.objects.filter(user=request.user, session_name=session_name).delete()

            if request.session.get('current_session') == session_name:
                request.session['current_session'] = None

            return JsonResponse({"deleted": True, "session_name": session_name})
        except Exception as e:
            return JsonResponse({"deleted": False, "error": str(e)}, status=500)

    return JsonResponse({"deleted": False, "error": "Invalid request"}, status=400)