import uuid

from api_v1.common.errors import ApiError

from .models import Errand


def get_errand(api_key, errand_id, lock=False):
    """The errand for this key's business and environment, or 404. Same answer whether it does not exist or
    belongs to someone else, so ids cannot be probed."""
    try:
        eid = uuid.UUID(str(errand_id))
    except ValueError:
        raise ApiError(404, "errand_not_found", "No errand with that id.")
    qs = Errand.objects.filter(pk=eid, business=api_key.business, environment=api_key.environment)
    if lock:
        qs = qs.select_for_update()
    e = qs.first()
    if e is None:
        raise ApiError(404, "errand_not_found", "No errand with that id.")
    return e
