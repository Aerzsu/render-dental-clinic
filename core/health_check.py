from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import logging

logger = logging.getLogger(__name__)

@require_http_methods(["GET", "HEAD"])
def health_check(request):
    """
    Lightweight health check endpoint for uptime monitoring.
    Returns 200 OK if the app is running.
    """
    try:
        return JsonResponse(
            {
                'status': 'ok',
                'message': 'Dental clinic app is running'
            },
            status=200
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Health check failed'
            },
            status=500
        )