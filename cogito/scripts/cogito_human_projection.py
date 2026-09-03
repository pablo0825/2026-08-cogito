"""Append-only human acceptance metadata, projected beside workflow transitions."""
from copy import deepcopy

HUMAN_EVENTS = {
    'human-feedback-queued',
    'human-feedback-recorded', 'human-feedback-classified', 'human-correction-started',
    'human-correction-complete', 'human-correction-verified', 'human-correction-reviewed',
    'human-correction-accepted', 'human-feedback-escalated', 'human-correction-exhausted',
}
HUMAN_POST_EVENTS = {'human-correction-reviewed', 'human-correction-accepted'}


def project_human_metadata(state, event, payload):
    if event == 'human-feedback-recorded':
        pending = [f for f in state.get('human', {}).get('pending_feedback', [])
                   if f['id'] != payload['feedback']['id']]
        state['human'] = {'feedback': deepcopy(payload['feedback']),
                          'binding': deepcopy(payload['binding']), 'triage': None,
                          'resolution': None, 'escalated': False,
                          'feedback_hash': payload['feedback_hash'], 'pending_feedback': pending}
    elif event == 'human-feedback-queued':
        state['human'].setdefault('pending_feedback', []).append(deepcopy(payload['feedback']))
        state['human']['grant_revoked'] = True
    elif event == 'human-feedback-classified':
        state['human']['triage'] = deepcopy(payload['triage'])
    elif event == 'human-correction-started':
        cohort = list(dict.fromkeys([*state['human'].get('cohort_task_ids', []), *payload['task_ids']]))
        state['human'].update(amendment_id=payload['amendment_id'],
                              task_ids=payload['task_ids'], resolution=None,
                              cohort_task_ids=cohort,
                              start_binding=deepcopy(payload['binding']),
                              attempt=state['counters']['human_corrections'])
    elif event == 'human-correction-complete':
        state['human']['resolution'] = deepcopy(payload['resolution'])
        state['human']['completion_binding'] = deepcopy(payload['binding'])
    elif event == 'human-correction-verified':
        state['human']['verification'] = deepcopy(payload)
        for task_id in state['human']['cohort_task_ids']:
            if state['tasks'][task_id]['status'] in {'complete', 'verified'}:
                state['tasks'][task_id]['status'] = 'verified'
    elif event in HUMAN_POST_EVENTS:
        state['human']['decision'] = deepcopy(payload)
        state['human']['binding'] = deepcopy(payload['binding'])
        for task_id in payload['reviews']:
            state['tasks'][task_id]['status'] = 'integrated'
    elif event == 'human-feedback-escalated':
        state['human']['escalated'] = True
        state['human']['escalation_reason'] = payload['reason']
    elif event == 'human-correction-exhausted':
        state['human']['exhausted'] = True
