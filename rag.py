import os
import re
import numpy as np
import unicodedata
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from models import db, Chunk, Chapitre, Manuel

# Modèle d'embeddings chargé une seule fois au démarrage
_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _model

class ManuelLeger:
    __slots__ = ('titre',)
    def __init__(self, titre):
        self.titre = titre


class ChunkLeger:
    """Copie légère d'un Chunk, sans dépendance à une session SQLAlchemy —
    sûre à garder en cache entre plusieurs requêtes web."""
    __slots__ = ('id_chunk', 'num_page', 'extrait_texte', 'manuel')
    def __init__(self, id_chunk, num_page, extrait_texte, titre_manuel):
        self.id_chunk = id_chunk
        self.num_page = num_page
        self.extrait_texte = extrait_texte
        self.manuel = ManuelLeger(titre_manuel)


_cache_embeddings = {}  # id_manuel -> {'chunks': [...], 'matrix': np.array}

def get_embeddings_manuel(id_manuel):
    """Charge et met en cache la matrice d'embeddings d'un manuel, sous
    forme de données pures (pas d'objets SQLAlchemy) pour rester valide
    entre plusieurs requêtes web."""
    if id_manuel in _cache_embeddings:
        return _cache_embeddings[id_manuel]

    chunks_orm = Chunk.query.filter_by(id_manuel=id_manuel).all()
    if not chunks_orm:
        return None

    manuel = Manuel.query.get(id_manuel)
    titre_manuel = manuel.titre if manuel else ''

    chunks = [
        ChunkLeger(c.id_chunk, c.num_page, c.extrait_texte, titre_manuel)
        for c in chunks_orm
    ]
    matrix = np.array([
        list(map(float, c.embedding.split(','))) for c in chunks_orm
    ])

    resultat = {'chunks': chunks, 'matrix': matrix}
    _cache_embeddings[id_manuel] = resultat
    return resultat

def invalider_cache(id_manuel=None):
    """À appeler après une réindexation pour forcer le rechargement
    depuis la base au prochain appel. Sans argument, vide tout le cache."""
    if id_manuel is None:
        _cache_embeddings.clear()
    else:
        _cache_embeddings.pop(id_manuel, None)

def extraire_texte_pdf(chemin_fichier):
    """Extrait tout le texte d'un fichier PDF page par page"""
    chemin_absolu = os.path.abspath(os.path.normpath(chemin_fichier))

    if not os.path.exists(chemin_absolu):
        print(f"❌ Fichier introuvable : {chemin_absolu}")
        return []

    reader = PdfReader(chemin_absolu)
    pages = []
    for i, page in enumerate(reader.pages):
        texte = page.extract_text()
        if texte:
            pages.append({'texte': texte, 'num_page': i + 1})
    return pages


def decouper_en_chunks(pages, taille=800, overlap=150):
    """Découpe le texte du document ENTIER (toutes les pages concaténées)
    en chunks cohérents, avec chevauchement — sans jamais couper au niveau
    d'une frontière de page. Chaque chunk garde un numéro de page précis
    (la page où il commence)."""
    texte_complet = ''
    offsets_pages = []  # [(offset_de_debut_dans_texte_complet, num_page), ...]

    for page in pages:
        texte_page = re.sub(r'\s+', ' ', page['texte']).strip()
        if not texte_page:
            continue
        offsets_pages.append((len(texte_complet), page['num_page']))
        texte_complet += texte_page + ' '

    def page_pour_offset(offset):
        """Retrouve le numéro de page correspondant à une position donnée
        dans le texte complet concaténé."""
        page_trouvee = offsets_pages[0][1] if offsets_pages else 1
        for offset_debut, num_page in offsets_pages:
            if offset_debut <= offset:
                page_trouvee = num_page
            else:
                break
        return page_trouvee

    chunks = []
    start = 0
    while start < len(texte_complet):
        end = start + taille
        morceau = texte_complet[start:end]
        if end < len(texte_complet):
            dernier_point = morceau.rfind('. ')
            if dernier_point > taille * 0.5:
                morceau = morceau[:dernier_point + 1]
                end = start + dernier_point + 1
        morceau = morceau.strip()
        if len(morceau) > 100:
            chunks.append({'texte': morceau, 'num_page': page_pour_offset(start)})
        start = end - overlap

    return chunks


