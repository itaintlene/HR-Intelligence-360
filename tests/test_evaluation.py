"""Quality gates: evaluation metrics must stay above thresholds (regression protection)."""
from hr360.evaluation import evaluate


def test_evaluation_thresholds(ctx):
    m = evaluate(ctx)
    assert m["routing_accuracy"] >= 0.9
    assert m["policy"]["answer_hit_rate"] >= 0.85 and m["policy"]["citation_validity"] >= 0.95
    assert m["policy"]["out_of_scope_refusal_rate"] == 1.0
    assert m["audit"]["precision"] == 1.0 and m["audit"]["recall"] == 1.0
    assert m["document_extraction_field_accuracy"] >= 0.95
