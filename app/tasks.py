# app/tasks.py

from datetime import datetime
from flask import current_app
from app import db
from app.models import Auction, Alert, Item, Bid, User


def close_auctions():
    to_close = Auction.query.filter(
        Auction.status=='open',
        Auction.end_time < now
    ).all()

    for a in to_close:
        a.status = 'closed'
        top = Bid.query.filter_by(auction_id=a.id) \
                       .order_by(Bid.amount.desc()) \
                       .first()
        if top and top.amount >= a.reserve_price:
            a.winning_bid = top.amount
            winner = User.query.filter_by(username=top.bidder).first()
            a.winner_id   = winner.id if winner else None

    db.session.commit()
    current_app.logger.info(f"Closed {len(to_close)} auctions at {now.isoformat()}")


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
