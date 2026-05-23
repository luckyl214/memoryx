"""P3: Eval metrics tests."""

from __future__ import annotations

from memoryx.eval.metrics import EvalSuite, EvalResult, evaluate_query


def test_recall_perfect():
    result = evaluate_query(["a", "b", "c"], {"a", "b", "c"}, k_values=(3, 5))
    assert result.recall_at_k[3] == 1.0
    assert result.recall_at_k[5] == 1.0


def test_recall_partial():
    result = evaluate_query(["a", "b", "c"], {"a", "d", "e"}, k_values=(3, 5))
    assert result.recall_at_k[3] == 1.0 / 3.0


def test_precision():
    result = evaluate_query(["a", "b"], {"a", "c"}, k_values=(2,))
    assert result.precision_at_k[2] == 0.5


def test_mrr_first():
    result = evaluate_query(["a", "b", "c"], {"a"})
    assert result.mrr == 1.0


def test_mrr_third():
    result = evaluate_query(["a", "b", "c"], {"c"})
    assert result.mrr == 1.0 / 3.0


def test_mrr_miss():
    result = evaluate_query(["a", "b"], {"x"})
    assert result.mrr == 0.0


def test_ndcg_perfect():
    result = evaluate_query(["a", "b", "c"], {"a", "b", "c"}, k_values=(3,))
    assert result.ndcg_at_k[3] == 1.0


def test_ndcg_partial():
    result = evaluate_query(["a", "x", "b"], {"a", "b"}, k_values=(3,))
    # a at rank 1 (gain=1), x at rank 2 (gain=0), b at rank 3 (gain=1)
    # dcg = 1 + 0 + 1/log2(4) = 1.5
    # idcg = 1 + 1 + 1/log2(4) = 1.5
    assert 0.9 < result.ndcg_at_k[3] <= 1.0


def test_eval_suite_mean():
    r1 = EvalResult(query="q1", recall_at_k={5: 1.0, 10: 1.0}, mrr=1.0)
    r2 = EvalResult(query="q2", recall_at_k={5: 0.5, 10: 0.8}, mrr=0.5)
    suite = EvalSuite(results=[r1, r2])
    assert suite.mean("recall_at_k", 5) == 0.75
    assert suite.mean("mrr", 0) == 0.75  # mrr is a scalar
