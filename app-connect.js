AP.register({
  'test-generator-dialog': function(dialog) {
    // Récupère les détails de l'issue Jira ou de la page Confluence
    AP.context.getContext(function(context) {
      if (context.jira) {
        // Contexte Jira
        AP.require('request', function(request) {
          request({
            url: '/rest/api/latest/issue/' + context.jira.issue.key,
            success: function(response) {
              const issue = JSON.parse(response);
              const description = issue.fields.description || '';
              const summary = issue.fields.summary || '';
              const issueKey = issue.key;
              
              // Envoyer les données au dialogue
              dialog.getContentOptions().then(function(options) {
                options.customData = {
                  type: 'jira',
                  issueKey: issueKey,
                  summary: summary,
                  description: description
                };
                return options;
              });
            }
          });
        });
      } else if (context.confluence) {
        // Contexte Confluence
        AP.request({
          url: '/rest/api/content/' + context.confluence.content.id + '?expand=body.storage',
          success: function(response) {
            const page = JSON.parse(response);
            const pageContent = page.body.storage.value || '';
            const pageTitle = page.title || '';
            const pageId = page.id;
            
            // Envoyer les données au dialogue
            dialog.getContentOptions().then(function(options) {
              options.customData = {
                type: 'confluence',
                pageId: pageId,
                pageTitle: pageTitle,
                pageContent: pageContent
              };
              return options;
            });
          }
        });
      }
    });
  }
});

// Handler pour le bouton dans Jira
function openGenerateTestDialog() {
  AP.dialog.create({
    key: 'test-generator-dialog',
    width: '800px',
    height: '600px'
  });
}

// S'exécute quand le glance est cliqué
AP.events.on('jira-issue-glance-clicked', function() {
  openGenerateTestDialog();
});

// S'exécute quand le bouton Confluence est cliqué
AP.events.on('confluence-content-byline-item-clicked', function() {
  openGenerateTestDialog();
});