from django.contrib.auth import views as auth_views
from django.core.cache import cache
from django.http import HttpResponse

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60


def _key(request):
    email = (request.POST.get("username") or "").strip().lower()
    return f"login-fail:{request.META.get('REMOTE_ADDR', '')}:{email}"


class ThrottledLoginView(auth_views.LoginView):
    """Login that locks an address + email pair for 15 minutes after 5 wrong passwords."""

    def post(self, request, *args, **kwargs):
        if cache.get(_key(request), 0) >= MAX_FAILURES:
            return HttpResponse("Too many failed sign-in attempts. Try again in 15 minutes.", status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = _key(self.request)
        cache.add(key, 0, WINDOW_SECONDS)
        cache.incr(key)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(_key(self.request))
        return super().form_valid(form)
