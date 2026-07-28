from raceintel.knowledge.knowledge_service import KnowledgeService


def test_search_returns_results():
    service = KnowledgeService()

    results = service.search(
        "British Grand Prix"
    )

    assert isinstance(results, dict)