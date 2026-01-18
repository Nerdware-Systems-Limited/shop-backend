"""
Context processors for email templates.
Provides common variables to all email templates.

Add to settings.py TEMPLATES['OPTIONS']['context_processors']:
'customers.context_processors.email_context',
"""

from django.conf import settings


def email_context(request):
    """
    Add common email-related variables to template context.
    
    This makes these variables available in all templates without
    having to pass them manually each time.
    """
    return {
        'site_name': 'SoundWaveAudio',
        'site_url': getattr(settings, 'FRONTEND_URL', 'https://soundwaveaudio.com'),
        'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@soundwaveaudio.com'),
        'company_address': 'Nairobi, Kenya',
        'company_phone': '+254 700 000 000',
        'social_media': {
            'facebook': 'https://facebook.com/soundwaveaudio',
            'twitter': 'https://twitter.com/soundwaveaudio',
            'instagram': 'https://instagram.com/soundwaveaudio',
            'youtube': 'https://youtube.com/soundwaveaudio',
        },
        'current_year': '2026',
    }