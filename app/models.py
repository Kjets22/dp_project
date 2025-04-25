# app/models.py

from datetime import datetime
from app import db

class User(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    def __repr__(self):
        return f"<User {self.username!r}>"

class Category(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    name      = db.Column(db.String(64), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    children  = db.relationship('Category')
    items     = db.relationship('Item', backref='category', lazy='dynamic')
    def __repr__(self):
        return f"<Category {self.name!r}>"

class Item(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(140), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    def __repr__(self):
        return f"<Item {self.title!r}>"

class Auction(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    item_id        = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    start_time     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    end_time       = db.Column(db.DateTime, nullable=False)
    init_price     = db.Column(db.Float, nullable=False)
    increment      = db.Column(db.Float, nullable=False)
    reserve_price  = db.Column(db.Float, nullable=False)
    status         = db.Column(db.String(10), nullable=False, default='open')

    item           = db.relationship('Item', backref='auctions')

    def __repr__(self):
        return (
            f"<Auction item={self.item_id} init={self.init_price} "
            f"end={self.end_time.isoformat()}>"
        )
class Bid(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    auction_id  = db.Column(db.Integer, db.ForeignKey('auction.id'), nullable=False)
    bidder      = db.Column(db.String(64), nullable=False)  # username of who placed it
    amount      = db.Column(db.Float,   nullable=False)     # the current bid price
    max_bid     = db.Column(db.Float,   nullable=True)      # <— our new field
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow)

    # relationship back to Auction so you can do auction.bids
    auction     = db.relationship('Auction', backref='bids')

    def __repr__(self):
        return f"<Bid {self.amount} by {self.bidder} on auction {self.auction_id}>"

class Alert(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(64), nullable=False)  # who set the alert
    criteria_json = db.Column(db.JSON,   nullable=False)      # e.g. {"category_id":1,"min_price":50}
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Alert {self.id} for {self.username}: {self.criteria_json}>"
