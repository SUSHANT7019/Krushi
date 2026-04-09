import logging
logger = logging.getLogger(__name__)

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.db import connections
from django.db.utils import OperationalError
from django.db.models import Q
from django.core.paginator import Paginator
from django.conf import settings
import json
import os
import pickle
from threading import Lock
import numpy as np
import re
import base64
import requests
# --- Gemini SDK Setup ---
# 1. Import detection for google.genai (Main) and google.generativeai (Fallback)
try:
    import google.genai as genai
    from google.genai import types as genai_types
    _GENAI_PKG = 'google.genai'
except (ImportError, AttributeError):
    try:
        import google.generativeai as genai
        genai_types = None
        _GENAI_PKG = 'google.generativeai'
    except (ImportError, AttributeError):
        genai = None
        genai_types = None
        _GENAI_PKG = None
from typing import Any, Dict, Optional
from django.views.decorators.http import require_POST,require_GET
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
import pandas as pd
# Razorpay is accessed via services.razorpay_service (not imported directly here)

from .models import User, Category, Product, Review, Feedback, Cart, CartItem, Order, OrderItem, NewsletterSubscription, EmailOTPVerification, PaymentTransaction
from .forms import (
    CustomUserCreationForm,
    CustomAuthenticationForm,
    FeedbackForm,
    ReviewForm,
    ContactForm,
    SellProductForm,
    FertilizerListingForm,
    ForgotPasswordForm,
    VerifyOTPForm,
    ResetPasswordForm,
    UserProfileForm,
)
from .services.crop_planner import generate_crop_plan, get_available_crops
from .models import PasswordResetOTP
# 3. Client cache and timeout tracking
_genai_client = None
_genai_client_timeout_ms = None

# 4. Reusable client helper with timeout and units fix
def get_genai_client(timeout_ms: int = 120000):
    """
    Returns a configured Gemini client. Recreates the client if requested timeout changes.
    """
    global _genai_client, _genai_client_timeout_ms
    
    api_key = getattr(settings, 'GOOGLE_API_KEY', None)
    if not api_key:
        raise ValueError("GOOGLE_API_KEY is not configured in Django settings.")

    if _GENAI_PKG == 'google.genai':
        # Rebuild if timeout changed (units: milliseconds) or client missing
        if _genai_client is None or _genai_client_timeout_ms != timeout_ms:
            _genai_client = genai.Client(
                api_key=api_key,
                http_options={'timeout': timeout_ms}
            )
            _genai_client_timeout_ms = timeout_ms
        return _genai_client
    elif _GENAI_PKG == 'google.generativeai':
        # Legacy SDK: Configure globally
        genai.configure(api_key=api_key)
        return genai
    
    raise ImportError("Gemini integration is disabled: No compatible SDK found.")

# 5. Startup initialization block with clean logging
if _GENAI_PKG == 'google.genai':
    logger.info("Gemini Integration: Initialized with new SDK (google.genai)")
elif _GENAI_PKG == 'google.generativeai':
    logger.info("Gemini Integration: Initialized with legacy SDK (google.generativeai)")
else:
    logger.warning("Gemini Integration: No supported SDK detected. Image analysis will be unavailable.")

# --- Crop recommendation model (pretrained pickle) ---
_crop_model = None
_crop_model_lock = Lock()

def _load_crop_model():
    global _crop_model
    if _crop_model is not None:
        return _crop_model
    with _crop_model_lock:
        if _crop_model is None:
            try:
                # Model path: Crop_Pridiction/crop_recommendation_model.pkl
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                model_path = os.path.join(base_dir, 'Crop_Pridiction', 'crop_recommendation_model.pkl')
                # In case the structure differs when running from project root
                if not os.path.exists(model_path):
                    project_root = os.path.dirname(base_dir)
                    alt_path = os.path.join(project_root, 'Crop_Pridiction', 'crop_recommendation_model.pkl')
                    if os.path.exists(alt_path):
                        model_path = alt_path
                with open(model_path, 'rb') as f:
                    _crop_model = pickle.load(f)
            except Exception as e:
                logger.warning(f"Crop model load failed: {e}")
                _crop_model = None
    return _crop_model

def _predict_crop(n: float, p: float, k: float, temperature: float, humidity: float, ph: float, rainfall: float):
    """Predict crop label using the pretrained model. Returns string or None."""
    model = _load_crop_model()
    if model is None:
        logger.warning("❌ Model is None in _predict_crop")
        return None
        
    try:
        # Log input values for debugging
        input_data = [float(n), float(p), float(k), float(temperature), float(humidity), float(ph), float(rainfall)]
        logger.warning(f"🔍 Model input values: {input_data}")
        
        # Create input array with feature names if available
        X = np.array([input_data], dtype=float)
        
        # Log model type and available methods
        logger.warning(f"🔍 Model type: {type(model).__name__}")
        if hasattr(model, 'predict'):
            logger.warning("✅ Model has predict method")
        
        # Make prediction
        try:
            # First try with feature names if model was trained with them
            if hasattr(model, 'feature_names_in_'):

                X_df = pd.DataFrame(X, columns=model.feature_names_in_)
                pred = model.predict(X_df)
            else:
                pred = model.predict(X)
                
            logger.warning(f"🔍 Raw prediction: {pred}")
            
            # Handle different prediction output formats
            if hasattr(pred, 'shape'):
                logger.warning(f"🔍 Prediction shape: {pred.shape}")
                
            if isinstance(pred, (np.ndarray, list)) and len(pred) > 0:
                label = pred[0] if not isinstance(pred[0], (np.ndarray, list)) else pred[0][0]
                logger.warning(f"✅ Prediction successful. Label: {label}, Type: {type(label)}")
                return str(label).strip()
                
            return str(pred).strip()
            
        except Exception as pred_error:
            logger.warning(f"⚠️ First prediction attempt failed: {pred_error}")
            # Fallback to simple prediction if feature names cause issues
            try:
                pred = model.predict(X)
                if isinstance(pred, (np.ndarray, list)) and len(pred) > 0:
                    label = pred[0] if not isinstance(pred[0], (np.ndarray, list)) else pred[0][0]
                    logger.warning(f"✅ Fallback prediction successful. Label: {label}")
                    return str(label).strip()
                return str(pred).strip()
            except Exception as fallback_error:
                logger.warning(f"❌ Fallback prediction also failed: {fallback_error}")
                raise fallback_error
        
    except Exception as e:
        import traceback
        logger.warning(f"❌ Crop prediction failed: {e}")
        logger.warning("Stack trace:")
        traceback.print_exc()
        return None

