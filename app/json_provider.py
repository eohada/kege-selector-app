from datetime import datetime

from flask.json.provider import DefaultJSONProvider

from app.utils.datetime_utc import as_utc_iso_z


class BooJSONProvider(DefaultJSONProvider):
    def default(self, o):
        if isinstance(o, datetime):
            return as_utc_iso_z(o)
        return super().default(o)
