import os
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import requests
import json
import jwt
import uuid
from datetime import datetime, timedelta
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="public", template_folder="template")
CORS(app)

# Constantes pour éviter les duplications de chaînes littérales
HTML_INDEX = "index.html"
CONTENT_TYPE_JSON = "application/json"

# Configurations
JIRA_BASE_URL = "http://127.0.0.1:1234/v1/chat/completions"
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")
API_URL = os.getenv("API_URL")  # URL de l'API LM Studio
APP_SECRET = os.getenv("APP_SECRET", "your-secret-key")


# Pour stocker les installations d'applications
app_installations = {}

def build_prompt(story_text, format_choice, language="fr"):
    """
    Construit le prompt pour le modèle IA en fonction du format choisi et de la langue
    """
    if language == "fr":
        if format_choice == "gherkin":
            return f"""Voici une user story : "{story_text}"
En tant qu'assistant de test, génère des scénarios de test au format Gherkin (Given/When/Then) en français.
Sépare clairement chaque scénario et assure-toi que tous les aspects importants de la user story sont couverts.

Format attendu:
Feature: [Titre de la fonctionnalité]

  Scenario: [Titre du scénario 1]
    Given [condition préalable]
    When [action utilisateur]
    Then [résultat attendu]
    And [résultat additionnel si nécessaire]

  Scenario: [Titre du scénario 2]
    Given [condition préalable]
    ...
"""
        else:  # Action/Résultat attendu
            return f"""Voici une user story : "{story_text}"
Génère des cas de test détaillés en français avec les étapes et résultats attendus.
Utilise le format Action/Résultat attendu, en numérotant chaque cas de test.

Format attendu:
# Cas de test 1 : [Titre du cas de test]
## Action
[Description détaillée de l'action utilisateur]

## Résultat attendu
[Description détaillée du résultat attendu]

# Cas de test 2 : [Titre du cas de test]
...
"""
    else:  # Anglais
        if format_choice == "gherkin":
            return f"""Here is a user story: "{story_text}"
As a test assistant, generate test scenarios in Gherkin format (Given/When/Then) in English.
Clearly separate each scenario and ensure all important aspects of the user story are covered.

Expected format:
Feature: [Feature title]

  Scenario: [Scenario 1 title]
    Given [precondition]
    When [user action]
    Then [expected result]
    And [additional result if needed]

  Scenario: [Scenario 2 title]
    Given [precondition]
    ...
"""
        else:  # Action/Expected Result
            return f"""Here is a user story: "{story_text}"
Generate detailed test cases in English with steps and expected results.
Use the Action/Expected Result format, numbering each test case.

Expected format:
# Test Case 1: [Test case title]
## Action
[Detailed description of user action]

## Expected Result
[Detailed description of expected result]

# Test Case 2: [Test case title]
...
"""

def generate_response(prompt, max_tokens=800):
    """
    Envoie le prompt au modèle IA local via l'API LM Studio
    """
    payload = {
        "model": "mistral-7b-instruct-v0.3",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }

    try:
        logger.info(f"Envoi de requête à LM Studio: {API_URL}")
        response = requests.post(API_URL, json=payload, timeout=30)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        logger.error(f"Erreur API LM Studio: {response.status_code} - {response.text}")
        return f"Erreur API : {response.status_code} - {response.text}"
    except Exception as e:
        logger.error(f"Exception lors de l'appel à LM Studio: {str(e)}")
        return f"Erreur LM Studio : {str(e)}"

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
    """
    Endpoint pour générer des cas de test à partir d'une user story
    """
    data = request.get_json()
    story = data.get("story", "").strip()
    format_choice = data.get("format", "gherkin")
    language = data.get("language", "fr")

    if not story:
        return jsonify({"error": "Aucune user story fournie"}), 400

    prompt = build_prompt(story, format_choice, language)
    generated = generate_response(prompt)
    return jsonify({"result": generated})

# Fonction de préparation des données pour la création de tâche JIRA
def prepare_jira_task_data(story, test_cases, format_choice, language):
    """
    Prépare les données pour la création d'une tâche JIRA
    """
    # Définir le titre de la tâche en fonction de la langue
    task_title = "Cas de test: " if language == "fr" else "Test Cases: "
    task_title += story[:50] + "..." if len(story) > 50 else story
    
    # Construire le corps de la description avec mise en forme pour JIRA
    description = {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "User Story: " + story}
                ]
            },
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [
                    {"type": "text", "text": "Tests générés" if language == "fr" else "Generated Test Cases"}
                ]
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "gherkin" if format_choice == "gherkin" else "text"},
                "content": [
                    {"type": "text", "text": test_cases}
                ]
            }
        ]
    }
    
    return task_title, description

# Fonction pour envoyer la requête à l'API JIRA
def send_jira_request(base_url, task_title, description):
    """
    Envoie la requête à l'API JIRA pour créer une tâche
    """
    payload = {
        "fields": {
            "project": {
                "key": JIRA_PROJECT_KEY
            },
            "summary": task_title,
            "description": description,
            "issuetype": {
                "name": "Task"
            }
        }
    }
    
    url = f"{base_url}/rest/api/3/issue"
    headers = {
        "Accept": CONTENT_TYPE_JSON,
        "Content-Type": CONTENT_TYPE_JSON
    }
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    
    response = requests.post(url, json=payload, headers=headers, auth=auth, timeout=10)
    response.raise_for_status()
    return response.json()

