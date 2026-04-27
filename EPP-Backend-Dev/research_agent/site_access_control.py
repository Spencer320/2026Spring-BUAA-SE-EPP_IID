from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from django.db import transaction

from .models import SiteAccessPolicyConfig, SiteAccessRule

DEFAULT_POLICY_MODE = "blacklist"
DEFAULT_POLICY_VERSION = 1


@dataclass(frozen=True)
class SiteAccessDecision:
    allowed: bool
    target_domain: str
    mode: str
    policy_version: str
    rule_hit: str
    reason_code: str
    reason_message: str


def normalize_domain(raw: str) -> str:
    text = (raw or "").strip().lower().rstrip(".")
    if ":" in text:
        text = text.split(":", 1)[0]
    return text


def _normalize_pattern(pattern: str) -> str:
    return normalize_domain(pattern)


def _pattern_match(domain: str, *, match_type: str, pattern: str) -> bool:
    host = normalize_domain(domain)
    rule_pattern = _normalize_pattern(pattern)
    if not host or not rule_pattern:
        return False
    if match_type == "exact":
        return host == rule_pattern
    if match_type == "suffix":
        return host == rule_pattern or host.endswith(f".{rule_pattern}")
    if match_type == "wildcard":
        return fnmatch(host, rule_pattern)
    return False


def _rule_hit_text(rule: SiteAccessRule) -> str:
    return f"site_access:{rule.rule_type}:{rule.match_type}:{rule.pattern}#{rule.rule_id}"


def current_policy() -> SiteAccessPolicyConfig | None:
    return SiteAccessPolicyConfig.objects.order_by("-id").first()


def get_policy_snapshot() -> tuple[str, str]:
    policy = current_policy()
    if policy is None:
        return DEFAULT_POLICY_MODE, str(DEFAULT_POLICY_VERSION)
    mode = policy.mode if policy.mode in {"whitelist", "blacklist"} else DEFAULT_POLICY_MODE
    return mode, str(int(policy.policy_version or DEFAULT_POLICY_VERSION))


def bump_policy_version(*, updated_by: str = "") -> SiteAccessPolicyConfig:
    with transaction.atomic():
        policy = (
            SiteAccessPolicyConfig.objects.select_for_update()
            .order_by("-id")
            .first()
        )
        if policy is None:
            return SiteAccessPolicyConfig.objects.create(
                mode=DEFAULT_POLICY_MODE,
                policy_version=DEFAULT_POLICY_VERSION + 1,
                updated_by=(updated_by or "")[:64],
            )
        policy.policy_version = int(policy.policy_version or DEFAULT_POLICY_VERSION) + 1
        if updated_by:
            policy.updated_by = updated_by[:64]
        policy.save(update_fields=["policy_version", "updated_by", "updated_at"])
        return policy


def evaluate_target_domain(target_domain: str) -> SiteAccessDecision:
    domain = normalize_domain(target_domain)
    mode, policy_version = get_policy_snapshot()
    if not domain:
        return SiteAccessDecision(
            allowed=False,
            target_domain=domain,
            mode=mode,
            policy_version=policy_version,
            rule_hit="site_access:invalid_domain",
            reason_code="SITE_ACCESS_INVALID_DOMAIN",
            reason_message="invalid target domain",
        )

    rules = list(
        SiteAccessRule.objects.filter(is_enabled=True)
        .order_by("priority", "rule_id")
    )

    first_allow: SiteAccessRule | None = None
    first_deny: SiteAccessRule | None = None
    for rule in rules:
        if not _pattern_match(domain, match_type=rule.match_type, pattern=rule.pattern):
            continue
        if rule.rule_type == "deny" and first_deny is None:
            first_deny = rule
        if rule.rule_type == "allow" and first_allow is None:
            first_allow = rule
        if first_allow is not None and first_deny is not None:
            break

    if first_deny is not None:
        return SiteAccessDecision(
            allowed=False,
            target_domain=domain,
            mode=mode,
            policy_version=policy_version,
            rule_hit=_rule_hit_text(first_deny),
            reason_code="SITE_ACCESS_DENIED_RULE",
            reason_message=f"domain denied by rule {first_deny.rule_id}",
        )

    if mode == "whitelist":
        if first_allow is None:
            return SiteAccessDecision(
                allowed=False,
                target_domain=domain,
                mode=mode,
                policy_version=policy_version,
                rule_hit="site_access:whitelist_miss",
                reason_code="SITE_ACCESS_WHITELIST_MISS",
                reason_message="domain not in whitelist",
            )
        return SiteAccessDecision(
            allowed=True,
            target_domain=domain,
            mode=mode,
            policy_version=policy_version,
            rule_hit=_rule_hit_text(first_allow),
            reason_code="SITE_ACCESS_ALLOWED_RULE",
            reason_message=f"domain allowed by rule {first_allow.rule_id}",
        )

    # blacklist mode
    if first_allow is not None:
        return SiteAccessDecision(
            allowed=True,
            target_domain=domain,
            mode=mode,
            policy_version=policy_version,
            rule_hit=_rule_hit_text(first_allow),
            reason_code="SITE_ACCESS_ALLOWED_RULE",
            reason_message=f"domain explicitly allowed by rule {first_allow.rule_id}",
        )
    return SiteAccessDecision(
        allowed=True,
        target_domain=domain,
        mode=mode,
        policy_version=policy_version,
        rule_hit="site_access:blacklist_default_allow",
        reason_code="SITE_ACCESS_ALLOWED_DEFAULT",
        reason_message="domain allowed by default policy",
    )
