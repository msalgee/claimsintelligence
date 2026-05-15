"""Microsoft Foundry Agent Service helpers used by the claimsdemo router.

These wrap the ``azure-ai-projects`` SDK to:
    * lazily build a single ``AIProjectClient`` per process (managed identity);
    * idempotently provision named prompt-based hosted agents on the
      Foundry Project (``ensure_agent``);
    * invoke them via the Responses API and parse a single JSON object
      response (``run_agent_json``).

Three named agents back the demo router:
    * ``claims-entities-extractor``
    * ``claims-recommendation-author``
    * ``claims-outcome-letter-drafter``

All agents are configured with the same ``gpt-5.1`` deployment as the
workflow service. Authentication uses ``DefaultAzureCredential`` end-to-end;
no API keys.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Optional

import requests
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.core.credentials import AccessToken
from azure.identity import DefaultAzureCredential

# Single shared credential — reused across project client + member-policy
# REST lookups so the MI token cache stays warm.
_SHARED_CREDENTIAL = DefaultAzureCredential()
_SEARCH_API_VERSION = "2024-07-01"
_SEARCH_SCOPE = "https://search.azure.com/.default"
_POLICY_NUMBER_RE = re.compile(r"\b[A-Z]{2,5}-AUTO-\d{6}\b", re.IGNORECASE)

# AzureAISearchTool wiring is optional — if the SDK build doesn't expose
# the new tool model classes we silently degrade to retrieval-free agents.
try:  # pragma: no cover - import shape varies by SDK version
    from azure.ai.projects.models import (  # type: ignore
        AISearchIndexResource,
        AzureAISearchQueryType,
        AzureAISearchTool,
        AzureAISearchToolResource,
    )

    _AI_SEARCH_TOOL_AVAILABLE = True
except ImportError:  # pragma: no cover
    AISearchIndexResource = None  # type: ignore[assignment]
    AzureAISearchQueryType = None  # type: ignore[assignment]
    AzureAISearchTool = None  # type: ignore[assignment]
    AzureAISearchToolResource = None  # type: ignore[assignment]
    _AI_SEARCH_TOOL_AVAILABLE = False

logger = logging.getLogger(__name__)


class PolicyGroundingUnavailable(RuntimeError):
    """Raised when the recommendation agent cannot be grounded in policy search."""

# ---------------------------------------------------------------------------
# Singleton project client
# ---------------------------------------------------------------------------

_client_lock = threading.Lock()
_clients: dict[str, AIProjectClient] = {}


def _get_project_client(project_endpoint: str) -> AIProjectClient:
    if not project_endpoint:
        raise RuntimeError("Foundry project endpoint is not configured.")
    with _client_lock:
        cached = _clients.get(project_endpoint)
        if cached is not None:
            return cached
        client = AIProjectClient(
            endpoint=project_endpoint,
            credential=_SHARED_CREDENTIAL,
        )
        _clients[project_endpoint] = client
        return client


# ---------------------------------------------------------------------------
# Agent registry — provisioned once per process, idempotent
# ---------------------------------------------------------------------------

ENTITIES_AGENT = "claims-entities-extractor"
RECOMMENDATION_AGENT = "claims-recommendation-author"
EMAIL_AGENT = "claims-outcome-letter-drafter"

_ENTITIES_INSTRUCTIONS = """You are an insurance claims analyst. Given a
single auto-insurance claim (with a written summary, classified documents,
and business / fraud check results), extract the structured entity model
the adjuster UI requires.

Return ONE JSON object only — no prose, no markdown fences — with exactly
these keys:
{
  "narrative": str,
  "watch_outs": [str],
  "people": [{"name": str, "role": str, "detail": str}],
  "vehicles": [{"description": str, "detail": str}],
  "locations": [{"description": str, "detail": str}],
  "timeline": [{"label": str, "timestamp": str, "detail": str}]
}

