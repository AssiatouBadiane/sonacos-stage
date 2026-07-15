import time
from app import app
from rag import rechercher_chunks

with app.app_context():
    debut = time.time()
    rechercher_chunks("procédure de congé", id_manuel=3, top_k=5)
    print(f"1er appel (sans cache) : {time.time() - debut:.3f}s")

    debut = time.time()
    rechercher_chunks("chapitre 14", id_manuel=3, top_k=5)
    print(f"2e appel (avec cache)  : {time.time() - debut:.3f}s")

    debut = time.time()
    rechercher_chunks("solde de conge", id_manuel=3, top_k=5)
    print(f"3e appel (avec cache)  : {time.time() - debut:.3f}s")
    
    def scores_mot_cle_par_chunk(question, id_manuel):
    """Calcule un score de rareté (type IDF) par CHUNK (pas par page) —
    utilisé pour booster le score sémantique dans la recherche hybride."""
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
        (chunk, set(re.findall(r'\w+', normaliser(chunk.extrait_texte))))
        for chunk in chunks
    ]

    frequences = {}
    for mot in mots_normalises:
        prefixe = mot[:5]
        nb = sum(1 for _, tokens in chunks_tokens if any(t.startswith(prefixe) for t in tokens))
        frequences[mot] = max(nb, 1)

    scores = {}
    for chunk, tokens in chunks_tokens:
        score = 0.0
        for mot in mots_normalises:
            prefixe = mot[:5]
            if any(t.startswith(prefixe) for t in tokens):
                score += 1.0 / frequences[mot]
        if score > 0:
            scores[chunk.id_chunk] = score  # ajuste 'id_chunk' si ta clé primaire s'appelle autrement

    return scores