import os
import numpy as np
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from models import db, Chunk

# Modèle d'embeddings chargé une seule fois au démarrage
_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2')
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


def decouper_en_chunks(pages, taille=500):
    """Découpe le texte en morceaux de 500 caractères maximum"""
    chunks = []
    for page in pages:
        texte = page['texte']
        num_page = page['num_page']
        for i in range(0, len(texte), taille):
            morceau = texte[i:i + taille]
            if len(morceau) > 100:
                chunks.append({'texte': morceau, 'num_page': num_page})
    return chunks


def indexer_document(chemin_fichier, id_manuel):
    """Extrait, découpe et stocke les chunks d'un PDF en base"""
    pages = extraire_texte_pdf(chemin_fichier)

    if not pages:
        print(f"❌ Aucun texte extrait pour le manuel ID {id_manuel}.")
        return 0

    chunks = decouper_en_chunks(pages)
    model = get_model()

    for chunk in chunks:
        embedding = model.encode(chunk['texte'])
        embedding_str = ','.join(map(str, embedding))

        nouveau_chunk = Chunk(
            extrait_texte=chunk['texte'],
            num_page=chunk['num_page'],
            id_manuel=id_manuel,
            embedding=embedding_str
        )
        db.session.add(nouveau_chunk)

    db.session.commit()
    print(f"💾 {len(chunks)} chunks enregistrés pour le manuel ID {id_manuel}.")
    return len(chunks)


def rechercher_chunks(question, id_manuel=None, top_k=3, seuil=0.3):
    """Recherche les chunks les plus pertinents par similarité cosinus"""
    model = get_model()
    question_embedding = model.encode(question)

    if id_manuel:
        chunks = Chunk.query.filter_by(id_manuel=id_manuel).all()
    else:
        chunks = Chunk.query.all()

    if not chunks:
        return []

    similarites = []
    for chunk in chunks:
        chunk_embedding = np.array(list(map(float, chunk.embedding.split(','))))
        similarite = cosine_similarity([question_embedding], [chunk_embedding])[0][0]
        similarites.append((chunk, similarite))

    similarites.sort(key=lambda x: x[1], reverse=True)
    resultats = [(chunk, score) for chunk, score in similarites[:top_k] if score >= seuil]

    return [chunk for chunk, score in resultats]
