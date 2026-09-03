import sys
sys.path[:0]=['/Users/pablo/Documents/project/2026-08-cogito/cogito/tests','/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts']
from test_feature_multitask import FeatureMultitaskTests
from test_maintenance_corrections import MaintenanceCorrectionTests
from cogito_test_support import git
from cogito_runtime import CogitoError
case=FeatureMultitaskTests()
try:
    repo, wt, store, ranges=case.fixture()
    finding=case.result(store,'T-1',*ranges[0]); finding.update(status='needs-fix',requested_transition='review-fix')
    store.submit_agent_result(finding)
    store.submit_agent_result(case.result(store,'T-2',*ranges[1]))
    store.enter_review_fix()
    store.add_amendment({'id':'TA-review','reason':'review adjustment','added_tasks':[{'id':'T-3','slice_id':'FS-1','paths':['src/a.txt'],'depends_on':['T-2']}]})
    store.update_task('T-3','leased','slice-worker')
    store.update_task('T-3','running','slice-worker')
    base=git(wt,'rev-parse','HEAD')
    git(wt,'commit','--allow-empty','-qm','review fix\n\nCogito-Amendment: TA-review')
    head=git(wt,'rev-parse','HEAD')
    result=case.result(store,'T-3',base,head);result.update(agent_id='slice-worker',role='implementer',requested_transition='verifying');result.pop('reviewed_implementer')
    store.submit_agent_result(result);store.update_task('T-3','complete','slice-worker')
    store.complete_review_fix('TA-review',head)
    evidence=MaintenanceCorrectionTests.check(store,wt,'review-fixed')
    store.complete_verification([evidence])
    store.submit_agent_result(case.result(store,'T-1',*ranges[0]))
    store.submit_agent_result(case.result(store,'T-3',base,head))
    try: store.transition('review-approved',{}); print('FAIL stale T-2 reused')
    except CogitoError as e:print('PASS stale T-2 blocked:',str(e))
    store.submit_agent_result(case.result(store,'T-2',*ranges[1]))
    print('PASS review-fix new + historical tasks:',store.transition('review-approved',{})['state'])
finally:case.doCleanups()