@app.route("/api/create-task", methods=["POST"])
def create_jira_task():
    """
    Endpoint pour créer une tâche JIRA contenant les cas de test générés
    """
    data = request.get_json()
    story = data.get("story", "").strip()
    test_cases = data.get("testCases", "").strip()
    format_choice = data.get("format", "gherkin")
    language = data.get("language", "fr")
    client_key = data.get("clientKey")
    
    if not all([story, test_cases, client_key]):
        return jsonify({"error": "Paramètres manquants"}), 400
    
    if client_key not in app_installations:
        # Utiliser les identifiants par défaut si l'installation n'est pas trouvée
        base_url = JIRA_BASE_URL
    else:
        installation = app_installations[client_key]
        base_url = installation["base_url"]
    
    try:
        # Préparer les données de la tâche
        task_title, description = prepare_jira_task_data(story, test_cases, format_choice, language)
        
        # Envoyer la requête à l'API JIRA
        response_data = send_jira_request(base_url, task_title, description)
        
        return jsonify(response_data), 201
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de la création de la tâche JIRA : {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/get-issue")
def get_issue():
    issue_key = request.args.get("key")
    if not issue_key:
        return jsonify({"error": "Clé d'issue manquante"}), 400

    client_key = request.args.get("clientKey")
    if not client_key or client_key not in app_installations:
        return jsonify({"error": "Authentification requise"}), 401

    installation = app_installations.get(client_key)
    base_url = installation.get("base_url")
    
    url = f"{base_url}/rest/api/3/issue/{issue_key}"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": CONTENT_TYPE_JSON}

    try:
        logger.info(f"Récupération de l'issue Jira: {issue_key}")
        res = requests.get(url, headers=headers, auth=auth, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        summary = data["fields"].get("summary", "")
        
        description = ""
        if data["fields"].get("description") and data["fields"]["description"].get("content"):
            for content_item in data["fields"]["description"]["content"]:
                if content_item.get("type") == "paragraph" and content_item.get("content"):
                    for text_item in content_item["content"]:
                        if text_item.get("type") == "text":
                            description += text_item.get("text", "") + "\n"
        
        return jsonify({
            "summary": summary,
            "description": description
        })
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de la récupération de l'issue: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/atlassian-connect.json")
def atlassian_connect():
    return send_from_directory(".", "atlassian-connect.json")

@app.route("/installed", methods=["POST"])
def installed():
    data = request.get_json()
    client_key = data.get("clientKey")
    
    if client_key:
        logger.info(f"Installation pour le client: {client_key}")
        app_installations[client_key] = {
            "client_key": client_key,
            "shared_secret": data.get("sharedSecret"),
            "base_url": data.get("baseUrl"),
            "installed_at": datetime.now().isoformat()
        }
        return "", 204
    else:
        logger.error("Installation sans client key")
        return jsonify({"error": "Client key required"}), 400

@app.route("/uninstalled", methods=["POST"])
def uninstalled():
    data = request.get_json()
    client_key = data.get("clientKey")
    
    if client_key and client_key in app_installations:
        logger.info(f"Désinstallation pour le client: {client_key}")
        del app_installations[client_key]
    
    return "", 204

@app.route("/jira-test-generator", methods=["GET"])
def jira_test_generator():
    issue_key = request.args.get("issueKey")
    client_key = request.args.get("clientKey", "")
    context = {
        "issue_key": issue_key,
        "client_key": client_key
    }
    return render_template(HTML_INDEX, **context)

@app.route("/confluence-test-generator", methods=["GET"])
def confluence_test_generator():
    client_key = request.args.get("clientKey", "")
    context = {
        "issue_key": None,
        "client_key": client_key
    }
    return render_template(HTML_INDEX, **context)

def create_jwt_token(client_key, shared_secret, method, uri):
    now = datetime.now()
    exp = now + timedelta(hours=1)
    
    claims = {
        "iss": "test-generator-app",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "qsh": compute_qsh(method, uri),
        "sub": client_key
    }
    
    return jwt.encode(claims, shared_secret, algorithm="HS256")

def compute_qsh(method, uri):
    canonical_uri = uri.split("?")[0]
    return f"{method}&{canonical_uri}&"

@app.route("/api/add-comment", methods=["POST"])
def add_comment():
    data = request.get_json()
    issue_key = data.get("issueKey")
    comment_text = data.get("comment")
    client_key = data.get("clientKey")
    
    if not all([issue_key, comment_text, client_key]):
        return jsonify({"error": "Paramètres manquants"}), 400
    
    if client_key not in app_installations:
        return jsonify({"error": "Installation non trouvée"}), 404
    
    installation = app_installations[client_key]
    base_url = installation["base_url"]
    
    comment_body = {
        "body": {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "Tests générés automatiquement"}]
                },
                {
                    "type": "codeBlock",
                    "attrs": {"language": "gherkin"},
                    "content": [{"type": "text", "text": comment_text}]
                }
            ]
        }
    }
    
    url = f"{base_url}/rest/api/3/issue/{issue_key}/comment"
    headers = {
        "Accept": CONTENT_TYPE_JSON,
        "Content-Type": CONTENT_TYPE_JSON
    }
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    
    try:
        response = requests.post(url, json=comment_body, headers=headers, auth=auth, timeout=10)
        response.raise_for_status()
        return jsonify({"message": "Commentaire ajouté avec succès"}), 200
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de l'ajout du commentaire : {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)