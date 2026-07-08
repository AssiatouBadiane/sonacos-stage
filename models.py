from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'utilisateur'

    id_utilisateur = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100))
    prenom = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    mot_de_passe = db.Column(db.String(255))
    role = db.Column(db.Enum('employe', 'admin'))

    def set_password(self, password):
        self.mot_de_passe = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.mot_de_passe, password)


class Manuel(db.Model):
    __tablename__ = 'manuel'

    id_manuel = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(100), unique=True, nullable=False)
    categorie = db.Column(db.Enum('Manuel', 'SET-LOXO', 'Autre'), nullable=False)
    description = db.Column(db.Text)
    date_ajout = db.Column(db.Date, default=datetime.utcnow)
    date_modification = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    chemin_fichier = db.Column(db.String(255))
    nb_pages = db.Column(db.Integer, default=0)
    taille = db.Column(db.String(20), default='')

    chunks = db.relationship('Chunk', backref='manuel', cascade='all, delete-orphan')

    @property
    def id(self):
        """Alias pour compatibilité avec les templates (m.id)"""
        return self.id_manuel

    @property
    def pages(self):
        """Alias pour compatibilité avec les templates (m.pages)"""
        return self.nb_pages

    @property
    def fichier(self):
        """Nom du fichier seul, pour les templates (m.fichier)"""
        import os
        return os.path.basename(self.chemin_fichier) if self.chemin_fichier else ''

class Chunk(db.Model):
    __tablename__ = 'chunk_source'

    id_chunk = db.Column(db.Integer, primary_key=True)
    extrait_texte = db.Column(db.Text)
    num_page = db.Column(db.Integer)
    chapitre = db.Column(db.String(255))
    section = db.Column(db.String(255))
    id_manuel = db.Column(db.Integer, db.ForeignKey('manuel.id_manuel'))
    embedding = db.Column(db.Text)


class Conversation(db.Model):
    __tablename__ = 'conversation'

    id_conversation = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(255))
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    id_utilisateur = db.Column(db.Integer, db.ForeignKey('utilisateur.id_utilisateur'))

    interactions = db.relationship('Interaction', backref='conversation', cascade='all, delete-orphan')


class Interaction(db.Model):
    __tablename__ = 'interaction'

    id_interaction = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text)
    reponse = db.Column(db.Text)
    date_heure = db.Column(db.DateTime, default=datetime.utcnow)
    id_conversation = db.Column(db.Integer, db.ForeignKey('conversation.id_conversation'))


class Journal(db.Model):
    """
    Journalisation des connexions, téléchargements et opérations d'administration.
    Cf. Cahier des charges, section 3.7 (Sécurité > Journalisation).
    """
    __tablename__ = 'journal'

    id_journal = db.Column(db.Integer, primary_key=True)
    id_utilisateur = db.Column(db.Integer, db.ForeignKey('utilisateur.id_utilisateur'))
    type_action = db.Column(db.Enum('connexion', 'telechargement', 'admin'))
    description = db.Column(db.String(255))
    date_heure = db.Column(db.DateTime, default=datetime.utcnow)

    utilisateur = db.relationship('User', backref='journaux')

    @property
    def utilisateur_nom(self):
        """Nom complet pour affichage dans les templates (j.utilisateur_nom)"""
        if self.utilisateur:
            return f"{self.utilisateur.prenom} {self.utilisateur.nom}"
        return "Utilisateur supprimé"