Rules:
- Use ONLY information present in the supplied claim context.
- `narrative` is a 3-5 sentence plain-English account of what happened
  (incident, parties, damage, what was filed). Write for a senior adjuster
  glancing at the claim for the first time. No headings, no bullets.
- `watch_outs` is 2-5 short bullet sentences flagging things the adjuster
  should pay attention to: discrepancies between documents, missing
  information, unusual amounts, anything inconsistent with a routine
  loss. If everything is clean, return an empty array.
- Roles must be one of: Claimant, Driver, Witness, Third Party,
  Police Officer, Examining Doctor, Other.
- ISO 8601 for any timestamp you can determine; otherwise echo the source
  text. Never invent dates.
- Be exhaustive on `people`, `vehicles`, `locations`, `timeline`: include
  every entity mentioned across the claim pack, even minor ones (e.g. the
  examining officer, witnesses, the body shop, the impound lot). Aim for
  completeness over brevity — the UI handles long lists fine.
- Output MUST be a single, syntactically valid JSON object. Do NOT include
  literal newline characters inside string values (replace any newline with
  a space). Keep each `detail` string under ~400 characters so the response
  cannot be truncated mid-string."""

_RECOMMENDATION_INSTRUCTIONS = """You are a senior auto insurance claims
adjuster. Given a single claim's summary, fraud + business check results,
and TWO grounding sources, produce an actionable recommendation.

## Two grounding sources (both REQUIRED)

### 1. Member policy snapshot (AUTHORITATIVE — exact match)
A `MEMBER_POLICY_SNAPSHOT` block has been pre-resolved for you from the
member-policies index by exact `policy_number`. Treat it as the single
source of truth for: status (ACTIVE / LAPSED / NOT_FOUND), in-force
window, named insureds, excluded drivers, covered VINs, comprehensive /
collision deductibles per VIN, carrier-specific endorsements, exclusions,
and lienholders.

Rules driven by the member policy snapshot:
- If `status` is `NOT_FOUND` (no matching member-held policy on file) or
    `UNAVAILABLE` (member-policy lookup could not run) — verdict MUST be
    "Investigate further".
- If `status` is `LAPSED` OR the date_of_loss falls outside the
  effective_date / expiration_date window — verdict MUST be
  "Investigate further" and `in_force_at_loss` must be false.
- If a driver listed in the claim is in `excluded_drivers` — verdict
  MUST be "Investigate further" or "Deny" (cite the exclusion).
- An "Approve" or "Approve with conditions" verdict requires:
  `in_force_at_loss == true`, a non-empty `applicable_coverage`, a
  numeric `applicable_deductible >= 0`, and at least ONE entry in
  `policy_excerpts` quoting the snapshot.

### 2. Claims-handling guidance (ADVISORY — use the search tool)
Use the `azure_ai_search` tool to retrieve from the handling-guidance
corpus (claim-type playbooks, SIU referral criteria, total-loss
valuation rules, state amendments, fraud-indicator playbook, etc.). Run
multiple targeted queries spanning the claim type (theft / glass /
collision / weather), state, and any flagged fraud indicators. These
guide HOW you handle the claim; they do NOT prove that the claimant has
coverage, and they do NOT override member-policy facts. Do not apply a
state-specific guidance excerpt unless its state matches the claim / member
policy state.

## Output (return ONE JSON object only — no prose, no markdown fences)

{
  "verdict": "Approve" | "Approve with conditions" | "Investigate further" | "Deny",
  "confidence": float between 0.0 and 1.0,
  "rationale": str (2-4 sentences; cite the policy excerpt sections AND
                    the guidance sections inline),
  "next_actions": [str, ...] (3-6 short imperative actions),
  "member_policy": {
    "policy_number": str,            // echo from snapshot, or "NOT_FOUND"
    "form_version": str,             // e.g. "SHI-AUTO-CO-2025.09" or ""
    "status": "ACTIVE" | "LAPSED" | "NOT_FOUND" | "UNAVAILABLE",
    "in_force_at_loss": bool,
    "applicable_coverage": str,      // e.g. "Comprehensive (Theft)" or ""
    "applicable_deductible": number, // dollar value; 0 if N/A
    "applicable_endorsements": [str],// e.g. ["OEM Parts CM-OEM-08", "Glass CM-GLB-12"]
    "policy_excerpts": [{"section": str, "text": str}]
  },
  "guidance_excerpts": [{"section": str, "source_filename": str, "text": str}]
}

