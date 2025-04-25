# app/__init__.py

from flask import Flask, jsonify, redirect, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    # Initialize & create tables
    db.init_app(app)
    with app.app_context():
        # import all models
        from app.models import User, Category, Item, Auction
        db.create_all()

    # --------------- Auction Endpoints ----------------

    @app.route("/auctions", methods=["GET"])
    def list_auctions():
        """Return all auctions with basic info."""
        auctions = Auction.query.all()
        return jsonify([
            {
                "id":         a.id,
                "item_id":    a.item_id,
                "start_time": a.start_time.isoformat(),
                "end_time":   a.end_time.isoformat(),
                "init_price": a.init_price,
                "increment":  a.increment,
                "reserve_price": a.reserve_price,
                "status":     a.status
            }
            for a in auctions
        ]), 200

    @app.route("/auctions/<int:item_id>", methods=["POST"])
    def create_auction(item_id):
        """
        Create an auction for an existing item.
        Expects JSON body:
          { "end_time":"YYYY-MM-DDThh:mm:ss",
            "init_price": float,
            "increment": float,
            "reserve_price": float }
        """
        data = request.get_json(force=True)
        # validate item exists
        if not Item.query.get(item_id):
            return jsonify(error="Item not found"), 404

        try:
            end = datetime.fromisoformat(data["end_time"])
        except Exception:
            return jsonify(error="Invalid end_time format"), 400

        a = Auction(
            item_id       = item_id,
            end_time      = end,
            init_price    = data["init_price"],
            increment     = data["increment"],
            reserve_price = data["reserve_price"]
        )
        db.session.add(a)
        db.session.commit()
        return jsonify(id=a.id), 201

    @app.route("/auctions/<int:auction_id>", methods=["GET"])
    def get_auction(auction_id):
        """Return full details of one auction."""
        a = Auction.query.get_or_404(auction_id)
        return jsonify({
            "id":         a.id,
            "item_id":    a.item_id,
            "start_time": a.start_time.isoformat(),
            "end_time":   a.end_time.isoformat(),
            "init_price": a.init_price,
            "increment":  a.increment,
            "reserve_price": a.reserve_price,
            "status":     a.status
        }), 200

    # -------------- (keep your existing routes) ----------------
    from app.models import User, Category, Item, Auction, Bid, Alert

    @app.route("/users", methods=["GET"])
    def list_users():
        return jsonify([u.username for u in User.query.all()]), 200

    
    # -----------------------
    # Alerts Endpoints
    # -----------------------

    @app.route("/alerts/<string:username>", methods=["GET"])
    def list_alerts(username):
        """List all alerts for a given user."""
        alerts = Alert.query.filter_by(username=username).all()
        return jsonify([
            {
                "id":            a.id,
                "criteria_json": a.criteria_json,
                "created_at":    a.created_at.isoformat()
            }
            for a in alerts
        ]), 200

    @app.route("/alerts/<string:username>", methods=["POST"])
    def create_alert(username):
        """
        Create an alert for `username`.
        JSON body is the criteria, e.g.:
          { "category_id":1, "min_price":50 }
        """
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            return jsonify(error="JSON object required"), 400

        a = Alert(username=username, criteria_json=data)
        db.session.add(a)
        db.session.commit()
        return jsonify(
            id=a.id,
            criteria_json=a.criteria_json,
            created_at=a.created_at.isoformat()
        ), 201

    # -----------------------
    # Bidding Endpoints
    # -----------------------

    @app.route("/auctions/<int:auction_id>/bids", methods=["GET"])
    def list_bids(auction_id):
        # ensure auction exists
        Auction.query.get_or_404(auction_id)
        bids = Bid.query.filter_by(auction_id=auction_id)\
                        .order_by(Bid.amount.desc()).all()
        return jsonify([
            {
                "id":        b.id,
                "bidder":    b.bidder,
                "amount":    b.amount,
                "timestamp": b.timestamp.isoformat()
            } for b in bids
        ]), 200
    
    @app.route("/auctions/<int:auction_id>/bid", methods=["POST"])
    def place_bid(auction_id):
        """
        Manual or automatic proxy bid.
        JSON body must include:
          - "username": bidder's username
        And either:
          - "amount": (float) exact bid amount
        or:
          - "max_bid": (float) your secret upper limit
        """
        data = request.get_json(force=True)
        user = data.get("username")
        if not user:
            return jsonify(error="username required"), 400

        auction = Auction.query.get_or_404(auction_id)
        now = datetime.utcnow()
        if auction.status != "open" or now > auction.end_time:
            return jsonify(error="Auction closed"), 400

        # find current highest amount (or init_price if no bids)
        highest = (
            db.session.query(db.func.max(Bid.amount))
                .filter_by(auction_id=auction_id)
                .scalar()
            or auction.init_price
        )

        # 1) Automatic proxy bidding
        if "max_bid" in data:
            max_bid = float(data["max_bid"])
            if max_bid <= highest:
                return jsonify(error=f"Your max_bid must exceed current bid ({highest})"), 400

            # your proxy bid: either just outbid or go straight to your max if that's smaller
            target = highest + auction.increment
            bid_amt = min(max_bid, target)

            b = Bid(
                auction_id=auction_id,
                bidder=user,
                amount=bid_amt,
                max_bid=max_bid
            )
            db.session.add(b)
            db.session.commit()
            return jsonify(
                id=b.id,
                bidder=b.bidder,
                amount=b.amount,
                max_bid=b.max_bid,
                timestamp=b.timestamp.isoformat()
            ), 201

        # 2) Manual bidding
        if "amount" in data:
            amt = float(data["amount"])
            if amt < highest + auction.increment:
                return jsonify(error=f"Bid must be ≥ {highest + auction.increment}"), 400
            if amt < auction.reserve_price:
                return jsonify(error="Bid below reserve price"), 400

            b = Bid(
                auction_id=auction_id,
                bidder=user,
                amount=amt,
                max_bid=None
            )
            db.session.add(b)
            db.session.commit()
            return jsonify(
                id=b.id,
                bidder=b.bidder,
                amount=b.amount,
                timestamp=b.timestamp.isoformat()
            ), 201

        # Neither amount nor max_bid supplied
        return jsonify(error="Either 'amount' or 'max_bid' is required"), 400
   
    # Manual trigger for testing alerts
    @app.route("/run_alerts", methods=["POST"])
    def run_alerts():
        """
        Manually invoke process_alerts() so you can see its log output immediately.
        """
        from app.tasks import process_alerts
        process_alerts()
        return "Alerts processed", 200

    @app.route("/users/<string:username>", methods=["POST"])
    def create_user(username):
        if User.query.filter_by(username=username).first():
            return jsonify(error="User already exists"), 400
        u = User(username=username)
        db.session.add(u); db.session.commit()
        return jsonify(username=u.username), 201

    @app.route("/categories", methods=["GET"])
    def list_categories():
        cats = Category.query.all()
        return jsonify([{"id":c.id,"name":c.name,"parent_id":c.parent_id} for c in cats]), 200

    @app.route("/categories/<string:name>", methods=["POST"])
    def create_category(name):
        parent = request.args.get("parent_id", type=int)
        if Category.query.filter_by(name=name, parent_id=parent).first():
            return jsonify(error="Category already exists"), 400
        c = Category(name=name, parent_id=parent)
        db.session.add(c); db.session.commit()
        return jsonify(id=c.id,name=c.name,parent_id=c.parent_id), 201

    @app.route("/items", methods=["GET"])
    def list_items():
        items = Item.query.all()
        return jsonify([{"id":i.id,"title":i.title,"category_id":i.category_id} for i in items]), 200

    @app.route("/items/<string:title>/<int:category_id>", methods=["POST"])
    def create_item(title, category_id):
        if not Category.query.get(category_id):
            return jsonify(error="Category not found"), 404
        i = Item(title=title, category_id=category_id)
        db.session.add(i); db.session.commit()
        return jsonify(id=i.id,title=i.title,category_id=i.category_id), 201

    @app.route("/ping")
    def ping():
        return "pong", 200

    @app.route("/")
    def home():
        return redirect("/ping")

    return app
