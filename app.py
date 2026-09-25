import os, re, csv, io, hashlib
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","change-this-secret-key")
db_url=os.environ.get("DATABASE_URL","sqlite:///cars.db")
if db_url.startswith("postgres://"): db_url=db_url.replace("postgres://","postgresql://",1)
app.config["SQLALCHEMY_DATABASE_URI"]=db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
db=SQLAlchemy(app)

class Vehicle(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    title=db.Column(db.String(200),nullable=False)
    make=db.Column(db.String(80),index=True)
    model=db.Column(db.String(80),index=True)
    year=db.Column(db.Integer)
    price=db.Column(db.Integer,index=True)
    mileage=db.Column(db.Integer)
    transmission=db.Column(db.String(40))
    fuel=db.Column(db.String(40))
    county=db.Column(db.String(80),index=True)
    image_url=db.Column(db.Text)
    source=db.Column(db.String(160))
    source_url=db.Column(db.Text)
    seller_phone=db.Column(db.String(80))
    exact_location=db.Column(db.Text)
    fingerprint=db.Column(db.String(64),unique=True,index=True)
    active=db.Column(db.Boolean,default=True,index=True)

class Admin(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    username=db.Column(db.String(80),unique=True,nullable=False)
    password_hash=db.Column(db.String(255),nullable=False)

def fp(d):
    raw="|".join(str(d.get(k,"")).strip().lower() for k in ("make","model","year","price","mileage"))
    return hashlib.sha256(raw.encode()).hexdigest()

def public(v):
    return {"id":v.id,"title":v.title,"make":v.make,"model":v.model,"year":v.year,
            "price":v.price,"mileage":v.mileage,"transmission":v.transmission,
            "fuel":v.fuel,"county":v.county,"image_url":v.image_url,
            "source":v.source,"source_url":v.source_url}

@app.before_request
def init():
    db.create_all()
    if not Admin.query.first():
        u=os.environ.get("ADMIN_USERNAME","admin")
        p=os.environ.get("ADMIN_PASSWORD","change-me")
        db.session.add(Admin(username=u,password_hash=generate_password_hash(p)))
        db.session.commit()

MPESA_NUMBER = os.environ.get("MPESA_NUMBER", "0780555504")

@app.route("/")
def home(): return render_template("index.html", mpesa_number=MPESA_NUMBER)

@app.route("/payment")
def payment(): return render_template("payment.html", mpesa_number=MPESA_NUMBER)

@app.get("/api/vehicles")
def api_vehicles():
    q=request.args.get("q","").strip()
    county=request.args.get("county","").strip()
    maxp=request.args.get("max_price","").strip()
    query=Vehicle.query.filter_by(active=True)
    if q: query=query.filter((Vehicle.title.ilike(f"%{q}%"))|(Vehicle.make.ilike(f"%{q}%"))|(Vehicle.model.ilike(f"%{q}%")))
    if county: query=query.filter_by(county=county)
    if maxp.isdigit(): query=query.filter(Vehicle.price<=int(maxp))
    return jsonify([public(v) for v in query.order_by(Vehicle.id.desc()).all()])

@app.route("/admin",methods=["GET","POST"])
def admin():
    if request.method=="POST":
        a=Admin.query.filter_by(username=request.form.get("username")).first()
        if a and check_password_hash(a.password_hash,request.form.get("password","")):
            session["admin"]=a.id; return redirect(url_for("dashboard"))
        flash("Invalid login")
    return render_template("login.html")

@app.route("/admin/dashboard")
def dashboard():
    if "admin" not in session: return redirect(url_for("admin"))
    return render_template("dashboard.html",vehicles=Vehicle.query.order_by(Vehicle.id.desc()).all())

@app.post("/admin/add")
def add():
    if "admin" not in session: return redirect(url_for("admin"))
    d=request.form.to_dict()
    v=Vehicle(title=d.get("title",""),make=d.get("make"),model=d.get("model"),year=int(d["year"]) if d.get("year","").isdigit() else None,
      price=int(d["price"]) if d.get("price","").isdigit() else None,mileage=int(d["mileage"]) if d.get("mileage","").isdigit() else None,
      transmission=d.get("transmission"),fuel=d.get("fuel"),county=d.get("county"),image_url=d.get("image_url"),
      source=d.get("source"),source_url=d.get("source_url"),seller_phone=d.get("seller_phone"),exact_location=d.get("exact_location"))
    v.fingerprint=fp(d)
    if Vehicle.query.filter_by(fingerprint=v.fingerprint).first(): flash("Possible duplicate: vehicle was not added.")
    else: db.session.add(v); db.session.commit(); flash("Vehicle added.")
    return redirect(url_for("dashboard"))

@app.post("/admin/toggle/<int:vid>")
def toggle(vid):
    if "admin" not in session: return redirect(url_for("admin"))
    v=Vehicle.query.get_or_404(vid); v.active=not v.active; db.session.commit()
    return redirect(url_for("dashboard"))

@app.post("/admin/import")
def import_csv():
    if "admin" not in session: return redirect(url_for("admin"))
    f=request.files.get("file")
    if not f: flash("Choose a CSV file."); return redirect(url_for("dashboard"))
    added=0; skipped=0
    for row in csv.DictReader(io.TextIOWrapper(f.stream,encoding="utf-8-sig")):
        if not row.get("title"): skipped+=1; continue
        key=fp(row)
        if Vehicle.query.filter_by(fingerprint=key).first(): skipped+=1; continue
        v=Vehicle(title=row.get("title",""),make=row.get("make"),model=row.get("model"),
          year=int(row["year"]) if row.get("year","").isdigit() else None,
          price=int(row["price"]) if row.get("price","").isdigit() else None,
          mileage=int(row["mileage"]) if row.get("mileage","").isdigit() else None,
          transmission=row.get("transmission"),fuel=row.get("fuel"),county=row.get("county"),
          image_url=row.get("image_url"),source=row.get("source"),source_url=row.get("source_url"),
          seller_phone=row.get("seller_phone"),exact_location=row.get("exact_location"),fingerprint=key)
        db.session.add(v); added+=1
    db.session.commit(); flash(f"Imported {added}; skipped {skipped}.")
    return redirect(url_for("dashboard"))

@app.get("/logout")
def logout(): session.clear(); return redirect(url_for("home"))

with app.app_context(): db.create_all()

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
