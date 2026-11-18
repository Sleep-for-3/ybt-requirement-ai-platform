"""Deterministic identifiers follow their local clause's citation scope."""
import unittest

from app.services.rag.grounded_answer_service import _identifier_gaps


class IdentifierBindingTests(unittest.TestCase):
    def check(self, answer, evidence, expected):
        citations = [{'knowledge_unit_id': identity, 'quoted_content': body}
                     for identity, body in evidence.items()]
        self.assertEqual(_identifier_gaps(answer, [], citations), expected)

    def test_trailing_citation_covers_semicolon_list(self):
        self.check('码值为01 营销、02 贷款；其他填03 [1]。',
                   {1: '码值01营销、02贷款、03其他'}, [])

    def test_semicolon_inside_numeric_example_keeps_binding(self):
        self.check('机构曾建议将码值拼接（如01;03），反馈为多行填报 [1]。',
                   {1: '建议码值01;03；反馈多行填报'}, [])

    def test_compound_claims_keep_their_original_citation(self):
        self.check('填报规则分别为：只能填01、另项应填02 [1]。',
                   {1: '只能填01；另项应填02'}, [])

    def test_numeric_semicolon_cannot_hide_an_unsupported_list_value(self):
        self.check('机构建议码值01;03 [1]。', {1: '机构建议码值01'}, ['03'])

    def test_explicit_cross_citations_cannot_borrow(self):
        self.check('字段F250007应填01 [1]；字段E010001应填02 [2]。',
                   {1: 'E010001应填02', 2: 'F250007应填01'},
                   ['01', '02', 'E010001', 'F250007'])

    def test_unreferenced_sentence_cannot_borrow_later_evidence(self):
        self.check('只能填99。另一个场景只能填01 [1]。',
                   {1: '只能填99；只能填01'}, ['99'])

    def test_unknown_explicit_id_cannot_be_replaced_by_later_valid_id(self):
        self.check('只能填99 [999]；只能填01 [1]。',
                   {1: '只能填99；只能填01'}, ['99'])

    def test_prohibitions_still_need_local_support(self):
        self.check('不得填01、02；只能填03 [1]。',
                   {1: '不得填01；只能填03'}, ['02'])

    def test_citation_immediately_after_sentence_punctuation_is_local(self):
        self.check('字段F190008按归档填报。[1]', {1: '字段F190008按归档填报'}, [])
        self.check('字段F190008填01。 [1][2]',
                   {1: '字段F190008', 2: '填01'}, [])

    def test_post_punctuation_citations_do_not_borrow_between_sentences(self):
        self.check('字段F190008填01。[1] 字段E010001填02。[2]',
                   {1: '字段E010001填02', 2: '字段F190008填01'},
                   ['01', '02', 'E010001', 'F190008'])

    def test_next_paragraph_citation_does_not_bind_previous_sentence(self):
        self.check('字段F190008填01。\n[1]其他说明。',
                   {1: '字段F190008填01'}, ['01', 'F190008'])

    def test_declared_claim_with_post_punctuation_citation_uses_local_source(self):
        citations = [{'knowledge_unit_id': 1, 'quoted_content': '字段F190008按归档填报'}]
        self.assertEqual(_identifier_gaps('', ['字段F190008按归档填报。[1]'], citations), [])


if __name__ == '__main__':
    unittest.main()
