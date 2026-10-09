"""Dados de exemplo opcionais; nenhuma conta ou senha é instalada automaticamente."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash


def seed(conn, email, password):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute("BEGIN IMMEDIATE")
    try:
        uid = conn.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                           ("Lojista de exemplo", email.strip().lower(), generate_password_hash(password), stamp)).lastrowid
        burger = "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=1200&auto=format&fit=crop&q=85"
        sid = conn.execute("""INSERT INTO stores(owner_id,name,slug,description,phone,address,logo,banner,open,pix_key,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (uid, "Bistrô da Vila", "bistro-da-vila",
            "Comida de verdade, feita com carinho. Seu favorito está por aqui.", "",
            "Endereço de exemplo — configure o endereço real da sua loja", "", burger, 1,
            "CHAVE-DE-EXEMPLO-NAO-PAGAR", stamp)).lastrowid
        categories = {}
        for i, name in enumerate(("Lanches", "Bowls", "Bebidas")):
            categories[name] = conn.execute("INSERT INTO categories(store_id,name,position) VALUES(?,?,?)", (sid, name, i)).lastrowid
        samples = [
            ("Burger da casa", "Lanches", 2900, "Pão brioche, blend artesanal, queijo, alface, tomate e molho especial.", burger, 1),
            ("Combo da vila", "Lanches", 3990, "Burger da casa, batata crocante e sua bebida favorita.", "https://images.unsplash.com/photo-1571091718767-18b5b1457add?w=700&auto=format&fit=crop&q=80", 1),
            ("Bowl tropical", "Bowls", 2490, "Arroz integral, frango, manga, abacate, cenoura e sementes.", "https://images.unsplash.com/photo-1540420773420-3366772f4999?w=700&auto=format&fit=crop&q=80", 1),
            ("Batata da vila", "Lanches", 1490, "Batatas douradas e crocantes com um toque de alecrim.", "https://images.unsplash.com/photo-1573080496219-bb080dd4f877?w=700&auto=format&fit=crop&q=80", 0),
            ("Suco natural", "Bebidas", 990, "Fruta de verdade, fresquinho e sem conservantes.", "https://images.unsplash.com/photo-1613478223719-2ab802602423?w=700&auto=format&fit=crop&q=80", 0),
        ]
        pids = []
        for i, (name, cat, price, description, photo, featured) in enumerate(samples):
            extras = [{"id": "queijo", "name": "Queijo extra", "price": 300}, {"id": "bacon", "name": "Bacon crocante", "price": 500}] if i == 0 else []
            pid = conn.execute("""INSERT INTO products(store_id,category_id,name,description,price,image,featured,extras,position)
                VALUES(?,?,?,?,?,?,?,?,?)""", (sid, categories[cat], name, description, price, photo, featured, json.dumps(extras), i)).lastrowid
            pids.append(pid)
        conn.execute("INSERT INTO coupons(store_id,code,kind,value,minimum,max_uses) VALUES(?,?,?,?,?,?)", (sid, "BEMVINDO10", "percent", 10, 2000, 100))
        conn.execute("INSERT INTO drivers(store_id,name,phone) VALUES(?,?,?)", (sid, "Entregador de exemplo", ""))
        names = ["Marina S.", "Carlos M.", "Ana L.", "Pedro F.", "Juliana R."]
        for i in range(5):
            token = secrets.token_urlsafe(32)
            status = ["new", "preparing", "ready", "new", "preparing"][i]
            qty = 2 if i == 0 else 1
            created = (datetime.now(timezone.utc) - timedelta(minutes=(i+1)*4)).isoformat(timespec="seconds")
            total = 2900*qty + 500
            oid = conn.execute("""INSERT INTO orders(store_id,number,tracking_hash,customer,phone,mode,payment,subtotal,delivery_fee,total,
                status,idempotency_key,payload_hash,tracking_token,created_at,updated_at,address) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, 1040+i, hashlib.sha256(token.encode()).hexdigest(), names[i], "11900000000", "delivery", "cash", 2900*qty, 500,
                 total, status, secrets.token_hex(16), "demo", token, created, created, "Endereço de exemplo")).lastrowid
            conn.execute("INSERT INTO order_items(order_id,product_id,name,quantity,unit_price) VALUES(?,?,?,?,?)", (oid, pids[0], "Burger da casa", qty, 2900))
            for event in ("new", "preparing", "ready"):
                conn.execute("INSERT INTO order_events(order_id,status,created_at) VALUES(?,?,?)", (oid, event, created))
                if event == status:
                    break
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
