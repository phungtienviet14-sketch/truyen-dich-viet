from fastapi.templating import Jinja2Templates
from app.config import BASE_DIR


def identity_context(request):
    session = getattr(request.state, "admin_session", None)
    return {"is_admin": session is not None, "admin_username": session.username if session else ""}


templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"), context_processors=[identity_context])
