# app/__init__.py
from sqlalchemy import or_
from flask import Flask, jsonify, redirect, request, render_template, url_for, flash
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
    @app.route("/auctions/open/<int:item_id>", methods=["GET","POST"])
    @login_required
    def open_auction(item_id):
        # 1) Grab the item, ensuring it belongs to current_user
        item = Item.query.get_or_404(item_id)
        if item.owner_id != current_user.id:
            return redirect(url_for("user_detail", id=current_user.id))

        # 2) On POST, read the form and create Auction
        if request.method == "POST":
            end_time_str  = request.form.get("end_time","").strip()
            init_price    = request.form.get("init_price", type=float)
            increment     = request.form.get("increment", type=float)
            reserve_price = request.form.get("reserve_price", type=float)

            # basic validation
            errors = []
            if not end_time_str:
                errors.append("End time is required.")
            if init_price is None:
                errors.append("Starting price is required.")
            if increment is None:
                errors.append("Increment is required.")
            if reserve_price is None:
                errors.append("Reserve price is required.")
            # parse datetime
            try:
                end_time = datetime.fromisoformat(end_time_str)
            except ValueError:
                errors.append("Invalid end-time format; use YYYY-MM-DDTHH:MM.")

            if errors:
                for e in errors:
                    flash(e, "danger")
            else:
                a = Auction(
                    item_id       = item.id,
                    seller_id     = current_user.id,
                    end_time      = end_time,
                    init_price    = init_price,
                    increment     = increment,
                    reserve_price = reserve_price
                )
                db.session.add(a)
                db.session.commit()
                return redirect(url_for("user_detail", id=current_user.id))

        # 3) On GET (or if validation failed), render the form
        return render_template("auctions/open.html", item=item)
    # @app.route('/auctions/<int:item_id>', methods=['POST'])
    # def create_auction(item_id):
    #     data = request.get_json(force=True)
    #     # must pass: username, end_time (ISO8601), init_price, increment, reserve_price
    #     username = data.get('username')
    #     end_str  = data.get('end_time')
    #     if not username or not end_str:
    #         return jsonify(error="username and end_time required"), 400
    
    #     user = User.query.filter_by(username=username).first()
    #     if not user:
    #         return jsonify(error="User not found"), 404
    
    #     item = Item.query.get(item_id)
    #     if not item:
    #         return jsonify(error="Item not found"), 404
    
    #     try:
    #         end_dt = datetime.fromisoformat(end_str)
    #     except ValueError:
    #         return jsonify(error="Invalid end_time format"), 400
    
    #     a = Auction(
    #         item_id       = item_id,
    #         seller_id     = user.id,
    #         end_time      = end_dt,
    #         init_price    = data.get('init_price', 0),
    #         increment     = data.get('increment', 1),
    #         reserve_price = data.get('reserve_price', 0),
    #     )
    #     db.session.add(a)
    #     db.session.commit()
    #     return jsonify(id=a.id), 201
    
    
    @app.route("/auctions/<int:auc_id>/detail", methods=["GET","POST"])
    @login_required
    def auction_detail(auc_id):
        auction = Auction.query.get_or_404(auc_id)
        item    = auction.item

        # 1) compute current price & highest‐bidder
        highest_bid_record = (
            Bid.query
            .filter_by(auction_id=auc_id)
            .order_by(Bid.amount.desc())
            .first()
        )
        if highest_bid_record:
            current_price  = highest_bid_record.amount
            highest_bidder = highest_bid_record.bidder
        else:
            current_price  = auction.init_price
            highest_bidder = None

        # 2) process new‐bid POST
        if request.method == "POST":
            # a) owner can’t bid on own auction
            if current_user.id == auction.seller_id:
                return redirect(url_for("auction_detail", auc_id=auc_id))

            # b) highest bidder can’t outbid themself
            if highest_bidder == current_user.username:
                return redirect(url_for("auction_detail", auc_id=auc_id))

            # c) parse & validate amount
            try:
                new_amount = float(request.form["bid_amount"])
            except (KeyError, ValueError):
                return redirect(url_for("auction_detail", auc_id=auc_id))

            required_min = current_price + auction.increment
            if new_amount < required_min:
                return redirect(url_for("auction_detail", auc_id=auc_id))

            # d) record the bid
            b = Bid(
                auction_id=auc_id,
                bidder=     current_user.username,
                amount=     new_amount
            )
            db.session.add(b)
            db.session.commit()
            return redirect(url_for("auction_detail", auc_id=auc_id))

        # 3) GET → render
        bids = (
            Bid.query
            .filter_by(auction_id=auc_id)
            .order_by(Bid.timestamp.desc())
            .all()
        )
        return render_template(
            "auctions/detail.html",
            auction=auction,
            item=item,
            bids=bids,
            current_price=current_price,
            highest_bidder=highest_bidder
        )
    
    @app.route('/auctions', methods=['GET'])
    def list_auctions():
        all_aucs = Auction.query.all()
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
        } for a in all_aucs])
    
    
    @app.route('/auctions/<int:auc_id>', methods=['GET'])
    def get_auction(auc_id):
        a = Auction.query.get(auc_id)
        if not a:
            return jsonify(error="Auction not found"), 404
        return jsonify({
            'id':            a.id,
            'item_id':       a.item_id,
            'seller_id':     a.seller_id,
            'start_time':    a.start_time.isoformat(),
            'end_time':      a.end_time.isoformat(),
            'init_price':    a.init_price,
            'increment':     a.increment,
            'reserve_price': a.reserve_price,
            'status':        a.status,
        }) 
    # -------------- (keep your existing routes) ----------------
    from app.models import User, Category, Item, Auction, Bid, Alert

    @app.route("/users", methods=["GET"])
    def list_users():
        return jsonify([u.username for u in User.query.all()]), 200
    
    # # Create a new category (optionally as a subcategory)
    @app.route("/categories/create", methods=["GET","POST"])
    @login_required
    def create_category_form():
        # pass existing categories if you want to allow nesting
        categories = Category.query.order_by(Category.name).all()

        if request.method == "POST":
            name      = request.form.get("name","").strip()
            parent_id = request.form.get("parent_id", type=int) or None

            if not name:
                return redirect(url_for("create_category_form"))

            cat = Category(name=name, parent_id=parent_id)
            db.session.add(cat)
            db.session.commit()
            return redirect(url_for("create_item_form"))

        return render_template(
            "category/create.html",
            categories=categories
        )
    # @app.route('/categories', methods=['POST'])
    # def create_category():
    #     data = request.get_json(force=True)
    #     name = data.get('name')
    #     parent_id = data.get('parent_id')  # optional
    #     if not name:
    #         return jsonify(error="name is required"), 400
    #     # verify parent exists if given
    #     if parent_id is not None and not Category.query.get(parent_id):
    #         return jsonify(error="parent_id not found"), 404
    
    #     cat = Category(name=name, parent_id=parent_id)
    #     db.session.add(cat)
    #     db.session.commit()
    #     return jsonify(cat.to_dict()), 201
    
    # # List all categories
    # @app.route('/categories', methods=['GET'])
    # def list_categories():
    #     cats = Category.query.all()
    #     return jsonify([c.to_dict() for c in cats]), 200
    
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
    
    @app.route('/auth/register', methods=['GET'])
    def auth_register_form():
        return render_template('/auth/register.html')

    @app.route('/auth/register', methods=['POST'])
    def auth_register():
        form      = request.form
        username  = form.get('username', '').strip()
        password  = form.get('password', '')
        full_name = form.get('full_name', '').strip()
        dob_str   = form.get('date_of_birth', '').strip()

        errors = []
        if not username:
            errors.append("Username is required.")
        if not password:
            errors.append("Password is required.")
        if not full_name:
            errors.append("Full name is required.")
        if not dob_str:
            errors.append("Date of birth is required.")

        # duplicate‐username check
        if username and User.query.filter_by(username=username).first():
            errors.append("That username is already taken.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for('auth_register'))

        # parse date_of_birth
        try:
            date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
        except ValueError:
            return redirect(url_for('auth_register'))

        # create & save the user
        user = User(
            username=username,
            full_name=full_name,
            date_of_birth=date_of_birth
        )
        user.set_password(password)     # your model’s hashing method
        db.session.add(user)
        db.session.commit()

        return redirect(url_for('auth_login'))
    
    @app.route("/auth/check_username", methods=["GET"])
    def check_username():
        uname = request.args.get("username", "").strip()
        if not uname:
            return jsonify(error="No username provided"), 400

        taken = User.query.filter_by(username=uname).first() is not None
        return jsonify(available=not taken), 200
    
    # @app.route('/auth/login', methods=['GET'])
    # def auth_login_form():
    #     return render_template('/auth/login.html')
    
    @app.route('/auth/login', methods=['GET','POST'])
    def auth_login():
        if request.method == 'GET':
            # Show the HTML login page
            return render_template('auth/login.html')

        # POST: process form fields
        form     = request.form
        username = form.get('username', '').strip()
        password = form.get('password', '')

        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            # re-render the form with a flash message
            return render_template('auth/login.html'), 400

        # login_user will set up the session
        login_user(user)
        # redirect to your user_detail view, which is /users/<id>
        return redirect(url_for('user_detail', id=user.id))
    
    @app.route("/auth/<int:id>", methods=["GET"])
    @login_required
    def user_detail(id):
        # fetch the user or 404
        user = User.query.get_or_404(id)

        # 1) Auctions they created
        created_aucs = Auction.query.filter_by(seller_id=user.id).all()

        # 2) Auctions they've bid on
        participated = (
            Auction.query
                   .join(Bid, Bid.auction_id == Auction.id)
                   .filter(Bid.bidder == user.username)
                   .filter(Auction.seller_id != user.id)
                   .distinct()
                   .all()
        )

        # 3) Items they own
        created_items = user.items  # thanks to owner backref in Item model

        return render_template(
            "/auth/detail.html",
            user=user,
            created_items=created_items,
            created_aucs=created_aucs,
            participated=participated
        )
    # def user_detail(id):
    #     user = User.query.get_or_404(id)
    #     print(1)
    #     return render_template("/auth/detail.html", user=user)

    @app.route('/auth/logout', methods=['POST'])
    @login_required
    def auth_logout():
        if  request.method == "POST":
            logout_user()
        return render_template("/auth/logout.html")

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

    @app.route("/run_close", methods=["POST"])
    def run_close():
        """
        Manually invoke close_auctions() so you can test closing of expired auctions immediately.
        """
        from app.tasks import close_auctions
        close_auctions()
        return "Auctions closed", 200

    @app.route("/users/<string:username>", methods=["POST"])
    def create_user(username):
        if User.query.filter_by(username=username).first():
            return jsonify(error="User already exists"), 400
        u = User(username=username)
        db.session.add(u); db.session.commit()
        return jsonify(username=u.username), 201

    
    # # Create a new item
    @app.route("/items/create", methods=["GET","POST"])
    @login_required
    def create_item_form():
        # load all categories for the dropdown
        categories = Category.query.order_by(Category.name).all()

        if request.method == "POST":
            title       = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            category_id = request.form.get("category_id", type=int)

            # form validation
            errors = []
            if not title:
                errors.append("Title is required.")
            if not category_id or not Category.query.get(category_id):
                errors.append("Please select a valid category.")

            if errors:
                for e in errors:
                    flash(e, "danger")
                return redirect(url_for("create_item_form"))

            # create the item
            item = Item(
                title=title,
                description=description,
                category_id=category_id,
                owner_id=current_user.id
            )
            db.session.add(item)
            db.session.commit()
            return redirect(url_for("user_detail", id=current_user.id))

        # GET → show the form
        return render_template(
            "items/create.html",
            categories=categories
        )
    @app.route("/items/<int:item_id>", methods=["GET"])
    @login_required
    def item_detail(item_id):
        item = Item.query.get_or_404(item_id)
        return render_template("items/detail.html", item=item)
    # @app.route('/items', methods=['GET'])
    # def create_item_form():
    #     return render_template("/items/create.html")
        
    # @app.route('/items', methods=['POST'])
    # @login_required
    # def create_item():
    #     data = request.get_json(force=True)
    #     title       = data.get('title')
    #     description = data.get('description')
    #     category_id = data.get('category_id')
    #     if not title or category_id is None:
    #         return jsonify(error="title and category_id are required"), 400
    #     if not Category.query.get(category_id):
    #         return jsonify(error="category_id not found"), 404
    
    #    # link to the current user
    #     item = Item(
    #         title=title,
    #         description=description,
    #         category_id=category_id,
    #         owner_id=current_user.id
    #     )
    #     db.session.add(item)
    #     db.session.commit()
    #     return jsonify(item.to_dict()), 201
    
    
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
        return jsonify(item.to_dict()), 200
    
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
        # fetch all items, newest first
        from app.models import Item
        items = Item.query.order_by(Item.id.desc()).all()
        return render_template("index.html", items=items)

    @app.route('/browse', methods=['GET'])
    def browse():
        # pull query params
        q           = request.args.get('q', '').strip()
        category_id = request.args.get('category_id', type=int)
        min_price   = request.args.get('min_price', type=float)
        max_price   = request.args.get('max_price', type=float)

        # show nothing until the user actually searches or picks a filter
        if not (q or category_id or min_price is not None or max_price is not None):
            return render_template(
                'browse.html',
                items=[],
                q=q,
                categories=Category.query.order_by(Category.name).all(),
                selected_category=category_id,
                min_price=min_price,
                max_price=max_price
            )

        # build the query
        query = Item.query

        # text search on title or description
        if q:
            query = query.filter(or_(
                Item.title.ilike(f'%{q}%'),
                Item.description.ilike(f'%{q}%')
            ))

        # filter by category if given
        if category_id:
            query = query.filter_by(category_id=category_id)

        # only show items with an open auction
        query = query.join(Auction, (Auction.item_id == Item.id) & (Auction.status == 'open'))

        # filter by auction’s starting price as an approximation for “price range”
        if min_price is not None:
            query = query.filter(Auction.init_price >= min_price)
        if max_price is not None:
            query = query.filter(Auction.init_price <= max_price)

        items = query.order_by(Item.id.desc()).all()

        return render_template(
            'browse.html',
            items=items,
            q=q,
            categories=Category.query.order_by(Category.name).all(),
            selected_category=category_id,
            min_price=min_price,
            max_price=max_price
        )
    return app