## Quoting rules (apply to BOTH excerpt arrays)
- `text` MUST be a verbatim quote from the source. Do NOT paraphrase.
- `section` is the §-heading or playbook section name from the source.
- `member_policy.policy_excerpts`: 1-3 entries quoting the snapshot's
  Coverage / Endorsement / Exclusion lines that justify the verdict.
    When `status` is `NOT_FOUND` or `UNAVAILABLE`, use an empty array and
    set every other member_policy field to its empty / zero value.
- `guidance_excerpts`: 1-4 entries from `azure_ai_search` results,
  ordered by relevance.

## General rules
- Ground every statement in the supplied context. Do not invent facts.
- If fraud risk is High or any business check failed, prefer
  "Investigate further" or "Deny" unless mitigating context overrides.
- `confidence` reflects your certainty in the verdict given both sources;
    cap at 0.6 when `status` is `NOT_FOUND`, `UNAVAILABLE`, or `LAPSED`."""

_EMAIL_INSTRUCTIONS = """You are an insurance claims correspondence agent.
Given a claim's summary and the adjuster's recommended verdict, draft a
polite, professional outcome letter to the claimant.

Return ONE JSON object only — no prose, no markdown fences — with exactly
these keys:
{
  "subject": str,
  "to": str (claimant email if known, otherwise "claimant@example.com"),
  "body_markdown": str (markdown letter, 3-6 short paragraphs),
  "tone": "approval" | "approval_with_conditions" | "investigation" | "denial"
}

Rules:
- Ground all factual statements in the supplied context.
- If the input contains an "Adjuster decision (locked in step 6)" line,
  that decision is AUTHORITATIVE — the letter's tone and outcome MUST
  match it, even if the upstream verdict line disagrees. Map decisions to
  tone as follows: approve → "approval"; approve_with_conditions →
  "approval_with_conditions"; decline → "denial"; refer_to_siu →
  "investigation".
