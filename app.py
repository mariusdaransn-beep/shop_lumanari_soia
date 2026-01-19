from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, logout_user, current_user, login_required
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from config import Config
from models import db, User, Category, Product, Review, Order, OrderItem, ContactMessage

from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# asigură-te că există folderul uploads
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


# ------------- CONTEXT GLOBAL (categorii, coș, anul curent) ------------- #

@app.context_processor
def inject_globals():
    all_categories = Category.query.all()
    cart = session.get("cart", {})
    cart_count = sum(cart.values())
    return {
        "all_categories": all_categories,
        "cart_count": cart_count,
        "current_year": datetime.now().year,
    }


# -------------------- RUTE STATICI IMAGINI -------------------- #

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# -------------------- HOME -------------------- #

@app.route("/")
def home():
    products_new = Product.query.order_by(Product.id.desc()).limit(4).all()
    products_promo = Product.query.filter(Product.old_price.isnot(None)).limit(4).all()
    return render_template(
        "home.html",
        products_new=products_new,
        products_promo=products_promo,
    )


# -------------------- CATEGORII & PRODUSE -------------------- #

@app.route("/category/<slug>")
def category_page(slug):
    category = Category.query.filter_by(slug=slug).first_or_404()
    products = Product.query.filter_by(category_id=category.id).all()
    return render_template("category.html", category=category, products=products)


@app.route("/product/<int:product_id>", methods=["GET", "POST"])
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    similar_products = (
        Product.query.filter(
            Product.category_id == product.category_id,
            Product.id != product.id
        ).limit(4).all()
    )
    reviews = Review.query.filter_by(product_id=product.id).order_by(
        Review.created_at.desc()
    ).all()
    avg_rating = sum([r.rating for r in reviews]) / len(reviews) if reviews else None

    if request.method == "POST":
        if not current_user.is_authenticated:
            flash("Trebuie să fii logat pentru a adăuga recenzii.", "warning")
            return redirect(url_for("login"))
        rating = int(request.form["rating"])
        comment = request.form["comment"]
        new_review = Review(
            rating=rating,
            comment=comment,
            product_id=product.id,
            user_id=current_user.id,
        )
        db.session.add(new_review)
        db.session.commit()
        flash("Recenzia a fost adăugată.", "success")
        return redirect(url_for("product_detail", product_id=product.id))

    return render_template(
        "product_detail.html",
        product=product,
        similar_products=similar_products,
        reviews=reviews,
        avg_rating=avg_rating,
    )


# -------------------- COȘ -------------------- #

@app.route("/cart")
def cart():
    cart_data = session.get("cart", {})
    products_items = []
    total = 0.0

    for pid_str, qty in cart_data.items():
        product = Product.query.get(int(pid_str))
        if not product:
            continue
        line_total = product.price * qty
        total += line_total
        products_items.append(
            {"product": product, "quantity": qty, "line_total": line_total}
        )

    return render_template("cart.html", products_items=products_items, total=total)


@app.route("/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    qty = int(request.form.get("quantity", 1))
    cart_data = session.get("cart", {})
    pid = str(product_id)
    cart_data[pid] = cart_data.get(pid, 0) + qty
    session["cart"] = cart_data
    flash("Produs adăugat în coș.", "success")
    return redirect(url_for("product_detail", product_id=product_id))


@app.route("/remove_from_cart/<int:product_id>")
def remove_from_cart(product_id):
    cart_data = session.get("cart", {})
    pid = str(product_id)
    if pid in cart_data:
        del cart_data[pid]
        session["cart"] = cart_data
        flash("Produs eliminat din coș.", "info")
    return redirect(url_for("cart"))


@app.route("/clear_cart")
def clear_cart():
    session["cart"] = {}
    flash("Coș golit.", "info")
    return redirect(url_for("cart"))


# -------------------- CHECKOUT -------------------- #

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart_data = session.get("cart", {})
    if not cart_data:
        flash("Coșul este gol.", "warning")
        return redirect(url_for("cart"))

    products_items = []
    total = 0.0

    for pid_str, qty in cart_data.items():
        product = Product.query.get(int(pid_str))
        if not product:
            continue
        line_total = product.price * qty
        total += line_total
        products_items.append(
            {"product": product, "quantity": qty, "line_total": line_total}
        )

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]
        address = request.form["address"]
        city = request.form["city"]
        payment_method = request.form["payment_method"]

        order = Order(
            name=name,
            email=email,
            phone=phone,
            address=address,
            city=city,
            payment_method=payment_method,
            total=total,
        )
        db.session.add(order)
        db.session.flush()

        for item in products_items:
            oi = OrderItem(
                order_id=order.id,
                product_name=item["product"].name,
                quantity=item["quantity"],
                price=item["product"].price,
            )
            db.session.add(oi)

        db.session.commit()
        session["cart"] = {}
        flash("Comanda a fost plasată cu succes!", "success")
        return redirect(url_for("home"))

    return render_template(
        "checkout.html",
        products_items=products_items,
        total=total,
    )


