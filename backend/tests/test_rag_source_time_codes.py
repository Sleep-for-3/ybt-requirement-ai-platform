"""Source timestamps must never create business-code conflicts."""
import unittest

from app.services.code_extraction import extract_code_values
from app.services.rag.grounded_answer_service import _answer_status, _evidence_conflicts


class SourceTimeCodeTests(unittest.TestCase):
    def test_datetime_and_clock_are_not_code_values(self):
        for value in ('2024-10-23 16:35:24', '2024-05-31T00:00:00',
                      '2024/10/23 16:35', '2024年10月23日 16:35:24',
                      '提出时间：16:35:24', '2024-10-23T16:35:24.123Z'):
            with self.subTest(value=value):
                self.assertEqual(extract_code_values(value), set())

    def test_business_values_survive_adjacent_datetime(self):
        self.assertEqual(extract_code_values(
            '提出时间2024-10-23 16:35:24；只允许填01，不得填99', affirmative_only=True), {'01'})
        self.assertEqual(extract_code_values('码值01:营销，02:其他'), {'01', '02'})

    def test_unrelated_product_qa_timestamps_do_not_create_conflict(self):
        rows = [dict(knowledge_unit_id=1, authority_rank=5, target_field_code='E010007',
                     content='问题：托收代收产品类别；提出时间：2024-05-31 00:00:00；建议0000-不适用'),
                dict(knowledge_unit_id=2, authority_rank=5, target_field_code='E010007',
                     content='问题：转贷款产品类别；提出时间：2024-10-23 16:35:24；建议6101-其他业务')]
        conflicts = _evidence_conflicts(rows)
        self.assertEqual(conflicts, [])
        for support in (None, {'verification': 'verified'}, {'verification': 'degraded'}):
            actual = _answer_status(invalid_output=False, claim_support=support, cited=True,
                                    declared_unanswerable=bool(conflicts))
            self.assertEqual(actual, 'needs_confirmation' if support and support['verification'] == 'degraded'
                             else 'grounded')

    def test_real_code_conflict_stays_blocked(self):
        rows = [dict(knowledge_unit_id=identity, authority_rank=5, target_field_code='F250007',
                     content=f'时间2024-10-23 16:35:24；合作方式只允许填{code}')
                for identity, code in ((1, '01'), (2, '02'))]
        self.assertTrue(_evidence_conflicts(rows))


if __name__ == '__main__':
    unittest.main()
