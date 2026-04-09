document.addEventListener('DOMContentLoaded', function() {
    const chatContainer = document.getElementById('chat-container');
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendButton = document.getElementById('send-button');
    const chatToggle = document.getElementById('chat-toggle');
    const closeChat = document.getElementById('close-chat');
    const resetChat = document.getElementById('reset-chat');
    const suggestionChips = document.querySelectorAll('.suggestion-chip');
    
    // Check if we're on the test page
    const isTestPage = document.body.classList.contains('test-chat-page');
    
    // Initialize Voice/Speech settings (Placeholder for future expansion)
    let speechEnabled = false;

    function hideSuggestions() {
        const suggestions = document.querySelector('.quick-suggestions');
        if (suggestions) suggestions.style.display = 'none';
    }

    // Initial setup
    // Removed loadMessages() call

    // Toggle Chat
    if (chatToggle) {
        chatToggle.addEventListener('click', () => {
            const isHidden = chatContainer.classList.contains('hidden');
            if (isHidden) {
                chatContainer.classList.remove('hidden');
                // Play a subtle entrance sound if desired, or focus input
                setTimeout(() => chatInput.focus(), 500);
            } else {
                chatContainer.classList.add('hidden');
            }
        });
    }

    if (closeChat) {
        closeChat.addEventListener('click', () => {
            chatContainer.classList.add('hidden');
        });
    }

    // Handle Suggestions
    suggestionChips.forEach(chip => {
        chip.addEventListener('click', () => {
            const text = chip.textContent;
            chatInput.value = text;
            sendMessage();
        });
    });

    // Send logic
    sendButton.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    async function sendMessage() {
        const message = chatInput.value.trim();
        if (!message) return;

        // Add user message
        addMessage('user', message);
        chatInput.value = '';
        
        // Hide suggestions on first interaction
        hideSuggestions();
        
        // Disable UI
        setLoading(true);

        // Show Typing Indicator
        showTypingIndicator();

        try {
            const response = await fetch('/api/chat/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken') || ''
                },
                body: JSON.stringify({ message: message }),
                credentials: 'same-origin'
            });

            const data = await response.json();
            
            removeTypingIndicator();
            setLoading(false);

            if (data.success) {
                addMessage('bot', data.response);
            } else {
                addMessage('bot', "I'm sorry, I'm having trouble connecting to my brain right now. Please try again later.");
            }
        } catch (error) {
            console.error('Chat Error:', error);
            removeTypingIndicator();
            setLoading(false);
            addMessage('bot', "Oops! Something went wrong on my end. I'll be back shortly.");
        }
    }

    function addMessage(sender, text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}-message`;
        msgDiv.textContent = text;
        
        // For test page consistency
        if (isTestPage) {
            msgDiv.style.margin = '8px 0';
        }

        chatMessages.appendChild(msgDiv);
        scrollToBottom();
    }

    function showTypingIndicator() {
        const indicator = document.createElement('div');
        indicator.id = 'typing-indicator';
        indicator.innerHTML = `
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        `;
        chatMessages.appendChild(indicator);
        scrollToBottom();
    }

    function removeTypingIndicator() {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) indicator.remove();
    }

    function setLoading(isLoading) {
        chatInput.disabled = isLoading;
        sendButton.disabled = isLoading;
        if (!isLoading) chatInput.focus();
    }

    function scrollToBottom() {
        chatMessages.scrollTo({
            top: chatMessages.scrollHeight,
            behavior: 'smooth'
        });
    }

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
});
