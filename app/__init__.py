# app/__init__.py

from flask import Flask, jsonify, redirect, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_apscheduler import APScheduler

db = SQLAlchemy()
login = LoginManager()
login.login_view = 'auth_login'

def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    # Initialize & create tables
    db.init_app(app)
    with app.app_context():
        # import all models
        from app.models import User, Category, Item, Auction
        db.create_all()
    
    login.init_app(app)

    @login.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))   

    


    # --------------- Auction Endpoints ----------------
 
    @app.route('/auctions/<int:item_id>', methods=['POST'])
    def create_auction(item_id):
        data = request.get_json(force=True)
        # must pass: username, end_time (ISO8601), init_price, increment, reserve_price
        username = data.get('username')
        end_str  = data.get('end_time')
        if not username or not end_str:
            return jsonify(error="username and end_time required"), 400
    
        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify(error="User not found"), 404
    
        item = Item.query.get(item_id)
        if not item:
            return jsonify(error="Item not found"), 404
    
        try:
            end_dt = datetime.fromisoformat(end_str)
        except ValueError:
            return jsonify(error="Invalid end_time format"), 400
    
        a = Auction(
            item_id       = item_id,
            seller_id     = user.id,
            end_time      = end_dt,
            init_price    = data.get('init_price', 0),
            increment     = data.get('increment', 1),
            reserve_price = data.get('reserve_price', 0),
        )
        db.session.add(a)
        db.session.commit()
        return jsonify(id=a.id), 201
    
    
    @app.route('/auctions', methods=['GET'])
    def list_auctions():
        # --- optional filters from query string ---
        status      = request.args.get('status')              # open/closed
        title       = request.args.get('title')               # substring match on item title
        description = request.args.get('description')         # substring match on item description
        category_id = request.args.get('category_id', type=int)
        min_price   = request.args.get('min_price',   type=float)
        max_price   = request.args.get('max_price',   type=float)

        # join Auction → Item so we can filter on item fields
        q = Auction.query.join(Item)

        # auction‐level filters
        if status in ('open', 'closed'):
            q = q.filter(Auction.status == status)
        if min_price is not None:
            q = q.filter(Auction.init_price >= min_price)
        if max_price is not None:
            q = q.filter(Auction.init_price <= max_price)

        # item‐level filters
        if title:
            q = q.filter(Item.title.ilike(f'%{title}%'))
        if description:
            q = q.filter(Item.description.ilike(f'%{description}%'))
        if category_id:
            q = q.filter(Item.category_id == category_id)        
        all_aucs = q.all()
        return jsonify([{
            'id':            a.id,
            'item_id':       a.item_id,
            'seller_id':     a.seller_id,
            'start_time':    a.start_time.isoformat(),
            'end_time':      a.end_time.isoformat(),
            'init_price':    a.init_price,
            'increment':     a.increment,
            'reserve_price': a.reserve_price,
            'status':        a.status,
        } for a in all_aucs]), 200

    
    @app.route('/auctions/search', methods=['GET'])
    def search_auctions():
        # join Auction ⇆ Item so we can filter by item fields
        q = Auction.query.join(Item)

        # pull query-params
        title       = request.args.get('title')
        category_id = request.args.get('category_id', type=int)
        min_price   = request.args.get('min_price',   type=float)
        max_price   = request.args.get('max_price',   type=float)
        status      = request.args.get('status')      # open/closed

        # apply filters
        if title:
            q = q.filter(Item.title.ilike(f'%{title}%'))
        if category_id:
            q = q.filter(Item.category_id == category_id)
        if min_price is not None:
            q = q.filter(Auction.init_price >= min_price)
        if max_price is not None:
            q = q.filter(Auction.init_price <= max_price)
        if status in ('open','closed'):
            q = q.filter(Auction.status == status)

        # fetch & serialize
        results = q.all()
        return jsonify([{
            'auction_id': a.id,
            'item_id':    a.item_id,
            'title':      a.item.title,
            'init_price': a.init_price,
            'status':     a.status
        } for a in results]), 200
    
    @app.route('/auctions/<int:auc_id>', methods=['GET'])
    def get_auction(auc_id):
        a = Auction.query.get_or_404(auc_id)
        bids = Bid.query.filter_by(auction_id=auc_id)\
                        .order_by(Bid.amount.desc()).all()
        bid_list = [{
            'id':        b.id,
            'bidder':    b.bidder,
            'amount':    b.amount,
            'max_bid':   b.max_bid,
            'timestamp': b.timestamp.isoformat()
        } for b in bids]
        high = bids[0].amount if bids else a.init_price

        resp = {
            'id':           a.id,
            'item_id':      a.item_id,
            'seller_id':    a.seller_id,
            'start_time':   a.start_time.isoformat(),
            'end_time':     a.end_time.isoformat(),
            'init_price':   a.init_price,
            'increment':    a.increment,
            'reserve_price':a.reserve_price,
            'status':       a.status,
            'current_high': high,
            'bids':         bid_list,
            # ← NEW ↓↓↓
            'winner':       a.winner.username if a.winner else None,
            'winning_bid':  a.winning_bid,
            # ↑↑↑
        }
        return jsonify(resp), 200
    
     # -------------- (keep your existing routes) ----------------
    from app.models import User, Category, Item, Auction, Bid, Alert

    @app.route("/users", methods=["GET"])
    def list_users():
        return jsonify([u.username for u in User.query.all()]), 200
    
    # Create a new category (optionally as a subcategory)
    @app.route('/categories', methods=['POST'])
    def create_category():
        data = request.get_json(force=True)
        name = data.get('name')
        parent_id = data.get('parent_id')  # optional
        if not name:
            return jsonify(error="name is required"), 400
        # verify parent exists if given
        if parent_id is not None and not Category.query.get(parent_id):
            return jsonify(error="parent_id not found"), 404
    
        cat = Category(name=name, parent_id=parent_id)
        db.session.add(cat)
        db.session.commit()
        return jsonify(cat.to_dict()), 201
    
    # List all categories
    @app.route('/categories', methods=['GET'])
    def list_categories():
        cats = Category.query.all()
        return jsonify([c.to_dict() for c in cats]), 200
    
    # Get a single category (with its children)
    @app.route('/categories/<int:cat_id>', methods=['GET'])
    def get_category(cat_id):
        cat = Category.query.get(cat_id)
        if not cat:
            return jsonify(error="Category not found"), 404
        d = cat.to_dict()
        d['children'] = [child.to_dict() for child in cat.children]
        return jsonify(d), 200
    
    class SchedulerConfig:
        SCHEDULER_API_ENABLED = True
        # add any other APScheduler settings here
    
    def create_app():
        app = Flask(__name__)
        app.config.from_object("config.Config")
        app.config.from_object(SchedulerConfig)
    
        # … your existing init_app, db.create_all(), login, routes, etc.
    
        # ↓↓↓ add this block at the bottom of create_app() before `return app` ↓↓↓
        scheduler = APScheduler()
        scheduler.init_app(app)
        scheduler.start()
    
        # Close auctions every minute
        scheduler.add_job(
            id='close_auctions',
            func=close_auctions,
            trigger='interval',
            minutes=1
        )
    
        # Process alerts every 5 minutes
        scheduler.add_job(
            id='process_alerts',
            func=process_alerts,
            trigger='interval',
            minutes=5
        )
        # ↑↑↑ end scheduler block ↑↑↑
    
        return app
    
    # ------------------------------
    # Participation & Bidder History
    # ------------------------------

    @app.route("/users/<string:username>/auctions", methods=["GET"])
    def user_auctions(username):
        u = User.query.filter_by(username=username).first_or_404()
        auctions = Auction.query.filter_by(seller_id=u.id).all()
        return jsonify([{
            "auction_id": a.id,
            "item_id":    a.item_id,
            "start_time": a.start_time.isoformat(),
            "end_time":   a.end_time.isoformat(),
            "status":     a.status
        } for a in auctions]), 200

    @app.route('/users/<string:username>/items', methods=['GET'])
    def user_items(username):
        u = User.query.filter_by(username=username).first_or_404()
        return jsonify([i.to_dict() for i in u.items]), 200
    
 
    @app.route("/users/<string:username>/bids", methods=["GET"])
    def user_bids(username):
        """
        List all bids placed by this user across all auctions.
        """
        bids = Bid.query.filter_by(bidder=username)\
                        .order_by(Bid.timestamp.desc()).all()
        return jsonify([{
            "bid_id":      b.id,
            "auction_id":  b.auction_id,
            "amount":      b.amount,
            "timestamp":   b.timestamp.isoformat()
        } for b in bids]), 200

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
    
    login.init_app(app)

    # -----------------
    # AUTH (API-only)
    # -----------------

    @app.route('/auth/register', methods=['POST'])
    def auth_register():
        data = request.get_json(force=True)
        u = data.get('username'); p = data.get('password')
        if not u or not p:
            return jsonify(error="username and password required"), 400
        if User.query.filter_by(username=u).first():
            return jsonify(error="User already exists"), 400
        user = User(username=u)
        user.set_password(p)
        db.session.add(user)
        db.session.commit()
        return jsonify(username=user.username), 201

    @app.route('/auth/login', methods=['POST'])
    def auth_login():
        data = request.get_json(force=True)
        u = data.get('username'); p = data.get('password')
        user = User.query.filter_by(username=u).first()
        if user is None or not user.check_password(p):
            return jsonify(error="Invalid credentials"), 400
        login_user(user)
        return jsonify(message="Logged in"), 200

    @app.route('/auth/logout', methods=['POST'])
    @login_required
    def auth_logout():
        logout_user()
        return jsonify(message="Logged out"), 200

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


    @app.route('/alerts/<string:username>/matches', methods=['GET'])
    def alert_matches(username):
        """
        GET /alerts/<username>/matches
        Returns, for each alert, the list of items matching its criteria.
        """
        alerts = Alert.query.filter_by(username=username).all()
        results = []
        for a in alerts:
            crit = a.criteria_json or {}
            q = Item.query
            for field, val in crit.items():
                if hasattr(Item, field):
                    q = q.filter(getattr(Item, field) == val)
            items = q.all()
            results.append({
                'alert_id':   a.id,
                'criteria':   crit,
                'matches':    [i.to_dict() for i in items]
            })
        return jsonify(results), 200    

    @app.route("/auctions/<int:auction_id>/close", methods=["POST"])
    def close_single_auction(auction_id):
        a = Auction.query.get_or_404(auction_id)
        if a.status == "closed":
            return jsonify(message=f"Auction {auction_id} already closed"), 200

        # 1) mark closed
        a.status = "closed"

        # 2) find top bid
        top = (
            Bid.query
               .filter_by(auction_id=auction_id)
               .order_by(Bid.amount.desc())
               .first()
        )
        # 3) if meets reserve, record it
        if top and top.amount >= a.reserve_price:
            a.winning_bid = top.amount
            winner = User.query.filter_by(username=top.bidder).first()
            a.winner_id   = winner.id if winner else None

        db.session.commit()
        return jsonify(
            message     = f"Auction {auction_id} closed",
            winner_id   = a.winner_id,
            winning_bid = a.winning_bid
        ), 200   

    @app.route("/users/<string:username>", methods=["POST"])
    def create_user(username):
        if User.query.filter_by(username=username).first():
            return jsonify(error="User already exists"), 400
        u = User(username=username)
        db.session.add(u); db.session.commit()
        return jsonify(username=u.username), 201

    
    @app.route('/auth/delete', methods=['DELETE'])
    @login_required
    def auth_delete():
        """Delete the currently logged-in user and all their data."""
        # grab the real User object before logout
        user = current_user._get_current_object()
        username = user.username
        # first log them out
        logout_user()
        # now delete the mapped User instance
        db.session.delete(user)
        db.session.commit()
        return jsonify(message=f"User {username!r} and all their data have been deleted"), 200
    
    # Update a category (only logged-in users)
    @app.route('/categories/<int:cat_id>', methods=['PUT'])
    @login_required
    def update_category(cat_id):
        cat = Category.query.get_or_404(cat_id)
        data = request.get_json(force=True)
        # allow changing name
        if 'name' in data:
            cat.name = data['name']
        # allow reparenting (or removing parent)
        if 'parent_id' in data:
            parent_id = data['parent_id']
            if parent_id is not None and not Category.query.get(parent_id):
                return jsonify(error="parent_id not found"), 404
            cat.parent_id = parent_id
        db.session.commit()
        return jsonify(cat.to_dict()), 200

    # Create a new item
    @app.route('/items', methods=['POST'])
    @login_required
    def create_item():
        data = request.get_json(force=True)
        title       = data.get('title')
        description = data.get('description')
        category_id = data.get('category_id')
    
        if not title or category_id is None:
            return jsonify(error="title and category_id are required"), 400
        if not Category.query.get(category_id):
            return jsonify(error="category_id not found"), 404
    
        # link to the currently-logged in user
        item = Item(
            title       = title,
            description = description,
            category_id = category_id,
            owner_id    = current_user.id
        )
        db.session.add(item)
        db.session.commit()
        return jsonify(item.to_dict()), 201   
    
    # Update an item (only its owner can)
    
    # Update an item (only its owner can)
    @app.route('/items/<int:item_id>', methods=['PUT'])
    @login_required
    def update_item(item_id):
        item = Item.query.get_or_404(item_id)
        if item.owner_id != current_user.id:
            return jsonify(error="Forbidden"), 403

        data = request.get_json(force=True)
        if 'title' in data:
            item.title = data['title']
        if 'description' in data:
            item.description = data['description']
        if 'category_id' in data:
            if not Category.query.get(data['category_id']):
                return jsonify(error="category_id not found"), 404
            item.category_id = data['category_id']

        db.session.commit()
        resp = item.to_dict()
        resp['owner_id'] = item.owner_id
        return jsonify(resp), 200

    # Delete an item (only its owner can)
    @app.route('/items/<int:item_id>', methods=['DELETE'])
    @login_required
    def delete_item(item_id):
        item = Item.query.get_or_404(item_id)
        if item.owner_id != current_user.id:
            return jsonify(error="Forbidden"), 403

        db.session.delete(item)
        db.session.commit()
        return '', 204
    
     # List all items (with optional ?category_id= filter)
    @app.route('/items', methods=['GET'])
    def list_items():
        cid = request.args.get('category_id', type=int)
        query = Item.query
        if cid is not None:
            query = query.filter_by(category_id=cid)
        items = query.all()
        return jsonify([i.to_dict() for i in items]), 200
    
    # Get a single item
    @app.route('/items/<int:item_id>', methods=['GET'])
    def get_item(item_id):
        item = Item.query.get(item_id)
        if not item:
            return jsonify(error="Item not found"), 404
        return jsonify(item.to_dict()), 200
        
    @app.route("/ping")
    def ping():
        return "pong", 200

    @app.route("/")
    def home():
        return redirect("/ping")

    return app
