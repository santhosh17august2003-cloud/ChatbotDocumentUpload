console.log("Custom JS loaded ✅");

const sendBtn = document.querySelector(".sendBtn");
const inputField = document.getElementById("userInput");
const chatBox = document.querySelector(".chat-box");

// Send message on button click
sendBtn.addEventListener("click", function() {
    const message = inputField.value.trim();
    if (!message) return;

    // Show user message in chat
    addMessageToChat("user", message);

    inputField.value = ""; // Clear input

    // Send message to Django via fetch
    postJson({ message: message });
});

// Function to add message to chat box
function addMessageToChat(sender, text) {
    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message", sender);
    messageDiv.innerHTML = `<div class="bubble">${text}</div>`;
    chatBox.appendChild(messageDiv);
    chatBox.scrollTop = chatBox.scrollHeight; // Auto scroll
}

// Async function to post JSON to Django
async function postJson(data) {
    const url = '/getvalue/'; // Django endpoint
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCookie("csrftoken")
            },
            credentials: "include",
            body: JSON.stringify(data)
        });

        const result = await response.json();   
        console.log("Success:", result);

        // Show bot reply
        if (result.reply) {
            addMessageToChat("bot", result.reply);
        }

    } catch (error) {
        console.error("Error:", error);
    }
}

// Helper function to get CSRF token Django sets in cookies
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let cookie of cookies) {
            cookie = cookie.trim();
            if (cookie.startsWith(name + "=")) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}
