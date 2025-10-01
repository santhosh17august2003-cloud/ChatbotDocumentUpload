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

# Gemini API
import google.generativeai as genai
from google.genai.errors import APIError
from langchain.document_loaders import UnstructuredWordDocumentLoader

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("⚠️ GEMINI_API_KEY not found in environment variables. Please set it securely.")
else:
    genai.configure(api_key=GEMINI_API_KEY)


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

            User.objects.create_user(
                username=username, email=email, password=password, first_name=full_name
            )
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


# ---------------- MAIN CHAT ---------------- #
@login_required(login_url='signin') 
def chat(request):
    return render(request, 'Chatapp/chat.html')


@login_required
def profile(request):
    return render(request, 'Chatapp/profile.html')


@login_required
def chat_history(request):
    chats = Chat.objects.filter(user=request.user).order_by('timestamp')
    return render(request, 'Chatapp/chathistory.html', {'chats': chats})


# ---------------- GEMINI FUNCTIONS ---------------- #
def get_gemini_response(prompt):
    try:
        if not GEMINI_API_KEY:
            return "Bot: Sorry, API key not configured."

        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.7,
                max_output_tokens=1000
            )
        )

        if response.candidates and response.candidates[0].content.parts:
            return response.text.strip()
        else:
            return "Bot: Sorry, I couldn't generate a valid response."

    except APIError:
        return "Bot: API connection error."
    except Exception as e:
        return f"Bot: Error - {e}"

# ---------------- FILE UPLOAD + QUERY ---------------- #
@csrf_exempt
@login_required
@csrf_exempt
@login_required
def getvalue(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    message = ""
    uploaded_file = None

    # Check if form-data (file upload) or JSON (text only)
    if request.content_type.startswith("multipart/form-data"):
        message = request.POST.get("message", "").strip()
        uploaded_file = request.FILES.get("doc_file")
    else:
        try:
            data = json.loads(request.body)
            message = data.get("message", "").strip()
        except json.JSONDecodeError:
            return JsonResponse({"reply": "Invalid JSON."})

    # If neither text nor file, prompt user
    if not message and not uploaded_file:
        return JsonResponse({"reply": "Please type a message or upload a file!"})

    # Initialize context text
    context_text = ""

    # Handle uploaded file
    if uploaded_file:
        import tempfile
        from langchain.document_loaders import UnstructuredPDFLoader, UnstructuredWordDocumentLoader, UnstructuredHTMLLoader

        # Save file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=uploaded_file.name) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            temp_file_path = tmp.name

        try:
            # Load based on file type
            if uploaded_file.name.endswith(".docx"):
                loader = UnstructuredWordDocumentLoader(temp_file_path)
            elif uploaded_file.name.endswith(".pdf"):
                loader = UnstructuredPDFLoader(temp_file_path)
            elif uploaded_file.name.endswith(".html") or uploaded_file.name.endswith(".htm"):
                loader = UnstructuredHTMLLoader(temp_file_path)
            else:
                # For images or unsupported types, just note upload
                loader = None

            if loader:
                documents = loader.load()
                file_text = "\n".join([doc.page_content for doc in documents])
                Chat.objects.create(user=request.user, message=file_text, sender="document")
                context_text = file_text
            else:
                Chat.objects.create(user=request.user, message=f"📄 Uploaded file: {uploaded_file.name}", sender="document")
                context_text = f"User uploaded a file named {uploaded_file.name}, content not extracted."

        finally:
            os.remove(temp_file_path)

    # Save user message if exists
    if message:
        Chat.objects.create(user=request.user, message=message, sender="user")

    # Combine document context and user message
    if context_text:
        final_prompt = (
            f"You are an AI assistant. The user uploaded the following documents:\n\n"
            f"{context_text}\n\n"
            f"Now the user is asking: {message}\n\n"
            f"Answer using the document context if possible."
        )
    else:
        final_prompt = message

    # Get response from Gemini
    bot_reply = get_gemini_response(final_prompt)
    Chat.objects.create(user=request.user, message=bot_reply, sender="bot")

    return JsonResponse({"reply": bot_reply})
