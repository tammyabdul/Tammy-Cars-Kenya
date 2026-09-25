import os
import csv
import io
import base64
import hashlib
import requests
from datetime import datetime

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key"
)

# Database
db_url = os.environ.get(
    "DATABASE_URL",
    "sqlite:///cars.db"
)

# Render/PostgreSQL compatibility
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============================================================
# M-PESA CONFIGURATION
# ============================================================

MPESA_NUMBER = os.environ.get(
    "MPESA_NUMBER",
    "0780555504"
)

MPESA_AMOUNT = int(
    os.environ.get("MPESA_AMOUNT", "10")
)

# Daraja credentials
MPESA_CONSUMER_KEY = os.environ.get(
    "MPESA_CONSUMER_KEY",
    ""
)

MPESA_CONSUMER_SECRET = os.environ.get(
    "MPESA_CONSUMER_SECRET",
    ""
)

MPESA_PASSKEY = os.environ.get(
    "MPESA_PASSKEY",
    ""
)

MPESA_SHORTCODE = os.environ.get(
    "MPESA_SHORTCODE",
    ""
)

MPESA_CALLBACK_URL = os.environ.get(
    "MPESA_CALLBACK_URL",
    ""
)

# Sandbox by default.
# Change to production when your Daraja account is ready.
MPESA_ENVIRONMENT = os.environ.get(
    "MPESA_ENVIRONMENT",
    "sandbox"
).lower()


