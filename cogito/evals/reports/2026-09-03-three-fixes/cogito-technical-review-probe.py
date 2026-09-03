import sys
from unittest.mock import patch
sys.path[:0]=['/Users/pablo/Documents/project/2026-08-cogito/cogito/tests','/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts']
from test_feature_multitask import FeatureMultitaskTests
from test_maintenance_corrections import MaintenanceCorrectionTests
from cogito_test_support import git
import cogito_runtime as runtime
case=FeatureMultitaskTests();verify=runtime.RunStore.complete_verification
span=[]
def corrected(self,evidence,*args,**kw):
    wt=next(iter(self.load()['tasks'].values()))['worktree']
    self.add_amendment({'id':'TA-tech','reason':'technical adjustment','added_tasks':[{'id':'T-3','slice_id':'FS-1','paths':['src/a.txt'],'depends_on':['T-2']}]})
    self.enter_correction()
    self.update_task('T-3','leased','slice-worker');self.update_task('T-3','running','slice-worker')
    base=git(wt,'rev-parse','HEAD');git(wt,'commit','--allow-empty','-qm','technical fix\n\nCogito-Amendment: TA-tech');head=git(wt,'rev-parse','HEAD');span.extend([base,head])
    result=case.result(self,'T-3',base,head);result.update(agent_id='slice-worker',role='implementer',requested_transition='verifying');result.pop('reviewed_implementer')
    self.submit_agent_result(result);self.update_task('T-3','complete','slice-worker');self.complete_correction('TA-tech',head)
    new_evidence=MaintenanceCorrectionTests.check(self,wt,'tech-fixed')
    return verify(self,[new_evidence],*args,**kw)
try:
    with patch.object(runtime.RunStore,'complete_verification',corrected):repo,wt,store,ranges=case.fixture()
    for i,change in enumerate([*ranges,span],1):store.submit_agent_result(case.result(store,f'T-{i}',*change))
    print('PASS technical-correction historical + new task review:',store.transition('review-approved',{})['state'])
finally:case.doCleanups()
