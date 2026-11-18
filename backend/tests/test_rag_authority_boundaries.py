"""Malformed and mixed provenance cannot promote answer authority."""
import pytest

from app.services.rag.grounded_answer_service import _effective_authority_rank, _trust


@pytest.mark.parametrize('value', [float('inf'), -float('inf'), float('nan'), True, '6', None, -1])
def test_invalid_authority_values_fail_closed(value):
    assert _effective_authority_rank({'authority_rank': value}) == 0


@pytest.mark.parametrize('category', ['unknown', 'unregistered', 'REGULATORY_UNKNOWN'])
def test_explicit_unknown_category_cannot_claim_formal_authority(category):
    assert _effective_authority_rank({'source_category': category, 'authority_rank': 6}) == 0


def test_legacy_missing_category_keeps_bounded_numeric_diagnostic():
    assert _effective_authority_rank({'authority_rank': 6}) == 6
    assert _effective_authority_rank({'authority_rank': 999999}) == 6


def supported_summary():
    return dict(verification='verified', unsupported_count=0, unknown_count=0,
                unjudged_count=0, coverage=1.0)


def test_mixed_cited_sources_cannot_receive_formal_only_grade():
    citations = [dict(knowledge_unit_id=i, source_category=category, authority_rank=6,
                      locator={'block_id': f'unit-{i}'})
                 for i, category in [(1, 'regulatory_formal'), (2, 'technical_evidence')]]
    trust = _trust(citations, citations, [], {'formal_index_current': True},
                   'normal', supported_summary())
    assert trust['grade'] == 'C'
    assert trust['dimensions']['authority']['level'] == 1


def test_citation_metadata_cannot_overwrite_weaker_governed_item():
    item = dict(knowledge_unit_id=1, source_category='technical_evidence', authority_rank=1)
    citation = dict(knowledge_unit_id=1, source_category='regulatory_formal', authority_rank=6,
                    locator={'block_id': 'unit-1'})
    trust = _trust([item], [citation], [], {'formal_index_current': True},
                   'normal', supported_summary())
    assert trust['grade'] == 'C'


def test_locator_only_citation_can_use_its_governed_item_metadata():
    item = dict(knowledge_unit_id=1, source_category='regulatory_formal', authority_rank=6)
    citation = dict(knowledge_unit_id=1, locator={'block_id': 'unit-1'})
    trust = _trust([item], [citation], [], {'formal_index_current': True},
                   'normal', supported_summary())
    assert trust['grade'] == 'A'
