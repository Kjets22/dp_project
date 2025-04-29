# app/__init__.py
from sqlalchemy import or_
from flask import Flask, jsonify, redirect, request, render_template, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_apscheduler import APScheduler
from werkzeug.security import check_password_hash

db = SQLAlchemy()
login = LoginManager()
login.login_view = 'auth_login'
sched = APScheduler()
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

    sched.init_app(app)
    sched.start()   
    @login.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))   

    
    @sched.task('interval', id='close_auctions', seconds=60, misfire_grace_time=120)
    def close_expired_auctions():
        now = datetime.utcnow()
        expired = Auction.query.filter(
            Auction.status=='open',
            Auction.end_time <= now
        ).all()
        for a in expired:
            top = (Bid.query
                      .filter_by(auction_id=a.id)
                      .order_by(Bid.amount.desc())
                      .first())
            if top and top.amount >= a.reserve_price:
                usr = User.query.filter_by(username=top.bidder).first()
                a.winner_id   = usr.id if usr else None
                a.winning_bid = top.amount
            else:
                a.winning_bid = top.amount if top else None
            a.status = 'closed'
        db.session.commit()

    # --------------- Auction Endpoints ----------------
    @app.route("/auctions/open/<int:item_id>", methods=["GET","POST"])
    @login_required
    def open_auction(item_id):
        item = Item.query.get_or_404(item_id)
        if item.owner_id != current_user.id:
            return redirect(url_for("user_detail", id=current_user.id))

        if request.method == "POST":
            end_time_str  = request.form.get("end_time","").strip()
            init_price    = request.form.get("init_price",    type=float)
            increment     = request.form.get("increment",     type=float)
            reserve_price = request.form.get("reserve_price", type=float)

            errors = []
            if not end_time_str:   errors.append("End time is required.")
            if init_price    is None: errors.append("Starting price is required.")
            if increment     is None: errors.append("Increment is required.")
            if reserve_price is None: errors.append("Reserve price is required.")
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
                    reserve_price = reserve_price,
                    status        = 'open'      # ← explicitly set to open
                )
                db.session.add(a)
                db.session.commit()
                return redirect(url_for("user_detail", id=current_user.id))

        return render_template("auctions/open.html", item=item)

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

        def get_top_bid():
            return (Bid.query
                    .filter_by(auction_id=auc_id)
                    .order_by(Bid.amount.desc())
                    .first())

        # 0) Auto‐close if past end_time (use local now, not UTC)
        if auction.status == 'open' and datetime.now() >= auction.end_time:
            top = get_top_bid()
            if top and top.amount >= auction.reserve_price:
                usr = User.query.filter_by(username=top.bidder).first()
                auction.winner_id   = usr.id if usr else None
                auction.winning_bid = top.amount
            else:
                auction.winning_bid = top.amount if top else None
            auction.status = 'closed'
            db.session.commit()

        # 1) Fetch the (possibly new) top bid & update winning_id
        top = get_top_bid()
        if top:
            current_price   = top.amount
            highest_bidder  = top.bidder
            usr_curr        = User.query.filter_by(username=top.bidder).first()
            auction.winning_id = usr_curr.id if usr_curr else None
        else:
            current_price   = auction.init_price
            highest_bidder  = None
            auction.winning_id = None
        db.session.commit()

        # 2) Handle a POST bid
        if request.method == "POST":
            if auction.status == 'closed':
                flash("This auction has ended; no more bids allowed.", "warning")
                return redirect(url_for("auction_detail", auc_id=auc_id))

            # ── Validation ─────────────────────────
            if current_user.id == auction.seller_id:
                flash("You cannot bid on your own auction.", "danger")
                return redirect(url_for("auction_detail", auc_id=auc_id))
            if highest_bidder == current_user.username:
                flash("You’re already the highest bidder.", "warning")
                return redirect(url_for("auction_detail", auc_id=auc_id))

            required_min = current_price + auction.increment
            max_raw      = request.form.get("max_bid","").strip()
            amt_raw      = request.form.get("bid_amount","").strip()

            # ── Build the user’s bid (with ceiling) ───────
            if max_raw:
                try:
                    ceiling = float(max_raw)
                except ValueError:
                    flash("Invalid max bid value.", "danger")
                    return redirect(url_for("auction_detail", auc_id=auc_id))
                if ceiling < required_min:
                    flash(f"Your max bid must be ≥ {required_min:.2f}.", "danger")
                    return redirect(url_for("auction_detail", auc_id=auc_id))
                bid_amt = min(ceiling, required_min)
            else:
                try:
                    bid_amt = float(amt_raw)
                except ValueError:
                    flash("Please enter a valid bid amount.", "danger")
                    return redirect(url_for("auction_detail", auc_id=auc_id))
                if bid_amt < required_min:
                    flash(f"Your bid must be at least {required_min:.2f}.", "danger")
                    return redirect(url_for("auction_detail", auc_id=auc_id))
                ceiling = bid_amt

            user_bid = Bid(
                auction_id=auc_id,
                bidder     = current_user.username,
                amount     = bid_amt,
                max_bid    = ceiling
            )
            db.session.add(user_bid)
            db.session.commit()
            flash("Your bid was placed!", "success")

            # 3) Collect each bidder’s top ceiling
            proxies = {}
            for b in Bid.query.filter_by(auction_id=auc_id):
                if b.max_bid is not None:
                    proxies[b.bidder] = max(proxies.get(b.bidder, 0), b.max_bid)

            # 4) Auto-bid back-and-forth between the top two ceilings
            while len(proxies) >= 2:
                top            = get_top_bid()
                current_price  = top.amount
                current_winner = top.bidder

                (u1,m1),(u2,m2) = sorted(proxies.items(), key=lambda x: x[1], reverse=True)[:2]
                if current_winner == u1:
                    nxt, nxt_max = u2, m2
                else:
                    nxt, nxt_max = u1, m1

                nxt_price = current_price + auction.increment
                if nxt_price > nxt_max:
                    break

                auto = Bid(
                    auction_id=auc_id,
                    bidder    = nxt,
                    amount    = nxt_price,
                    max_bid   = nxt_max
                )
                db.session.add(auto)
                db.session.commit()
                flash(f"Auto-bid: {nxt} → {nxt_price:.2f}", "info")

                usr_next = User.query.filter_by(username=nxt).first()
                auction.winning_id = usr_next.id if usr_next else None
                db.session.commit()

            return redirect(url_for("auction_detail", auc_id=auc_id))

        # 5) GET → render the page
        bids = (Bid.query
                .filter_by(auction_id=auc_id)
                .order_by(Bid.timestamp.desc())
                .all())

        return render_template(
            "auctions/detail.html",
            auction=        auction,
            item=           item,
            bids=           bids,
            current_price=  current_price,
            highest_bidder= highest_bidder
        )

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
    
    @app.route('/auth/delete', methods=['GET'])
    @login_required
    def auth_delete():
        # only allow yourself
        if current_user.is_authenticated:
            return render_template('auth/delete.html')
        return redirect(url_for('auth_login'))

    # Process deletion
    @app.route('/auth/delete', methods=['POST'])
    @login_required
    def auth_delete_post():
        pwd = request.form.get('password', '')
        user = User.query.get(current_user.id)

        # check password
        if not user or not user.check_password(pwd):
            flash('Password incorrect. Account not deleted.', 'danger')
            return render_template('auth/delete.html'), 400

        # delete user and cascade all related objects
        logout_user()
        db.session.delete(user)
        db.session.commit()
        flash('Your account and all associated data have been removed.', 'success')
        return redirect(url_for('home'))
    
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


    @app.route('/auctions/<int:auc_id>/similar', methods=['GET'])
    def similar_auctions(auc_id):
        """
        Return auctions on similar items (same category) in the last 30 days,
        excluding auction `auc_id` itself.
        """
        # 1) Look up the target auction (404 if not found)
        a = Auction.query.get_or_404(auc_id)
    
        # 2) Determine cutoff (30 days ago)
        cutoff = datetime.utcnow() - timedelta(days=30)
    
        # 3) Query for other auctions in same category
        sims = (
            db.session.query(Auction)
              .join(Item)
              .filter(
                  Auction.id != auc_id,
                  Item.category_id == a.item.category_id,
                  Auction.start_time >= cutoff
              )
              .order_by(Auction.start_time.desc())
              .all()
        )
    
        # 4) Build JSON response
        out = []
        for s in sims:
            out.append({
                'auction_id':   s.id,
                'item_id':      s.item_id,
                'title':        s.item.title,
                'description':  s.item.description,
                'start_time':   s.start_time.isoformat(),
                'end_time':     s.end_time.isoformat(),
                'init_price':   s.init_price,
                'status':       s.status
            })
        return jsonify(out), 200

    @app.route("/users/<string:username>", methods=["POST"])
    def create_user(username):
        if User.query.filter_by(username=username).first():
            return jsonify(error="User already exists"), 400
        u = User(username=username)
        db.session.add(u); db.session.commit()
        return jsonify(username=u.username), 201

    
    # @app.route('/auth/delete', methods=['DELETE'])
    # @login_required
    # def auth_delete():
    #     """Delete the currently logged-in user and all their data."""
    #     # grab the real User object before logout
    #     user = current_user._get_current_object()
    #     username = user.username
    #     # first log them out
    #     logout_user()
    #     # now delete the mapped User instance
    #     db.session.delete(user)
    #     db.session.commit()
    #     return jsonify(message=f"User {username!r} and all their data have been deleted"), 200
    
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
        # 1) load the item (and its auctions)
        item = Item.query.get_or_404(item_id)

        # 2) auto-close any expired auctions on this item
        now = datetime.now()
        for auc in item.auctions:
            if auc.status == 'open' and now >= auc.end_time:
                # find the top bid
                top = (Bid.query
                        .filter_by(auction_id=auc.id)
                        .order_by(Bid.amount.desc())
                        .first())
                if top and top.amount >= auc.reserve_price:
                    winner = User.query.filter_by(username=top.bidder).first()
                    auc.winner_id   = winner.id if winner else None
                    auc.winning_bid = top.amount
                else:
                    auc.winning_bid = top.amount if top else None
                auc.status = 'closed'
        db.session.commit()

        # 3) render the template (status on each auc is now up-to-date)
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
        resp = item.to_dict()
        resp['owner_id'] = item.owner_id
        return jsonify(resp), 200
    
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
        # 0) Auto-close any expired auctions
        now = datetime.now()
        expired = Auction.query.filter(
            Auction.status == 'open',
            Auction.end_time <= now
        ).all()
        for auc in expired:
            top = (Bid.query
                    .filter_by(auction_id=auc.id)
                    .order_by(Bid.amount.desc())
                    .first())
            if top and top.amount >= auc.reserve_price:
                usr = User.query.filter_by(username=top.bidder).first()
                auc.winner_id   = usr.id if usr else None
                auc.winning_bid = top.amount
            else:
                auc.winning_bid = top.amount if top else None
            auc.status = 'closed'
        if expired:
            db.session.commit()

        # 1) Load all items
        items = Item.query.order_by(Item.id.desc()).all()
        return render_template("index.html", items=items)

    @app.route('/browse', methods=['GET'])
    def browse():
        # pull query-params
        q            = request.args.get('q', '').strip()
        category_id  = request.args.get('category_id', type=int)
        min_price    = request.args.get('min_price',   type=float)
        max_price    = request.args.get('max_price',   type=float)
        status       = request.args.get('status')  # 'open', 'closed', or None

        # start from Item → Auction (left join so we still see items without auctions)
        query = (
            Item.query
                .outerjoin(Auction, Auction.item_id == Item.id)
        )

        # text search on Item
        if q:
            query = query.filter(or_(
                Item.title.ilike(f'%{q}%'),
                Item.description.ilike(f'%{q}%')
            ))

        # category filter
        if category_id:
            query = query.filter(Item.category_id == category_id)

        # auction‐level filters
        if min_price is not None:
            query = query.filter(Auction.init_price >= min_price)
        if max_price is not None:
            query = query.filter(Auction.init_price <= max_price)
        if status in ('open', 'closed'):
            query = query.filter(Auction.status == status)

        # finally, fetch and render
        items = query.order_by(Item.id.desc()).all()
        return render_template(
            'browse.html',
            items=items,
            # pass back all the filter values so the form can re-populate
            q=q,
            categories=Category.query.order_by(Category.name).all(),
            selected_category=category_id,
            min_price=min_price,
            max_price=max_price,
            selected_status=status
        )
    return app