def _safe_json_from_text(text: str) -> Dict[str, Any]:
    """Try to parse JSON from model output, with fallback to extracting the first JSON block."""
    try:
        return json.loads(text)
    except Exception:
        pass
    # Extract first {...} block
    try:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
    except Exception:
        pass
    return {
        "species": None,
        "health_status": "Unknown",
        "detected_diseases": [],
        "pests": [],
        "care_tips": [],
        "fertilizer_recommendations": []
    }

def _as_string_list(value) -> list[str]:
    """Normalize mixed lists (strings/objects) to a list of human-readable strings.

    This prevents frontend rendering issues like "[object Object]" by converting
    any objects into concise strings using common fields or key:value pairs.
    """
    out: list[str] = []
    if isinstance(value, list):
        for x in value:
            if isinstance(x, str):
                s = x.strip()
            elif isinstance(x, dict):
                # Prefer common text-bearing fields if present
                s = (
                    str(x.get('text') or x.get('recommendation') or x.get('note') or x.get('summary')
                        or x.get('description') or x.get('tip') or '').strip()
                )
                if not s:
                    # Fallback: join key:value pairs
                    parts = []
                    for k, v in x.items():
                        if v is None or v == '':
                            continue
                        parts.append(f"{k}: {v}")
                    s = ", ".join(parts).strip()
            else:
                s = str(x).strip()

            if s:
                out.append(s)
    elif isinstance(value, dict) or isinstance(value, str):
        out = _as_string_list([value])
    else:
        out = []
    return out



import time
from django.conf import settings

