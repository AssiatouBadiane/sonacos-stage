# 🌿 SONACOS — Plateforme Assistant IA
> Développé par **Assiatou Badiane** — Stagiaire Génie Logiciel & SI

## Description
Plateforme web intelligente de gestion et consultation des procédures administratives de la SONACOS, intégrant un assistant conversationnel basé sur l'IA (RAG + LLaMA 3 via Groq).

## 🗂️ Structure du projet
```
sonacos/
├── app.py                  # Application Flask principale
├── requirements.txt        # Dépendances Python
├── .env.example            # Variables d'environnement (copier en .env)
├── uploads/                # Fichiers PDF uploadés
├── static/
│   ├── css/style.css       # Feuille de style complète
│   └── js/main.js          # JavaScript principal
└── templates/
    ├── base.html           # Template de base (navbar, mascotte)
    ├── landing.html        # Page d'accueil publique
    ├── login.html          # Page de connexion
    ├── accueil.html        # Dashboard utilisateur
    ├── manuels.html        # Liste des manuels
    ├── manuel_detail.html  # Détail d'un manuel
    ├── assistant.html      # Chat IA
    ├── historique.html     # Historique des conversations
    ├── administration.html # Console admin
    ├── ajouter_manuel.html # Formulaire ajout manuel
    └── faq.html            # Questions fréquentes
```

## 🚀 Installation

### 1. Cloner et entrer dans le dossier
```bash
cd sonacos
```

### 2. Créer et activer l'environnement virtuel
```bash
python -m venv venv
# Windows :
venv\Scripts\activate
# Linux/Mac :
source venv/bin/activate
```

### 3. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 4. Configurer les variables d'environnement
```bash
cp .env.example .env
# Éditer .env et renseigner votre clé GROQ_API_KEY
```

### 5. Lancer l'application
```bash
python app.py
```

Ouvrir **http://localhost:5000** dans le navigateur.

## 🔑 Comptes de démonstration
| Email | Mot de passe | Rôle |
|-------|-------------|------|
| admin@sonacos.sn | admin123 | Administrateur |
| employe@sonacos.sn | emp123 | Employé |

## 🤖 Intégration IA (Groq + LLaMA 3)
1. Créer un compte sur [console.groq.com](https://console.groq.com)
2. Générer une clé API
3. Renseigner `GROQ_API_KEY` dans `.env`
4. Dans `app.py`, remplacer la section `# Simulation RAG` par :

```python
from groq import Groq
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Appel LLaMA 3 avec contexte RAG
completion = client.chat.completions.create(
    model="llama3-8b-8192",
    messages=[
        {"role": "system", "content": "Tu es l'assistant documentaire de la SONACOS. Réponds uniquement à partir des extraits fournis. Indique toujours la source."},
        {"role": "user", "content": f"Contexte: {contexte_rag}\n\nQuestion: {question}"}
    ],
    max_tokens=1024,
)
reponse = completion.choices[0].message.content
```

## 🗄️ Base de données MySQL (production)
```sql
CREATE DATABASE sonacos_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'sonacos_user'@'localhost' IDENTIFIED BY 'votre_mot_de_passe';
GRANT ALL PRIVILEGES ON sonacos_db.* TO 'sonacos_user'@'localhost';
```

## 🎨 Design
- **Couleurs** : Vert #2d7a27 · Jaune #F4A500 · Rouge #c0392b
- **Police** : Inter (Google Fonts)
- **Mascotte** : Goutte d'huile animée flottante (SVG inline)
- **Logo SONACOS** : SVG inline avec goutte d'huile intégrée
- **Design system** : CSS variables, responsive, mobile-first

## 📋 Technologies utilisées
| Couche | Technologie |
|--------|------------|
| Frontend | HTML5, CSS3, JavaScript |
| Backend | Python, Flask |
| Base de données | MySQL (sqlite en dev) |
| IA | Groq API + LLaMA 3 |
| RAG | PyMuPDF + embeddings |

---
© 2026 SONACOS — Plateforme Assistant IA
