"""
Script d'initialisation de la base de données SONACOS.
Usage : python init_db.py

1. Crée la base MySQL `sonacos_db` si elle n'existe pas (via XAMPP/phpMyAdmin,
   ou laisse ce script le faire automatiquement).
2. Crée toutes les tables à partir des modèles.
3. Crée un compte administrateur de départ.
"""
import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_USER = os.environ.get('DB_USER', 'root')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_NAME = os.environ.get('DB_NAME', 'sonacos_db')

# Étape 1 : créer la base si elle n'existe pas
conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD)
with conn.cursor() as cursor:
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4")
conn.close()
print(f"✅ Base '{DB_NAME}' prête.")

# Étape 2 : créer les tables via SQLAlchemy
from app import app
from models import db, User

with app.app_context():
    db.create_all()
    print("✅ Tables créées.")

    # Étape 3 : créer un compte admin si aucun n'existe
    admin_email = 'admin@sonacos.sn'
    if not User.query.filter_by(email=admin_email).first():
        admin = User(
            nom='Badiane',
            prenom='Assiatou',
            email=admin_email,
            role='admin'
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print(f"✅ Compte admin créé : {admin_email} / admin123  (⚠️ à changer en production)")
    else:
        print("ℹ️ Compte admin déjà existant.")