if MPESA_ENVIRONMENT == "production":
    MPESA_AUTH_URL = (
        "https://api.safaricom.co.ke/oauth/v1/generate"
        "?grant_type=client_credentials"
    )

    MPESA_STK_URL = (
        "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    )
else:
    MPESA_AUTH_URL = (
        "https://sandbox.safaricom.co.ke/oauth/v1/generate"
        "?grant_type=client_credentials"
    )

    MPESA_STK_URL = (
        "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    )


# ============================================================
# DATABASE MODELS
# ============================================================

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(
        db.String(200),
        nullable=False
    )

    make = db.Column(
        db.String(80),
        index=True
    )

    model = db.Column(
        db.String(80),
        index=True
    )

    year = db.Column(
        db.Integer
    )

    price = db.Column(
        db.Integer,
        index=True
    )

    mileage = db.Column(
        db.Integer
    )

    transmission = db.Column(
        db.String(40)
    )

    fuel = db.Column(
        db.String(40)
    )

    county = db.Column(
        db.String(80),
        index=True
    )

    image_url = db.Column(
        db.Text
    )

    source = db.Column(
        db.String(160)
    )

    source_url = db.Column(
        db.Text
    )

    seller_phone = db.Column(
        db.String(80)
    )

    exact_location = db.Column(
        db.Text
    )

    fingerprint = db.Column(
        db.String(64),
        unique=True,
        index=True
    )

    active = db.Column(
        db.Boolean,
        default=True,
        index=True
    )


class Admin(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )


class Payment(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    vehicle_id = db.Column(
        db.Integer,
        nullable=False,
        index=True
    )

    phone = db.Column(
        db.String(30),
        nullable=False
    )

    amount = db.Column(
        db.Integer,
        nullable=False,
        default=10
    )

    merchant_request_id = db.Column(
        db.String(100)
    )

    checkout_request_id = db.Column(
        db.String(100),
        index=True
    )

    mpesa_receipt = db.Column(
        db.String(100)
    )

    result_code = db.Column(
        db.Integer
    )

    status = db.Column(
        db.String(30),
        default="pending",
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    paid_at = db.Column(
        db.DateTime
    )


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def vehicle_fingerprint(vehicle):
    raw = "|".join(
        str(getattr(vehicle, key, "") or "").strip().lower()
        for key in (
            "make",
            "model",
            "year",
            "price",
            "mileage"
        )
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def public_vehicle(vehicle):
    """
    Information safe for the public vehicle-search page.

    Seller phone and exact location are intentionally excluded.
    Those can be released after successful payment.
    """

    return {
        "id": vehicle.id,
        "title": vehicle.title,
        "make": vehicle.make,
        "model": vehicle.model,
        "year": vehicle.year,
        "price": vehicle.price,
        "mileage": vehicle.mileage,
        "transmission": vehicle.transmission,
        "fuel": vehicle.fuel,
        "county": vehicle.county,
        "image_url": vehicle.image_url,
        "source": vehicle.source,
        "source_url": vehicle.source_url
    }


def protected_vehicle(vehicle):
    """
    Full vehicle information available after payment.
    """

    data = public_vehicle(vehicle)

    data.update({
        "seller_phone": vehicle.seller_phone,
        "exact_location": vehicle.exact_location
    })

    return data


def normalize_phone(phone):
    """
    Converts Kenyan phone numbers into 2547XXXXXXXX format.
    """

    phone = (phone or "").strip()
    phone = phone.replace(" ", "")
    phone = phone.replace("-", "")

    if phone.startswith("+254"):
        phone = phone[1:]

    elif phone.startswith("07"):
        phone = "254" + phone[1:]

    elif phone.startswith("01"):
        phone = "254" + phone[1:]

    elif phone.startswith("7") and len(phone) == 9:
        phone = "254" + phone

    elif phone.startswith("1") and len(phone) == 9:
        phone = "254" + phone

    return phone


def valid_mpesa_phone(phone):
    phone = normalize_phone(phone)

    return (
        len(phone) == 12
        and phone.startswith("254")
        and phone[3] in ("7", "1")
    )


def admin_required():
    return "admin" in session


def customer_has_paid(vehicle_id):
    """
    Checks whether this browser session has successfully paid
    for the selected vehicle.
    """

    paid_vehicle_ids = session.get(
        "paid_vehicle_ids",
        []
    )

    return int(vehicle_id) in [
        int(x) for x in paid_vehicle_ids
    ]


def mark_vehicle_paid(vehicle_id):
    paid_vehicle_ids = session.get(
        "paid_vehicle_ids",
        []
    )

    vehicle_id = int(vehicle_id)

    if vehicle_id not in paid_vehicle_ids:
        paid_vehicle_ids.append(vehicle_id)

    session["paid_vehicle_ids"] = paid_vehicle_ids
    session.modified = True


# ============================================================
# M-PESA FUNCTIONS
# ============================================================

def get_mpesa_access_token():
    """
    Gets an OAuth access token from Safaricom Daraja.
    """

    if not MPESA_CONSUMER_KEY or not MPESA_CONSUMER_SECRET:
        raise RuntimeError(
            "M-PESA Consumer Key and Consumer Secret "
            "have not been configured."
        )

    response = requests.get(
        MPESA_AUTH_URL,
        auth=(
            MPESA_CONSUMER_KEY,
            MPESA_CONSUMER_SECRET
        ),
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    token = data.get("access_token")

    if not token:
        raise RuntimeError(
            "Safaricom did not return an access token."
        )

    return token


def initiate_stk_push(phone, account_reference):
    """
    Initiates a Safaricom M-PESA STK Push.
    """

    if not MPESA_SHORTCODE:
        raise RuntimeError(
            "MPESA_SHORTCODE has not been configured."
        )

    if not MPESA_PASSKEY:
        raise RuntimeError(
            "MPESA_PASSKEY has not been configured."
        )

    if not MPESA_CALLBACK_URL:
        raise RuntimeError(
            "MPESA_CALLBACK_URL has not been configured."
        )

    phone = normalize_phone(phone)

    token = get_mpesa_access_token()

    timestamp = datetime.now().strftime(
        "%Y%m%d%H%M%S"
    )

    password_string = (
        str(MPESA_SHORTCODE)
        + str(MPESA_PASSKEY)
        + timestamp
    )

    password = base64.b64encode(
        password_string.encode("utf-8")
    ).decode("utf-8")

    payload = {
        "BusinessShortCode": MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": MPESA_AMOUNT,
        "PartyA": phone,
        "PartyB": MPESA_SHORTCODE,
        "PhoneNumber": phone,
        "CallBackURL": MPESA_CALLBACK_URL,
        "AccountReference": account_reference,
        "TransactionDesc": "Tammy Cars Kenya vehicle access"
    }

    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json"
    }

    response = requests.post(
        MPESA_STK_URL,
        json=payload,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

@app.before_request
def init_database():
    db.create_all()

    if not Admin.query.first():
        username = os.environ.get(
            "ADMIN_USERNAME",
            "admin"
        )

        password = os.environ.get(
            "ADMIN_PASSWORD",
            "change-me"
        )

        admin = Admin(
            username=username,
            password_hash=generate_password_hash(password)
        )

        db.session.add(admin)
        db.session.commit()


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def home():
    return render_template(
        "index.html",
        mpesa_number=MPESA_NUMBER,
        mpesa_amount=MPESA_AMOUNT
    )


# ============================================================
# PAYMENT PAGE
# ============================================================

@app.route(
    "/payment",
    methods=["GET", "POST"]
)
def payment():

    vehicle_id = request.args.get(
        "vehicle_id",
        request.form.get("vehicle_id")
    )

    vehicle = None

    if vehicle_id:
        try:
            vehicle = Vehicle.query.get(
                int(vehicle_id)
            )
        except (ValueError, TypeError):
            vehicle = None

    if request.method == "GET":

        return render_template(
            "payment.html",
            mpesa_number=MPESA_NUMBER,
            mpesa_amount=MPESA_AMOUNT,
            vehicle=vehicle
        )

    # --------------------------------------------------------
    # POST - START PAYMENT
    # --------------------------------------------------------

    if not vehicle:
        flash("Vehicle not found.")
        return redirect(url_for("home"))

    phone = request.form.get(
        "phone",
        ""
    )

    if not valid_mpesa_phone(phone):
        flash(
            "Enter a valid Kenyan M-PESA phone number."
        )

        return redirect(
            url_for(
                "payment",
                vehicle_id=vehicle.id
            )
        )

    phone = normalize_phone(phone)

    payment_record = Payment(
        vehicle_id=vehicle.id,
        phone=phone,
        amount=MPESA_AMOUNT,
        status="pending"
    )

    db.session.add(payment_record)
    db.session.commit()

    try:

        response = initiate_stk_push(
            phone,
            "TAMMYCARS-" + str(vehicle.id)
        )

        response_code = str(
            response.get("ResponseCode", "")
        )

        if response_code != "0":

            payment_record.status = "failed"

            db.session.commit()

            flash(
                response.get(
                    "CustomerMessage",
                    "M-PESA payment request failed."
                )
            )

            return redirect(
                url_for(
                    "payment",
                    vehicle_id=vehicle.id
                )
            )

        payment_record.merchant_request_id = (
            response.get("MerchantRequestID")
        )

        payment_record.checkout_request_id = (
            response.get("CheckoutRequestID")
        )

        db.session.commit()

        session["pending_payment_id"] = (
            payment_record.id
        )

        flash(
            "M-PESA prompt sent. Check your phone and enter your M-PESA PIN."
        )

        return render_template(
            "payment.html",
            mpesa_number=MPESA_NUMBER,
            mpesa_amount=MPESA_AMOUNT,
            vehicle=vehicle,
            payment_started=True,
            payment=response
        )

    except Exception as exc:

        payment_record.status = "failed"

        db.session.commit()

        app.logger.exception(
            "M-PESA STK Push error: %s",
            exc
        )

        flash(
            "Unable to start M-PESA payment. "
            "Please check the payment configuration."
        )

        return redirect(
            url_for(
                "payment",
                vehicle_id=vehicle.id
            )
        )


# ============================================================
# M-PESA CALLBACK
# ============================================================

@app.route(
    "/mpesa/callback",
    methods=["POST"]
)
def mpesa_callback():

    data = request.get_json(
        silent=True
    ) or {}

    app.logger.info(
        "M-PESA callback received: %s",
        data
    )

    stk_callback = (
        data
        .get("Body", {})
        .get("stkCallback", {})
    )

    checkout_request_id = stk_callback.get(
        "CheckoutRequestID"
    )

    merchant_request_id = stk_callback.get(
        "MerchantRequestID"
    )

    result_code = stk_callback.get(
        "ResultCode"
    )

    result_desc = stk_callback.get(
        "ResultDesc",
        ""
    )

    payment_record = None

    if checkout_request_id:
        payment_record = Payment.query.filter_by(
            checkout_request_id=checkout_request_id
        ).first()

    if not payment_record and merchant_request_id:
        payment_record = Payment.query.filter_by(
            merchant_request_id=merchant_request_id
        ).first()

    if not payment_record:

        app.logger.warning(
            "No payment record found for M-PESA callback."
        )

        return jsonify({
            "ResultCode": 0,
            "ResultDesc": "Accepted"
        })

    payment_record.result_code = (
        int(result_code)
        if result_code is not None
        else None
    )

    # --------------------------------------------------------
    # SUCCESS
    # --------------------------------------------------------

    if str(result_code) == "0":

        callback_items = (
            stk_callback
            .get("CallbackMetadata", {})
            .get("Item", [])
        )

        receipt = None
        paid_amount = None
        paid_phone = None

        for item in callback_items:

            name = item.get("Name")
            value = item.get("Value")

            if name == "MpesaReceiptNumber":
                receipt = str(value)

            elif name == "Amount":
                paid_amount = value

            elif name == "PhoneNumber":
                paid_phone = str(value)

        # Only mark successful when amount matches.
        if paid_amount is not None and int(
            float(paid_amount)
        ) != MPESA_AMOUNT:

            payment_record.status = "failed"

            db.session.commit()

            app.logger.warning(
                "M-PESA amount mismatch: expected %s, received %s",
                MPESA_AMOUNT,
                paid_amount
            )

        else:

            payment_record.status = "paid"

            payment_record.mpesa_receipt = receipt

            payment_record.paid_at = datetime.utcnow()

            db.session.commit()

    else:

        payment_record.status = "failed"

        db.session.commit()

        app.logger.info(
            "M-PESA payment failed: %s",
            result_desc
        )

    return jsonify({
        "ResultCode": 0,
        "ResultDesc": "Accepted"
    })


# ============================================================
# PAYMENT STATUS
# ============================================================

@app.route(
    "/payment/status",
    methods=["GET"]
)
def payment_status():

    payment_id = session.get(
        "pending_payment_id"
    )

    if not payment_id:

        return jsonify({
            "status": "none"
        })

    payment_record = Payment.query.get(
        payment_id
    )

    if not payment_record:

        return jsonify({
            "status": "not_found"
        })

    if payment_record.status == "paid":

        mark_vehicle_paid(
            payment_record.vehicle_id
        )

        session.pop(
            "pending_payment_id",
            None
        )

        return jsonify({
            "status": "paid",
            "vehicle_id": payment_record.vehicle_id,
            "receipt": payment_record.mpesa_receipt
        })

    if payment_record.status == "failed":

        return jsonify({
            "status": "failed"
        })

    return jsonify({
        "status": "pending"
    })


# ============================================================
# PUBLIC VEHICLE SEARCH API
# ============================================================

@app.get("/api/vehicles")
def api_vehicles():

    q = request.args.get(
        "q",
        ""
    ).strip()

    county = request.args.get(
        "county",
        ""
    ).strip()

    max_price = request.args.get(
        "max_price",
        ""
    ).strip()

    query = Vehicle.query.filter_by(
        active=True
    )

    if q:

        search_term = f"%{q}%"

        query = query.filter(
            db.or_(
                Vehicle.title.ilike(search_term),
                Vehicle.make.ilike(search_term),
                Vehicle.model.ilike(search_term)
            )
        )

    if county:

        query = query.filter_by(
            county=county
        )

    if max_price.isdigit():

        query = query.filter(
            Vehicle.price <= int(max_price)
        )

    vehicles = query.order_by(
        Vehicle.id.desc()
    ).all()

    return jsonify([
        public_vehicle(vehicle)
        for vehicle in vehicles
    ])


# ============================================================
# SINGLE VEHICLE API
# ============================================================

@app.get("/api/vehicles/<int:vehicle_id>")
def api_vehicle(vehicle_id):

    vehicle = Vehicle.query.filter_by(
        id=vehicle_id,
        active=True
    ).first_or_404()

    if customer_has_paid(vehicle.id):

        return jsonify({
            "paid": True,
            "vehicle": protected_vehicle(vehicle)
        })

    return jsonify({
        "paid": False,
        "payment_required": True,
        "amount": MPESA_AMOUNT,
        "vehicle": public_vehicle(vehicle),
        "payment_url": url_for(
            "payment",
            vehicle_id=vehicle.id
        )
    })


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route(
    "/admin",
    methods=["GET", "POST"]
)
def admin():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        admin_user = Admin.query.filter_by(
            username=username
        ).first()

        if (
            admin_user
            and check_password_hash(
                admin_user.password_hash,
                password
            )
        ):

            session["admin"] = admin_user.id

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid username or password."
        )

    return render_template(
        "login.html"
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin/dashboard")
def dashboard():

    if not admin_required():

        return redirect(
            url_for("admin")
        )

    vehicles = Vehicle.query.order_by(
        Vehicle.id.desc()
    ).all()

    payments = Payment.query.order_by(
        Payment.id.desc()
    ).limit(100).all()

    return render_template(
        "dashboard.html",
        vehicles=vehicles,
        payments=payments
    )


# ============================================================
# ADD VEHICLE
# ============================================================

@app.post("/admin/add")
def add():

    if not admin_required():

        return redirect(
            url_for("admin")
        )

    data = request.form

    vehicle = Vehicle(
        title=data.get("title", ""),
        make=data.get("make"),
        model=data.get("model"),
        year=int(data["year"])
        if data.get("year", "").isdigit()
        else None,
        price=int(data["price"])
        if data.get("price", "").isdigit()
        else None,
        mileage=int(data["mileage"])
        if data.get("mileage", "").isdigit()
        else None,
        transmission=data.get("transmission"),
        fuel=data.get("fuel"),
        county=data.get("county"),
        image_url=data.get("image_url"),
        source=data.get("source"),
        source_url=data.get("source_url"),
        seller_phone=data.get("seller_phone"),
        exact_location=data.get("exact_location")
    )

    vehicle.fingerprint = vehicle_fingerprint(
        vehicle
    )

    duplicate = Vehicle.query.filter_by(
        fingerprint=vehicle.fingerprint
    ).first()

    if duplicate:

        flash(
            "Possible duplicate vehicle was not added."
        )

    else:

        db.session.add(vehicle)
        db.session.commit()

        flash(
            "Vehicle added successfully."
        )

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# EDIT VEHICLE
# ============================================================

@app.route(
    "/admin/edit/<int:vehicle_id>",
    methods=["GET", "POST"]
)
def edit_vehicle(vehicle_id):

    if not admin_required():

        return redirect(
            url_for("admin")
        )

    vehicle = Vehicle.query.get_or_404(
        vehicle_id
    )

    if request.method == "GET":

        return render_template(
            "dashboard.html",
            vehicles=Vehicle.query.order_by(
                Vehicle.id.desc()
            ).all(),
            edit_vehicle=vehicle,
            payments=Payment.query.order_by(
                Payment.id.desc()
            ).limit(100).all()
        )

    data = request.form

    vehicle.title = data.get(
        "title",
        vehicle.title
    )

    vehicle.make = data.get(
        "make",
        vehicle.make
    )

    vehicle.model = data.get(
        "model",
        vehicle.model
    )

    vehicle.year = (
        int(data["year"])
        if data.get("year", "").isdigit()
        else None
    )

    vehicle.price = (
        int(data["price"])
        if data.get("price", "").isdigit()
        else None
    )

    vehicle.mileage = (
        int(data["mileage"])
        if data.get("mileage", "").isdigit()
        else None
    )

    vehicle.transmission = data.get(
        "transmission"
    )

    vehicle.fuel = data.get(
        "fuel"
    )

    vehicle.county = data.get(
        "county"
    )

    vehicle.image_url = data.get(
        "image_url"
    )

    vehicle.source = data.get(
        "source"
    )

    vehicle.source_url = data.get(
        "source_url"
    )

    vehicle.seller_phone = data.get(
        "seller_phone"
    )

    vehicle.exact_location = data.get(
        "exact_location"
    )

    vehicle.fingerprint = vehicle_fingerprint(
        vehicle
    )

    db.session.commit()

    flash(
        "Vehicle updated successfully."
    )

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# ACTIVATE / DEACTIVATE VEHICLE
# ============================================================

@app.post("/admin/toggle/<int:vehicle_id>")
def toggle(vehicle_id):

    if not admin_required():

        return redirect(
            url_for("admin")
        )

    vehicle = Vehicle.query.get_or_404(
        vehicle_id
    )

    vehicle.active = not vehicle.active

    db.session.commit()

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# DELETE VEHICLE
# ============================================================

@app.post("/admin/delete/<int:vehicle_id>")
def delete_vehicle(vehicle_id):

    if not admin_required():

        return redirect(
            url_for("admin")
        )

    vehicle = Vehicle.query.get_or_404(
        vehicle_id
    )

    Payment.query.filter_by(
        vehicle_id=vehicle.id
    ).delete(
        synchronize_session=False
    )

    db.session.delete(
        vehicle
    )

    db.session.commit()

    flash(
        "Vehicle deleted."
    )

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# CSV IMPORT
# ============================================================

@app.post("/admin/import")
def import_csv():

    if not admin_required():

        return redirect(
            url_for("admin")
        )

    uploaded_file = request.files.get(
        "file"
    )

    if not uploaded_file:

        flash(
            "Choose a CSV file."
        )

        return redirect(
            url_for("dashboard")
        )

    if not uploaded_file.filename.lower().endswith(
        ".csv"
    ):

        flash(
            "Only CSV files are allowed."
        )

        return redirect(
            url_for("dashboard")
        )

    added = 0
    skipped = 0

    try:

        stream = io.TextIOWrapper(
            uploaded_file.stream,
            encoding="utf-8-sig"
        )

        reader = csv.DictReader(
            stream
        )

        for row in reader:

            if not row.get("title"):
                skipped += 1
                continue

            vehicle = Vehicle(
                title=row.get(
                    "title",
                    ""
                ),
                make=row.get("make"),
                model=row.get("model"),
                year=int(row["year"])
                if row.get("year", "").isdigit()
                else None,
                price=int(row["price"])
                if row.get("price", "").isdigit()
                else None,
                mileage=int(row["mileage"])
                if row.get("mileage", "").isdigit()
                else None,
                transmission=row.get(
                    "transmission"
                ),
                fuel=row.get(
                    "fuel"
                ),
                county=row.get(
                    "county"
                ),
                image_url=row.get(
                    "image_url"
                ),
                source=row.get(
                    "source"
                ),
                source_url=row.get(
                    "source_url"
                ),
                seller_phone=row.get(
                    "seller_phone"
                ),
                exact_location=row.get(
                    "exact_location"
                )
            )

            vehicle.fingerprint = (
                vehicle_fingerprint(vehicle)
            )

            duplicate = Vehicle.query.filter_by(
                fingerprint=vehicle.fingerprint
            ).first()

            if duplicate:

                skipped += 1
                continue

            db.session.add(
                vehicle
            )

            added += 1

        db.session.commit()

        flash(
            f"Imported {added}; skipped {skipped}."
        )

    except Exception as exc:

        db.session.rollback()

        app.logger.exception(
            "CSV import failed: %s",
            exc
        )

        flash(
            "CSV import failed. Check the file format."
        )

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# LOGOUT
# ============================================================

@app.get("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "Tammy Cars Kenya"
    })


# ============================================================
# APPLICATION START
# ============================================================

with app.app_context():
    db.create_all()


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        )
    )
