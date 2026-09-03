from pathlib import Path
import sys,subprocess,unittest
sys.path.insert(0,str(Path('cogito/tests').resolve()))
from test_maintenance_multitask import MaintenanceMultitaskTests
from unittest.mock import patch
original=subprocess.run
watch=[None]
def run(*args,**kwargs):
    index=watch[0]
    before=index.read_bytes() if index and index.exists() else None
    result=original(*args,**kwargs)
    if before is not None and index.read_bytes()!=before:
        print('INDEX MUTATION',args,kwargs.get('env',{}).get('GIT_INDEX_FILE'),flush=True)
    return result
old=MaintenanceMultitaskTests.assert_rejected_without_mutation
def wrapped(self,repo,*args,**kwargs):
    watch[0]=repo/'.git/index'
    try:return old(self,repo,*args,**kwargs)
    finally:watch[0]=None
suite=unittest.TestSuite(MaintenanceMultitaskTests('test_second_task_cannot_modify_first_task_path_declared_or_omitted') for _ in range(30))
with patch.object(MaintenanceMultitaskTests,'assert_rejected_without_mutation',wrapped),patch('subprocess.run',run):
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(not result.wasSuccessful())
