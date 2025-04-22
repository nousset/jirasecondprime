AP.register({
  'test-generator-dialog': function(dialog) {
    // Récupère le contexte (Jira ou Confluence)
    AP.context.getContext(function(context) {
      const clientKey = context.hostClientKey;
      
      
        if (context?.jira?.issue) { const issueKey = context.jira.issue.key;
        
          // Redirection vers l'endpoint de l'application pour Jira
          dialog.getContentOptions().then(function(options) {
            options.customData = {
              url: `/jira-test-generator?issueKey=${issueKey}&clientKey=${clientKey}`
            };
            dialog.setContent(options);
          });}
        // --- Cas Jira ---
       
        
       else if (context.confluence) {
        // --- Cas Confluence ---
        // Redirection vers l'endpoint de l'application pour Confluence
        dialog.getContentOptions().then(function(options) {
          options.customData = {
            url: `/confluence-test-generator?clientKey=${clientKey}`
          };
          dialog.setContent(options);
        });
      }
    });
  }
});

// Fonction pour ouvrir le dialogue
function openGenerateTestDialog() {
  AP.dialog.create({
    key: 'test-generator-dialog',
    width: '80%',
    height: '80%',
    chrome: true
  });
}

// Initialisation pour Jira
function initJira() {
  // Ajouter un glance dans l'interface JIRA
  AP.jira.addGlance({
    moduleKey: 'test-generator-glance',
    icon: {
      url: '/static/test-icon.png'
    },
    name: {
      value: 'Générateur de tests'
    },
    target: 'jira-issue-glance',
    apiVersion: 1
  });
}

// Initialisation pour Confluence
function initConfluence() {
  // Ajouter un élément dans la barre d'outils de Confluence
  AP.confluence.addContentBylineItem({
    moduleKey: 'test-generator-confluence',
    callback: openGenerateTestDialog,
    label: 'Générateur de tests'
  });
}

// Initialisation en fonction du produit
AP.context.getContext(function(context) {
  if (context.jira) {
    initJira();
    // Écouter l'événement de clic sur le glance
    AP.events.on('jira-issue-glance-click:test-generator-glance', openGenerateTestDialog);
  } else if (context.confluence) {
    initConfluence();
  }
});
