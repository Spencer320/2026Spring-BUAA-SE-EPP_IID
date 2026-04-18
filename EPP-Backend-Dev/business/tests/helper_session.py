from django.contrib.sessions.models import Session


def get_session_dict(response) -> dict:
    session_id = response.cookies.get("sessionid").value
    session = Session.objects.filter(session_key=session_id).first()
    if session is None:
        return {}
    return session.get_decoded()