def indexer_document(chemin_fichier, id_manuel):
    """Extrait, découpe et stocke les chunks d'un PDF en base"""
    pages = extraire_texte_pdf(chemin_fichier)

    if not pages:
        print(f"❌ Aucun texte extrait pour le manuel ID {id_manuel}.")
        return 0

    chunks = decouper_en_chunks(pages)
    if not chunks:
        print(f"❌ Aucun chunk généré pour le manuel ID {id_manuel}.")
        return 0

    model = get_model()

    # Encodage en une seule fois (batch) au lieu d'un chunk à la fois : beaucoup plus rapide
    textes = [chunk['texte'] for chunk in chunks]
    embeddings = model.encode(textes, batch_size=32, show_progress_bar=False)

    nouveaux_chunks = []
    for chunk, embedding in zip(chunks, embeddings):
        embedding_str = ','.join(map(str, embedding))
        nouveaux_chunks.append(Chunk(
            extrait_texte=chunk['texte'],
            num_page=chunk['num_page'],
            id_manuel=id_manuel,
            embedding=embedding_str
        ))

    db.session.bulk_save_objects(nouveaux_chunks)
    db.session.commit()
    print(f"💾 {len(chunks)} chunks enregistrés pour le manuel ID {id_manuel}.")
    
    sommaire = extraire_sommaire(pages)
    if sommaire:
        for ch in sommaire:
            db.session.add(Chapitre(
                id_manuel=id_manuel,
                numero=ch['numero'],
                titre=ch['titre'],
                page_debut=ch['page_debut'],
                page_fin=ch['page_fin']
            ))
        db.session.commit()
        print(f"📑 {len(sommaire)} chapitres détectés et enregistrés.")
        
    invalider_cache(id_manuel)
    return len(chunks)

def rechercher_chunks(question, id_manuel=None, top_k=5, seuil=0.3, poids_mot_cle=6.0):
    """Recherche hybride : combine le score sémantique (embeddings) avec
    un boost basé sur la présence de mots-clés rares (type IDF). Un chunk
    contenant un mot-clé rare de la question (ex: 'congé') remonte même
    si sa similarité sémantique brute est moyenne."""
    model = get_model()
    question_embedding = model.encode(question)

    if id_manuel:
        data = get_embeddings_manuel(id_manuel)
        if not data:
            return []
        chunks, chunk_embeddings = data['chunks'], data['matrix']
    else:
        chunks = Chunk.query.all()
        if not chunks:
            return []
        chunk_embeddings = np.array([list(map(float, c.embedding.split(','))) for c in chunks])

    similarites = cosine_similarity([question_embedding], chunk_embeddings)[0]

    boost_mot_cle = scores_mot_cle_par_chunk(question, id_manuel) if id_manuel else {}

    resultats = []
    for chunk, score_semantique in zip(chunks, similarites):
        boost = boost_mot_cle.get(chunk.id_chunk, 0.0)
        score_final = score_semantique + poids_mot_cle * boost
        resultats.append((chunk, score_final, score_semantique))

    resultats.sort(key=lambda x: x[1], reverse=True)

    # Garde un chunk si son score sémantique dépasse le seuil, OU s'il a
    # un boost mot-clé (permet à un chunk pertinent par mot-clé mais un peu
    # faible sémantiquement de passer quand même)
    resultats = [
        (chunk, score_final) for chunk, score_final, score_sem in resultats[:top_k * 2]
        if score_sem >= seuil or boost_mot_cle.get(chunk.id_chunk, 0.0) > 0
    ][:top_k]

    return [chunk for chunk, score in resultats]

def extraire_sommaire(pages):
    """Détecte les entrées 'CHAPITRE N : titre ..... page' dans les
    premières pages d'un document. Générique : marche pour n'importe
    quel manuel qui suit ce format, retourne [] sinon."""
    texte_debut = "\n".join(p['texte'] for p in pages[:6])  # sommaire = début du doc

    pattern = r'CHAPITRE\s+(\d+)\s*:\s*(.+?)\s*\.{3,}\s*(\d+)'
    matches = re.findall(pattern, texte_debut, re.DOTALL)

    chapitres = []
    for numero, titre, page in matches:
        titre_propre = re.sub(r'\s+', ' ', titre).strip()
        chapitres.append({
            'numero': int(numero),
            'titre': titre_propre,
            'page_debut': int(page)
        })

    chapitres.sort(key=lambda c: c['numero'])
    for i, ch in enumerate(chapitres):
        if i + 1 < len(chapitres):
            ch['page_fin'] = chapitres[i + 1]['page_debut'] - 1
        else:
            ch['page_fin'] = None

    return chapitres


