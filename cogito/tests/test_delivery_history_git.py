"""Final delivery history must contain the claimed preparation and corrections."""

from dataclasses import replace
from pathlib import Path
import tempfile

from cogito_test_support import GitTestCase, git, init_repo
from cogito_common import CogitoError
from cogito_finalization import _validate_commit_history
from cogito_git import GitRepository
from test_finalization_rules import context


class DeliveryHistoryGitTests(GitTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        init_repo(self.repo)
        (self.repo / 'note.txt').write_text('baseline\n')
        git(self.repo, 'add', 'note.txt')
        git(self.repo, 'commit', '-qm', 'baseline')
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        git(self.repo, 'checkout', '-qb', 'codex/unmerged-correction')
        (self.repo / 'note.txt').write_text('unmerged\n')
        git(self.repo, 'commit', '-qam', 'fix: unmerged correction\n\nCogito-Amendment: TA-1')
        self.unmerged = git(self.repo, 'rev-parse', 'HEAD')
        git(self.repo, 'checkout', '-qb', 'codex/delivery', self.base)
        (self.repo / 'note.txt').write_text('delivered\n')
        git(self.repo, 'commit', '-qam', 'fix: delivered correction\n\nCogito-Amendment: TA-1')
        self.correction = git(self.repo, 'rev-parse', 'HEAD')
        (self.repo / 'result.json').write_text('{}\n')
        git(self.repo, 'add', 'result.json')
        git(self.repo, 'commit', '-qm', 'docs: close delivery')
        self.final = git(self.repo, 'rev-parse', 'HEAD')

    def records(self, correction=None, checkpoint=None, enabled=True):
        original = context()
        return replace(original, state={**original.state, 'stage_commits': enabled},
                       events=[{'type': 'stage-committed', 'payload': {'commit_id': checkpoint or self.base}},
                               {'type': 'auto-accept-ready', 'payload': {'delivery_head': self.correction}},
                               {'type': 'agent-result-recorded', 'payload': {'result': {
                                   'role': 'implementer', 'status': 'blocked', 'head_commit': self.unmerged}}}],
                       result={**original.result, 'integration_commits': [self.base],
                               'amendments': [{'id': 'TA-1', 'commit_id': correction or self.correction}]})

    def validate(self, records):
        _validate_commit_history(records, self.final, GitRepository(self.repo).run)

    def test_tagged_but_unmerged_correction_is_rejected(self):
        with self.assertRaises(CogitoError):
            self.validate(self.records(correction=self.unmerged))

    def test_unmerged_preparation_is_rejected(self):
        with self.assertRaises(CogitoError):
            self.validate(self.records(checkpoint=self.unmerged))

    def test_delivered_history_allows_unmerged_blocked_attempt(self):
        self.validate(self.records())

    def test_legacy_ancestry_behavior_is_unchanged(self):
        self.validate(self.records(correction=self.unmerged, checkpoint=self.unmerged, enabled=False))
