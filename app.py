from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from functools import wraps
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from pypdf import PdfReader

from config import Config
from models import db, User, Manuel, Chunk, Conversation, Interaction
from rag import indexer_document
from ai import generer_reponse

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

FAQ = [
    {'question': 'Comment demander un congé annuel ?', 'reponse': 'Remplissez le formulaire sur l\'intranet RH, obtenez la validation de votre supérieur, puis transmettez au service RH 15 jours à l\'avance.', 'source': 'Manuel RH'},
    {'question': 'Quels sont les EPI obligatoires en atelier ?', 'reponse': 'Casque, lunettes de protection, gants, chaussures de sécurité et gilet réfléchissant sont obligatoires dans toutes les zones de production.', 'source': 'Guide Sécurité'},
    {'question': 'Comment signaler un incident de sécurité ?', 'reponse': 'Tout incident doit être signalé immédiatement au responsable HSE via le formulaire F-HSE-001 et enregistré dans le registre des incidents.', 'source': 'Guide Sécurité'},
]


# ─── Helpers ─────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Accès réservé aux administrateurs.', 'error')
            return redirect(url_for('accueil'))
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def get_stats():
    return {
        'utilisateurs_actifs': User.query.count(),
        'manuels_publies': Manuel.query.count(),
        'questions_chatbot': Interaction.query.count(),
        'chunks_indexes': Chunk.query.count(),
    }


# ─── Routes publiques ─────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('accueil'))
    return render_template('landing.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session['user_id'] = user.id_utilisateur
            session['user'] = user.email
            session['role'] = user.role
            session['nom'] = user.nom
            session['prenom'] = user.prenom
            return redirect(url_for('accueil'))
        flash('Email ou mot de passe incorrect.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ─── Routes protégées ─────────────────────────────────────────────────────────
@app.route('/accueil')
@login_required
def accueil():
    return render_template('accueil.html', stats=get_stats(), faq=FAQ[:3])


@app.route('/manuels')
@login_required
def manuels():
    categorie = request.args.get('categorie', '')
    search = request.args.get('search', '')
    query = Manuel.query
    if categorie:
        query = query.filter_by(categorie=categorie)
    if search:
        query = query.filter(Manuel.titre.ilike(f'%{search}%'))
    filtered = query.all()
    categories = sorted(set(m.categorie for m in Manuel.query.all() if m.categorie))
    return render_template('manuels.html', manuels=filtered, categories=categories, categorie_active=categorie)


@app.route('/manuels/<int:id>')
@login_required
def manuel_detail(id):
    manuel = Manuel.query.get(id)
    if not manuel:
        flash('Manuel introuvable.', 'error')
        return redirect(url_for('manuels'))
    return render_template('manuel_detail.html', manuel=manuel)


@app.route('/assistant')
@login_required
def assistant():
    conversations = Conversation.query.filter_by(id_utilisateur=session['user_id']).order_by(Conversation.date_creation.desc()).all()
    return render_template('assistant.html', conversations=conversations)


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    """Endpoint IA réel — RAG + Groq/LLaMA 3"""
    data = request.get_json()
    question = (data.get('question') or '').strip()
    id_conversation = data.get('id_conversation')

    if not question:
        return jsonify({'error': 'Question vide'}), 400

    resultat = generer_reponse(question)

    # Sauvegarde de la conversation
    if id_conversation:
        conversation = Conversation.query.get(id_conversation)
    else:
        conversation = Conversation(
            titre=question[:80],
            id_utilisateur=session['user_id']
        )
        db.session.add(conversation)
        db.session.flush()

    interaction = Interaction(
        question=question,
        reponse=resultat['reponse'],
        id_conversation=conversation.id_conversation
    )
    db.session.add(interaction)
    db.session.commit()

    resultat['id_conversation'] = conversation.id_conversation
    return jsonify(resultat)


@app.route('/historique')
@login_required
def historique():
    conversations = Conversation.query.filter_by(id_utilisateur=session['user_id']).order_by(Conversation.date_creation.desc()).all()
    return render_template('historique.html', conversations=conversations)


@app.route('/faq')
@login_required
def faq():
    return render_template('faq.html', faqs=FAQ)


# ─── Routes admin ──────────────────────────────────────────────────────────────
@app.route('/administration')
@admin_required
def administration():
    all_users = User.query.all()
    all_manuels = Manuel.query.order_by(Manuel.date_ajout.desc()).all()
    return render_template('administration.html', stats=get_stats(), users=all_users, manuels=all_manuels)


@app.route('/administration/ajouter-manuel', methods=['GET', 'POST'])
@admin_required
def ajouter_manuel():
    if request.method == 'POST':
        titre = request.form.get('titre')
        categorie = request.form.get('categorie')
        description = request.form.get('description')
        fichier = request.files.get('fichier')

        if not fichier or not allowed_file(fichier.filename):
            flash('Fichier invalide, seuls les PDF sont acceptés.', 'error')
            categories = sorted(set(m.categorie for m in Manuel.query.all() if m.categorie))
            return render_template('ajouter_manuel.html', categories=categories)

        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        filename = secure_filename(fichier.filename)
        chemin = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        fichier.save(chemin)

        taille_octets = os.path.getsize(chemin)
        taille_str = f"{taille_octets / (1024*1024):.1f} MB" if taille_octets > 1024*1024 else f"{taille_octets / 1024:.0f} KB"

        try:
            nb_pages = len(PdfReader(chemin).pages)
        except Exception:
            nb_pages = 0

        manuel = Manuel(
            titre=titre,
            categorie=categorie,
            description=description,
            chemin_fichier=chemin,
            nb_pages=nb_pages,
            taille=taille_str,
            date_ajout=datetime.utcnow().date()
        )
        db.session.add(manuel)
        db.session.commit()

        # Indexation automatique pour le RAG
        nb_chunks = indexer_document(chemin, manuel.id_manuel)

        flash(f'Manuel "{titre}" ajouté et indexé avec succès ({nb_chunks} extraits).', 'success')
        return redirect(url_for('administration'))

    categories = sorted(set(m.categorie for m in Manuel.query.all() if m.categorie))
    return render_template('ajouter_manuel.html', categories=categories)


@app.route('/administration/supprimer-manuel/<int:id>', methods=['POST'])
@admin_required
def supprimer_manuel(id):
    manuel = Manuel.query.get_or_404(id)
    chemin = manuel.chemin_fichier
    db.session.delete(manuel)  # cascade supprime aussi les chunks
    db.session.commit()
    if chemin and os.path.exists(chemin):
        os.remove(chemin)
    flash('Manuel supprimé.', 'success')
    return redirect(url_for('administration'))


@app.route('/administration/supprimer-utilisateur/<int:id>', methods=['POST'])
@admin_required
def supprimer_utilisateur(id):
    if id == session.get('user_id'):
        flash('Vous ne pouvez pas supprimer votre propre compte.', 'error')
        return redirect(url_for('administration'))
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    flash('Utilisateur supprimé.', 'success')
    return redirect(url_for('administration'))


@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    app.run(debug=True, port=5001)
