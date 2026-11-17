"""

time_utils.py — Unified Timezone and Datetime Utilities

-------------------------------------------------------

Ensures all scheduling, deadlines, and submissions use consistent UTC timestamps.

Eliminates offset-naive vs offset-aware comparison crashes.

"""



from datetime import datetime, timezone

from typing import Optional, Union



def utc_now() -> datetime:

    """Return the current time as a timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)



def to_utc(dt: Optional[Union[datetime, str]]) -> Optional[datetime]:

    """

    Convert a datetime or ISO datetime string into a timezone-aware UTC datetime.

    If naive datetime is given, it is assumed to be in UTC.

    If string is given, it handles ISO formats (with or without 'Z' or offset).

    """

    if dt is None:

        return None



    if isinstance(dt, str):

        cleaned = dt.strip()

        if not cleaned:

            return None

        # Replace 'Z' with UTC offset

        cleaned = cleaned.replace("Z", "+00:00")

        try:

            parsed = datetime.fromisoformat(cleaned)

        except Exception:

            # Fallback for HTML5 datetime-local input (%Y-%m-%dT%H:%M)

            try:

                parsed = datetime.strptime(cleaned, "%Y-%m-%dT%H:%M")

            except Exception:

                parsed = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")

        dt = parsed



    if dt.tzinfo is None:

        # Naive datetime -> treat as UTC

        return dt.replace(tzinfo=timezone.utc)



    # Already aware -> convert to UTC

    return dt.astimezone(timezone.utc)



def to_utc_iso(dt: Optional[datetime]) -> str:

    """Return ISO-8601 string representation of a UTC datetime."""

    if dt is None:

        return ""

    utc_dt = to_utc(dt)

    return utc_dt.isoformat()
