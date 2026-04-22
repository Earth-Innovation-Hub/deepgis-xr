"""
Authentication AJAX endpoints (phone login, logout, status check).

Moved out of the legacy `views.py` monolith in the Tier B refactor.
These are the three endpoints consumed by the frontend login drawer;
routes are wired in `deepgis_xr/apps/web/urls.py` and re-exported via
`views/__init__.py`, so URL names are unchanged
(`check_auth_status`, `ajax_phone_login`, `ajax_logout`).

SMS verification for production deployments is still a TODO — in DEBUG
mode users are auto-verified on first login; in production the endpoint
returns `verification_required` and expects a separate verification flow
to be plumbed in.
"""

import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def check_auth_status(request):
    """Check if user is authenticated"""
    if request.user.is_authenticated:
        return JsonResponse({
            'authenticated': True,
            'username': request.user.username,
            'phone': getattr(request.user, 'phone_number', None)
        })
    return JsonResponse({'authenticated': False})


@csrf_exempt
def ajax_phone_login(request):
    """AJAX endpoint for phone-based login"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        phone_number = data.get('phone_number', '').strip()
        
        if not phone_number:
            return JsonResponse({'error': 'Phone number is required'}, status=400)
        
        # Validate phone number format (basic validation)
        import re
        if not re.match(r'^\+?[1-9]\d{6,14}$', phone_number.replace(' ', '').replace('-', '')):
            return JsonResponse({'error': 'Invalid phone number format. Use international format (e.g., +1234567890)'}, status=400)
        
        # Import User model from auth app
        from deepgis_xr.apps.auth.models import User
        from django.contrib.auth import login
        
        # Get or create user by phone number
        user, created = User.objects.get_or_create(
            phone_number=phone_number,
            defaults={'username': phone_number}
        )
        
        # In development/DEBUG mode, auto-verify and login
        # For production, you would implement SMS verification here
        if settings.DEBUG:
            user.is_phone_verified = True
            user.save()
            login(request, user)
            
            return JsonResponse({
                'status': 'success',
                'message': 'Logged in successfully',
                'authenticated': True,
                'username': user.username,
                'phone': str(user.phone_number) if user.phone_number else None
            })
        else:
            # In production, send verification code
            # For now, return that verification is needed
            return JsonResponse({
                'status': 'verification_required',
                'message': 'Verification code sent to your phone',
                'authenticated': False
            })
            
    except Exception as e:
        import traceback
        print(f"Login error: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def ajax_logout(request):
    """AJAX endpoint for logout"""
    from django.contrib.auth import logout
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    logout(request)
    return JsonResponse({
        'status': 'success',
        'message': 'Logged out successfully',
        'authenticated': False
    })
