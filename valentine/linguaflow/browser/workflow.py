""" Workflow
"""
import logging
from zope.event import notify
from Products.CMFCore.utils import getToolByName
from Products.CMFCore.WorkflowCore import WorkflowException
from Products.CMFPlone import PloneMessageFactory as _
from valentine.linguaflow.events import TranslationObjectUpdate
from DateTime import DateTime
from valentine.linguaflow.browser.topic import syncTopicCriteria as stc

logger = logging.getLogger('valentine.linguaflow')

class WorkflowHistory(object):
    """ Workflow History """

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def histories(self):
        """ Return workflow history of this context.
            Taken from plone_scripts/getWorkflowHistory.py
        """
        context = self.context

        workflow = getToolByName(context, 'portal_workflow')
        pmem = getToolByName(context, 'portal_membership')

        history = {}

        # check if the current user has the proper permissions
        if (pmem.checkPermission('Request review', self.context) or
            pmem.checkPermission('Review portal content', self.context) and
            getToolByName(context,
                          'portal_url').getPortalObject() != context):
            try:
                # get total history with old unused workflows too
                allWorkflows = getattr(context,
                                       'workflow_history',
                                       {}).keys()
                for wfId in allWorkflows:
                    review_history = list(workflow.getInfoFor(
                                                     self.context,
                                                     'review_history',
                                                     [], wfId))

                    for r in review_history:
                        if r['action']:
                            r['transition_title'] = \
                                  workflow.getTitleForTransitionOnType(
                                         r['action'],
                                         self.context.portal_type)
                        else:
                            r['transition_title'] = ''

                        actorid = r['actor']
                        r['actorid'] = actorid
                        if actorid is None:
                            # action performed by an anonymous user
                            r['actor'] = {
           'username': _(u'label_anonymous_user', default=u'Anonymous User')}
                            r['actor_home'] = ''
                        else:
                            r['actor'] = pmem.getMemberInfo(actorid)
                            if r['actor'] is not None:
                                r['actor_home'] = '/author/' + actorid
                            else:
                                # member info is not available
                                # the user was probably deleted
                                r['actor_home'] = ''
                    review_history.reverse()
                    history[wfId] = review_history

            except WorkflowException:
                logger.info('valentine.linguaflow: %s has no associated '
                            'workflow', self.context.absolute_url())
        return history

class LinguaflowInvalidateAll(object):
    """ Called by invalidate all transition in lingua flow. Here we redistribute
        invalidate translation to each translation. """

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context = self.context
        comment = self.request.get('comment',
                                   'Invalidate all translations initiated.')
        context.invalidateTranslations(comment)
        cUpdate = TranslationObjectUpdate(context,
                                          context,
                                          'nochange',
                                          comment=comment)
        notify(cUpdate)
        self.request.RESPONSE.redirect(context.absolute_url())

class LinguaflowValidateAll(object):
    """ Called by validate all transition in lingua flow. Here we redistribute
        validate translation to each translation. """

    def __init__(self, context, request):
        self.context = context.getCanonical()
        self.request = request

    def __call__(self):
        context = self.context
        comment = self.request.get('comment',
                                   'Validate all translations initiated.')
        translations = context.getNonCanonicalTranslations()
        for lang in translations.keys():
            translation = translations[lang][0]
            cUpdate = TranslationObjectUpdate(context,
                                              translation,
                                              'validate',
                                              comment=comment)
            notify(cUpdate)
        self.request.RESPONSE.redirect(context.absolute_url())

class SyncWorkflow(object):
    """ Sync Workflow """

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.languages = request.get('languages', [])

    def __call__(self):
        comment = self.request.get('comment', 'Sync workflow state')
        expirationDate = self.request.get('syncExpirationDate', None)
        effectiveDate = self.request.get('syncEffectiveDate', None)
        syncLocalRoles = self.request.get('syncLocalRoles', False)
        syncWorkflowState = self.request.get('syncWorkflowState', False)
        syncTopicCriteria = self.request.get('syncTopicCriteria', False)
        self.sync(syncWorkflowState,
                  effectiveDate,
                  expirationDate,
                  syncLocalRoles,
                  syncTopicCriteria,
                  comment=comment)
        self.request.RESPONSE.redirect(self.context.absolute_url() + \
                                       '/manage_translations_form')

    def updateRoleMappings(self, wf_tool, wf_id, translation):
        """ Update Role Mappings """
        wf_tool.getWorkflowById(wf_id).updateRoleMappingsFor(translation)

    def sync(self, syncWorkflowState=False, syncEffectiveDate=None,
             syncExpirationDate=None, syncLocalRoles=False,
             syncTopicCriteria=False, comment=''):
        """ Sync """
        if not (syncWorkflowState or syncEffectiveDate or
                syncExpirationDate or syncLocalRoles or syncTopicCriteria):
            return

        context = self.context.getCanonical()
        wf = getToolByName(context, 'portal_workflow')
        wf_id = wf.getChainFor(context)[0]
        canonical_state = wf.getInfoFor(context, 'review_state')
        last_transition = wf.getHistoryOf(wf_id, context)[-1]
        last_transition['comments'] = comment
        last_transition['actor'] = getToolByName(context,
                        'portal_membership').getAuthenticatedMember().getId()
        last_transition['time'] = DateTime()
        translations = context.getNonCanonicalTranslations()
        expirationDate = syncExpirationDate and context.getExpirationDate()
        effectiveDate = syncEffectiveDate and context.getEffectiveDate()
        local_roles = context.get_local_roles()
        for lang in self.languages:
            if lang in translations.keys():
                translation = translations[lang][0]
                if syncWorkflowState:
                    translation_state = wf.getInfoFor(translation,
                                                      'review_state')
                    if canonical_state != translation_state:
                        translation_history = \
                                   list(translation.workflow_history[wf_id])
                        translation_history.append(last_transition)
                        translation.workflow_history[wf_id] = \
                                   tuple(translation_history)
                        self.updateRoleMappings(wf, wf_id, translation)

                    if effectiveDate is not None:
                        translation.setEffectiveDate(effectiveDate)

                    if expirationDate is not None:
                        translation.setExpirationDate(expirationDate)

                if syncLocalRoles:
                    existingRoles = \
                      [tid for tid, roles in translation.get_local_roles()]
                    if existingRoles:
                        translation.manage_delLocalRoles(existingRoles)
                    for userid, roles in local_roles:
                        translation.manage_setLocalRoles(userid, roles)

                if syncTopicCriteria:
                    stc(context, translation)

                translation.reindexObject()
