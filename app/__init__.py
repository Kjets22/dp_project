# app/__init__.py
from sqlalchemy import or_
from flask import Flask, jsonify, redirect, request, render_template, url_for, flash, session
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_apscheduler import APScheduler
from flask_mail import Mail, Message
from sqlalchemy import func

db = SQLAlchemy()
login = LoginManager()
login.login_view = 'auth_login'
mail = Mail()
sched = APScheduler()
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            return jsonify(error="Forbidden"), 403
        return f(*args, **kwargs)
    return decorated

def rep_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not (current_user.is_rep or current_user.is_admin):
            return jsonify(error="Forbidden"), 403
        return f(*args, **kwargs)
    return decorated
    
def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")
    mail.init_app(app)

    db.init_app(app)
    with app.app_context():
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

        if auction.status == 'open' and datetime.now() >= auction.end_time:
            top = get_top_bid()
            if top and top.amount >= auction.reserve_price:
                auction.winner_id   = top.bidder_id
                auction.winning_bid = top.amount
            else:
                auction.winning_bid = top.amount if top else None
            auction.status = 'closed'
            db.session.commit()

        top = get_top_bid()
        if top:
            current_price   = top.amount
            highest_bidder  = top.bidder
            auction.winning_id = top.bidder_id
        else:
            current_price   = auction.init_price
            highest_bidder  = None
            auction.winning_id = None
        db.session.commit()

        if request.method == "POST":
            if auction.status == 'closed':
                flash("This auction has ended; no more bids allowed.", "warning")
                return redirect(url_for("auction_detail", auc_id=auc_id))

            if current_user.id == auction.seller_id:
                flash("You cannot bid on your own auction.", "danger")
                return redirect(url_for("auction_detail", auc_id=auc_id))

            if highest_bidder in (current_user.username, f"anonymous{current_user.id}"):
                flash("You’re already the highest bidder.", "warning")
                return redirect(url_for("auction_detail", auc_id=auc_id))

            prev_top = top
            prev_bidder_id = prev_top.bidder_id if prev_top else None

            required_min = (top.amount if top else auction.init_price) + auction.increment
            max_raw      = request.form.get("max_bid","").strip()
            amt_raw      = request.form.get("bid_amount","").strip()

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

            anonymous = bool(request.form.get("anonymous"))
            bidder_str = f"anonymous{current_user.id}" if anonymous else current_user.username

            user_bid = Bid(
                auction_id = auc_id,
                bidder     = bidder_str,
                bidder_id  = current_user.id,
                amount     = bid_amt,
                max_bid    = ceiling
            )
            db.session.add(user_bid)
            db.session.commit()
            flash("Your bid was placed!", "success")

            if prev_bidder_id and prev_bidder_id != current_user.id:
                prev_user = User.query.get(prev_bidder_id)
                if prev_user and prev_user.email:
                    with app.app_context():
                        msg = Message(
                            subject="You’ve been outbid!",
                            recipients=[prev_user.email]
                        )
                        msg.body = (
                            f"Hi {prev_user.username},\n\n"
                            f"You were the highest bidder on “{item.title}” "
                            f"but have just been outbid at ${bid_amt:.2f}.\n"
                            "If you want to place a higher bid, go back to the auction now!\n\n"
                            "– The Auction Team"
                        )
                        mail.send(msg)

            proxies = {}
            for b in Bid.query.filter_by(auction_id=auc_id):
                if b.max_bid is not None:
                    proxies[b.bidder] = max(proxies.get(b.bidder, 0), b.max_bid)

            while len(proxies) >= 2:
                top            = get_top_bid()
                current_price  = top.amount
                current_winner = top.bidder

                (b1,c1),(b2,c2) = sorted(proxies.items(), key=lambda x: x[1], reverse=True)[:2]
                nxt, nxt_max    = (b2, c2) if current_winner == b1 else (b1, c1)

                nxt_price = current_price + auction.increment
                if nxt_price > nxt_max:
                    break

                if nxt.startswith("anonymous"):
                    try:
                        anon_id = int(nxt.replace("anonymous",""))
                    except ValueError:
                        anon_id = None
                    auto_bidder_id = anon_id
                else:
                    real = User.query.filter_by(username=nxt).first()
                    auto_bidder_id = real.id if real else None

                auto = Bid(
                    auction_id = auc_id,
                    bidder     = nxt,
                    bidder_id  = auto_bidder_id,
                    amount     = nxt_price,
                    max_bid    = nxt_max
                )
                db.session.add(auto)
                db.session.commit()
                flash(f"Auto-bid: {nxt} → {nxt_price:.2f}", "info")

                auction.winning_id = auto.bidder_id
                db.session.commit()

            return redirect(url_for("auction_detail", auc_id=auc_id))

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
        status      = request.args.get('status')
        title       = request.args.get('title')
        description = request.args.get('description')
        category_id = request.args.get('category_id', type=int)
        min_price   = request.args.get('min_price',   type=float)
        max_price   = request.args.get('max_price',   type=float)

        q = Auction.query.join(Item)

        if status in ('open', 'closed'):
            q = q.filter(Auction.status == status)
        if min_price is not None:
            q = q.filter(Auction.init_price >= min_price)
        if max_price is not None:
            q = q.filter(Auction.init_price <= max_price)

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
        q = Auction.query.join(Item)

        title       = request.args.get('title')
        category_id = request.args.get('category_id', type=int)
        min_price   = request.args.get('min_price',   type=float)
        max_price   = request.args.get('max_price',   type=float)
        status      = request.args.get('status')

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
            'winner':       a.winner.username if a.winner else None,
            'winning_bid':  a.winning_bid,
        }
        return jsonify(resp), 200

    @app.route('/questions', methods=['POST'])
    @login_required
    def ask_question():
        data = request.get_json(force=True)
        aq   = data.get('auction_id')
        txt  = data.get('question')
        if not aq or not txt:
            return jsonify(error="auction_id and question required"), 400
        Auction.query.get_or_404(aq)
        q = Question(
            auction_id   = aq,
            user_id      = current_user.id,
            question_text= txt
        )
        db.session.add(q)
        db.session.commit()
        return jsonify(
            id         = q.id,
            created_at = q.created_at.isoformat()
        ), 201
    
    @app.route('/questions', methods=['GET'])
    @login_required
    def list_questions():
        aq = request.args.get('auction_id', type=int)
        q = Question.query
        if aq is not None:
            q = q.filter_by(auction_id=aq)
        qs = q.order_by(Question.created_at).all()
        return jsonify([{
          'id':           ques.id,
          'auction_id':   ques.auction_id,
          'asker_id':     ques.user_id,
          'question':     ques.question_text,
          'asked_at':     ques.created_at.isoformat(),
          'answer':       ques.answer_text,
          'answered_at':  ques.answered_at and ques.answered_at.isoformat()
        } for ques in qs]), 200   

    @app.route('/questions/<int:q_id>', methods=['GET'])
    @login_required
    def get_question(q_id):
        ques = Question.query.get_or_404(q_id)
        return jsonify({
          'id':           ques.id,
          'auction_id':   ques.auction_id,
          'asker_id':     ques.user_id,
          'question':     ques.question_text,
          'asked_at':     ques.created_at.isoformat(),
          'answer':       ques.answer_text,
          'answered_at':  ques.answered_at and ques.answered_at.isoformat()
        }), 200   

    @app.route('/questions/<int:q_id>/answer', methods=['POST'])
    @rep_required
    def answer_question(q_id):
        q = Question.query.get_or_404(q_id)

        # First try to pull from form data (your HTML form)
        ans = request.form.get('answer', '').strip()

        # If not in form, try JSON payload
        if not ans:
            data = request.get_json(silent=True) or {}
            ans = (data.get('answer') or '').strip()

        if not ans:
            # If this was an API call, return JSON error
            if request.is_json:
                return jsonify(error="answer required"), 400
            # Otherwise flash & redirect back to rep dashboard
            flash("Please enter an answer before submitting.", "danger")
            return redirect(url_for('rep_detail', id=current_user.id))

        # Save the answer
        q.answer_text     = ans
        q.answered_by_id  = current_user.id
        q.answered_at     = datetime.utcnow()
        db.session.commit()

        # Respond appropriately
        if request.is_json:
            return jsonify(message="answered", answered_at=q.answered_at.isoformat()), 200

        flash("Your reply has been posted.", "success")
        return redirect(url_for('rep_detail', id=current_user.id))
        
    from app.models import User, Category, Item, Auction, Bid, Alert, Question

    @app.route("/users", methods=["GET"])
    def list_users():
        return jsonify([u.username for u in User.query.all()]), 200
    
    @app.route("/categories/create", methods=["GET","POST"])
    @login_required
    def create_category_form():
        next_page = request.args.get('next') or request.referrer or url_for('home')
        categories = Category.query.order_by(Category.name).all()

        if request.method == "POST":
            name      = request.form.get("name","").strip()
            parent_id = request.form.get("parent_id", type=int) or None
            if not name:
                return redirect(request.url)

            cat = Category(name=name, parent_id=parent_id)
            db.session.add(cat)
            db.session.commit()
            return redirect(next_page)

        return render_template(
            "category/create.html",
            categories=categories,
            next_page=next_page
        )
    
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
        
    @app.route("/alerts/<int:id>", methods=["GET"])
    @login_required
    def alert_detail(id):
        if current_user.id != id:
            return jsonify(message="Forbidden"), 403

        alerts = (
            Alert.query
                .filter_by(username=current_user.username)
                .order_by(Alert.created_at.desc())
                .all()
        )
        return render_template("alerts/detail.html", alerts=alerts)
    
    @app.route("/alerts/<int:alert_id>/delete", methods=["POST"])
    @login_required
    def delete_alert(alert_id):
        a = Alert.query.get_or_404(alert_id)
        if a.username != current_user.username:
            return jsonify(message="Forbidden"), 403
        db.session.delete(a)
        db.session.commit()
        return redirect(url_for("manage_alerts"))

    @app.route("/alerts/<int:id>/create", methods=["GET","POST"])
    @login_required
    def create_alert(id):
        if current_user.id != id:
            return jsonify(message="Forbidden"), 403

        categories = Category.query.order_by(Category.name).all()

        if request.method == "POST":
            crit = {}
            cat_id    = request.form.get("category_id", type=int)
            min_price = request.form.get("min_price",   type=float)
            max_price = request.form.get("max_price",   type=float)

            if cat_id:
                crit["category_id"] = cat_id
            if min_price is not None:
                crit["min_price"] = min_price
            if max_price is not None:
                crit["max_price"] = max_price

            a = Alert(username=current_user.username, criteria_json=crit)
            db.session.add(a)
            db.session.commit()
            return redirect(url_for("alert_detail", id=id))

        return render_template(
            "alerts/create.html",
            categories=categories,
        )


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
    
    @app.route('/auth/register', methods=['GET'])
    def auth_register_form():
        return render_template('/auth/register.html')

    @app.route('/auth/register', methods=['GET','POST'])
    def auth_register():
        if request.method == 'GET':
            return render_template('auth/register.html')

        form = request.form
        username      = form.get('username', '').strip()
        password      = form.get('password', '')
        full_name     = form.get('full_name', '').strip()
        dob_str       = form.get('date_of_birth', '').strip()
        email         = form.get('email', '').strip()

        errors = []
        if not username:
            errors.append("Username is required.")
        if not password:
            errors.append("Password is required.")
        if not full_name:
            errors.append("Full name is required.")
        if not dob_str:
            errors.append("Date of birth is required.")
        if not email:
            errors.append("Email is required.")

        if username and User.query.filter_by(username=username).first():
            errors.append("That username is already taken.")
        if email and User.query.filter_by(email=email).first():
            errors.append("That email is already registered.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for('auth_register'))

        try:
            date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid date of birth format; use YYYY-MM-DD.", "danger")
            return redirect(url_for('auth_register'))

        user = User(
            username=username,
            email=email,
            full_name=full_name,
            date_of_birth=date_of_birth
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for('auth_login'))
    
    @app.route('/auth/delete', methods=['GET'])
    @login_required
    def auth_delete():
        if current_user.is_authenticated:
            return render_template('auth/delete.html')
        return redirect(url_for('auth_login'))

    @app.route('/auth/delete', methods=['POST'])
    @login_required
    def auth_delete_post():
        pwd = request.form.get('password', '')
        user = User.query.get(current_user.id)

        if not user or not user.check_password(pwd):
            flash('Password incorrect. Account not deleted.', 'danger')
            return render_template('auth/delete.html'), 400

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
    
    @app.route("/auth/check_email", methods=["GET"])
    def check_email():
        email = request.args.get("email", "").strip()
        if not email:
            return jsonify(error="No email provided"), 400
        taken = User.query.filter_by(email=email).first() is not None
        return jsonify(available=not taken), 200
    
    
    @app.route('/auth/login', methods=['GET','POST'])
    def auth_login():
        if request.method == 'GET':
            return render_template('auth/login.html')

        form     = request.form
        username = form.get('username', '').strip()
        password = form.get('password', '')

        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            return render_template('auth/login.html'), 400

        login_user(user)

        if user.is_admin:
            return redirect(url_for('admin_detail', id=user.id))
        elif user.is_rep:
            return redirect(url_for('rep_detail', id=user.id))
        else:
            return redirect(url_for('user_detail',  id=user.id))
    
    @app.route("/auth/<int:id>", methods=["GET"])
    @login_required
    def user_detail(id):
        user = User.query.get_or_404(id)

        created_aucs = Auction.query.filter_by(seller_id=user.id).all()

        participated = (
            Auction.query
                   .join(Bid, Bid.auction_id == Auction.id)
                   .filter(Bid.bidder == user.username)
                   .filter(Auction.seller_id != user.id)
                   .distinct()
                   .all()
        )

        created_items = user.items

        if user.is_admin:
            return redirect(url_for('admin_detail', id=user.id))
        elif user.is_rep:
            return redirect(url_for('rep_detail', id=user.id))
        else:
            return render_template(
                "/auth/detail.html",
                user=user,
                created_items=created_items,
                created_aucs=created_aucs,
                participated=participated
            )

    @app.route('/auth/logout', methods=['POST'])
    @login_required
    def auth_logout():
        if  request.method == "POST":
            logout_user()
        return render_template("/auth/logout.html")

    @app.route("/auctions/<int:auction_id>/bids", methods=["GET"])
    def list_bids(auction_id):
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
        user_obj = User.query.filter_by(username=user).first_or_404()
        highest = (
            db.session.query(db.func.max(Bid.amount))
                .filter_by(auction_id=auction_id)
                .scalar()
            or auction.init_price
        )

        if "max_bid" in data:
            max_bid = float(data["max_bid"])
            if max_bid <= highest:
                return jsonify(error=f"Your max_bid must exceed current bid ({highest})"), 400

            target = highest + auction.increment
            bid_amt = min(max_bid, target)

            b = Bid(
                auction_id=auction_id,
                bidder=user,
                bidder_id=user_obj.id,
                amount=bid_amt,
                max_bid=max_bid
            )
            db.session.add(b)
            db.session.commit()
            return jsonify(
                id=b.id,
                bidder=b.bidder,
                bidder_id=user_obj.id,
                amount=b.amount,
                max_bid=b.max_bid,
                timestamp=b.timestamp.isoformat()
            ), 201

        if "amount" in data:
            amt = float(data["amount"])
            if amt < highest + auction.increment:
                return jsonify(error=f"Bid must be ≥ {highest + auction.increment}"), 400
            if amt < auction.reserve_price:
                return jsonify(error="Bid below reserve price"), 400

            b = Bid(
                auction_id=auction_id,
                bidder=user,
                bidder_id=user_obj.id,
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

        return jsonify(error="Either 'amount' or 'max_bid' is required"), 400
   

    
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

        a.status = "closed"

        top = (
            Bid.query
               .filter_by(auction_id=auction_id)
               .order_by(Bid.amount.desc())
               .first()
        )
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
        a = Auction.query.get_or_404(auc_id)
    
        cutoff = datetime.utcnow() - timedelta(days=30)
    
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
    
    @app.route('/categories/<int:cat_id>', methods=['PUT'])
    @login_required
    def update_category(cat_id):
        cat = Category.query.get_or_404(cat_id)
        data = request.get_json(force=True)
        if 'name' in data:
            cat.name = data['name']
        if 'parent_id' in data:
            parent_id = data['parent_id']
            if parent_id is not None and not Category.query.get(parent_id):
                return jsonify(error="parent_id not found"), 404
            cat.parent_id = parent_id
        db.session.commit()
        return jsonify(cat.to_dict()), 200

    @app.route("/items/create", methods=["GET","POST"])
    @login_required
    def create_item_form():
        categories = Category.query.order_by(Category.name).all()

        if request.method == "POST":
            title       = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            category_id = request.form.get("category_id", type=int)

            errors = []
            if not title:
                errors.append("Title is required.")
            if not category_id or not Category.query.get(category_id):
                errors.append("Please select a valid category.")

            if errors:
                for e in errors:
                    flash(e, "danger")
                return redirect(url_for("create_item_form"))

            item = Item(
                title=title,
                description=description,
                category_id=category_id,
                owner_id=current_user.id
            )
            db.session.add(item)
            db.session.commit()
            return redirect(url_for("user_detail", id=current_user.id))

        return render_template(
            "items/create.html",
            categories=categories
        )
        
    @app.route("/items/<int:item_id>", methods=["GET"])
    @login_required
    def item_detail(item_id):
        item = Item.query.get_or_404(item_id)

        now = datetime.now()
        for auc in item.auctions:
            if auc.status == 'open' and now >= auc.end_time:
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

        return render_template("items/detail.html", item=item)
    
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

        items = Item.query.order_by(Item.id.desc()).all()
        return render_template("index.html", items=items)

    @app.route('/browse', methods=['GET'])
    def browse():
        q            = request.args.get('q', '').strip()
        category_id  = request.args.get('category_id', type=int)
        min_price    = request.args.get('min_price',   type=float)
        max_price    = request.args.get('max_price',   type=float)
        status       = request.args.get('status')

        query = (
            Item.query
                .outerjoin(Auction, Auction.item_id == Item.id)
        )

        if q:
            query = query.filter(or_(
                Item.title.ilike(f'%{q}%'),
                Item.description.ilike(f'%{q}%')
            ))

        if category_id:
            query = query.filter(Item.category_id == category_id)

        if min_price is not None:
            query = query.filter(Auction.init_price >= min_price)
        if max_price is not None:
            query = query.filter(Auction.init_price <= max_price)
        if status in ('open', 'closed'):
            query = query.filter(Auction.status == status)

        items = query.order_by(Item.id.desc()).all()
        return render_template(
            'browse.html',
            items=items,
            q=q,
            categories=Category.query.order_by(Category.name).all(),
            selected_category=category_id,
            min_price=min_price,
            max_price=max_price,
            selected_status=status
        )
    @app.route('/admin/register', methods=['POST'])
    def admin_register():
        has_admin = User.query.filter_by(is_admin=True).first() is not None
        if has_admin:
            if not current_user.is_authenticated or not current_user.is_admin:
                return jsonify(error="Forbidden"), 403

        data = request.get_json(force=True)
        u = (data.get('username') or "").strip()
        p = (data.get('password') or "").strip()
        e = (data.get('email')    or "").strip()

        if not u or not p or not e:
            return jsonify(error="username, password and email required"), 400

        if User.query.filter_by(username=u).first():
            return jsonify(error="Username already exists"), 400
        if User.query.filter_by(email=e).first():
            return jsonify(error="Email already in use"), 400

        user = User(username=u, email=e, is_admin=True)
        user.set_password(p)
        db.session.add(user)
        db.session.commit()

        return jsonify(
            username=user.username,
            email=user.email,
            is_admin=user.is_admin
        ), 201

    @app.route('/admin/<int:id>', methods=['GET'])
    @admin_required
    def admin_detail(id):
        if current_user.id != id:
            return jsonify(error="Forbidden"), 403

        success_filter = (
            Auction.status == 'closed',
            Auction.winning_bid != None,
            Auction.winning_bid >= Auction.reserve_price
        )

        total = (
            db.session
              .query(func.coalesce(func.sum(Auction.winning_bid), 0.0))
              .filter(*success_filter)
              .scalar()
        )

        per_item = (
            db.session
              .query(
                  Item.title,
                  func.coalesce(func.sum(Auction.winning_bid), 0.0).label('earnings')
              )
              .join(Auction, Auction.item_id == Item.id)
              .filter(*success_filter)
              .group_by(Item.id)
              .order_by(func.sum(Auction.winning_bid).desc())
              .all()
        )

        per_category = (
            db.session
              .query(
                  Category.name,
                  func.coalesce(func.sum(Auction.winning_bid), 0.0).label('earnings')
              )
              .join(Item, Item.category_id == Category.id)
              .join(Auction, Auction.item_id == Item.id)
              .filter(*success_filter)
              .group_by(Category.id)
              .all()
        )

        per_user = (
            db.session
              .query(
                  User.username,
                  func.coalesce(func.sum(Auction.winning_bid), 0.0).label('earnings')
              )
              .join(Auction, Auction.winner_id == User.id)
              .filter(*success_filter)
              .group_by(User.id)
              .all()
        )

        best_items  = per_item[:5]
        best_buyers = per_user[:5]

        return render_template(
            'admin/detail.html',
            total=total,
            per_item=per_item,
            per_category=per_category,
            per_user=per_user,
            best_items=best_items,
            best_buyers=best_buyers
        )

    @app.route('/admin/create', methods=['GET','POST'])
    @admin_required
    def admin_create():
        if request.method == 'POST':
            username = request.form.get('username','').strip()
            password = request.form.get('password','').strip()
            email    = request.form.get('email','').strip()

            if not username or not password or not email:
                flash("Username, password and email are all required.", "danger")
                return redirect(request.url)

            if User.query.filter_by(username=username).first():
                flash("That username is already taken.", "danger")
                return redirect(request.url)
            if User.query.filter_by(email=email).first():
                flash("That email is already registered.", "danger")
                return redirect(request.url)

            rep = User(username=username, email=email, is_rep=True)
            rep.set_password(password)
            db.session.add(rep)
            db.session.commit()

            flash(f"Customer-rep {username!r} created.", "success")
            return redirect(url_for('admin_detail', id=current_user.id))

        return render_template('admin/create.html')
    
    @app.route('/rep/<int:id>', methods=['GET'])
    @rep_required
    def rep_detail(id):
        if current_user.id != id and not current_user.is_admin:
            return jsonify(error="Forbidden"), 403

        users = User.query.filter(
            User.is_rep == False,
            User.is_admin == False
        ).all()

        bids = Bid.query.order_by(Bid.timestamp.desc()).all()
        auctions = Auction.query.order_by(Auction.start_time.desc()).all()

        from app.models import Question
        questions = (
            Question.query
                    .order_by(Question.created_at.desc())
                    .all()
        )

        return render_template(
            'rep/detail.html',
            users=users,
            bids=bids,
            auctions=auctions,
            questions=questions
        )
        
    @app.route('/rep/edit_user/<string:username>', methods=['GET','POST'])
    @rep_required
    def rep_edit_user(username):
        user = User.query.filter_by(username=username).first_or_404()
        if request.method == 'POST':
            full_name = request.form.get('full_name','').strip()
            dob_str   = request.form.get('date_of_birth','').strip()
            user.full_name = full_name
            try:
                user.date_of_birth = datetime.fromisoformat(dob_str) if dob_str else None
            except ValueError:
                flash("Invalid date format; use YYYY-MM-DD.", "danger")
                return redirect(request.url)
            db.session.commit()
            flash(f"User {username!r} updated.", "success")
            return redirect(url_for('rep_detail', id=current_user.id))
        return render_template('rep/edit_user.html', user=user)

    @app.route('/rep/delete_user/<string:username>', methods=['POST'])
    @rep_required
    def rep_delete_user(username):
        user = User.query.filter_by(username=username).first_or_404()
        db.session.delete(user)
        db.session.commit()
        flash(f"User {username!r} deleted.", "info")
        return redirect(url_for('rep_detail', id=current_user.id))
    
    @app.route('/rep/reset_password/<string:username>', methods=['POST'])
    @rep_required
    def rep_reset_password(username):
        data = request.get_json(force=True)
        new_p = data.get('new_password')
        if not new_p:
            return jsonify(error="new_password required"), 400
        user = User.query.filter_by(username=username).first_or_404()
        user.set_password(new_p)
        db.session.commit()
        return jsonify(message=f"Password for {username} reset"), 200
    
    @app.route('/rep/remove_bid/<int:bid_id>', methods=['POST'])
    @rep_required
    def rep_remove_bid(bid_id):
        bid = Bid.query.get_or_404(bid_id)
        db.session.delete(bid)
        db.session.commit()
        flash(f"Bid {bid_id} removed", "info")
        return redirect(url_for('rep_detail', id=current_user.id))
    
    @app.route('/rep/remove_auction/<int:auction_id>', methods=['POST'])
    @rep_required
    def rep_remove_auction(auction_id):
        auc = Auction.query.get_or_404(auction_id)
        db.session.delete(auc)
        db.session.commit()
        return redirect(url_for('rep_detail', id=current_user.id))
    @app.route('/qna', methods=['GET','POST'])
    @login_required
    def qna():
        auctions = (
            Auction.query
                   .join(Bid, Bid.auction_id == Auction.id)
                   .filter(Bid.bidder_id == current_user.id)
                   .distinct()
                   .order_by(Auction.id.desc())
                   .all()
        )

        if request.method == 'POST':
            auction_id = request.form.get('auction_id', type=int)
            text       = request.form.get('question', '').strip()
            if not auction_id or not text:
                flash('Please select an auction and enter a question.', 'danger')
                return redirect(url_for('qna'))
            Auction.query.get_or_404(auction_id)
            q = Question(
                auction_id   = auction_id,
                user_id      = current_user.id,
                question_text= text
            )
            db.session.add(q)
            db.session.commit()
            return redirect(url_for('qna'))

        questions = (
            Question.query
                    .filter_by(user_id=current_user.id)
                    .order_by(Question.created_at.desc())
                    .all()
        )
        return render_template('qna.html', auctions=auctions, questions=questions)
    return app
