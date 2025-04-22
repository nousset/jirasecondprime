import os
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import requests
import json
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
API_URL = os.getenv("API_URL", "https://abraham-certification-memories-cl.trycloudflare.com")  # Modifiable par variable d'env
APP_SECRET = os.getenv("APP_SECRET", "your-secret-key")

# Session HTTP avec retry
def create_retry_session(retries=3, backoff_factor=0.3):
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

# Vérification réelle de l'état de LM Studio
def check_lm_studio_status():
    try:
        # Essayer plusieurs formats d'URL possibles
        endpoints = [
            f"{API_URL}/v1/models",
            f"{API_URL}/models",
        ]
        
        if API_URL.endswith('/'):
            endpoints = [
                f"{API_URL}v1/models",
                f"{API_URL}models",
            ]
        
        session = create_retry_session(retries=1)
        
        for endpoint in endpoints:
            try:
                logger.info(f"Vérification disponibilité LM Studio sur: {endpoint}")
                response = session.get(endpoint, timeout=5)
                if response.status_code == 200:
                    logger.info(f"LM Studio disponible sur: {endpoint}")
                    return True
            except Exception as e:
                logger.warning(f"Échec vérification sur {endpoint}: {e}")
                continue
                
        logger.error("LM Studio n'est pas accessible sur aucun endpoint")
        return False
    except Exception as e:
        logger.error(f"Erreur lors de la vérification de LM Studio: {e}")
        return False

# Construction du prompt
def build_prompt(story_text, format_choice, language="fr"):
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
def generate_response(prompt, max_tokens=800):
    # Vérification réelle de la disponibilité
    if not check_lm_studio_status():
        logger.error("LM Studio n'est pas accessible")
        return "Erreur de connexion : LM Studio n'est pas accessible. Vérifiez la configuration de CloudFlare."
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "mistral-7b-instruct-v0.3",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    
    # Liste des endpoints possibles à essayer
    endpoints = []
    if not API_URL.endswith('/'):
        endpoints = [
            f"{API_URL}/v1/chat/completions",
            f"{API_URL}/chat/completions"
        ]
    else:
        endpoints = [
            f"{API_URL}v1/chat/completions",
            f"{API_URL}chat/completions"
        ]
    
    session = create_retry_session(retries=1)
    last_error = None
    
    # Essai de chaque endpoint
    for api_endpoint in endpoints:
        try:
            logger.info(f"Envoi requête à: {api_endpoint}")
            response = session.post(api_endpoint, json=payload, headers=headers, timeout=90)
            
            # Log pour debug
            logger.info(f"Statut réponse: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"Réponse: {response.text}")
                continue  # Essayer l'endpoint suivant
                
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"Erreur avec endpoint {api_endpoint}: {e}")
            last_error = e
            continue  # Essayer l'endpoint suivant
    
    # Si on arrive ici, aucun endpoint n'a fonctionné
    error_message = f"Erreur API: Aucun endpoint n'a fonctionné. Dernière erreur: {last_error}"
    logger.error(error_message)
    return error_message

@app.route("/")
def home():
    return render_template(HTML_INDEX)

@app.route("/public/<path:path>")
def serve_public(path):
    return send_from_directory("public", path)

@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)

@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json()
    story = data.get("story", "").strip()
    format_choice = data.get("format", "gherkin")
    language = data.get("language", "fr")

    if not story:
        return jsonify({"error": "Aucune user story fournie"}), 400

    prompt = build_prompt(story, format_choice, language)
    generated = generate_response(prompt)
    return jsonify({"result": generated})

# Endpoint test pour vérifier LM Studio avec détails
@app.route("/api/status", methods=["GET"])
def api_status():
    if check_lm_studio_status():
        return jsonify({"status": "LM Studio disponible", "api_url": API_URL}), 200
    return jsonify({"status": "LM Studio non disponible", "api_url": API_URL}), 503

# Endpoint de diagnostic pour vérifier les différentes configurations
@app.route("/api/diagnostic", methods=["GET"])
def api_diagnostic():
    results = {
        "api_url": API_URL,
        "endpoints_tested": [],
        "configuration": {
            "api_url_ends_with_slash": API_URL.endswith('/')
        }
    }
    
    # Tester différents endpoints
    endpoints = [
        {"name": "v1/models", "url": f"{API_URL}/v1/models" if not API_URL.endswith('/') else f"{API_URL}v1/models"},
        {"name": "models", "url": f"{API_URL}/models" if not API_URL.endswith('/') else f"{API_URL}models"},
        {"name": "v1/chat/completions", "url": f"{API_URL}/v1/chat/completions" if not API_URL.endswith('/') else f"{API_URL}v1/chat/completions"},
        {"name": "chat/completions", "url": f"{API_URL}/chat/completions" if not API_URL.endswith('/') else f"{API_URL}chat/completions"},
    ]
    
    session = create_retry_session(retries=1)
    
    for endpoint in endpoints:
        try:
            response = session.get(endpoint["url"], timeout=5)
            results["endpoints_tested"].append({
                "name": endpoint["name"],
                "url": endpoint["url"],
                "status_code": response.status_code,
                "working": response.status_code < 500  # Même un 404 est "working" car le serveur répond
            })
        except Exception as e:
            results["endpoints_tested"].append({
                "name": endpoint["name"],
                "url": endpoint["url"],
                "error": str(e),
                "working": False
            })
    
    return jsonify(results)

if __name__ == "__main__":
    app.run(debug=True, port=5000)