AP.register({
  'test-generator-dialog': function(dialog) {
    // Récupère le contexte (Jira ou Confluence)
    AP.context.getContext(function(context) {

      if (context.jira) {
        // --- Cas Jira ---
        AP.require('request', function(request) {
          const issueKey = context.jira.issue.key;

          request({
            url: '/rest/api/latest/issue/' + issueKey,
            type: 'GET',
            success: function(response) {
              const issue = JSON.parse(response);
              const description = issue.fields.description || '';
              const summary = issue.fields.summary || '';

              dialog.getContentOptions().then(function(options) {
                options.customData = {
                  type: 'jira',
                  issueKey: issueKey,
                  summary: summary,
                  description: description
                };
                dialog.setContent(options); // 💡 Assure la mise à jour
              });
            },
            error: function(xhr) {
              console.error('Erreur lors de la récupération de l’issue Jira:', xhr);
            }
          });
        });

      } else if (context.confluence) {
        // --- Cas Confluence ---
        const pageId = context.confluence.content.id;

        AP.request({
          url: '/rest/api/content/' + pageId + '?expand=body.storage',
          type: 'GET',
          success: function(response) {
            const page = JSON.parse(response);
            const pageContent = page.body?.storage?.value || '';
            const pageTitle = page.title || '';

            dialog.getContentOptions().then(function(options) {
              options.customData = {
                type: 'confluence',
                pageId: pageId,
                pageTitle: pageTitle,
                pageContent: pageContent
              };
              dialog.setContent(options); // 💡 Assure la mise à jour
            });
          },
          error: function(xhr) {
            console.error('Erreur lors de la récupération de la page Confluence:', xhr);
          }
        });
      }

    });
  }
});

// ✅ Fonction pour ouvrir le dialogue
function openGenerateTestDialog() {
  AP.dialog.create({
    key: 'test-generator-dialog',
    width: '800px',
    height: '600px'
  });
}

// ✅ Gestion des événements
AP.events.on('jira-issue-glance-clicked', openGenerateTestDialog);
AP.events.on('confluence-content-byline-item-clicked', openGenerateTestDialog);
