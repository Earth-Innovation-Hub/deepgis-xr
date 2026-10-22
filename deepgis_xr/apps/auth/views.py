import os
from datetime import datetime, timedelta
import random
from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.views.generic import View
from twilio.rest import Client
from .models import User, VerificationCode
from .forms import PhoneLoginForm, VerificationForm

# Initialize Twilio client only if credentials are available
twilio_client = None
if getattr(settings, 'TWILIO_ACCOUNT_SID', None) and getattr(settings, 'TWILIO_AUTH_TOKEN', None):
    twilio_client = Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN
    )

# Test phone number for development
TEST_PHONE_NUMBER = '+12345678900'

def generate_verification_code():
    """Generate a random 6-digit code"""
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])

class PhoneLoginView(View):
    template_name = 'auth/phone_login.html'
    
    def get(self, request):
        form = PhoneLoginForm()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        form = PhoneLoginForm(request.POST)
        if form.is_valid():
            phone_number = form.cleaned_data['phone_number']

            # Without SMS there is no way to verify the number, so no account either
            if not twilio_client and not settings.DEBUG:
                form.add_error(None, 'Phone sign-in is not available on this server.')
                return render(request, self.template_name, {'form': form})

            # Get or create user
            user, created = User.objects.get_or_create(
                phone_number=phone_number,
                defaults={'username': str(phone_number)}
            )
            
            # Development only: auto-verify all numbers
            if settings.DEBUG:
                user.is_phone_verified = True
                user.save()
                login(request, user)
                return redirect('index')
            
            # Generate verification code
            code = generate_verification_code()
            
            # Save verification code
            VerificationCode.objects.create(
                user=user,
                code=code,
                expires_at=datetime.now() + timedelta(minutes=10)
            )
            
            # Send verification code via Twilio
            try:
                twilio_client.messages.create(
                    body=f'Your verification code is: {code}',
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=str(phone_number)
                )
            except Exception as e:
                print(f"Failed to send SMS: {e}")
                # In case of SMS failure, still allow verification in development
                if settings.DEBUG:
                    user.is_phone_verified = True
                    user.save()
                    login(request, user)
                    return redirect('index')
            
            # Redirect to verification page
            return redirect('verify_code')
        
        return render(request, self.template_name, {'form': form})

class VerifyCodeView(View):
    template_name = 'auth/verify_code.html'
    
    def get(self, request):
        if 'phone_auth_user_id' not in request.session:
            return redirect('phone_login')
            
        form = VerificationForm()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        if 'phone_auth_user_id' not in request.session:
            return redirect('phone_login')
            
        form = VerificationForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            user_id = request.session['phone_auth_user_id']
            
            try:
                user = User.objects.get(id=user_id)
                verification = VerificationCode.objects.filter(
                    user=user,
                    code=code,
                    is_used=False,
                    expires_at__gt=datetime.now()
                ).latest('created_at')
                
                # Mark code as used
                verification.is_used = True
                verification.save()
                
                # Mark user as verified and login
                user.is_phone_verified = True
                user.save()
                login(request, user)
                
                # Clean up session
                del request.session['phone_auth_user_id']
                
                return redirect('index')
                
            except (User.DoesNotExist, VerificationCode.DoesNotExist):
                form.add_error(None, "Invalid or expired verification code")
        
        return render(request, self.template_name, {'form': form}) 