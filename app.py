from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_babel import Babel, gettext as _, lazy_gettext as _l
from functools import wraps
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from pypdf import PdfReader

from config import Config
from models import db, User, Manuel, Chunk, Conversation, Interaction, Journal
from rag import indexer_document
from ai import generer_reponse

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# ─── Configuration Flask-Babel (langues) ──────────────────────────────────────
app.config['LANGUAGES'] = ['fr', 'en']
app.config['BABEL_DEFAULT_LOCALE'] = 'fr'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'


def get_locale():
    # 1. Langue explicitement choisie et stockée en session
    if 'langue' in session:
        return session['langue']
    # 2. Sinon, on se base sur les préférences du navigateur
    return request.accept_languages.best_match(app.config['LANGUAGES']) or 'fr'


babel = Babel(app, locale_selector=get_locale)

FAQ = [
    {'question': _l('Comment demander un congé annuel ?'), 'reponse': _l("Remplissez le formulaire sur l'intranet RH, obtenez la validation de votre supérieur, puis transmettez au service RH 15 jours à l'avance."), 'source': _l('Manuel RH')},
    {'question': _l('Quels sont les EPI obligatoires en atelier ?'), 'reponse': _l('Casque, lunettes de protection, gants, chaussures de sécurité et gilet réfléchissant sont obligatoires dans toutes les zones de production.'), 'source': _l('Guide Sécurité')},
    {'question': _l('Comment signaler un incident de sécurité ?'), 'reponse': _l('Tout incident doit être signalé immédiatement au responsable HSE via le formulaire F-HSE-001 et enregistré dans le registre des incidents.'), 'source': _l('Guide Sécurité')},
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
            flash(_('Accès réservé aux administrateurs.'), 'error')
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


def log_action(type_action, description, id_utilisateur=None):
    """
    Enregistre une entrée dans le journal (connexions, téléchargements, actions admin).
    Cf. Cahier des charges, section 3.7 (Sécurité > Journalisation).
    """
    entree = Journal(
        id_utilisateur=id_utilisateur or session.get('user_id'),
        type_action=type_action,
        description=description
    )
    db.session.add(entree)
    db.session.commit()


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
            log_action('connexion', f'Connexion de {user.prenom} {user.nom}', id_utilisateur=user.id_utilisateur)
            return redirect(url_for('accueil'))
        flash(_('Email ou mot de passe incorrect.'), 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/set-langue/<langue>')
def set_langue(langue):
    if langue in app.config['LANGUAGES']:
        session['langue'] = langue
    return redirect(request.referrer or url_for('index'))

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
    categories = ['Manuel', 'SET-LOXO', 'Autre']
    return render_template('manuels.html', manuels=filtered, categories=categories, categorie_active=categorie)


@app.route('/manuels/<int:id>')
@login_required
def manuel_detail(id):
    manuel = Manuel.query.get(id)
    if not manuel:
        flash(_('Manuel introuvable.'), 'error')
        return redirect(url_for('manuels'))
    return render_template('manuel_detail.html', manuel=manuel)


@app.route('/assistant')
@login_required
def assistant():
    conversations = Conversation.query.filter_by(id_utilisateur=session['user_id']).order_by(Conversation.date_creation.desc()).all()
    manuels = Manuel.query.all()
    return render_template('assistant.html', conversations=conversations, manuels=manuels)

@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    """Endpoint IA réel — RAG + Groq/LLaMA 3"""
    data = request.get_json()
    question = (data.get('question') or '').strip()
    id_conversation = data.get('id_conversation')
    id_manuel = data.get('id_manuel')  # ← AJOUT : reçu du front pour une nouvelle conversation
    langue = session.get('langue', 'fr')

    if not question:
        return jsonify({'error': 'Question vide'}), 400

    if id_conversation:
        conversation = Conversation.query.get(id_conversation)
        if conversation:
            id_manuel = conversation.id_manuel  # ← on réutilise le manuel déjà choisi pour cette conversation
    else:
        conversation = None

    resultat = generer_reponse(question, id_manuel=id_manuel, langue=langue)  # ← AJOUT id_manuel

    if not conversation:
        conversation = Conversation(
            titre=question[:80],
            id_utilisateur=session['user_id'],
            id_manuel=id_manuel  # ← AJOUT
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

@app.route('/api/conversation/<int:id>')
@login_required
def get_conversation(id):
    conv = Conversation.query.get_or_404(id)
    if conv.id_utilisateur != session['user_id']:
        return jsonify({'error': 'Non autorisé'}), 403
    interactions = Interaction.query.filter_by(id_conversation=id).all()
    return jsonify({
        'titre': conv.titre,
        'messages': [{'question': i.question, 'reponse': i.reponse} for i in interactions]
    })

@app.route('/historique')
@login_required
def historique():
    conversations = Conversation.query.filter_by(id_utilisateur=session['user_id']).order_by(Conversation.date_creation.desc()).all()
    return render_template('historique.html', conversations=conversations)

@app.route('/historique/effacer-tout', methods=['POST'])
@login_required
def effacer_historique():
    conversations = Conversation.query.filter_by(id_utilisateur=session['user_id']).all()
    for conv in conversations:
        Interaction.query.filter_by(id_conversation=conv.id_conversation).delete()
    Conversation.query.filter_by(id_utilisateur=session['user_id']).delete()
    db.session.commit()
    flash(_("Tout l'historique a été effacé."), 'success')
    return redirect(url_for('historique'))

@app.route('/historique/supprimer/<int:id>', methods=['POST'])
@login_required
def supprimer_conversation(id):
    conv = Conversation.query.get_or_404(id)
    if conv.id_utilisateur != session['user_id']:
        flash(_('Action non autorisée.'), 'error')
        return redirect(url_for('assistant'))
    Interaction.query.filter_by(id_conversation=conv.id_conversation).delete()
    db.session.delete(conv)
    db.session.commit()
    return redirect(url_for('assistant'))

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
            flash(_('Fichier invalide, seuls les PDF sont acceptés.'), 'error')
            categories = ['Manuel', 'SET-LOXO', 'Autre']
            return render_template('ajouter_manuel.html', categories=categories)

        # Vérifie qu'un manuel avec ce titre n'existe pas déjà
        if Manuel.query.filter_by(titre=titre).first():
            flash(_('Un manuel intitulé "%(titre)s" existe déjà. Choisissez un autre titre.', titre=titre), 'error')
            categories = ['Manuel', 'SET-LOXO', 'Autre']
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

        log_action('admin', f'Ajout du manuel "{titre}"')
        
        flash(_('Manuel "%(titre)s" ajouté et indexé avec succès (%(nb_chunks)s extraits).', titre=titre, nb_chunks=nb_chunks), 'success') 
        
        return redirect(url_for('administration'))

    categories = ['Manuel', 'SET-LOXO', 'Autre']
    return render_template('ajouter_manuel.html', categories=categories)


@app.route('/administration/ajouter-utilisateur', methods=['GET', 'POST'])
@admin_required
def ajouter_utilisateur():
    if request.method == 'POST':
        nom = request.form.get('nom')
        prenom = request.form.get('prenom')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'employe')
        if User.query.filter_by(email=email).first():
            flash(_('Cet email est déjà utilisé.'), 'error')
        else:
            user = User(nom=nom, prenom=prenom, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            log_action('admin', f'Création de l\'utilisateur {prenom} {nom} ({role})')
            flash(_('Utilisateur %(prenom)s %(nom)s créé avec succès.', prenom=prenom, nom=nom), 'success')
            return redirect(url_for('administration'))


@app.route('/administration/supprimer-manuel/<int:id>', methods=['POST'])
@admin_required
def supprimer_manuel(id):
    manuel = Manuel.query.get_or_404(id)
    titre = manuel.titre
    chemin = manuel.chemin_fichier
    db.session.delete(manuel)  # cascade supprime aussi les chunks
    db.session.commit()
    if chemin and os.path.exists(chemin):
        os.remove(chemin)
    log_action('admin', f'Suppression du manuel "{titre}"')
    flash(_('Manuel supprimé.'), 'success')
    return redirect(url_for('administration'))


@app.route('/administration/supprimer-utilisateur/<int:id>', methods=['POST'])
@admin_required
def supprimer_utilisateur(id):
    if id == session.get('user_id'):
        flash(_('Vous ne pouvez pas supprimer votre propre compte.'), 'error')
        return redirect(url_for('administration'))
    user = User.query.get_or_404(id)
    nom_complet = f'{user.prenom} {user.nom}'
    db.session.delete(user)
    db.session.commit()
    log_action('admin', f'Suppression de l\'utilisateur {nom_complet}')
    flash(_('Utilisateur supprimé.'), 'success')
    return redirect(url_for('administration'))


@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    manuel = Manuel.query.filter(Manuel.chemin_fichier.like(f'%{filename}')).first()
    log_action('telechargement', f'Téléchargement de "{manuel.titre}"' if manuel else f'Téléchargement de {filename}')
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/administration/effacer-historique', methods=['POST'])
@admin_required
def effacer_historique_admin():
    Interaction.query.delete()
    Conversation.query.delete()
    db.session.commit()
    flash("Tout l'historique a été effacé.", 'success')
    return redirect(url_for('administration'))

@app.context_processor
def inject_locale():
    return dict(get_locale=get_locale)

if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    app.run(debug=True, port=5001)