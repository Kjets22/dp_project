# app/tasks.py

from datetime import datetime
from flask import current_app
from app import db
from app.models import Auction, Alert, Item


def close_auctions():
    """
    Closes all auctions whose end_time has passed by setting status to 'closed'.
    """
    now = datetime.utcnow()
    open_aucs = Auction.query.filter_by(status='open').all()
    num_closed = 0

    for a in open_aucs:
        if a.end_time < now:
            a.status = 'closed'
            num_closed += 1

    db.session.commit()
    current_app.logger.info(f"Closed {num_closed} auctions at {now.isoformat()}")
    
def process_alerts():
    """
    Evaluates each Alert.criteria_json against the Item table.
    For any alert with matching items, logs the number of matches.
    """
    for alert in Alert.query.all():
        crit = alert.criteria_json or {}
        q = Item.query
        # Dynamically apply each field == value filter
        for field, val in crit.items():
            if hasattr(Item, field):
                q = q.filter(getattr(Item, field) == val)
        matches = q.all()
        if matches:
            current_app.logger.info(
                f"Alert {alert.id} ({alert.username}): {len(matches)} matches"
            )