def _gemini_analyze_image(image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    """
    Call Gemini with resilience: automatic retries and fallback models.
    """
    prompt = (
        "You are an expert agronomy assistant. Analyze the plant/crop image and return STRICT JSON only with keys: "
        "species (string), health_status (string among ['Healthy','Stressed','Diseased','Unknown']), "
        "detected_diseases (array of objects with name, confidence (0-1), description, recommended_treatments (array)), "
        "pests (array of objects with name, confidence (0-1), control (array)), "
        "care_tips (array of strings), "
        "fertilizer_recommendations (array of strings specific to species and condition). "
        "Output JSON only, no prose."
    )

    # Model sequence: Primary -> Fallback
    models_to_try = ['gemini-2.5-flash','gemini-flash-latest']
    max_retries = 3
    
    last_error_msg = "Unknown error"
    
    for model_name in models_to_try:
        current_delay = 1.0  # seconds
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Gemini Analysis: Attempting {model_name} (Attempt {attempt})")
                
                if _GENAI_PKG == 'google.genai':
                    client = get_genai_client(timeout_ms=120000)
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=[
                            genai_types.Part.from_text(text=prompt),
                            genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                        ],
                        config=genai_types.GenerateContentConfig(
                            temperature=0.2,
                            response_mime_type="application/json"
                        )
                    )
                    text = resp.text
                elif _GENAI_PKG == 'google.generativeai':
                    get_genai_client() 
                    model = genai.GenerativeModel(model_name)
                    resp = model.generate_content(
                        [prompt, {"mime_type": mime_type, "data": image_bytes}],
                        generation_config={"temperature": 0.2, "response_mime_type": "application/json"},
                        request_options={"timeout": 120.0}
                    )
                    text = resp.text
                else:
                    return {"error": "Gemini SDK missing.", "status_code": 500}

                if text:
                    logger.info(f"Gemini Analysis: Success using {model_name} on attempt {attempt}")
                    return _safe_json_from_text(text)
                
                last_error_msg = "Empty response from API"
                
            except Exception as e:
                err_str = str(e).lower()
                last_error_msg = str(e)
                
                # Check for transient errors (503, Overloaded, Resource Exhausted, Timeout)
                is_transient = any(x in err_str for x in ["503", "overloaded", "unavailable", "deadline", "timeout", "429"])
                
                if not is_transient:
                    logger.error(f"Gemini Analysis: Non-transient error in {model_name}: {last_error_msg}")
                    return {"error": f"AI model failed: {last_error_msg}", "status_code": 500}
                
                logger.warning(f"Gemini Analysis: Transient error in {model_name} (Attempt {attempt}): {last_error_msg}")
                
                if attempt < max_retries:
                    logger.info(f"Gemini Analysis: Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= 2  # Exponential backoff
                else:
                    logger.warning(f"Gemini Analysis: {model_name} exhausted all retries.")

        # If we are here, model_name failed sessions. Try next model if applicable.
        logger.info(f"Gemini Analysis: Switching to fallback model after {model_name} failure.")

    # All models and retries failed
    final_status = 503 if "overloaded" in last_error_msg.lower() or "503" in last_error_msg.lower() else 504 if "timeout" in last_error_msg.lower() else 500
    return {"error": last_error_msg, "status_code": final_status}

def home(request):
    """Home page view"""
    # Get featured products
    featured_products = Product.objects.filter(is_active=True).order_by('-rating')[:4]
    
    # Get categories
    categories = Category.objects.all()[:6]
    
    context = {
        'featured_products': featured_products,
        'categories': categories,
    }
    return render(request, 'index.html', context)

def generate_registration_otp(user):
    """
    Generate a 6-digit OTP, hash it, and save it to the database.
    Invalidates any previous registration OTPs for the user.
    """
    import random
    from django.utils import timezone
    
    # Invalidate existing OTPs
    EmailOTPVerification.objects.filter(user=user, is_verified=False).delete()
    
    # Generate 6-digit OTP
    otp = ''.join(random.choices('0123456789', k=6))
    otp_hash = make_password(otp)
    
    # Create new record
    EmailOTPVerification.objects.create(
        user=user,
        otp_hash=otp_hash
    )
    
    return otp

def send_registration_otp_email(user, otp):
    """Send OTP directly to user's email using HTML template"""
    from django.template.loader import render_to_string
    from django.utils.html import strip_tags
    
    subject = 'Verify your account - Krushi'
    html_message = render_to_string('emails/registration_otp.html', {'otp': otp})
    plain_message = strip_tags(html_message)
    from_email = settings.DEFAULT_FROM_EMAIL
    
    try:
        send_mail(subject, plain_message, from_email, [user.email], html_message=html_message)
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {user.email}: {e}")
        return False

def send_password_reset_email(user, otp):
    """Send password reset OTP directly to user's email using HTML template"""
    from django.template.loader import render_to_string
    from django.utils.html import strip_tags
    
    subject = 'Reset your password - Krushi'
    html_message = render_to_string('emails/password_reset_otp.html', {'otp': otp})
    plain_message = strip_tags(html_message)
    from_email = settings.DEFAULT_FROM_EMAIL
    
    try:
        send_mail(subject, plain_message, from_email, [user.email], html_message=html_message)
        return True
    except Exception as e:
        logger.error(f"Failed to send password reset email to {user.email}: {e}")
        return False

def shop(request):
    """Shop page view with products from database"""
    # Get search and filter parameters
    search_query = request.GET.get('search', '')
    category_filter = request.GET.get('category', '')
    sort_by = request.GET.get('sort', 'newest')
    
    # Base queryset - Only show active and approved products
    products = Product.objects.filter(is_active=True, is_approved=True)
    
    # Apply search filter
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) | 
            Q(description__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )
    
    # Apply category filter
    if category_filter and category_filter != 'all':
        products = products.filter(category__name=category_filter)
    
    # Apply sorting
    if sort_by == 'price_low':
        products = products.order_by('price')
    elif sort_by == 'price_high':
        products = products.order_by('-price')
    elif sort_by == 'rating':
        products = products.order_by('-rating')
    elif sort_by == 'name':
        products = products.order_by('name')
    else:  # newest
        products = products.order_by('-created_at')
    
    # Pagination
    paginator = Paginator(products, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get all categories for filter
    categories = Category.objects.all()
    
    context = {
        'products': page_obj,
        'categories': categories,
        'search_query': search_query,
        'category_filter': category_filter,
        'sort_by': sort_by,
    }
    return render(request, 'shop.html', context)


@login_required
def sell_product(request):
    """Allow authenticated users to list a product for sale."""
    if request.method == 'POST':
        form = SellProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.seller = request.user
            # User-submitted products require admin approval
            product.is_approved = False
            product.save()
            
            # Send email to farmer
            try:
                from django.template.loader import render_to_string
                from django.utils.html import strip_tags
                from django.contrib.sites.shortcuts import get_current_site
                
                current_site = get_current_site(request)
                subject = 'Selling Request Received - Krushi'
                html_message = render_to_string('emails/sell_request_received.html', {
                    'user': request.user,
                    'product': product,
                    'site_url': f"http://{current_site.domain}"
                })
                plain_message = strip_tags(html_message)
                
                send_mail(
                    subject,
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [request.user.email],
                    html_message=html_message,
                    fail_silently=True,
                )
            except Exception as e:
                logger.error(f"Error sending sell request email: {str(e)}")

            messages.success(request, 'Product listed successfully and is pending approval. You will receive an email confirmation shortly.')
            return redirect('my_products')
    else:
        form = SellProductForm()
    return render(request, 'sell_product.html', {'form': form})


@login_required
def my_products(request):
    products = Product.objects.filter(seller=request.user).order_by('-created_at')
    total_count = products.count()
    active_count = products.filter(is_active=True).count()
    context = {'products': products, 'total_count': total_count, 'active_count': active_count}
    return render(request, 'my_products.html', context)


@login_required
def edit_product(request, product_id):
    product = get_object_or_404(Product, id=product_id, seller=request.user)
    if request.method == 'POST':
        form = SellProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated successfully.')
            return redirect('my_products')
    else:
        form = SellProductForm(instance=product)
    return render(request, 'edit_product.html', {'form': form, 'product': product})


@login_required
def delete_product(request, product_id):
    try:
        product = Product.objects.get(id=product_id, seller=request.user)
    except Product.DoesNotExist:
        messages.error(request, 'Product not found.')
        return redirect('my_products')

    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Product deleted successfully.')
        return redirect('my_products')

    # If not POST, just redirect back
    return redirect('my_products')


@login_required
def create_fertilizer_listing(request):
    if request.method == 'POST':
        form = FertilizerListingForm(request.POST)
        if form.is_valid():
            listing = form.save(commit=False)
            listing.seller = request.user
            listing.save()
            messages.success(request, 'Fertilizer listing created successfully.')
            return redirect('shop')
    else:
        form = FertilizerListingForm()
    return render(request, 'sell_fertilizer.html', {'form': form})


@login_required
def user_profile(request):
    """View to display and update user profile info"""
    # Fetch existing data for the dashboard
    cart = Cart.objects.filter(user=request.user).first()
    cart_item_count = cart.items.count() if cart else 0
    user_orders = Order.objects.filter(user=request.user).order_by('-created_at')
    user_products = Product.objects.filter(seller=request.user).order_by('-created_at')

    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('user_profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserProfileForm(instance=request.user)
    
    context = {
        'form': form,
        'user': request.user,
        'cart_item_count': cart_item_count,
        'user_orders': user_orders,
        'user_products': user_products,
    }
    return render(request, 'user_profile.html', context)


def forgot_password(request):
    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                messages.error(request, 'No account found for that email.')
                return redirect('forgot_password')

            # Create OTP record
            import random
            otp = ''.join(random.choices('0123456789', k=6))
            expires_at = None
            try:
                from django.utils import timezone
                expires_at = timezone.now() + timezone.timedelta(minutes=10)
            except Exception:
                expires_at = None

            PasswordResetOTP.objects.create(user=user, otp=otp, expires_at=expires_at)
            
            # Send real email
            if send_password_reset_email(user, otp):
                messages.success(request, 'A 6-digit OTP has been sent to your registered email.')
            else:
                messages.warning(request, 'OTP generated but email delivery failed. Please contact support or try again later.')
                
            request.session['reset_email'] = email
            return redirect('verify_otp')
    else:
        form = ForgotPasswordForm()
    return render(request, 'forgot_password.html', {'form': form})


def verify_otp(request):
    if request.method == 'POST':
        form = VerifyOTPForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            email = request.session.get('reset_email')
            try:
                user = User.objects.get(email=email)
            except Exception:
                messages.error(request, 'Session expired. Please try again.')
                return redirect('forgot_password')

            try:
                record = PasswordResetOTP.objects.filter(user=user, otp=otp, is_used=False).order_by('-created_at').first()
                if record and record.is_valid():
                    record.is_used = True
                    record.save()
                    request.session['reset_user_id'] = user.id
                    return redirect('reset_password')
                else:
                    messages.error(request, 'Invalid or expired OTP.')
            except Exception:
                messages.error(request, 'Invalid OTP.')
    else:
        form = VerifyOTPForm()
    return render(request, 'verify_otp.html', {'form': form})


def reset_password(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        messages.error(request, 'Session expired. Please request a new OTP.')
        return redirect('forgot_password')

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'User not found.')
        return redirect('forgot_password')

    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            user.set_password(new_password)
            user.save()
            # Cleanup session
            request.session.pop('reset_user_id', None)
            request.session.pop('reset_email', None)
            messages.success(request, 'Password reset successfully. You can now log in.')
            return redirect('login')
    else:
        form = ResetPasswordForm()
    return render(request, 'reset_password.html', {'form': form})


def resend_otp(request):
    email = request.POST.get('email') or request.session.get('reset_email')
    if not email:
        return JsonResponse({'success': False, 'message': 'Email not provided'}, status=400)
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'No account for this email'}, status=400)

    import random
    otp = ''.join(random.choices('0123456789', k=6))
    from django.utils import timezone
    expires_at = timezone.now() + timezone.timedelta(minutes=10)
    PasswordResetOTP.objects.create(user=user, otp=otp, expires_at=expires_at)
    
    # Send email
    if send_password_reset_email(user, otp):
        return JsonResponse({'success': True, 'message': 'OTP resent successfully.'})
    else:
        return JsonResponse({'success': False, 'message': 'Failed to send OTP email.'}, status=500)