# -------------------- CONTACT -------------------- #

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        msg = ContactMessage(
            name=request.form["name"],
            email=request.form["email"],
            message=request.form["message"],
        )
        db.session.add(msg)
        db.session.commit()
        flash("Mesaj trimis!", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html")


# -------------------- AUTH -------------------- #

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash("Autentificare reușită.", "success")
            return redirect(url_for("home"))
        flash("Date de autentificare greșite.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    logout_user()
    flash("Delogat.", "info")
    return redirect(url_for("home"))


# -------------------- ADMIN -------------------- #

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Acces interzis.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    total_products = Product.query.count()
    total_orders = Order.query.count()
    total_users = User.query.count()
    return render_template(
        "admin/dashboard.html",
        total_products=total_products,
        total_orders=total_orders,
        total_users=total_users,
    )


@app.route("/admin/products")
@login_required
@admin_required
def admin_products():
    products = Product.query.order_by(Product.id.desc()).all()
    return render_template("admin/products.html", products=products)


@app.route("/admin/products/add", methods=["GET", "POST"])
@login_required
@admin_required
def admin_add_product():
    categories = Category.query.all()
    if request.method == "POST":
        name = request.form["name"]
        description = request.form["description"]
        price = float(request.form["price"])
        old_price = request.form.get("old_price")
        old_price = float(old_price) if old_price else None
        stock = int(request.form["stock"])
        category_id = int(request.form["category_id"]) if request.form["category_id"] else None
        fragrance = request.form.get("fragrance")
        burn_time = request.form.get("burn_time")
        weight = request.form.get("weight")

        image_url = None
        file = request.files.get("image")
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)
            image_url = url_for("uploaded_file", filename=filename)

        product = Product(
            name=name,
            description=description,
            price=price,
            old_price=old_price,
            stock=stock,
            category_id=category_id,
            fragrance=fragrance,
            burn_time=burn_time,
            weight=weight,
            image_url=image_url,
        )
        db.session.add(product)
        db.session.commit()
        flash("Produs adăugat.", "success")
        return redirect(url_for("admin_products"))

    return render_template("admin/product_form.html", categories=categories, product=None)


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    categories = Category.query.all()

    if request.method == "POST":
        product.name = request.form["name"]
        product.description = request.form["description"]
        product.price = float(request.form["price"])
        old_price = request.form.get("old_price")
        product.old_price = float(old_price) if old_price else None
        product.stock = int(request.form["stock"])
        product.category_id = int(request.form["category_id"]) if request.form["category_id"] else None
        product.fragrance = request.form.get("fragrance")
        product.burn_time = request.form.get("burn_time")
        product.weight = request.form.get("weight")

        file = request.files.get("image")
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)
            product.image_url = url_for("uploaded_file", filename=filename)

        db.session.commit()
        flash("Produs actualizat.", "success")
        return redirect(url_for("admin_products"))

    return render_template(
        "admin/product_form.html",
        categories=categories,
        product=product,
    )


@app.route("/admin/products/<int:product_id>/delete")
@login_required
@admin_required
def admin_delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash("Produs șters.", "info")
    return redirect(url_for("admin_products"))


# -------------------- INIT DB -------------------- #

def init_db():
    db.create_all()

    if not User.query.filter_by(email="admin@lumanari.ro").first():
        admin = User(
            email="admin@lumanari.ro",
            password=generate_password_hash("admin123"),
            is_admin=True,
        )
        db.session.add(admin)

    if not Category.query.first():
        cat1 = Category(name="Lumânări parfumate", slug="lumanari-parfumate")
        cat2 = Category(name="Seturi cadou", slug="seturi-cadou")
        cat3 = Category(name="Accesorii", slug="accesorii")
        db.session.add_all([cat1, cat2, cat3])
        db.session.flush()

        p1 = Product(
            name="Lumânare soia - Vanilie & Ambră",
            description="Lumânare artizanală din ceară de soia, turnată manual, cu parfum cald de vanilie și ambră.",
            price=45.0,
            old_price=55.0,
            stock=30,
            category=cat1,
            image_url="https://via.placeholder.com/400x300?text=Vanilie+%26+Ambra",
            fragrance="Vanilie, ambră",
            burn_time="35-40 ore",
            weight="200 g",
        )

        p2 = Product(
            name="Lumânare soia - Lavandă & Bergamotă",
            description="Lumânare din ceară de soia cu parfum floral-fresh, perfectă pentru relaxare seara.",
            price=42.0,
            stock=25,
            category=cat1,
            image_url="https://via.placeholder.com/400x300?text=Lavanda+Bergamota",
            fragrance="Lavandă, bergamotă",
            burn_time="30-35 ore",
            weight="180 g",
        )

        p3 = Product(
            name="Set cadou - 3 lumânări mini",
            description="Set cadou cu 3 lumânări mini din ceară de soia, arome diferite.",
            price=75.0,
            stock=15,
            category=cat2,
            image_url="https://via.placeholder.com/400x300?text=Set+Cadou",
            fragrance="Mix arome",
            burn_time="3x15 ore",
            weight="3 x 80 g",
        )

        db.session.add_all([p1, p2, p3])

    db.session.commit()


# -------------------- MAIN -------------------- #

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
