import os
import re
import numpy as np
import unicodedata
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from models import db, Chunk, Chapitre

# Modèle d'embeddings chargé une seule fois au démarrage
_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _model


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
    """Découpe le texte en chunks cohérents, en respectant les phrases et avec chevauchement"""
    chunks = []
    for page in pages:
        texte = re.sub(r'\s+', ' ', page['texte']).strip()
        num_page = page['num_page']
        start = 0
        while start < len(texte):
            end = start + taille
            morceau = texte[start:end]
            if end < len(texte):
                dernier_point = morceau.rfind('. ')
                if dernier_point > taille * 0.5:
                    morceau = morceau[:dernier_point + 1]
                    end = start + dernier_point + 1
            morceau = morceau.strip()
            if len(morceau) > 100:
                chunks.append({'texte': morceau, 'num_page': num_page})
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
    
    return len(chunks)


def rechercher_chunks(question, id_manuel=None, top_k=3, seuil=0.3):
    model = get_model()
    question_embedding = model.encode(question)

    if id_manuel:
        chunks = Chunk.query.filter_by(id_manuel=id_manuel).all()
    else:
        chunks = Chunk.query.all()

    if not chunks:
        return []

    chunk_embeddings = np.array([
        list(map(float, chunk.embedding.split(','))) for chunk in chunks
    ])
    similarites = cosine_similarity([question_embedding], chunk_embeddings)[0]

    resultats = sorted(zip(chunks, similarites), key=lambda x: x[1], reverse=True)

    resultats = [(chunk, score) for chunk, score in resultats[:top_k] if score >= seuil]

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
    """Recherche par préfixe (tolère fautes de frappe/pluriels) en excluant
    les mots trop génériques qui polluent le résultat."""
    mots_normalises = [
        normaliser(m) for m in mots_cles
        if len(m) > 3 and normaliser(m) not in MOTS_VIDES
    ]
    if not mots_normalises:
        return []

    chunks = Chunk.query.filter_by(id_manuel=id_manuel).all()
    pages_trouvees = {}

    for chunk in chunks:
        texte_normalise = normaliser(chunk.extrait_texte)
        mots_du_texte = set(re.findall(r'\w+', texte_normalise))
        for mot in mots_normalises:
            prefixe = mot[:5]  # tolère fin de mot différente (conger → congé/congés)
            if any(m.startswith(prefixe) for m in mots_du_texte) and chunk.num_page not in pages_trouvees:
                pages_trouvees[chunk.num_page] = chunk.extrait_texte[:150]
                break

    return sorted(pages_trouvees.items())[:max_pages]