@require_POST
def generate_crop_plan_api(request):
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
        lat = float(data.get('latitude') or data.get('lat'))
        lon = float(data.get('longitude') or data.get('lon'))
        crop = str(data.get('crop_name') or data.get('crop') or '')
    except Exception:
        return JsonResponse({'error': 'Invalid request payload'}, status=400)

    result = generate_crop_plan(lat, lon, crop)
    return JsonResponse(result)


def get_available_crops_api(request):
    crops = get_available_crops()
    return JsonResponse({'crops': crops})


def crop_planning_page(request):
    crops = get_available_crops()
    return render(request, 'crop_planning.html', {'available_crops': crops})

def disease(request):
    """Disease detection page"""
    return render(request, 'disease.html')

def soil(request):
    """Legacy Soil URL that redirects to the new dedicated page."""
    return render(request, 'soil.html')

@ensure_csrf_cookie
def soil_analysis(request):
    """Dedicated Soil Analysis & Recommendations page"""
    return render(request, 'soil_analysis.html')

def about(request):
    """About us page"""
    return render(request, 'about.html')

def contact(request):
    """Contact page"""
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            contact_msg = form.save(commit=False)
            if request.user.is_authenticated:
                contact_msg.user = request.user
            contact_msg.save()
            messages.success(request, 'Your message has been sent successfully!   ')
            return redirect('contact')
    else:
        form = ContactForm()
    
    context = {'form': form}
    return render(request, 'contact.html', context)

def rating(request):
    """Rating/feedback page"""
    if request.method == 'POST':
        form = FeedbackForm(request.POST)
        if form.is_valid():
            feedback = form.save(commit=False)
            if request.user.is_authenticated:
                feedback.user = request.user
            feedback.save()
            messages.success(request, 'Thank you for your feedback!   ')
            return redirect('rating')
    else:
        form = FeedbackForm()
    
    # Get recent feedback
    recent_feedback = Feedback.objects.filter(is_active=True).order_by('-created_at')[:6]
    
    context = {
        'form': form,
        'recent_feedback': recent_feedback,
    }
    return render(request, 'rating.html', context)
def login_view(request):
    """User login view"""
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            
            # Try to authenticate with username
            user = authenticate(username=username, password=password)
            if user is None:
                # Try to authenticate with email
                try:
                    user_obj = User.objects.get(email=username)
                    user = authenticate(username=user_obj.username, password=password)
                except User.DoesNotExist:
                    pass
            
            if user is not None:
                login(request, user)
                next_url = request.GET.get('next', 'home')
                return redirect(next_url)
            else:
                # Optional: Add an error message if login fails entirely
                messages.error(request, "Invalid username or password.  ")
    else:
        form = CustomAuthenticationForm()
    
    context = {'form': form}
    return render(request, 'login.html', context)

def register(request):
    """User registration view with OTP verification step"""
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            if username and User.objects.filter(username=username).exists():
                form.add_error('username', 'This username is already taken. Please choose another one.')
            else:
                try:
                    # Create user as inactive
                    user = form.save(commit=False)
                    user.is_active = False
                    user.save()
                    
                    # Generate and send OTP
                    otp = generate_registration_otp(user)
                    send_registration_otp_email(user, otp)
                    
                    # Store user ID in session for verification page
                    request.session['registration_user_id'] = user.id
                    messages.success(request, f'An OTP has been sent to {user.email}. Please verify to activate your account.')
                    return redirect('verify_registration_otp')
                    
                except Exception as e:
                    logger.error(f"Registration error: {e}")
                    form.add_error(None, 'Unable to create account right now. Please try again.')
    else:
        form = CustomUserCreationForm()
    
    context = {'form': form}
    return render(request, 'register.html', context)

def verify_registration_otp(request):
    """View to handle OTP entry and verification during signup"""
    user_id = request.session.get('registration_user_id')
    if not user_id:
        messages.error(request, 'Session expired. Please register again.')
        return redirect('register')
        
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, 'User not found.')
        return redirect('register')

    if request.method == 'POST':
        otp_input = request.POST.get('otp', '').strip()
        
        # Get active OTP record
        otp_record = EmailOTPVerification.objects.filter(user=user, is_verified=False).order_by('-created_at').first()
        
        if not otp_record or not otp_record.is_valid():
            messages.error(request, 'Code expired or invalid attempts exceeded. Please resend.')
        elif check_password(otp_input, otp_record.otp_hash):
            # Success
            otp_record.is_verified = True
            otp_record.save()
            
            user.is_active = True
            user.save()
            
            # Login user
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            
            # Cleanup session
            request.session.pop('registration_user_id', None)
            
            messages.success(request, 'Account verified and created successfully! Welcome to Krushi.')
            return redirect('home')
        else:
            # Wrong OTP
            otp_record.attempts += 1
            otp_record.save()
            remaining = 5 - otp_record.attempts
            if remaining > 0:
                messages.error(request, f'Invalid code. {remaining} attempts remaining.')
            else:
                messages.error(request, 'Max attempts exceeded. Please resend a new code.')
    
    # We use register.html with show_otp_verification=True to avoid creating new page
    context = {
        'show_otp_verification': True,
        'user_email': user.email
    }
    return render(request, 'register.html', context)

def resend_registration_otp(request):
    """View to resend OTP with cooldown logic"""
    user_id = request.session.get('registration_user_id')
    if not user_id:
        return JsonResponse({'success': False, 'message': 'Session expired'}, status=400)
        
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'User not found'}, status=400)
    
    # Rate limit check (e.g. 60 seconds)
    from django.utils import timezone
    last_otp = EmailOTPVerification.objects.filter(user=user).order_by('-created_at').first()
    if last_otp and (timezone.now() - last_otp.created_at).total_seconds() < 60:
        remaining = 60 - int((timezone.now() - last_otp.created_at).total_seconds())
        return JsonResponse({'success': False, 'message': f'Please wait {remaining} seconds before resending.'}, status=429)

    otp = generate_registration_otp(user)
    if send_registration_otp_email(user, otp):
        return JsonResponse({'success': True, 'message': 'New code sent to your email.'})
    else:
        return JsonResponse({'success': False, 'message': 'Failed to send email. Please check your email address.'}, status=500)
    
