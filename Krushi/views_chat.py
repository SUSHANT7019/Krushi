import logging
logger = logging.getLogger(__name__)

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.shortcuts import render
import json
import os
try:
    import google.genai as genai
    _GENAI_PKG = 'google.genai'
except Exception:
    try:
        import google.generativeai as genai
        _GENAI_PKG = 'google.generativeai'
    except Exception:
        genai = None
        _GENAI_PKG = None

import re
from typing import List
import string

# Initialize Gemini client if available
if getattr(settings, 'GOOGLE_API_KEY', None):
    try:
        if genai is not None and getattr(genai, 'configure', None):
            genai.configure(api_key=settings.GOOGLE_API_KEY)
        else:
            # Some installs require env var instead of SDK configure
            os.environ.setdefault('GOOGLE_API_KEY', settings.GOOGLE_API_KEY)
    except Exception as e:
        logger.warning(f"Error initializing Gemini ({_GENAI_PKG}): {e}")

def generate_chat_response(prompt):
    """Generate response by KrushiBot."""
    if not hasattr(settings, 'GOOGLE_API_KEY') or not settings.GOOGLE_API_KEY:
        return "Error: API key not configured. Please contact support."

    if genai is None:
        return "Error: GenAI client not available. Please install 'google-genai' or 'google-generativeai'."

    try:
        # Check if using the new google.genai V1 client
        if _GENAI_PKG == 'google.genai':
            client = genai.Client(api_key=settings.GOOGLE_API_KEY)
            response = client.models.generate_content(
                model='gemini-flash-latest', 
                contents=prompt
            )
            return getattr(response, 'text', '') or "(no response)"
        else:
            # Fallback to the old google.generativeai SDK
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(prompt)
            return getattr(response, 'text', '') or "(no response)"

    except Exception as e:
        return f"Error connecting to AI service: {str(e)}"


def _normalize_text(text: str) -> str:
    """Lowercase and strip extra whitespace/punctuation around words."""
    if not text:
        return ""
    text = text.strip().lower()
    # Replace punctuation with spaces except within numbers/percent like 20% npk
    table = str.maketrans({ch: " " for ch in string.punctuation})
    text = text.translate(table)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _shape_single_word_query(text: str) -> str:
    """If user entered a single word, expand into a conversational clarifying query."""
    t = _normalize_text(text)
    tokens = t.split()
    if len(tokens) == 1:
        w = tokens[0]
        # Instead of just explaining, we ask the user what they need specifically about this topic
        return (
            f"The user just typed '{w}'. Acknowledge that you are an expert in {w} (if related to agriculture) "
            "and ask if they want to know about cultivation practices, disease management, or current market availability for it."
        )
    return text



def generate_response_with_history(prompt: str, history: List[dict] = None) -> str:
    """Generate response via API with history context."""
SYSTEM_INSTRUCTION = (
    "You are KrushiBot, the premier AI Farming Assistant. Your expertise is strictly limited to agriculture, "
    "crops, soil health, irrigation, pest control, fertilizers, weather impacts, and livestock management. "
    "If a question is NOT related to agriculture (e.g., general news, math, music, coding), politely decline "
    "by saying: 'I'm sorry, KrushiBot is specialized in agricultural expertise and cannot assist with that topic.' "
    "Keep responses concise (max 3 sentences), practical, and professional. Always match the user's language."
)

def generate_ai_response(prompt: str, context: str = "") -> str:
    """Generate response via API with a small context."""
    full_prompt = f"{SYSTEM_INSTRUCTION}\n\nContext: {context}\nUser: {prompt}\nKrushiBot:"

    if not getattr(settings, 'GOOGLE_API_KEY', None):
        return "Error: API key not configured. Please contact support."

    try:
        return generate_chat_response(full_prompt)
    except Exception as api_err:
        return f"Error generating response: {str(api_err)}"

@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def chat_api(request):
    """
    API endpoint for handling chat messages.
    Now stateless with small context.
    """
    if request.method == 'OPTIONS':
        response = JsonResponse({}, status=200)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, X-CSRFToken'
        response['Access-Control-Max-Age'] = '86400'
        return response
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_message = data.get('message', '').strip()

            if not user_message:
                return JsonResponse({'error': 'Empty message', 'success': False}, status=400)
            
            # Small Context: Identify platform and user if logged in
            platform_context = "User is browsing KrushiPro, an AI-powered agricultural portal."
            if request.user.is_authenticated:
                user_context = f"User's name is {request.user.username}."
                context = f"{platform_context} {user_context}"
            else:
                context = platform_context

            # Single-word shaping
            shaped = _shape_single_word_query(user_message)

            # Generate response with context
            response_text = generate_ai_response(shaped, context)
            
            response = JsonResponse({
                'response': response_text,
                'success': True,
                'meta': {
                    'original': user_message
                }
            })
            response['Access-Control-Allow-Origin'] = '*'
            return response
            
        except json.JSONDecodeError:
            resp = JsonResponse({'error': 'Invalid JSON', 'success': False}, status=400)
            resp['Access-Control-Allow-Origin'] = '*'
            return resp
        except Exception as e:
            resp = JsonResponse({'error': str(e), 'success': False}, status=500)
            resp['Access-Control-Allow-Origin'] = '*'
            return resp
    
    resp = JsonResponse({'error': 'Method not allowed', 'success': False}, status=405)
    resp['Access-Control-Allow-Origin'] = '*'
    return resp