def chercher_par_chapitre(question, id_manuel):
    """Si la question mentionne 'chapitre N', récupère les chunks par
    plage de pages plutôt que par similarité sémantique. Retourne None
    si aucun numéro n'est détecté ou si ce manuel n'a pas de sommaire indexé."""
    match = re.search(r'chapitre\s*(\d+)', question.lower())
    if not match:
        return None

    numero = int(match.group(1))
    chapitre = Chapitre.query.filter_by(id_manuel=id_manuel, numero=numero).first()
    if not chapitre:
        return None

    page_fin = chapitre.page_fin or (chapitre.page_debut + 15)
    chunks = Chunk.query.filter(
        Chunk.id_manuel == id_manuel,
        Chunk.num_page >= chapitre.page_debut,
        Chunk.num_page <= page_fin
    ).order_by(Chunk.num_page).limit(8).all()

    return chunks if chunks else None

def normaliser(texte):
    """Enlève les accents et met en minuscules — recherche insensible aux accents/casse."""
    nfkd = unicodedata.normalize('NFKD', texte)
    sans_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return sans_accents.lower()


MOTS_VIDES = {
    'procedure', 'procedures', 'manuel', 'sonacos', 'annee', 'chapitre',
    'quelle', 'quel', 'comment', 'pourquoi', 'concernant', 'information',
    'informations', 'donne', 'parle', 'dis', 'peux', 'peut', 'veux'
}

def rechercher_par_mot_cle(mots_cles, id_manuel, max_pages=8):
    """Recherche par préfixe, en pondérant chaque mot-clé par sa rareté :
    un mot présent dans peu de pages (ex: 'congé') compte plus qu'un mot
    omniprésent (ex: 'solde' dans un contexte financier)."""
    mots_normalises = [
        normaliser(m) for m in mots_cles
        if len(m) > 3 and normaliser(m) not in MOTS_VIDES
    ]
    if not mots_normalises:
        return []

    chunks = Chunk.query.filter_by(id_manuel=id_manuel).all()

    chunks_tokens = [
        (chunk, set(re.findall(r'\w+', normaliser(chunk.extrait_texte))))
        for chunk in chunks
    ]

    frequences = {}
    for mot in mots_normalises:
        prefixe = mot[:5]
        nb = sum(1 for _, tokens in chunks_tokens if any(t.startswith(prefixe) for t in tokens))
        frequences[mot] = max(nb, 1)

    scores_par_page = {}
    for chunk, tokens in chunks_tokens:
        score = 0.0
        for mot in mots_normalises:
            prefixe = mot[:5]
            if any(t.startswith(prefixe) for t in tokens):
                score += 1.0 / frequences[mot]
        if score > 0:
            if chunk.num_page not in scores_par_page or score > scores_par_page[chunk.num_page][0]:
                scores_par_page[chunk.num_page] = (score, chunk.extrait_texte[:150])

    resultats = sorted(scores_par_page.items(), key=lambda x: (-x[1][0], x[0]))
    return [(page, extrait) for page, (score, extrait) in resultats[:max_pages]]

def scores_mot_cle_par_chunk(question, id_manuel):
    """Calcule un score TF-IDF par CHUNK : fréquence du mot-clé DANS le
    chunk (TF), pondérée par sa rareté dans le document entier (IDF).
    Un chunk qui mentionne 'congé' 4 fois pèse plus qu'un chunk qui le
    mentionne une seule fois en passant."""
    mots_bruts = re.findall(r'\w+', question)
    mots_normalises = [
        normaliser(m) for m in mots_bruts
        if len(m) > 3 and normaliser(m) not in MOTS_VIDES
    ]
    if not mots_normalises:
        return {}

    data = get_embeddings_manuel(id_manuel)
    if not data:
        return {}
    chunks = data['chunks']

    chunks_tokens = [
        (chunk, re.findall(r'\w+', normaliser(chunk.extrait_texte)))  # liste, pas set : garde les doublons
        for chunk in chunks
    ]

    frequences_docs = {}
    for mot in mots_normalises:
        prefixe = mot[:5]
        nb = sum(1 for _, tokens in chunks_tokens if any(t.startswith(prefixe) for t in tokens))
        frequences_docs[mot] = max(nb, 1)

    scores = {}
    for chunk, tokens in chunks_tokens:
        score = 0.0
        for mot in mots_normalises:
            prefixe = mot[:5]
            tf = sum(1 for t in tokens if t.startswith(prefixe))  # compte les occurrences
            if tf > 0:
                score += tf / frequences_docs[mot]
        if score > 0:
            scores[chunk.id_chunk] = score

    return scores