- The "Adjuster follow-up actions" list contains every next step from the
    recommendation in step 6. Split them into two groups and include BOTH
    in the letter:
    (a) Claimant-facing requests — things the claimant must supply or do.
        Present these as explicit requirements (e.g. under "What we need
        from you" or equivalent natural phrasing).
    (b) Insurer next steps — carrier-internal investigation actions.
        Frame these as commitments by the insurer (e.g. "We will be
        verifying…", "Our team will review…", "We are scheduling…").
        Always include insurer next steps when the verdict is
        "Investigate further" or "Approve with conditions" so the
        claimant understands the investigation process.
- Do not ask the claimant to perform insurer operations such as documenting
    coverage, approving an estimate, notifying a lienholder, monitoring for
    inconsistencies, assigning an adjuster, or updating internal claim notes.
- If an "Adjuster note" is supplied, incorporate its substance into the
  letter (reasoning, conditions, or context) without quoting the
  adjuster directly or revealing that an internal note exists.
- NEVER put the internal claim_id GUID (e.g. "e0104fec-fd0b-4c8a-...") in
  the subject line or anywhere visible to the claimant. The subject must
  reference the claimant by name and the topic (e.g. "Auto claim update
  for Camille Roy — additional information needed").
- If a customer-facing claim number is present in the documents (e.g. a
  field named claim_number, claim_no, or similar starting with letters),
  you may reference that in the body. Never reference the internal GUID.
- If verdict is "Approve with conditions" or "Investigate further", state
    exactly what is required of the claimant.
- If the claimant needs to provide more than one item, format those required
    actions as a Markdown bullet list under a short lead-in sentence. Do not
    bury multiple required actions in one comma- or semicolon-separated sentence."""


_AGENT_SPECS: list[tuple[str, str]] = [
    (ENTITIES_AGENT, _ENTITIES_INSTRUCTIONS),
    (RECOMMENDATION_AGENT, _RECOMMENDATION_INSTRUCTIONS),
    (EMAIL_AGENT, _EMAIL_INSTRUCTIONS),
]

_provision_lock = threading.Lock()
_provisioned: set[str] = set()
_search_conn_cache: dict[str, str] = {}


def _resolve_search_connection_id(
    project_client: AIProjectClient,
    project_endpoint: str,
    connection_name: str,
) -> Optional[str]:
    """Look up the AI Search connection on the Foundry project and cache
    the connection id. Returns None if the connection does not exist or
    the lookup fails — the caller will then provision the recommendation
    agent without retrieval.
    """
    cache_key = f"{project_endpoint}::{connection_name}"
    cached = _search_conn_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        conn = project_client.connections.get(name=connection_name)
        conn_id = getattr(conn, "id", None)
        if conn_id:
            _search_conn_cache[cache_key] = conn_id
            return conn_id
    except Exception:
        logger.error(
            "Foundry project connection %r not found; recommendation agent "
            "will run without policy retrieval.",
            connection_name,
        )
    return None


def _build_search_tools(
    project_client: AIProjectClient,
    project_endpoint: str,
    connection_name: str,
    index_name: str,
) -> Optional[list[Any]]:
    """Build an ``AzureAISearchTool`` list for the recommendation agent if
    the SDK supports it and the connection + index are configured."""
    if not (_AI_SEARCH_TOOL_AVAILABLE and connection_name and index_name):
        return None
    conn_id = _resolve_search_connection_id(
        project_client, project_endpoint, connection_name
    )
    if not conn_id:
        return None
    try:
        return [
            AzureAISearchTool(  # type: ignore[misc]
                azure_ai_search=AzureAISearchToolResource(  # type: ignore[misc]
                    indexes=[
                        AISearchIndexResource(  # type: ignore[misc]
                            project_connection_id=conn_id,
                            index_name=index_name,
                            query_type=AzureAISearchQueryType.SEMANTIC,  # type: ignore[union-attr]
                        )
                    ]
                )
            )
        ]
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to build AzureAISearchTool for index %r; recommendation "
            "agent will run without retrieval.",
            index_name,
        )
        return None


def _ensure_agent(
    project_client: AIProjectClient,
    project_endpoint: str,
    agent_name: str,
    instructions: str,
    model: str,
    tools: Optional[list[Any]] = None,
) -> None:
    """Create the agent version if we have not already provisioned it in
    this process. ``create_version`` is itself idempotent on
    (agent_name, definition) — repeated calls with identical config just
    return the existing version.
    """
    cache_key = f"{project_endpoint}::{agent_name}"
    if cache_key in _provisioned:
        return
    with _provision_lock:
        if cache_key in _provisioned:
            return
        try:
            definition_kwargs: dict[str, Any] = {
                "model": model,
                "instructions": instructions,
            }
            if tools:
                definition_kwargs["tools"] = tools
            project_client.agents.create_version(
                agent_name=agent_name,
                definition=PromptAgentDefinition(**definition_kwargs),
            )
        except Exception:
            logger.exception(
                "Foundry agent provisioning failed for %s.", agent_name
            )
            raise
        _provisioned.add(cache_key)
        logger.info(
            "Foundry agent ensured: %s (model=%s, tools=%d)",
            agent_name,
            model,
            len(tools) if tools else 0,
        )


def ensure_all_agents(
    project_endpoint: str,
    model: str,
    *,
    search_connection_name: str = "",
    search_index_name: str = "",
) -> None:
    """Best-effort provisioning of every demo agent on startup."""
    project_client = _get_project_client(project_endpoint)
    rec_tools = _build_search_tools(
        project_client,
        project_endpoint,
        search_connection_name,
        search_index_name,
    )
    for name, instructions in _AGENT_SPECS:
        try:
            _ensure_agent(
                project_client,
                project_endpoint,
                name,
                instructions,
                model,
                tools=rec_tools if name == RECOMMENDATION_AGENT else None,
            )
        except Exception:  # noqa: BLE001 - non-fatal at startup
            logger.warning(
                "Could not pre-provision agent %s; will retry on first use.",
                name,
            )


# ---------------------------------------------------------------------------
# Agent invocation — Responses API
# ---------------------------------------------------------------------------


def _parse_agent_json(text: str) -> dict[str, Any]:
    """Parse a single JSON object out of the agent's output text. Tolerates
    prose / markdown fences by falling back to the outermost ``{...}``."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            return json.loads(text[start : end + 1])
        raise


def _run_agent_json(
    project_endpoint: str,
    model: str,
    agent_name: str,
    instructions: str,
    user_message: str,
    tools: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """Invoke a Foundry agent via the Responses API and return the
    single JSON object the system prompt enforces.

    Retries once on empty / truncated output (gpt-5.1 occasionally returns a
    JSON body cut off mid-string) and asks the Responses API to constrain the
    output to a JSON object so the model can't wrap it in prose.
    """
    project_client = _get_project_client(project_endpoint)
    _ensure_agent(
        project_client, project_endpoint, agent_name, instructions, model, tools=tools
    )

    openai_client = project_client.get_openai_client()
    # NOTE: when ``agent_reference`` is set, the Foundry Responses surface
    # rejects ``text.format`` (returns 400 ``invalid_payload``: "Not allowed
    # when agent is specified"). We therefore rely on the system prompt to
    # constrain output to JSON and on the retry-once fallback below to
    # absorb the rare truncated-string case.
    extra_body = {
        "agent_reference": {"name": agent_name, "type": "agent_reference"},
    }

    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            response = openai_client.responses.create(
                input=user_message,
                # Generous output cap so long entity / timeline lists don't
                # get truncated mid-string by a low default ceiling.
                max_output_tokens=16000,
                extra_body=extra_body,
            )
        except TypeError:
            # Older openai SDKs don't accept ``max_output_tokens`` as a
            # top-level kwarg — fall back to passing it via extra_body.
            response = openai_client.responses.create(
                input=user_message,
                extra_body={**extra_body, "max_output_tokens": 16000},
            )
        text = (getattr(response, "output_text", "") or "").strip()
        if not text:
            last_exc = RuntimeError(f"Agent {agent_name} returned empty output.")
            logger.warning(
                "Agent %s returned empty output (attempt %d); retrying.",
                agent_name,
                attempt,
            )
            continue
        try:
            return _parse_agent_json(text)
        except json.JSONDecodeError as exc:
            last_exc = exc
            logger.warning(
                "Agent %s returned non-JSON / truncated output (attempt %d): %s",
                agent_name,
                attempt,
                exc,
            )
            continue

    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Claim context — shared by all three callers
# ---------------------------------------------------------------------------


def build_claim_context(
    *,
    claim_id: str,
    documents: list[dict[str, Any]],
    classification: list[dict[str, Any]],
    summary_markdown: Optional[str],
    fraud: Optional[dict[str, Any]],
    business: Optional[list[dict[str, Any]]],
) -> str:
    return json.dumps(
        {
            "claim_id": claim_id,
            "documents": documents,
            "classification": classification,
            "summary_markdown": summary_markdown or "",
            "fraud_check": fraud or {},
            "business_checks": business or [],
        },
        indent=2,
        default=str,
    )


# ---------------------------------------------------------------------------
# Public callers wired to the router
# ---------------------------------------------------------------------------


def extract_entities(
    *, project_endpoint: str, model: str, claim_context: str
) -> dict[str, Any]:
    return _run_agent_json(
        project_endpoint=project_endpoint,
        model=model,
        agent_name=ENTITIES_AGENT,
        instructions=_ENTITIES_INSTRUCTIONS,
        user_message=f"Claim context:\n{claim_context}",
    )


def recommend_outcome(
    *,
    project_endpoint: str,
    model: str,
    claim_context: str,
    search_connection_name: str = "",
    search_index_name: str = "",
    member_policies_endpoint: str = "",
    member_policies_index_name: str = "",
) -> dict[str, Any]:
    """Run the dual-source recommendation agent.

    1. Server-side: scan the claim context for a policy_number and look it
       up by exact match in the member-policies index (REST + MI). The
       resolved snapshot (or ``status: NOT_FOUND``) is injected into the
       agent's user message as a ``MEMBER_POLICY_SNAPSHOT`` block.
    2. Agent-side: ``AzureAISearchTool`` over the claims-handling guidance
       index supplies advisory excerpts.
    """
    project_client = _get_project_client(project_endpoint)
    rec_tools = _build_search_tools(
        project_client,
        project_endpoint,
        search_connection_name,
        search_index_name,
    )
    if not rec_tools:
        raise PolicyGroundingUnavailable(
            "Handling-guidance grounding is unavailable, so no recommendation "
            "was generated. Check the Foundry AI Search connection and the "
            "claims-handling-kb index."
        )

    snapshot = _resolve_member_policy_snapshot(
        claim_context,
        member_policies_endpoint,
        member_policies_index_name,
    )
    user_message = (
        "MEMBER_POLICY_SNAPSHOT (authoritative; pre-resolved by exact "
        "policy_number lookup against the member-policies index):\n"
        f"{json.dumps(snapshot, indent=2, default=str)}\n\n"
        f"Claim context:\n{claim_context}"
    )

    return _run_agent_json(
        project_endpoint=project_endpoint,
        model=model,
        agent_name=RECOMMENDATION_AGENT,
        instructions=_RECOMMENDATION_INSTRUCTIONS,
        user_message=user_message,
        tools=rec_tools,
    )


# ---------------------------------------------------------------------------
# Member-policy snapshot resolver (authoritative source)
# ---------------------------------------------------------------------------


def _search_token() -> str:
    token: AccessToken = _SHARED_CREDENTIAL.get_token(_SEARCH_SCOPE)
    return token.token


def _extract_policy_number(claim_context: str) -> Optional[str]:
    """Pull the first carrier auto-policy number from the claim context.

    Demo policies follow a carrier-prefixed AUTO format such as
    ``NM-AUTO-554301`` or ``SHI-AUTO-708216``. A production lookup would
    walk extracted-document fields by schema; the regex is intentionally
    narrow enough to avoid claim numbers while supporting multiple demo
    carriers.
    """
    match = _POLICY_NUMBER_RE.search(claim_context or "")
    if not match:
        return None
    return match.group(0).upper()


def _resolve_member_policy_snapshot(
    claim_context: str,
    endpoint: str,
    index_name: str,
) -> dict[str, Any]:
    """Look up the member auto-policy by exact policy_number.

    Returns a dict containing either the matching index document
    (``status`` mirrors what the seed step uploaded \u2014 ACTIVE / LAPSED /
    etc.) or a ``NOT_FOUND`` envelope. Network / permission failures
    degrade gracefully to ``UNAVAILABLE`` so the agent can still produce
    an Investigate-further verdict and the demo never silently 500s.
    """
    policy_number = _extract_policy_number(claim_context)
    if not policy_number:
        return {
            "policy_number": "",
            "status": "NOT_FOUND",
            "lookup_note": (
                "No carrier auto-policy number (for example, "
                "SHI-AUTO-708216) found in the "
                "claim context."
            ),
        }
    if not endpoint or not index_name:
        return {
            "policy_number": policy_number,
            "status": "UNAVAILABLE",
            "lookup_note": (
                "Member-policies AI Search index is not configured."
            ),
        }

    # The Search key is a sanitised form of policy_number that mirrors
    # the seed step in claimsdemo.py::_seed_member_policies_index.
    key = re.sub(r"[^A-Za-z0-9_\-=]", "_", policy_number)
    url = (
        f"{endpoint.rstrip('/')}/indexes('{index_name}')/docs('{key}')"
        f"?api-version={_SEARCH_API_VERSION}"
    )
    try:
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {_search_token()}",
                "Accept": "application/json",
            },
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Member-policies REST lookup failed for %s: %s", policy_number, exc
        )
        return {
            "policy_number": policy_number,
            "status": "UNAVAILABLE",
            "lookup_note": f"Lookup error: {exc}",
        }

    if response.status_code == 404:
        return {
            "policy_number": policy_number,
            "status": "NOT_FOUND",
            "lookup_note": (
                "No member policy exists in the member-policies index for "
                f"{policy_number}."
            ),
        }
    if response.status_code != 200:
        logger.warning(
            "Member-policies REST lookup returned %s for %s: %s",
            response.status_code,
            policy_number,
            response.text[:500],
        )
        return {
            "policy_number": policy_number,
            "status": "UNAVAILABLE",
            "lookup_note": (
                f"AI Search returned HTTP {response.status_code}."
            ),
        }

    document = response.json()
    # Trim the ``content`` field so the agent prompt stays under token
    # limits but still has enough quotable text. The full body is in the
    # index for richer follow-on retrieval if/when we move to Foundry IQ.
    content = (document.get("content") or "")[:6000]
    return {
        "policy_number": document.get("policy_number") or policy_number,
        "status": document.get("status") or "ACTIVE",
        "form_version": document.get("form_version") or "",
        "carrier": document.get("carrier") or "",
        "state": document.get("state") or "",
        "effective_date": document.get("effective_date") or "",
        "expiration_date": document.get("expiration_date") or "",
        "named_insureds": document.get("named_insureds") or [],
        "excluded_drivers": document.get("excluded_drivers") or [],
        "vins": document.get("vins") or [],
        "endorsements": document.get("endorsements") or [],
        "source_filename": document.get("source_filename") or "",
        "content": content,
    }


def draft_email(
    *,
    project_endpoint: str,
    model: str,
    claim_context: str,
    verdict: str,
    decision: str | None = None,
    adjuster_note: str | None = None,
    follow_ups: list[str] | None = None,
    decided_by: str | None = None,
) -> dict[str, Any]:
    """Draft an outcome letter.

    When the adjuster has already locked a disposition in step 6, callers
    should pass ``decision`` / ``adjuster_note`` / ``follow_ups`` so the
    letter is grounded in the human-attested decision rather than a fresh
    re-derivation. The block below is wrapped in clear delimiters so the
    model treats it as authoritative over anything implied by the claim
    context alone.
    """
    parts: list[str] = [f"Verdict: {verdict}"]
    if decision:
        parts.append(f"Adjuster decision (locked in step 6): {decision}")
    if decided_by:
        parts.append(f"Decided by: {decided_by}")
    if follow_ups:
        bullet = "\n".join(f"- {item}" for item in follow_ups if item)
        if bullet:
            parts.append(
                "Adjuster follow-up actions from step 6 (categorise each as "
                "claimant-facing OR insurer next step; include BOTH groups in "
                "the letter using appropriate framing):\n"
                f"{bullet}"
            )
    if adjuster_note:
        parts.append(
            "Adjuster note (verbatim — reflect this in the letter; do not "
            f"quote the adjuster directly):\n{adjuster_note}"
        )
    parts.append(f"Claim context:\n{claim_context}")
    return _run_agent_json(
        project_endpoint=project_endpoint,
        model=model,
        agent_name=EMAIL_AGENT,
        instructions=_EMAIL_INSTRUCTIONS,
        user_message="\n\n".join(parts),
    )
