from fastapi.templating import Jinja2Templates
from app.config import BASE_DIR


def identity_context(request):
    admin_session = getattr(request.state, "admin_session", None)
    current_user = getattr(request.state, "current_user", None)
    return {
        "is_admin": admin_session is not None,
        "admin_username": admin_session.username if admin_session else "",
        "current_user": current_user,
        "is_user_authenticated": current_user is not None
    }


templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"), context_processors=[identity_context])
