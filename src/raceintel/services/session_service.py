from sqlalchemy.orm import Session

from database.models import Event
from database.models import Season
from database.models import Session as RaceSession


def get_sessions(
    db: Session,
    season: int | None = None,
):
   

    query = (
        db.query(RaceSession)
        .join(Event)
        .join(Season)
    )

    if season is not None:
        query = query.filter(
            Season.season_year == season
        )

    return query.order_by(
        Season.season_year.desc(),
        Event.event_name,
        RaceSession.session_name,
    ).all()