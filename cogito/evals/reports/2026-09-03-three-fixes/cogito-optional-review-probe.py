import sys,json
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['/Users/pablo/Documents/project/2026-08-cogito/cogito/tests','/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts']
import cogito_runtime as runtime
from test_feature_multitask import FeatureMultitaskTests
prepare=runtime.RunStore.prepare_package
verify=runtime.RunStore.complete_verification
def optional(self,draft,*args,**kw):
    draft['checks'][0]['required']=False
    return prepare(self,draft,*args,**kw)
def fake(self,ev,*args,**kw):
    item=dict(ev[0]);target=self.run_dir/'evidence'/'fake-optional.json';item['evidence_path']=str(target);target.write_text(json.dumps(item))
    return verify(self,[item],*args,**kw)
for forged in [False,True]:
    case=FeatureMultitaskTests()
    try:
        with patch.object(runtime.RunStore,'prepare_package',optional):
            if forged:
                with patch.object(runtime.RunStore,'complete_verification',fake):repo,wt,store,ranges=case.fixture()
            else:repo,wt,store,ranges=case.fixture()
        if forged:
            try:store.submit_agent_result(case.result(store,'T-1',*ranges[0]));print('FAIL forged optional accepted')
            except runtime.CogitoError as e:print('PASS forged optional rejected:',e)
        else:
            for i,span in enumerate(ranges,1):store.submit_agent_result(case.result(store,f'T-{i}',*span))
            print('PASS genuine optional-only verification:',store.transition('review-approved',{})['state'])
    finally:case.doCleanups()