def logout_view(request):
    """User logout view"""
    logout(request)
    messages.success(request, 'You have been logged out successfully!   ')
    return redirect('home')

@login_required
def add_to_cart(request, product_id):
    """Add product to cart"""
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id, is_active=True)
        quantity = int(request.POST.get('quantity', 1))
        
        # Get or create cart for user
        cart, created = Cart.objects.get_or_create(user=request.user)
        
        # Check if product already in cart
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={'quantity': quantity}
        )
        
        if not created:
            cart_item.quantity += quantity
            cart_item.save()
        
        messages.success(request, f'{product.name} added to cart!')
        return JsonResponse({'success': True, 'message': 'Product added to cart!'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@login_required
def view_cart(request):
    """View shopping cart"""
    try:
        cart = Cart.objects.get(user=request.user)
        cart_items = cart.items.all()
    except Cart.DoesNotExist:
        cart = None
        cart_items = []
    
    context = {
        'cart': cart,
        'cart_items': cart_items,
    }
    return render(request, 'cart.html', context)

@login_required
def update_cart(request, item_id):
    """Update cart item quantity"""
    if request.method == 'POST':
        try:
            cart_item = CartItem.objects.get(id=item_id, cart__user=request.user)
            quantity = int(request.POST.get('quantity', 1))
            
            if quantity > 0:
                cart_item.quantity = quantity
                cart_item.save()
            else:
                cart_item.delete()
            
            return JsonResponse({'success': True})
        except CartItem.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Item not found'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@login_required
def remove_from_cart(request, item_id):
    """Remove item from cart"""
    try:
        cart_item = CartItem.objects.get(id=item_id, cart__user=request.user)
        cart_item.delete()
        messages.success(request, 'Item removed from cart!  ')
    except CartItem.DoesNotExist:
        messages.error(request, 'Item not found!  ')
    
    return redirect('view_cart')

def is_serviceable_state(state):
    """Helper to check if a state is serviceable (Maharashtra only)."""
    if not state:
        return False
    return state.strip().lower() == 'maharashtra'

@login_required
def checkout(request):
    """Checkout with Razorpay or Cash on Delivery.

    GET  → render checkout page with cart summary + payment options.
    POST (AJAX) → create local Order, branch by payment_method.
    """
    from decimal import Decimal
    from .forms import CheckoutForm

    try:
        cart = Cart.objects.get(user=request.user)
        cart_items = cart.items.select_related('product').all()

        if not cart_items.exists():
            messages.warning(request, 'Your cart is empty!')
            return redirect('shop')

        if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
            form = CheckoutForm(request.POST)
            if not form.is_valid():
                # Extract first error message
                errors = form.errors.get_json_data()
                first_error = "Validation error."
                for field in errors:
                    first_error = errors[field][0]['message']
                    break
                return JsonResponse({'success': False, 'message': first_error}, status=400)

            # Extract validated data
            full_name = form.cleaned_data['full_name']
            shipping_address = form.cleaned_data['shipping_address']
            city = form.cleaned_data['city']
            district = form.cleaned_data['district']
            state = form.cleaned_data['state']
            pincode = form.cleaned_data['pincode']
            phone = form.cleaned_data['phone']
            notes = form.cleaned_data['notes']
            payment_method = request.POST.get('payment_method', 'razorpay').strip().lower()

            # Server-side serviceable state check (Double check)
            if not is_serviceable_state(state):
                return JsonResponse(
                    {'success': False, 'message': 'Sorry, delivery is available only within Maharashtra.'}, 
                    status=400
                )

            if payment_method not in ('razorpay', 'cod'):
                return JsonResponse(
                    {'success': False, 'message': 'Invalid payment method.'}, status=400
                )

            # Compute total from server-side cart data only
            total_amount = cart.total_amount
            if total_amount <= 0:
                return JsonResponse(
                    {'success': False, 'message': 'Cart total must be greater than 0.'}, status=400
                )

            # ── COD-specific validation ──
            if payment_method == 'cod':
                if not getattr(settings, 'COD_ENABLED', True):
                    return JsonResponse(
                        {'success': False, 'message': 'Cash on Delivery is currently unavailable.'}, status=400
                    )
                cod_max = Decimal(str(getattr(settings, 'COD_MAX_AMOUNT', 5000)))
                if total_amount > cod_max:
                    return JsonResponse(
                        {'success': False,
                         'message': f'Cash on Delivery is only available for orders up to ₹{cod_max}. Please use online payment.'},
                        status=400,
                    )

            # ── Duplicate protection (idempotency token) ──
            idempotency_key = request.POST.get('idempotency_key', '').strip()
            if idempotency_key:
                existing = Order.objects.filter(
                    user=request.user,
                    idempotency_key=idempotency_key,
                ).exclude(status='cancelled').first()
                if existing:
                    # Return the existing order instead of creating a duplicate
                    if existing.is_cod:
                        return JsonResponse({'success': True, 'payment_method': 'cod', 'order_id': existing.id})
                    else:
                        return JsonResponse({
                            'success': True,
                            'payment_method': 'razorpay',
                            'razorpay_order_id': existing.razorpay_order_id,
                            'amount': int(existing.total_amount * 100),
                            'currency': existing.currency,
                            'key_id': settings.RAZORPAY_KEY_ID,
                            'order_id': existing.id,
                            'order_number': existing.order_number,
                            'user': {
                                'name': request.user.get_full_name() or request.user.username,
                                'email': request.user.email,
                                'contact': phone,
                            },
                        })

            # ── Create local order ──
            order = Order.objects.create(
                user=request.user,
                total_amount=total_amount,
                currency='INR',
                full_name=full_name,
                shipping_address=shipping_address,
                city=city,
                district=district,
                state=state,
                pincode=pincode,
                phone=phone,
                notes=notes,
                payment_method=payment_method,
                idempotency_key=idempotency_key,
                status='pending',
                payment_status='pending',
            )

            # Create order items from cart
            for ci in cart_items:
                OrderItem.objects.create(
                    order=order,
                    product=ci.product,
                    quantity=ci.quantity,
                    price=ci.product.price,
                )

            # ── Branch by payment method ──

            if payment_method == 'cod':
                # Final validation again for COD
                if not is_serviceable_state(order.state):
                    order.status = 'cancelled'
                    order.save()
                    return JsonResponse({'success': False, 'message': 'Delivery not available for this state.'}, status=400)

                # COD: finalise immediately, no payment gateway
                order.status = 'placed'
                order.save(update_fields=['status'])

                # Deduct stock
                for ci in cart_items:
                    product = ci.product
                    product.stock_quantity = max(0, product.stock_quantity - ci.quantity)
                    product.save(update_fields=['stock_quantity'])

                # Clear cart immediately for COD
                cart.items.all().delete()

                logger.info("COD order placed: %s", order.order_number)

                return JsonResponse({
                    'success': True,
                    'payment_method': 'cod',
                    'order_id': order.id,
                })

            else:
                # Razorpay: existing flow
                from .services.razorpay_service import create_razorpay_order

                # Final validation before creating Razorpay order
                if not is_serviceable_state(order.state):
                    return JsonResponse({'success': False, 'message': 'Delivery not available for this state.'}, status=400)

                try:
                    rp_order = create_razorpay_order(
                        amount=total_amount,
                        currency='INR',
                        receipt=order.order_number,
                        notes={'order_id': str(order.id), 'user': request.user.username},
                    )
                except Exception as e:
                    logger.error("Razorpay order creation failed: %s", e)
                    order.payment_status = 'failed'
                    order.save(update_fields=['payment_status'])
                    return JsonResponse(
                        {'success': False, 'message': f'Payment gateway error: {e}'}, status=500
                    )

                # Persist Razorpay order ID
                order.razorpay_order_id = rp_order['id']
                order.payment_status = 'created'
                order.save(update_fields=['razorpay_order_id', 'payment_status'])

                return JsonResponse({
                    'success': True,
                    'payment_method': 'razorpay',
                    'razorpay_order_id': rp_order['id'],
                    'amount': rp_order['amount'],  # paise
                    'currency': rp_order.get('currency', 'INR'),
                    'key_id': settings.RAZORPAY_KEY_ID,
                    'order_id': order.id,
                    'order_number': order.order_number,
                    'user': {
                        'name': request.user.get_full_name() or request.user.username,
                        'email': request.user.email,
                        'contact': phone,
                    },
                })

        # GET request — render checkout page
        cod_max = Decimal(str(getattr(settings, 'COD_MAX_AMOUNT', 5000)))
        cod_available = (
            getattr(settings, 'COD_ENABLED', True) and cart.total_amount <= cod_max
        )
        context = {
            'cart': cart,
            'cart_items': cart_items,
            'razorpay_key_id': settings.RAZORPAY_KEY_ID,
            'cod_enabled': getattr(settings, 'COD_ENABLED', True),
            'cod_available': cod_available,
            'cod_max_amount': cod_max,
        }
        return render(request, 'checkout.html', context)

    except Cart.DoesNotExist:
        messages.warning(request, 'Your cart is empty!')
        return redirect('shop')


@login_required
@require_POST
def payment_verify(request):
    """Verify Razorpay payment signature and finalise order.

    Called by the frontend after Razorpay Checkout succeeds.
    """
    from django.utils import timezone as tz
    from .services.razorpay_service import verify_payment_signature
    from .models import PaymentTransaction

    rp_order_id = request.POST.get('razorpay_order_id', '').strip()
    rp_payment_id = request.POST.get('razorpay_payment_id', '').strip()
    rp_signature = request.POST.get('razorpay_signature', '').strip()

    if not (rp_order_id and rp_payment_id and rp_signature):
        return JsonResponse(
            {'success': False, 'message': 'Missing payment parameters.'}, status=400
        )

    # Look up local order by razorpay_order_id
    try:
        order = Order.objects.get(razorpay_order_id=rp_order_id, user=request.user)
    except Order.DoesNotExist:
        return JsonResponse(
            {'success': False, 'message': 'Order not found for this payment.'}, status=404
        )

    # Idempotency: if already paid, just return success
    if order.payment_status == 'paid':
        return JsonResponse({'success': True, 'order_id': order.id, 'already_paid': True})

    # Verify signature (HMAC-SHA256)
    if not verify_payment_signature(rp_order_id, rp_payment_id, rp_signature):
        order.payment_status = 'failed'
        order.save(update_fields=['payment_status'])

        PaymentTransaction.objects.create(
            order=order,
            razorpay_order_id=rp_order_id,
            razorpay_payment_id=rp_payment_id,
            razorpay_signature=rp_signature,
            event='checkout_callback',
            status='signature_failed',
        )
        return JsonResponse(
            {'success': False, 'message': 'Payment verification failed.'}, status=400
        )

    # Signature valid → mark order as paid
    order.razorpay_payment_id = rp_payment_id
    order.razorpay_signature = rp_signature
    order.payment_status = 'paid'
    order.status = 'placed'
    order.paid_at = tz.now()
    order.save(update_fields=[
        'razorpay_payment_id', 'razorpay_signature',
        'payment_status', 'status', 'paid_at',
    ])

    # Log transaction
    PaymentTransaction.objects.create(
        order=order,
        razorpay_order_id=rp_order_id,
        razorpay_payment_id=rp_payment_id,
        razorpay_signature=rp_signature,
        event='checkout_callback',
        amount_paise=int(order.total_amount * 100),
        currency=order.currency,
        status='paid',
    )

    # Clear cart only after confirmed payment
    Cart.objects.filter(user=request.user).delete()

    logger.info(
        "Payment verified for Order %s (Razorpay %s)",
        order.order_number, rp_payment_id,
    )

    return JsonResponse({'success': True, 'order_id': order.id})


@login_required
def payment_cancelled(request):
    """User closed Razorpay modal or payment failed on client-side."""
    messages.warning(request, 'Payment was cancelled. You can try again from checkout.')
    return render(request, 'payment_cancelled.html')


@login_required
def order_confirmation(request, order_id):
    """Order confirmation page"""
    order = get_object_or_404(Order, id=order_id, user=request.user)
    context = {'order': order}
    return render(request, 'order_confirmation.html', context)

@login_required
def my_orders(request):
    """User's order history"""
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    context = {'orders': orders}
    return render(request, 'my_orders.html', context)

@login_required
@require_POST
def cancel_order(request, order_id):
    """Cancel an order"""
    try:
        order = Order.objects.get(id=order_id, user=request.user)
        
        # Allow cancellation of pending, placed, confirmed, or shipped orders
        if order.status in ['pending', 'placed', 'confirmed', 'shipped']:
            order.status = 'cancelled'
            order.save()
            messages.success(request, f'Order #{order.order_number} has been cancelled successfully.')
        else:
            messages.error(request, f'Order #{order.order_number} cannot be cancelled. It is already {order.get_status_display()}.')
    except Order.DoesNotExist:
        messages.error(request, 'Order not found.')
    
    return redirect('my_orders')

@require_POST
def newsletter_subscribe(request):
    """Subscribe an email to the newsletter.

    Expects 'email' in POST form data. Returns JSON.
    """
    email = (request.POST.get('email') or '').strip()
    if not email:
        return JsonResponse({'success': False, 'message': 'Email is required.'}, status=400)
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({'success': False, 'message': 'Please enter a valid email address.'}, status=400)

    try:
        _, created = NewsletterSubscription.objects.get_or_create(email=email)
        if created:
            return JsonResponse({'success': True, 'message': 'Subscribed successfully!', 'created': True})
        else:
            return JsonResponse({'success': True, 'message': 'You are already subscribed.', 'created': False})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Failed to subscribe: {str(e)}'}, status=500)

@login_required
def add_review(request, product_id):
    """Add product review"""
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id, is_active=True)
        form = ReviewForm(request.POST)
        
        if form.is_valid():
            review = form.save(commit=False)
            review.product = product
            review.user = request.user
            review.save()
            
            messages.success(request, 'Review submitted successfully!   ')
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False, 'errors': form.errors})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@csrf_exempt
def analyze_disease(request):
    """API endpoint for disease analysis with robust error checking."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        # Support both multipart (preferred) and base64 in JSON (legacy)
        if 'image' in request.FILES:
            image_file = request.FILES['image']
            image_bytes = image_file.read()
            mime_type = image_file.content_type or 'image/jpeg'
        else:
            body = request.body.decode('utf-8') or '{}'
            data = json.loads(body)
            if 'image_base64' in data:
                image_bytes = base64.b64decode(data['image_base64'].split(',')[-1])
                mime_type = data.get('mime_type', 'image/jpeg')
            else:
                return JsonResponse({'error': 'No image provided'}, status=400)

        # Gemini Analysis with Resilience Layer
        ai_result = _gemini_analyze_image(image_bytes, mime_type)
        
        # FIX: Robust error handling with correct HTTP status codes
        if 'error' in ai_result:
            msg = ai_result['error'].lower()
            status_code = ai_result.get('status_code', 500)
            
            # Clean user-facing messages
            user_msg = "An internal system error occurred."
            if "timeout" in msg or "deadline" in msg:
                user_msg = "Image analysis timed out. Please try again."
            elif any(x in msg for x in ["overloaded", "503", "unavailable", "capacity", "exhausted"]):
                user_msg = "AI service is currently busy. Please try again in a few seconds."
            elif "image" in msg:
                user_msg = f"Analysis failed: {ai_result['error']}"
            
            return JsonResponse({'error': user_msg}, status=status_code)

        result = {
            'species': ai_result.get('species'),
            'health_status': ai_result.get('health_status', 'Unknown'),
            'detected_diseases': ai_result.get('detected_diseases', []),
            'pests': ai_result.get('pests', []),
            'care_tips': _as_string_list(ai_result.get('care_tips', [])),
            'fertilizer_recommendations': _as_string_list(ai_result.get('fertilizer_recommendations', [])),
        }
        return JsonResponse(result)
    except Exception as e:
        logger.error(f"Critical error in analyze_disease: {str(e)}")
        return JsonResponse({'error': 'An internal system error occurred.'}, status=500)

@csrf_exempt
def analyze_soil(request):
    """Crop recommendation only (no Gemini).

    Expects JSON body with exactly the 7 numeric features used by the local ML model:
    - nitrogen, phosphorus, potassium, temperature, humidity, ph_level, rainfall
    Returns JSON with only: {"recommended_crop": str} or {"prediction_error": str}
    """
    logger.warning("\n=== Soil Analysis Request ===")
    logger.warning(f"Method: {request.method}")
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        # Log raw request body for debugging
        payload_raw = request.body.decode('utf-8') or '{}'
        logger.warning(f"Raw request body: {payload_raw}")
        
        try:
            data = json.loads(payload_raw)
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON: {str(e)}"
            logger.warning(f"❌ {error_msg}")
            return JsonResponse({'prediction_error': 'Invalid JSON format'}, status=400)
            
        logger.warning(f"Parsed JSON data: {data}")

        # Pull only the 7 required features
        def _to_float(x, name):
            try:
                if x is None or x == '':
                    logger.warning(f"⚠️ Missing or empty value for {name}")
                    return None
                return float(x)
            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ Could not convert {name} to float: {x}")
                return None

        feats = {
            'nitrogen': _to_float(data.get('nitrogen'), 'nitrogen'),
            'phosphorus': _to_float(data.get('phosphorus'), 'phosphorus'),
            'potassium': _to_float(data.get('potassium'), 'potassium'),
            # Divide temperature by 10 before sending to frontend
            'temperature': _to_float(data.get('temperature'), 'temperature') ,
            'humidity': _to_float(data.get('humidity'), 'humidity'),
            'ph_level': _to_float(data.get('ph_level'), 'ph_level'),
            'rainfall': _to_float(data.get('rainfall'), 'rainfall'),
        }

        # Check for missing or invalid values
        missing = [k for k, v in feats.items() if v is None]
        if missing:
            error_msg = f"Missing or invalid values for: {', '.join(missing)}"
            logger.warning(f"❌ {error_msg}")
            return JsonResponse({
                'prediction_error': f'Please provide valid numeric values for all fields. Issues with: {", ".join(missing)}'
            }, status=200)
            
        logger.warning(f"✅ All input values valid: {feats}")

        # Make prediction (top-1)
        rec_crop = _predict_crop(
            feats['nitrogen'],
            feats['phosphorus'],
            feats['potassium'],
            feats['temperature'],
            feats['humidity'],
            feats['ph_level'],
            feats['rainfall'],
        )
        # Attempt to compute top-3 recommendations (if model supports probabilities)
        top_recs = []
        try:
            model = _load_crop_model()
            if model is not None and hasattr(model, 'predict_proba') and hasattr(model, 'classes_'):
                import numpy as np
                X = np.array([[
                    float(feats['nitrogen']),
                    float(feats['phosphorus']),
                    float(feats['potassium']),
                    float(feats['temperature']),
                    float(feats['humidity']),
                    float(feats['ph_level']),
                    float(feats['rainfall']),
                ]], dtype=float)
                probs = model.predict_proba(X)
                if probs is not None and len(probs.shape) == 2 and probs.shape[0] == 1:
                    prob_row = probs[0]
                    class_labels = list(getattr(model, 'classes_', []))
                    pairs = list(zip(class_labels, prob_row))
                    # Sort by probability descending
                    pairs.sort(key=lambda t: t[1], reverse=True)
                    for lbl, p in pairs[:3]:
                        top_recs.append({
                            'crop': str(lbl),
                            'score': float(p)
                        })
        except Exception as e:
            # Non-fatal; just log and continue with top-1 only
            logger.warning(f"Top-3 computation skipped due to error: {e}")

        if rec_crop:
            logger.warning(f"✅ Recommended crop: {rec_crop}")
            # Ensure top_recs contains the top-1 as first; if empty, synthesize from rec_crop
            if not top_recs:
                top_recs = [{ 'crop': str(rec_crop), 'score': None }]
            return JsonResponse({'recommended_crop': rec_crop, 'top_recommendations': top_recs})
            
        logger.warning("❌ No prediction returned from model")
        return JsonResponse({
            'prediction_error': 'Could not determine a suitable crop. Please check your input values and try again.'
        }, status=200)
        
    except Exception as e:
        import traceback
        error_msg = f"Unexpected error: {str(e)}"
        logger.warning(f"❌ {error_msg}")
        logger.warning("Stack trace:")
        traceback.print_exc()
        return JsonResponse({
            'prediction_error': 'An unexpected error occurred. Please try again later.'
        }, status=500)



def govsites(request):
    return render(request, 'gov_sites.html')


@require_GET
def weather_api(request):
    """Return current weather using API Ninjas by latitude/longitude.

    Query params:
    - lat: latitude (-90..90)
    - lon: longitude (-180..180)

    Response: JSON passthrough from API Ninjas with selected fields, or error.
    """
    lat = request.GET.get('lat')
    lon = request.GET.get('lon')
    if not lat or not lon:
        return JsonResponse({'error': 'Missing lat or lon query params'}, status=400)
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'lat and lon must be valid numbers'}, status=400)
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return JsonResponse({'error': 'lat/lon out of range'}, status=400)

    api_key = getattr(settings, 'API_NINJAS_API_KEY', '')
    if not api_key:
        return JsonResponse({'error': 'API_NINJAS_API_KEY not configured on server'}, status=500)

    url = 'https://api.api-ninjas.com/v1/weather'
    headers = {"X-Api-Key": api_key}
    params = {"lat": lat_f, "lon": lon_f}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            return JsonResponse({'error': f'Upstream error {resp.status_code}', 'detail': resp.text[:500]}, status=502)
        data = resp.json()
    except requests.exceptions.Timeout:
        return JsonResponse({'error': 'Weather provider timeout'}, status=504)
    except requests.exceptions.RequestException as e:
        return JsonResponse({'error': f'Weather provider error: {str(e)}'}, status=502)
    except ValueError:
        return JsonResponse({'error': 'Invalid JSON from weather provider'}, status=502)

    # Optionally, ensure expected keys exist; otherwise just passthrough
    return JsonResponse(data)


# ---------------------------------------------------------------------------
# Razorpay Webhook
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """Handle Razorpay webhook events.

    Events handled:
      - payment.captured  → mark order as paid (fallback / reconciliation)
      - payment.failed    → mark order as failed
      - order.paid        → mark order as paid

    Idempotent: will not re-process an already-paid order.
    """
    from django.utils import timezone as tz
    from .services.razorpay_service import verify_webhook_signature

    raw_body = request.body
    signature = request.headers.get('X-Razorpay-Signature', '')

    if not verify_webhook_signature(raw_body, signature):
        logger.warning("Webhook signature verification failed.")
        return JsonResponse({'status': 'invalid_signature'}, status=400)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'bad_json'}, status=400)

    event = payload.get('event', '')
    entity = (payload.get('payload', {}).get('payment', {}).get('entity', {})
              or payload.get('payload', {}).get('order', {}).get('entity', {}))

    rp_order_id = entity.get('order_id', '') or entity.get('id', '')
    rp_payment_id = entity.get('id', '')

    logger.info("Razorpay webhook received: event=%s order=%s payment=%s", event, rp_order_id, rp_payment_id)

    # Look up local order
    order = None
    if rp_order_id:
        try:
            order = Order.objects.get(razorpay_order_id=rp_order_id)
        except Order.DoesNotExist:
            pass

    # For order.paid event, the entity IS the order
    if not order and event == 'order.paid':
        try:
            order = Order.objects.get(razorpay_order_id=entity.get('id', ''))
        except Order.DoesNotExist:
            pass

    if not order:
        logger.warning("Webhook: no local order found for razorpay_order_id=%s", rp_order_id)
        return JsonResponse({'status': 'order_not_found'}, status=200)  # 200 to avoid retries

    # Determine event type mapping
    event_map = {
        'payment.captured': 'webhook_payment_captured',
        'payment.failed': 'webhook_payment_failed',
        'order.paid': 'webhook_order_paid',
    }
    event_type = event_map.get(event)

    if not event_type:
        # Unknown event — acknowledge but don't process
        logger.info("Webhook: ignoring unknown event '%s'", event)
        return JsonResponse({'status': 'ignored'}, status=200)

    # Log transaction
    PaymentTransaction.objects.create(
        order=order,
        razorpay_order_id=rp_order_id,
        razorpay_payment_id=rp_payment_id if 'payment' in event else '',
        event=event_type,
        amount_paise=entity.get('amount', 0),
        currency=entity.get('currency', 'INR'),
        status=entity.get('status', event),
        raw_response=payload,
    )

    if event in ('payment.captured', 'order.paid'):
        # Idempotency: skip if already paid
        if order.payment_status == 'paid':
            logger.info("Webhook: Order %s already paid, skipping.", order.order_number)
            return JsonResponse({'status': 'already_processed'}, status=200)

        order.payment_status = 'paid'
        order.status = 'placed'
        if not order.paid_at:
            order.paid_at = tz.now()
        if rp_payment_id and not order.razorpay_payment_id:
            order.razorpay_payment_id = rp_payment_id
        order.save(update_fields=[
            'payment_status', 'status', 'paid_at', 'razorpay_payment_id',
        ])

        # Clear cart (best-effort — user may have already had it cleared by callback)
        Cart.objects.filter(user=order.user).delete()
        logger.info("Webhook: Order %s marked as paid.", order.order_number)

    elif event == 'payment.failed':
        if order.payment_status not in ('paid',):
            order.payment_status = 'failed'
            order.save(update_fields=['payment_status'])
            logger.info("Webhook: Order %s marked as failed.", order.order_number)

    return JsonResponse({'status': 'ok'}, status=200)


def health_check(request):
    """
    Health check endpoint for production monitoring (Docker/K8s/ALB).
    Returns 200 if the app and database are responsive.
    """
    health = {"status": "ok", "checks": {"database": "ok"}}
    try:
        # Check database connection
        connections['default'].cursor()
    except OperationalError:
        health["status"] = "unhealthy"
        health["checks"]["database"] = "fail"
    
    status_code = 200 if health["status"] == "ok" else 503
    return JsonResponse(health, status=status_code)

def privacy_policy(request):
    """Privacy Policy page"""
    return render(request, 'privacy_policy.html')

def terms_conditions(request):
    """Terms & Conditions page"""
    return render(request, 'terms_conditions.html')

def disclaimer(request):
    """Disclaimer page"""
    return render(request, 'disclaimer.html')
