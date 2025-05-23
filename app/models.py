# app/models.py
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from app import db
from flask_login import UserMixin


class User(UserMixin, db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    username       = db.Column(db.String(64), unique=True, nullable=False)
    email          = db.Column(db.String(64), unique=True, nullable=False)
    password_hash  = db.Column(db.String(128), nullable=False)
    full_name       = db.Column(db.String(128), nullable=True)
    date_of_birth   = db.Column(db.Date, nullable=True)
    is_rep         = db.Column(db.Boolean, default=False, nullable=False)
    is_admin       = db.Column(db.Boolean, default=False, nullable=False)   

    auctions = db.relationship(
        'Auction',
        back_populates='seller',
        cascade='all, delete-orphan',
        foreign_keys='Auction.seller_id'
    )
    items = db.relationship(
        'Item',
        back_populates='owner',
        cascade='all, delete-orphan'
    )
     
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
 
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f"<User {self.username!r}>"   
        

class Category(db.Model):
    __tablename__ = 'category'
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(64), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)

    parent   = db.relationship('Category', remote_side=[id], backref='children')

    def to_dict(self):
        return {
            'id':        self.id,
            'name':      self.name,
            'parent_id': self.parent_id
        }

    def __repr__(self):
        return f"<Category {self.name!r} parent={self.parent_id}>"
    
class Item(db.Model):
    __tablename__ = 'item'
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    owner_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    category    = db.relationship('Category', backref=db.backref('items', lazy='dynamic'))
    auctions    = db.relationship(
        'Auction', back_populates='item',
        cascade='all, delete-orphan'
    )
    owner       = db.relationship(
        'User',
        back_populates='items'
    )
    
    def to_dict(self):
        return {
            'id':          self.id,
            'title':       self.title,
            'description': self.description,
            'category_id': self.category_id
        }

    def __repr__(self):
        return f"<Item {self.title!r} in category={self.category_id}>"
    
class Auction(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    item_id       = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    seller_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_time    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    end_time      = db.Column(db.DateTime, nullable=False)
    init_price    = db.Column(db.Float, nullable=False)
    increment     = db.Column(db.Float, nullable=False)
    reserve_price = db.Column(db.Float, nullable=False)
    status        = db.Column(db.String(10), default='open', nullable=False)
    winner_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    winning_bid   = db.Column(db.Float, nullable=True)
    winner        = db.relationship('User', foreign_keys=[winner_id])
    winning_id    = db.Column(db.Integer, default='open', nullable=True)

    seller = db.relationship(
        'User',
        back_populates='auctions',
        foreign_keys=[seller_id]
    )
    item   = db.relationship('Item', back_populates='auctions')
    bids   = db.relationship(
        'Bid',
        back_populates='auction',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return (f"<Auction #{self.id} item={self.item_id} "
                f"seller={self.seller_id} status={self.status!r}>")   
        
class Bid(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    auction_id  = db.Column(db.Integer, db.ForeignKey('auction.id'), nullable=False)
    bidder      = db.Column(db.String(64), nullable=False)
    amount      = db.Column(db.Float,   nullable=False)
    max_bid     = db.Column(db.Float,   nullable=True)
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow)
    bidder_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    
    person_bidder      = db.relationship(
            'User', 
            backref='bids', 
            foreign_keys=[bidder_id])

    auction     = db.relationship(
        'Auction',
        back_populates='bids'
    )

    def __repr__(self):
        return f"<Bid {self.amount} by {self.bidder} on auction {self.auction_id}>"

class Alert(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(64), nullable=False)
    criteria_json = db.Column(db.JSON,   nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Alert {self.id} for {self.username}: {self.criteria_json}>"


class Question(db.Model):
    __tablename__ = 'question'
    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    auction_id      = db.Column(db.Integer, db.ForeignKey('auction.id'), nullable=False)
    question_text   = db.Column(db.Text,    nullable=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    answer_text     = db.Column(db.Text,    nullable=True)
    answered_by_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    answered_at     = db.Column(db.DateTime, nullable=True)

    asker       = db.relationship('User', foreign_keys=[user_id], backref='questions')
    answered_by = db.relationship('User', foreign_keys=[answered_by_id])
    auction     = db.relationship('Auction', backref='questions')

    
    def __repr__(self):
        return (f"<Question #{self.id} on auction={self.auction_id} "
                f"asked_by=user_id={self.user_id!r}>")
