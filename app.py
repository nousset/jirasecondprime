import os
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import requests
import json
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from functools import lru_cache

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="public", template_folder="template")
CORS(app)

# Constantes
HTML_INDEX = "index.html"
CONTENT_TYPE_JSON = "application/json"

# Configuration des variables d'environnement
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_API", "https://ventures-zu-richards-descriptions.trycloudflare.com")
APP_SECRET = os.getenv("APP_SECRET", "your-secret-key")

# URLs pour les APIs LM Studio
LM_STUDIO_MODELS_URL = f"{LM_STUDIO_BASE_URL}/v1/models"
LM_STUDIO_CHAT_URL = f"{LM_STUDIO_BASE_URL}/v1/chat/completions"

# Session HTTP avec retry - création singleton
@lru_cache(maxsize=1)
def get_http_session(retries=3, backoff_factor=0.3):
    """Crée et garde en cache une session HTTP avec retry"""
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(500, 502, 504),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Vérification de l'état de LM Studio
def check_lm_studio_status():
    """Vérifie si LM Studio est disponible en interrogeant l'API des modèles"""
    try:
        logger.info(f"Vérification LM Studio à {LM_STUDIO_MODELS_URL}")
        response = get_http_session().get(LM_STUDIO_MODELS_URL, timeout=10)
        logger.info(f"Réponse: {response.status_code}")
        
        if response.status_code == 200:
            # Vérifier que la réponse contient bien des modèles
            models_data = response.json()
            if "data" in models_data and len(models_data["data"]) > 0:
                logger.info(f"Modèles disponibles: {[model.get('id') for model in models_data['data']]}")
                return True
        return False
    except Exception as e:
        logger.error(f"Erreur lors de la vérification LM Studio : {e}")
        return False

# Construction du prompt - cache les prompts fréquents
@lru_cache(maxsize=32)
def build_prompt(story_text, format_choice, language="fr"):
    """Génère le prompt approprié selon le format et la langue choisis"""
    if language == "fr":
        if format_choice == "gherkin":
            return f"""Voici une user story : "{story_text}"
En tant qu'assistant de test, génère des scénarios de test au format Gherkin (Given/When/Then) en français.

Format attendu:
Feature: [Titre de la fonctionnalité]

  Scenario: [Titre du scénario 1]
    Given [condition préalable]
    When [action utilisateur]
    Then [résultat attendu]

  Scenario: [Titre du scénario 2]
    ...
"""
        else:
            return f"""Voici une user story : "{story_text}"
Génère des cas de test détaillés en français avec les étapes et résultats attendus.

Format attendu:
# Cas de test 1 : [Titre du cas de test]
## Action
[Description détaillée]

## Résultat attendu
[Description détaillée]

# Cas de test 2 : ...
"""
    else:
        if format_choice == "gherkin":
            return f"""Here is a user story: "{story_text}"
Generate test scenarios in Gherkin format (Given/When/Then) in English.

Expected format:
Feature: [Feature title]

  Scenario: [Scenario 1 title]
    Given [precondition]
    When [user action]
    Then [expected result]

  Scenario: [Scenario 2 title]
    ...
"""
        else:
            return f"""Here is a user story: "{story_text}"
Generate detailed test cases in English with steps and expected results.

Expected format:
# Test Case 1: [Title]
## Action
[Action description]

## Expected Result
[Expected outcome]

# Test Case 2: ...
"""

# Envoi du prompt à LM Studio
def generate_response(prompt, max_tokens=800, temperature=0.7, model="mistral-7b-instruct-v0.3"):
    """Envoie un prompt à LM Studio et retourne la réponse générée"""
    if not check_lm_studio_status():
        logger.error("LM Studio n'est pas accessible")
        return "Erreur de connexion : LM Studio n'est pas accessible."

    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    try:
        session = get_http_session(retries=1)
        logger.info(f"Envoi d'une requête à {LM_STUDIO_CHAT_URL}")
        response = session.post(LM_STUDIO_CHAT_URL, json=payload, headers=headers, timeout=90)
        response.raise_for_status()
        
        # Extraction de la réponse
        result = response.json()
        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        else:
            logger.error(f"Format de réponse inattendu: {result}")
            return "Erreur: Format de réponse inattendu."
    except requests.exceptions.Timeout:
        logger.error("Timeout lors de la requête LM Studio")
        return "Timeout : le modèle met trop de temps à répondre."
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur requête LM Studio : {e}")
        return f"Erreur : {str(e)}"

@app.route("/")
def home():
    """Page d'accueil de l'application"""
    return render_template(HTML_INDEX)

@app.route("/public/<path:path>")
def serve_public(path):
    """Sert les fichiers statiques du dossier public"""
    return send_from_directory("public", path)

@app.route("/static/<path:path>")
def serve_static(path):
    """Sert les fichiers statiques du dossier static"""
    return send_from_directory("static", path)

@app.route("/api/debug", methods=["GET"])
def api_debug():
    """Endpoint de débogage qui affiche les URLs configurées"""
    return jsonify({
        "lm_studio_base_url": LM_STUDIO_BASE_URL,
        "models_url": LM_STUDIO_MODELS_URL,
        "chat_url": LM_STUDIO_CHAT_URL,
        "env_var": os.getenv("LM_STUDIO_API", "non défini"),
        "models_check": check_lm_studio_status()
    }), 200

@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Endpoint pour générer des tests à partir d'une user story"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Données JSON manquantes"}), 400
            
        story = data.get("story", "").strip()
        format_choice = data.get("format", "gherkin")
        language = data.get("language", "fr")
        model = data.get("model", "mistral-7b-instruct-v0.3")
        
        if not story:
            return jsonify({"error": "Aucune user story fournie"}), 400

        # Générer et renvoyer les tests
        prompt = build_prompt(story, format_choice, language)
        generated = generate_response(prompt, model=model)
        return jsonify({"result": generated})
    except Exception as e:
        logger.error(f"Erreur lors du traitement de la requête: {e}")
        return jsonify({"error": f"Erreur serveur: {str(e)}"}), 500

@app.route("/api/status", methods=["GET"])
def api_status():
    """Endpoint pour vérifier l'état de LM Studio"""
    if check_lm_studio_status():
        return jsonify({
            "status": "LM Studio disponible", 
            "url": LM_STUDIO_BASE_URL
        }), 200
    return jsonify({
        "status": "LM Studio non disponible", 
        "url": LM_STUDIO_BASE_URL
    }), 503

@app.route("/api/models", methods=["GET"])
def api_models():
    """Endpoint pour récupérer la liste des modèles disponibles"""
    try:
        response = get_http_session().get(LM_STUDIO_MODELS_URL, timeout=10)
        if response.status_code == 200:
            return jsonify(response.json()), 200
        return jsonify({"error": f"Erreur {response.status_code}"}), response.status_code
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des modèles: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Vérifier la configuration au démarrage
    logger.info(f"LM Studio URL: {LM_STUDIO_BASE_URL}")
    logger.info(f"LM Studio Models URL: {LM_STUDIO_MODELS_URL}")
    logger.info(f"LM Studio Chat URL: {LM_STUDIO_CHAT_URL}")
    
    # Vérifier si LM Studio est disponible
    if check_lm_studio_status():
        logger.info("LM Studio est disponible")
    else:
        logger.warning("LM Studio n'est pas disponible")
    
    app.run(debug=True, port=5000)