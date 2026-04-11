"""Regression guard for ``configs/grafana/alerting/alerts.yml``.

Grafana provisioning files are loaded and validated only when the Grafana
container (re-)starts — there is no fast feedback loop for YAML breakage
or drift from the unified alerting schema. These tests parse the file
statically and pin the shape of the rule set so a silent edit that would
cause Grafana to reject the file on next startup trips a unit test
failure first.

Pins three invariants:

1. File-level structure: ``apiVersion: 1``, exactly one group named
   ``mlops-alerts`` in folder ``MLOps`` with interval ``1m``.
2. Rule set: exactly 5 rules with the expected uids (3 baseline from
   Phase E-3 and 2 new orchestration trigger failure rules from this
   session, §6-E3-alert-rules).
3. Orchestration rule contracts: the two new rules use the Grafana v8+
   unified alerting two-stage pattern (refId ``A`` Prometheus query +
   refId ``C`` ``__expr__`` threshold), query
   ``orchestration_trigger_failure_total`` with ``increase([5m])`` over
   a window so stale counter history does not perpetually fire, filter
   out the ``error_class="none"`` prime samples, evaluate against a
   strictly-greater-than-zero threshold, and route via the canonical
   ``severity`` label scheme (warning vs critical).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ALERTS_YAML = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "grafana"
    / "alerting"
    / "alerts.yml"
)


@pytest.fixture(scope="module")
def alerts_doc() -> dict:
    """Parse alerts.yml once per module."""
    assert ALERTS_YAML.exists(), f"missing {ALERTS_YAML}"
    with ALERTS_YAML.open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def rules_by_uid(alerts_doc: dict) -> dict[str, dict]:
    groups = alerts_doc["groups"]
    assert len(groups) == 1
    return {r["uid"]: r for r in groups[0]["rules"]}


class TestGrafanaAlertsProvisioning:
    """File-level structure pins."""

    def test_api_version_is_one(self, alerts_doc: dict) -> None:
        assert alerts_doc["apiVersion"] == 1

    def test_single_group_named_mlops_alerts(self, alerts_doc: dict) -> None:
        groups = alerts_doc["groups"]
        assert len(groups) == 1
        g = groups[0]
        assert g["name"] == "mlops-alerts"
        assert g["folder"] == "MLOps"
        assert g["interval"] == "1m"
        assert g["orgId"] == 1

    def test_exactly_five_rules(self, rules_by_uid: dict[str, dict]) -> None:
        assert len(rules_by_uid) == 5

    def test_expected_uids_present(self, rules_by_uid: dict[str, dict]) -> None:
        expected = {
            "drift-score-warning",
            "api-error-rate-critical",
            "api-latency-warning",
            "orchestration-trigger-failure-warning",
            "orchestration-rollback-failure-critical",
        }
        assert set(rules_by_uid.keys()) == expected


class TestOrchestrationTriggerFailureWarning:
    """Pins for the warning-severity rule that covers non-rollback sites."""

    UID = "orchestration-trigger-failure-warning"

    def test_is_warning_severity(self, rules_by_uid: dict[str, dict]) -> None:
        assert rules_by_uid[self.UID]["labels"]["severity"] == "warning"

    def test_condition_refs_threshold_stage(
        self, rules_by_uid: dict[str, dict]
    ) -> None:
        assert rules_by_uid[self.UID]["condition"] == "C"

    def test_nodata_state_is_ok(self, rules_by_uid: dict[str, dict]) -> None:
        assert rules_by_uid[self.UID]["noDataState"] == "OK"

    def test_hold_down_one_minute(self, rules_by_uid: dict[str, dict]) -> None:
        assert rules_by_uid[self.UID]["for"] == "1m"

    def test_query_uses_increase_window(
        self, rules_by_uid: dict[str, dict]
    ) -> None:
        rule = rules_by_uid[self.UID]
        data_stages = {stage["refId"]: stage for stage in rule["data"]}
        query_expr = data_stages["A"]["model"]["expr"]
        # Counter name
        assert "orchestration_trigger_failure_total" in query_expr
        # Window-based semantic so stale history doesn't perpetually fire
        assert "increase(" in query_expr
        assert "[5m]" in query_expr
        # Excludes the error_class="none" prime samples
        assert 'error_class!~"none|"' in query_expr
        # Excludes rollback (covered by the critical rule)
        assert 'trigger_type!="rollback"' in query_expr
        # Multi-dimensional aggregation pins the alert cardinality — swapping
        # to `sum by (job)` alone would silently collapse per-trigger-type
        # instances into one. Guard against that refactor.
        assert "sum by (trigger_type, job)" in query_expr

    def test_threshold_stage_gt_zero(
        self, rules_by_uid: dict[str, dict]
    ) -> None:
        rule = rules_by_uid[self.UID]
        data_stages = {stage["refId"]: stage for stage in rule["data"]}
        stage_c = data_stages["C"]
        assert stage_c["datasourceUid"] == "__expr__"
        model = stage_c["model"]
        assert model["type"] == "threshold"
        assert model["expression"] == "A"
        evaluator = model["conditions"][0]["evaluator"]
        assert evaluator["type"] == "gt"
        assert evaluator["params"] == [0]


class TestOrchestrationRollbackFailureCritical:
    """Pins for the critical-severity rule dedicated to rollback failure."""

    UID = "orchestration-rollback-failure-critical"

    def test_is_critical_severity(self, rules_by_uid: dict[str, dict]) -> None:
        assert rules_by_uid[self.UID]["labels"]["severity"] == "critical"

    def test_condition_refs_threshold_stage(
        self, rules_by_uid: dict[str, dict]
    ) -> None:
        assert rules_by_uid[self.UID]["condition"] == "C"

    def test_nodata_state_is_ok(self, rules_by_uid: dict[str, dict]) -> None:
        # Structural parity with the warning rule — if someone flips one but
        # not the other, the two rules would have divergent "no data" semantics.
        assert rules_by_uid[self.UID]["noDataState"] == "OK"

    def test_hold_down_one_minute(self, rules_by_uid: dict[str, dict]) -> None:
        assert rules_by_uid[self.UID]["for"] == "1m"

    def test_query_filters_rollback_only(
        self, rules_by_uid: dict[str, dict]
    ) -> None:
        rule = rules_by_uid[self.UID]
        data_stages = {stage["refId"]: stage for stage in rule["data"]}
        query_expr = data_stages["A"]["model"]["expr"]
        assert "orchestration_trigger_failure_total" in query_expr
        assert 'trigger_type="rollback"' in query_expr
        assert 'error_class!~"none|"' in query_expr
        assert "increase(" in query_expr
        assert "[5m]" in query_expr
        # Rollback aggregates by job only (no trigger_type dimension since the
        # selector already pins trigger_type="rollback"). Swapping to
        # `sum by (trigger_type, job)` here would double-report the rollback
        # instance across dimensions. Pin the intended cardinality.
        assert "sum by (job)" in query_expr

    def test_threshold_stage_gt_zero(
        self, rules_by_uid: dict[str, dict]
    ) -> None:
        rule = rules_by_uid[self.UID]
        data_stages = {stage["refId"]: stage for stage in rule["data"]}
        evaluator = data_stages["C"]["model"]["conditions"][0]["evaluator"]
        assert evaluator["type"] == "gt"
        assert evaluator["params"] == [0]
