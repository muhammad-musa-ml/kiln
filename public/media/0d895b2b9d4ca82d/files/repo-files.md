# triage-desk: repository files

Every file in the repository except `README.md` (which is in `README.md` next to this file). Each section heading is the file's path relative to the repository root. Copy each block into place as-is.

## pyproject.toml

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "triage-desk"
version = "0.1.0"
description = "A customer-support triage agent on LangGraph: typed state, tool calling, SQLite checkpoints and human approval for large refunds."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "langgraph==1.2.12",
    "langgraph-checkpoint-sqlite==3.1.1",
    "langchain==1.4.2",
    "langchain-anthropic==1.7.4",
    "python-dotenv==1.2.3",
]

[project.optional-dependencies]
dev = [
    "pytest==9.1.1",
]

[project.scripts]
triage-desk = "triage_desk.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

## .env.example

```dotenv
# Copy this file to .env and fill in the values. .env is git-ignored.
# Never put real keys in this file or in code.

# Required for the live agent (not needed for the tests).
ANTHROPIC_API_KEY=

# Optional settings. The values shown are the defaults.
TRIAGE_MODEL=claude-sonnet-5
REFUND_APPROVAL_THRESHOLD=50
LLM_REQUEST_TIMEOUT_SECONDS=30
NODE_TIMEOUT_SECONDS=45
LLM_MAX_ATTEMPTS=3
CHECKPOINT_DB=data/checkpoints.sqlite
LEDGER_DB=data/ledger.sqlite

# Optional LangSmith tracing. Leave LANGSMITH_TRACING=false to keep everything local.
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=triage-desk
# EU accounts only:
# LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com
```

## .gitignore

```gitignore
# Secrets
.env

# Python
__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.venv/
venv/
.pytest_cache/

# Local data: checkpoints and the refund ledger
data/
*.sqlite
*.sqlite-journal
*.sqlite-shm
*.sqlite-wal
```

## LICENSE

```text
MIT License

Copyright (c) 2026 muhammad-musa-ml

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## src/triage_desk/\_\_init\_\_.py

```python
"""triage-desk: a customer-support triage agent built on LangGraph."""

__version__ = "0.1.0"
```

## src/triage_desk/\_\_main\_\_.py

```python
from triage_desk.cli import main

if __name__ == "__main__":
    main()
```

## src/triage_desk/config.py

```python
"""Runtime settings, read from environment variables.

The CLI loads a .env file first, so anything in .env shows up here too.
"""

import os
from dataclasses import dataclass


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    model: str = "claude-sonnet-5"
    # Refunds strictly above this many dollars pause for a person.
    refund_approval_threshold: float = 50.0
    # HTTP timeout for one request to the model provider.
    llm_request_timeout_s: float = 30.0
    # Hard cap on one attempt of the agent node, whatever it is waiting on.
    node_timeout_s: float = 45.0
    # Attempts for the agent node, including the first one.
    llm_max_attempts: int = 3
    retry_initial_interval_s: float = 1.0
    retry_jitter: bool = True
    checkpoint_db: str = "data/checkpoints.sqlite"
    ledger_db: str = "data/ledger.sqlite"
    # Upper bound on steps in one run, so a model stuck calling tools cannot loop forever.
    recursion_limit: int = 25

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            model=_env_str("TRIAGE_MODEL", defaults.model),
            refund_approval_threshold=_env_float(
                "REFUND_APPROVAL_THRESHOLD", defaults.refund_approval_threshold
            ),
            llm_request_timeout_s=_env_float(
                "LLM_REQUEST_TIMEOUT_SECONDS", defaults.llm_request_timeout_s
            ),
            node_timeout_s=_env_float("NODE_TIMEOUT_SECONDS", defaults.node_timeout_s),
            llm_max_attempts=_env_int("LLM_MAX_ATTEMPTS", defaults.llm_max_attempts),
            checkpoint_db=_env_str("CHECKPOINT_DB", defaults.checkpoint_db),
            ledger_db=_env_str("LEDGER_DB", defaults.ledger_db),
        )
```

## src/triage_desk/state.py

```python
"""The graph's state: what every node can read, and how updates are merged."""

import operator
from typing import Annotated, Literal

from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

Category = Literal["refund", "order_status", "general", "escalate"]


class ReviewRecord(TypedDict):
    """One human decision on one held refund."""

    order_id: str
    amount: float | None
    approved: bool
    reviewer: str
    note: str


class SupportState(TypedDict):
    # add_messages appends new messages (and replaces any with a matching id),
    # so each node returns only the messages it adds.
    messages: Annotated[list[AnyMessage], add_messages]

    # Plain fields: the latest write wins.
    customer_id: str
    category: Category
    order_id: str | None
    escalated: bool
    error: str | None

    # operator.add concatenates lists: an append-only audit trail of approvals.
    review_log: Annotated[list[ReviewRecord], operator.add]
```

## src/triage_desk/store.py

```python
"""A stand-in for the shop's back office: seeded orders, a policy handbook and a
SQLite refund ledger.

Orders are fixed seed data so demos and tests are repeatable. Refunds are written
to SQLite so they survive a restart, keyed by the model's tool-call id: if the same
tool call runs twice (a crash between the refund and the next checkpoint, then a
resume), the second run finds the first refund instead of paying again.
Money is held as integer cents.
"""

import hashlib
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

REFUNDABLE_STATUSES = frozenset({"delivered"})


class OrderError(Exception):
    """The order system refused a request. The message is safe to show the model."""


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    item: str
    amount_paid_cents: int
    status: str
    days_since_delivery: int | None


@dataclass(frozen=True)
class Refund:
    refund_id: str
    order_id: str
    amount_cents: int
    reason: str
    created_at: str


SEED_ORDERS: dict[str, Order] = {
    order.order_id: order
    for order in (
        Order("A1001", "cus_maria", "Wireless headphones", 8900, "delivered", 6),
        Order("A1002", "cus_maria", "Standing desk", 42000, "delivered", 12),
        Order("A1003", "cus_maria", "USB-C cable", 1250, "in_transit", None),
        Order("A1004", "cus_maria", "Coffee grinder", 6400, "delivered", 45),
        Order("B2001", "cus_dev", "Mechanical keyboard", 14900, "delivered", 3),
    )
}

POLICIES: list[tuple[str, str]] = [
    (
        "refund-window",
        "Refund window: delivered items can be refunded in full within 30 days of "
        "delivery. After 30 days, offer store credit instead of a cash refund, or "
        "escalate to a human agent.",
    ),
    (
        "partial-refunds",
        "Partial refunds: for an item that arrived damaged or with parts missing, you "
        "may offer a partial refund of up to 50 percent of the price paid without "
        "asking for a return.",
    ),
    (
        "in-transit",
        "Orders in transit cannot be refunded. Share the tracking status; if the "
        "order is more than 7 days late, escalate to a human agent.",
    ),
    (
        "shipping",
        "Shipping: standard delivery takes 3 to 5 business days after dispatch. "
        "Tracking updates can lag by up to 24 hours.",
    ),
]

_WORD_RE = re.compile(r"[a-z0-9]+")


def to_cents(amount: float | int | str) -> int:
    """Convert a dollar amount from the model into integer cents, rounding half up."""
    try:
        cents = (Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (ArithmeticError, ValueError) as exc:
        raise OrderError(f"{amount!r} is not a valid dollar amount.") from exc
    return int(cents)


def format_cents(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def search_policies(query: str, limit: int = 2) -> str:
    """Return the policies that share the most words with the query."""
    wanted = {word for word in _WORD_RE.findall(query.lower()) if len(word) > 2}
    scored: list[tuple[int, str, str]] = []
    for policy_id, text in POLICIES:
        words = set(_WORD_RE.findall(text.lower())) | set(policy_id.split("-"))
        score = len(wanted & words)
        if score:
            scored.append((score, policy_id, text))
    if not scored:
        return "No matching policy found. If unsure, escalate to a human agent."
    scored.sort(key=lambda item: item[0], reverse=True)
    return "\n".join(f"[{policy_id}] {text}" for _, policy_id, text in scored[:limit])


class ShopStore:
    def __init__(self, ledger_path: str | Path) -> None:
        path = str(ledger_path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # When the graph runs async, ToolNode can run these sync tools on a worker
        # thread, so the connection is shared across threads behind a lock.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS refunds (
                    idempotency_key TEXT PRIMARY KEY,
                    refund_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_order(self, order_id: str, customer_id: str | None) -> Order:
        key = order_id.strip().upper()
        order = SEED_ORDERS.get(key)
        # One message for "does not exist" and "belongs to someone else", so the
        # tool cannot be used to find out which order ids exist.
        if order is None or order.customer_id != customer_id:
            raise OrderError(f"No order {key} found for this customer.")
        return order

    def refunds_for(self, order_id: str) -> list[Refund]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT refund_id, order_id, amount_cents, reason, created_at "
                "FROM refunds WHERE order_id = ? ORDER BY rowid",
                (order_id.strip().upper(),),
            ).fetchall()
        return [Refund(*row) for row in rows]

    def refunded_cents(self, order_id: str) -> int:
        return sum(refund.amount_cents for refund in self.refunds_for(order_id))

    def issue_refund(
        self,
        *,
        order_id: str,
        amount_cents: int,
        reason: str,
        customer_id: str | None,
        idempotency_key: str,
    ) -> tuple[Refund, bool]:
        """Record a refund. Returns (refund, created); created is False if this
        idempotency key was already used, in which case nothing new is paid."""
        order = self.get_order(order_id, customer_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT refund_id, order_id, amount_cents, reason, created_at "
                "FROM refunds WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                return Refund(*row), False

            if amount_cents <= 0:
                raise OrderError("Refund amount must be more than $0.00.")
            if order.status not in REFUNDABLE_STATUSES:
                raise OrderError(
                    f"Order {order.order_id} is {order.status.replace('_', ' ')}; "
                    "only delivered orders can be refunded."
                )
            remaining = order.amount_paid_cents - self.refunded_cents(order.order_id)
            if amount_cents > remaining:
                raise OrderError(
                    f"Refund of {format_cents(amount_cents)} is more than the "
                    f"{format_cents(remaining)} left to refund on order {order.order_id}."
                )

            refund = Refund(
                refund_id="RF-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:8].upper(),
                order_id=order.order_id,
                amount_cents=amount_cents,
                reason=reason.strip() or "no reason given",
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            with self._conn:
                self._conn.execute(
                    "INSERT INTO refunds "
                    "(idempotency_key, refund_id, order_id, amount_cents, reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        idempotency_key,
                        refund.refund_id,
                        refund.order_id,
                        refund.amount_cents,
                        refund.reason,
                        refund.created_at,
                    ),
                )
        return refund, True
```

## src/triage_desk/tools.py

```python
"""Tools the model can call.

They are built around a ShopStore instance so tests can use a throwaway ledger.
ToolRuntime is filled in by ToolNode and is not part of the schema the model sees;
it gives each tool the current state (for the customer id) and its own tool-call id.
"""

import json

from langchain.tools import ToolRuntime, tool

from triage_desk.store import ShopStore, format_cents, search_policies, to_cents

REFUND_TOOL_NAME = "issue_refund"


def make_tools(store: ShopStore) -> list:
    @tool
    def lookup_order(order_id: str, runtime: ToolRuntime) -> str:
        """Look up one of the current customer's orders by id, for example A1001.

        Returns the item, the amount paid, the delivery status, the days since
        delivery and how much has already been refunded.
        """
        order = store.get_order(order_id, runtime.state.get("customer_id"))
        return json.dumps(
            {
                "order_id": order.order_id,
                "item": order.item,
                "amount_paid": format_cents(order.amount_paid_cents),
                "status": order.status,
                "days_since_delivery": order.days_since_delivery,
                "already_refunded": format_cents(store.refunded_cents(order.order_id)),
            }
        )

    @tool
    def search_policy(query: str) -> str:
        """Search the support policy handbook: refund window, partial refunds,
        orders in transit, shipping times."""
        return search_policies(query)

    @tool
    def issue_refund(order_id: str, amount: float, reason: str, runtime: ToolRuntime) -> str:
        """Refund money to the current customer for one of their orders.

        amount is in US dollars. Refunds above the approval threshold are held for
        a human reviewer by the system before this tool runs; do not ask the
        customer to approve anything themselves.
        """
        refund, created = store.issue_refund(
            order_id=order_id,
            amount_cents=to_cents(amount),
            reason=reason,
            customer_id=runtime.state.get("customer_id"),
            idempotency_key=runtime.tool_call_id,
        )
        if not created:
            return (
                f"Refund {refund.refund_id} for {format_cents(refund.amount_cents)} on order "
                f"{refund.order_id} was already issued for this request; nothing new was paid."
            )
        return (
            f"Refund {refund.refund_id} issued: {format_cents(refund.amount_cents)} "
            f"on order {refund.order_id}."
        )

    return [lookup_order, search_policy, issue_refund]
```

## src/triage_desk/nodes.py

```python
"""Node functions and routers.

classify and escalate are plain Python: cheap, predictable and easy to test.
agent is the only node that calls the model. human_review pauses the graph.
"""

import re
from typing import Any, Literal

from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import NodeError
from langgraph.graph import END
from langgraph.types import Command, interrupt

from triage_desk.state import Category, ReviewRecord, SupportState
from triage_desk.tools import REFUND_TOOL_NAME

ESCALATE_RE = re.compile(
    r"\b(chargeback|lawyer|attorney|legal action|fraud"
    r"|(?:speak|talk) to (?:a |an )?(?:human|person|manager))\b",
    re.IGNORECASE,
)
REFUND_RE = re.compile(r"\b(refund\w*|money back|reimburs\w*|return(?:ed|ing)?)\b", re.IGNORECASE)
ORDER_RE = re.compile(r"\b(where is|track\w*|shipp\w*|deliver\w*|arriv\w*|status)\b", re.IGNORECASE)
ORDER_ID_RE = re.compile(r"\b[AB]\d{4}\b", re.IGNORECASE)

SYSTEM_PROMPT = """You are the support assistant for a small online shop.

Customer id: {customer_id}
Triage category of the latest message: {category}
Order id mentioned so far: {order_id}
Refund approval threshold: ${threshold:.2f}

Rules:
- Call lookup_order before discussing or refunding an order. Never guess order details.
- Call search_policy when a policy question comes up, and follow what it says.
- Only call issue_refund when the customer has asked for money back and the policy allows it.
- Refunds above the threshold are held for a human reviewer by the system. If a tool
  result says a refund was rejected, tell the customer plainly and offer what the policy allows.
- If a tool returns an error, explain it in plain words; do not retry with the same arguments.
- Keep replies to two to four sentences.
"""


def message_text(message: AnyMessage) -> str:
    """The text of a message whose content is a string or a list of content blocks."""
    content = message.content
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def last_human_text(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message_text(message)
    return ""


# ---- deterministic nodes -------------------------------------------------------


def classify(state: SupportState) -> dict:
    """Tag the latest customer message with a category and any order id, using rules only."""
    text = last_human_text(state["messages"])
    match = ORDER_ID_RE.search(text)
    order_id = match.group(0).upper() if match else state.get("order_id")

    category: Category
    if ESCALATE_RE.search(text):
        category = "escalate"
    elif REFUND_RE.search(text):
        category = "refund"
    elif ORDER_RE.search(text):
        category = "order_status"
    else:
        category = "general"
    return {"category": category, "order_id": order_id, "escalated": False, "error": None}


def escalate(state: SupportState) -> dict:
    """Hand the conversation to a person. Reached from classify or from the agent's error handler."""
    if state.get("error"):
        text = (
            "Sorry, I cannot finish this right now because of a problem on our side. "
            "I have passed your conversation to a person on the support team, who will reply by email."
        )
    else:
        text = (
            "I have passed this to a person on the support team. "
            "They will read this conversation and reply by email."
        )
    return {"escalated": True, "messages": [AIMessage(content=text)]}


def agent_error_handler(state: SupportState, error: NodeError) -> Command[Literal["escalate"]]:
    """Runs once the agent node has failed for good: retries used up, or an error not worth retrying."""
    return Command(
        goto="escalate",
        update={"error": f"{type(error.error).__name__}: {error.error}"},
    )


# ---- routers --------------------------------------------------------------------


def route_after_classify(state: SupportState) -> Literal["agent", "escalate"]:
    return "escalate" if state["category"] == "escalate" else "agent"


def refund_amount(tool_call: dict) -> float | None:
    try:
        return float(tool_call["args"].get("amount"))
    except (TypeError, ValueError):
        return None


def needs_review(tool_call: dict, threshold: float) -> bool:
    """A refund needs a person if it is above the threshold or its amount cannot be read."""
    if tool_call["name"] != REFUND_TOOL_NAME:
        return False
    amount = refund_amount(tool_call)
    return amount is None or amount > threshold


def make_route_after_agent(threshold: float):
    def route_after_agent(state: SupportState) -> str:
        last = state["messages"][-1]
        tool_calls = last.tool_calls if isinstance(last, AIMessage) else []
        if not tool_calls:
            return END
        if any(needs_review(call, threshold) for call in tool_calls):
            return "human_review"
        return "tools"

    return route_after_agent


# ---- model node -------------------------------------------------------------------


def build_system_prompt(state: SupportState, threshold: float) -> str:
    return SYSTEM_PROMPT.format(
        customer_id=state.get("customer_id") or "unknown",
        category=state.get("category") or "general",
        order_id=state.get("order_id") or "none",
        threshold=threshold,
    )


def make_agent_node(model_with_tools: Any, threshold: float):
    # async so that the node-level TimeoutPolicy applies; LangGraph only enforces
    # node timeouts on async nodes.
    async def agent(state: SupportState) -> dict:
        system = SystemMessage(content=build_system_prompt(state, threshold))
        response = await model_with_tools.ainvoke([system, *state["messages"]])
        return {"messages": [response]}

    return agent


# ---- human in the loop -------------------------------------------------------------


def parse_decision(value: Any) -> tuple[bool, str, str]:
    """Turn the resume value into (approved, reviewer, note). Anything unrecognised is a rejection."""
    if isinstance(value, bool):
        return value, "unknown", ""
    if isinstance(value, dict):
        return (
            value.get("approved") is True,
            str(value.get("reviewer") or "unknown"),
            str(value.get("note") or ""),
        )
    return False, "unknown", f"unrecognised decision {value!r}"


def make_human_review_node(threshold: float):
    def human_review(state: SupportState) -> Command[Literal["tools", "agent"]]:
        # When the graph resumes, LangGraph runs this node again from the top and
        # interrupt() returns the reviewer's answer. So nothing before interrupt()
        # may have side effects; this code only reads the state.
        last = state["messages"][-1]
        held = [call for call in last.tool_calls if needs_review(call, threshold)]
        if not held:
            return Command(goto="tools")

        decision = interrupt(
            {
                "kind": "refund_approval",
                "threshold": threshold,
                "customer_id": state.get("customer_id"),
                "refunds": [
                    {
                        "tool_call_id": call["id"],
                        "order_id": call["args"].get("order_id"),
                        "amount": call["args"].get("amount"),
                        "reason": call["args"].get("reason"),
                    }
                    for call in held
                ],
            }
        )
        approved, reviewer, note = parse_decision(decision)
        records: list[ReviewRecord] = [
            {
                "order_id": str(call["args"].get("order_id")),
                "amount": refund_amount(call),
                "approved": approved,
                "reviewer": reviewer,
                "note": note,
            }
            for call in held
        ]
        if approved:
            return Command(goto="tools", update={"review_log": records})

        # The model's message asked for tools; every one of those calls needs an
        # answer before the model is called again, including any that were not refunds.
        held_ids = {call["id"] for call in held}
        answers = [
            ToolMessage(
                content=(
                    f"REJECTED by reviewer {reviewer}. Note: {note or 'none'}. No money was moved."
                    if call["id"] in held_ids
                    else "Not run: a refund in the same step was rejected. "
                    "Call this tool again if you still need it."
                ),
                tool_call_id=call["id"],
                name=call["name"],
            )
            for call in last.tool_calls
        ]
        return Command(goto="agent", update={"messages": answers, "review_log": records})

    return human_review
```

## src/triage_desk/graph.py

```python
"""Assemble the triage graph.

    START -> classify -> escalate | agent
    agent -> END | tools | human_review
    human_review -> tools (approved) | agent (rejected)
    tools -> agent
    escalate -> END
    agent -- failed for good --> escalate   (error handler)
"""

from typing import Any

import anthropic
from langgraph.errors import NodeTimeoutError
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import RetryPolicy, TimeoutPolicy

from triage_desk.config import Settings
from triage_desk.nodes import (
    agent_error_handler,
    classify,
    escalate,
    make_agent_node,
    make_human_review_node,
    make_route_after_agent,
    route_after_classify,
)
from triage_desk.state import SupportState
from triage_desk.store import ShopStore
from triage_desk.tools import make_tools

TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    NodeTimeoutError,
    TimeoutError,
    ConnectionError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def is_transient(exc: Exception) -> bool:
    """Retry timeouts, dropped connections, rate limits and 5xx responses, nothing else.

    A 400 or a 401 fails the same way every time, and a bug in our own code should
    surface at once rather than after several slow attempts.
    """
    return isinstance(exc, TRANSIENT_ERRORS)


def build_graph(model: Any, store: ShopStore, settings: Settings, checkpointer: Any = None):
    """Build and compile the graph.

    model is a LangChain chat model, or any object with bind_tools(tools) and an
    async ainvoke(messages) (the tests pass a scripted stub).
    """
    tools = make_tools(store)
    threshold = settings.refund_approval_threshold

    builder = StateGraph(SupportState)
    builder.add_node("classify", classify)
    builder.add_node(
        "agent",
        make_agent_node(model.bind_tools(tools), threshold),
        retry_policy=RetryPolicy(
            max_attempts=settings.llm_max_attempts,
            initial_interval=settings.retry_initial_interval_s,
            jitter=settings.retry_jitter,
            retry_on=is_transient,
        ),
        timeout=TimeoutPolicy(run_timeout=settings.node_timeout_s),
        error_handler=agent_error_handler,
    )
    # ToolNode's default only catches invalid arguments from the model and re-raises
    # errors from inside a tool. True sends every tool failure back to the model as
    # a ToolMessage it can explain to the customer.
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    builder.add_node("human_review", make_human_review_node(threshold))
    builder.add_node("escalate", escalate)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", route_after_classify, ["agent", "escalate"])
    builder.add_conditional_edges(
        "agent", make_route_after_agent(threshold), ["tools", "human_review", END]
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("escalate", END)
    # human_review has no static edges: it returns Command(goto=...) to pick tools or agent.

    return builder.compile(checkpointer=checkpointer)
```

## src/triage_desk/model.py

```python
"""The live chat model. Only the CLI imports this; the tests use a stub."""

import os

from langchain_anthropic import ChatAnthropic

from triage_desk.config import Settings


class MissingApiKey(RuntimeError):
    pass


def make_chat_model(settings: Settings) -> ChatAnthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise MissingApiKey(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    # max_retries=0: retries happen in one place, the agent node's RetryPolicy,
    # so the backoff is configured once and every attempt is a separate node run.
    return ChatAnthropic(
        model=settings.model,
        temperature=0,
        max_tokens=1024,
        timeout=settings.llm_request_timeout_s,
        max_retries=0,
    )
```

## src/triage_desk/cli.py

```python
"""Command-line entry point.

    triage-desk chat    [--thread demo] [--customer cus_maria] [--memory]
    triage-desk resume  --thread demo
    triage-desk history --thread demo
    triage-desk graph

The chat loop is synchronous so that Ctrl+C at a prompt stops the program at once.
Graph calls run on one asyncio.Runner, which keeps the SQLite checkpointer's
connection on a single event loop for the whole session.
"""

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from triage_desk.config import Settings
from triage_desk.graph import build_graph
from triage_desk.model import MissingApiKey, make_chat_model
from triage_desk.nodes import message_text
from triage_desk.store import ShopStore

APPROVE_WORDS = {"approve", "approved", "a", "yes", "y"}
REJECT_WORDS = {"reject", "rejected", "r", "no", "n"}


class OfflineModel:
    """Stands in for the model in commands that only read the graph or saved state."""

    def bind_tools(self, tools: list) -> "OfflineModel":
        return self

    async def ainvoke(self, messages: list, *args: Any, **kwargs: Any) -> AIMessage:
        raise RuntimeError("This command does not call the model.")


@asynccontextmanager
async def open_checkpointer(settings: Settings, in_memory: bool) -> AsyncIterator[Any]:
    if in_memory:
        yield InMemorySaver()
        return
    Path(settings.checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db) as checkpointer:
        yield checkpointer


# ---- printing ----------------------------------------------------------------------


def shorten(text: str, limit: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def format_args(args: dict) -> str:
    return ", ".join(f"{key}={value!r}" for key, value in args.items())


def format_amount(amount: Any) -> str:
    if isinstance(amount, (int, float)) and not isinstance(amount, bool):
        return f"${amount:.2f}"
    return repr(amount)


def show_update(node: str, delta: Any) -> None:
    """Print one node's state update as a line of the execution trace."""
    if not isinstance(delta, dict):
        return
    if node == "classify":
        print(f"  [classify] category={delta.get('category')} order={delta.get('order_id') or '-'}")
        return
    for message in delta.get("messages", []):
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                print(f"  [{node}] calls {call['name']}({format_args(call['args'])})")
            text = message_text(message).strip()
            if text:
                print(f"bot> {text}")
        elif isinstance(message, ToolMessage):
            print(f"  [{node}] {message.name} -> {shorten(message_text(message))}")
    for record in delta.get("review_log", []):
        verdict = "APPROVED" if record["approved"] else "REJECTED"
        print(
            f"  [{node}] {verdict} {format_amount(record['amount'])} "
            f"on {record['order_id']} by {record['reviewer']}"
        )
    if delta.get("error"):
        print(f"  [{node}] gave up: {delta['error']}")


def ask_reviewer(payload: dict) -> dict:
    print()
    print("=" * 60)
    print(
        f"APPROVAL NEEDED: refund above {format_amount(payload.get('threshold'))} "
        f"for customer {payload.get('customer_id')}"
    )
    for refund in payload.get("refunds", []):
        print(
            f"  order {refund.get('order_id')}  amount {format_amount(refund.get('amount'))}  "
            f"reason: {refund.get('reason')}"
        )
    print("Type 'approve' or 'reject', optionally followed by a note.")
    print("Or press Ctrl+C: the pause is saved, and 'triage-desk resume' picks it up later.")
    while True:
        verb, _, note = input("reviewer> ").strip().partition(" ")
        if verb.lower() in APPROVE_WORDS:
            return {"approved": True, "note": note.strip(), "reviewer": getpass.getuser()}
        if verb.lower() in REJECT_WORDS:
            return {"approved": False, "note": note.strip(), "reviewer": getpass.getuser()}
        print("Please type approve or reject.")


def announce_tracing() -> None:
    if os.environ.get("LANGSMITH_TRACING", "").strip().lower() != "true":
        return
    if not os.environ.get("LANGSMITH_API_KEY"):
        print(
            "LANGSMITH_TRACING is true but LANGSMITH_API_KEY is empty; no traces will be sent.",
            file=sys.stderr,
        )
        return
    print(f"LangSmith tracing on, project: {os.environ.get('LANGSMITH_PROJECT') or 'default'}")


# ---- running the graph -------------------------------------------------------------


async def stream_turn(graph: Any, payload: Any, config: dict) -> None:
    """Run the graph until it ends or pauses, printing each node's update as it happens.

    payload is new input, a Command(resume=...) answering an interrupt, or None to
    continue from the latest checkpoint after a crash.
    """
    async for update in graph.astream(payload, config, stream_mode="updates"):
        for node, delta in update.items():
            # "__interrupt__" is read from the saved state afterwards instead.
            if not node.startswith("__"):
                show_update(node, delta)


def chat_loop(runner: asyncio.Runner, graph: Any, config: dict, customer_id: str) -> None:
    while True:
        snapshot = runner.run(graph.aget_state(config))
        if snapshot.interrupts:
            decision = ask_reviewer(snapshot.interrupts[0].value)
            runner.run(stream_turn(graph, Command(resume=decision), config))
            continue
        if snapshot.next:
            print(f"Continuing the unfinished run at: {', '.join(snapshot.next)}")
            runner.run(stream_turn(graph, None, config))
            continue

        text = input("you> ").strip()
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            return
        turn = {"messages": [HumanMessage(content=text)], "customer_id": customer_id}
        runner.run(stream_turn(graph, turn, config))


def run_session(args: argparse.Namespace, settings: Settings, must_exist: bool) -> int:
    model = make_chat_model(settings)
    announce_tracing()
    store = ShopStore(settings.ledger_db)
    stack = AsyncExitStack()
    with asyncio.Runner() as runner:
        try:
            checkpointer = runner.run(
                stack.enter_async_context(open_checkpointer(settings, args.memory))
            )
            graph = build_graph(model, store, settings, checkpointer)
            config = {
                "configurable": {"thread_id": args.thread},
                "recursion_limit": settings.recursion_limit,
            }
            snapshot = runner.run(graph.aget_state(config))
            customer_id = args.customer
            if snapshot.values:
                customer_id = snapshot.values.get("customer_id") or customer_id
                saved = len(snapshot.values.get("messages", []))
                print(f"Resuming thread {args.thread}: {saved} messages saved, customer {customer_id}.")
            elif must_exist:
                print(f"No saved thread {args.thread!r} in {settings.checkpoint_db}.", file=sys.stderr)
                return 1
            else:
                print(f"New thread {args.thread} for customer {customer_id}. Type 'quit' to leave.")
            chat_loop(runner, graph, config, customer_id)
        except (KeyboardInterrupt, EOFError):
            print()
            if args.memory:
                print("Stopped. This thread was kept in memory only, so it is gone.")
            else:
                print(f"Stopped. Every completed step is saved in {settings.checkpoint_db}.")
                print(f"Pick up where you left off with:  triage-desk resume --thread {args.thread}")
        except Exception as exc:
            print(f"Run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            if not args.memory:
                print(
                    f"State up to the last completed step is saved. After fixing the cause, run:"
                    f"  triage-desk resume --thread {args.thread}",
                    file=sys.stderr,
                )
            return 1
        finally:
            runner.run(stack.aclose())
            store.close()
    return 0


async def print_history(settings: Settings, store: ShopStore, thread_id: str) -> int:
    async with open_checkpointer(settings, in_memory=False) as checkpointer:
        graph = build_graph(OfflineModel(), store, settings, checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await graph.aget_state(config)
        if not snapshot.values:
            print(f"No saved thread {thread_id!r} in {settings.checkpoint_db}.")
            return 1

        values = snapshot.values
        print(
            f"Thread {thread_id}  customer {values.get('customer_id')}  "
            f"last category {values.get('category')}"
        )
        print("-" * 60)
        for message in values.get("messages", []):
            if isinstance(message, HumanMessage):
                print(f"you>  {message_text(message)}")
            elif isinstance(message, AIMessage):
                for call in message.tool_calls:
                    print(f"      calls {call['name']}({format_args(call['args'])})")
                text = message_text(message).strip()
                if text:
                    print(f"bot>  {text}")
            elif isinstance(message, ToolMessage):
                print(f"tool> {message.name}: {shorten(message_text(message))}")
        print("-" * 60)
        for record in values.get("review_log", []):
            verdict = "approved" if record["approved"] else "rejected"
            print(
                f"review: {verdict} {format_amount(record['amount'])} on {record['order_id']} "
                f"by {record['reviewer']} ({record['note'] or 'no note'})"
            )
        if snapshot.interrupts:
            print(f"Status: paused, waiting for a reviewer. Run: triage-desk resume --thread {thread_id}")
        elif snapshot.next:
            print(
                f"Status: stopped before {', '.join(snapshot.next)}. "
                f"Run: triage-desk resume --thread {thread_id}"
            )
        else:
            print("Status: idle, waiting for the customer's next message.")

        checkpoints = 0
        async for _ in graph.aget_state_history(config):
            checkpoints += 1
        print(f"{checkpoints} checkpoints saved for this thread.")
    return 0


def run_history(args: argparse.Namespace, settings: Settings) -> int:
    store = ShopStore(settings.ledger_db)
    try:
        with asyncio.Runner() as runner:
            return runner.run(print_history(settings, store, args.thread))
    finally:
        store.close()


def run_graph(args: argparse.Namespace, settings: Settings) -> int:
    store = ShopStore(":memory:")
    try:
        graph = build_graph(OfflineModel(), store, settings)
        print(graph.get_graph().draw_mermaid())
    finally:
        store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="triage-desk",
        description="Customer-support triage agent on LangGraph.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    chat = commands.add_parser("chat", help="start or continue a conversation")
    chat.add_argument("--thread", default="demo", help="conversation id; reuse it to continue (default: demo)")
    chat.add_argument("--customer", default="cus_maria", help="customer the agent acts for (default: cus_maria)")
    chat.add_argument("--memory", action="store_true", help="keep checkpoints in memory; nothing survives exit")
    chat.set_defaults(handler=lambda args, settings: run_session(args, settings, must_exist=False))

    resume = commands.add_parser("resume", help="continue a saved thread, including a pending approval")
    resume.add_argument("--thread", required=True)
    resume.set_defaults(
        customer=None,
        memory=False,
        handler=lambda args, settings: run_session(args, settings, must_exist=True),
    )

    history = commands.add_parser("history", help="print a saved thread and its checkpoints")
    history.add_argument("--thread", required=True)
    history.set_defaults(handler=run_history)

    graph = commands.add_parser("graph", help="print the compiled graph as a Mermaid diagram")
    graph.set_defaults(handler=run_graph)
    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    try:
        code = args.handler(args, settings)
    except MissingApiKey as exc:
        print(exc, file=sys.stderr)
        code = 2
    sys.exit(code)
```

## tests/helpers.py

```python
"""Test doubles and small helpers shared by the test modules."""

import asyncio
from dataclasses import dataclass
from typing import Any

from langchain.messages import AIMessage, HumanMessage


@dataclass
class Stall:
    """A scripted step that hangs for this many seconds, to trip the node timeout."""

    seconds: float


class ScriptedModel:
    """Stands in for ChatAnthropic.

    Each call to ainvoke takes the next item from the script: an AIMessage is
    returned, an exception is raised, and a Stall sleeps. Every prompt the graph
    sends is kept in .calls so tests can check what the model saw.
    """

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[list[Any]] = []
        self.bound_tools: list[str] = []

    def bind_tools(self, tools: list) -> "ScriptedModel":
        self.bound_tools = [t.name for t in tools]
        return self

    async def ainvoke(self, messages: list, *args: Any, **kwargs: Any) -> AIMessage:
        self.calls.append(list(messages))
        if not self.script:
            raise AssertionError("ScriptedModel was called more times than scripted")
        step = self.script.pop(0)
        if isinstance(step, Stall):
            await asyncio.sleep(step.seconds)
            return AIMessage(content="(a stalled reply that should never arrive)")
        if isinstance(step, BaseException):
            raise step
        return step


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def reply(text: str) -> AIMessage:
    return AIMessage(content=text)


def large_refund(call_id: str = "call-large") -> AIMessage:
    return tool_call(
        "issue_refund",
        {"order_id": "A1002", "amount": 120, "reason": "desk arrived with a cracked leg"},
        call_id,
    )


def config_for(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


async def say(graph: Any, thread_id: str, text: str, customer_id: str = "cus_maria") -> dict:
    return await graph.ainvoke(
        {"messages": [HumanMessage(content=text)], "customer_id": customer_id},
        config_for(thread_id),
    )
```

## tests/conftest.py

```python
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from helpers import ScriptedModel
from triage_desk.config import Settings
from triage_desk.graph import build_graph
from triage_desk.store import ShopStore


@pytest.fixture
def settings(tmp_path) -> Settings:
    # Fast settings: two attempts, no backoff wait, no jitter, a short node timeout.
    return Settings(
        refund_approval_threshold=50.0,
        llm_max_attempts=2,
        retry_initial_interval_s=0.0,
        retry_jitter=False,
        node_timeout_s=0.5,
        checkpoint_db=str(tmp_path / "checkpoints.sqlite"),
        ledger_db=str(tmp_path / "ledger.sqlite"),
    )


@pytest.fixture
def store(settings):
    shop = ShopStore(settings.ledger_db)
    yield shop
    shop.close()


@pytest.fixture
def make_app(store, settings):
    """Build the real graph around a ScriptedModel and an in-memory checkpointer."""

    def _make(script: list):
        model = ScriptedModel(script)
        graph = build_graph(model, store, settings, InMemorySaver())
        return graph, model

    return _make
```

## tests/test_routing.py

```python
import asyncio

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END

from helpers import reply, say, tool_call
from triage_desk.nodes import classify, make_route_after_agent


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("I want a refund for A1002, the desk wobbles", "refund"),
        ("Where is my order A1003?", "order_status"),
        ("What are your opening hours?", "general"),
        ("Fix this or I will file a chargeback", "escalate"),
        ("Can I speak to a human please", "escalate"),
    ],
)
def test_classify_sets_category(text, category):
    update = classify({"messages": [HumanMessage(content=text)]})
    assert update["category"] == category


def test_classify_extracts_and_keeps_order_id():
    first = classify({"messages": [HumanMessage(content="refund a1001 please")]})
    assert first["order_id"] == "A1001"

    later = classify(
        {"messages": [HumanMessage(content="how long will it take?")], "order_id": "A1001"}
    )
    assert later["order_id"] == "A1001"


route = make_route_after_agent(threshold=50.0)


def state_ending_with(message: AIMessage) -> dict:
    return {"messages": [HumanMessage(content="hi"), message]}


def test_plain_reply_ends_the_run():
    assert route(state_ending_with(reply("Hello!"))) == END


def test_lookup_goes_to_tools():
    message = tool_call("lookup_order", {"order_id": "A1001"}, "c1")
    assert route(state_ending_with(message)) == "tools"


def test_small_refund_goes_to_tools():
    message = tool_call("issue_refund", {"order_id": "A1001", "amount": 20, "reason": "x"}, "c1")
    assert route(state_ending_with(message)) == "tools"


def test_refund_exactly_at_threshold_goes_to_tools():
    message = tool_call("issue_refund", {"order_id": "A1001", "amount": 50, "reason": "x"}, "c1")
    assert route(state_ending_with(message)) == "tools"


def test_refund_above_threshold_goes_to_review():
    message = tool_call("issue_refund", {"order_id": "A1002", "amount": 50.01, "reason": "x"}, "c1")
    assert route(state_ending_with(message)) == "human_review"


def test_unreadable_amount_is_held_for_review():
    message = tool_call("issue_refund", {"order_id": "A1002", "amount": "fifty", "reason": "x"}, "c1")
    assert route(state_ending_with(message)) == "human_review"


def test_one_large_refund_among_several_calls_holds_the_step():
    message = AIMessage(
        content="",
        tool_calls=[
            {"name": "lookup_order", "args": {"order_id": "A1002"}, "id": "c1", "type": "tool_call"},
            {
                "name": "issue_refund",
                "args": {"order_id": "A1002", "amount": 300, "reason": "x"},
                "id": "c2",
                "type": "tool_call",
            },
        ],
    )
    assert route(state_ending_with(message)) == "human_review"


def test_escalation_never_calls_the_model(make_app):
    graph, model = make_app([])
    result = asyncio.run(say(graph, "t-escalate", "I am calling my lawyer about A1002"))

    assert model.calls == []
    assert result["escalated"] is True
    assert isinstance(result["messages"][-1], AIMessage)


def test_model_sees_tools_and_triage_context(make_app):
    graph, model = make_app([reply("Our hours are 9 to 5, Monday to Friday.")])
    asyncio.run(say(graph, "t-context", "Where is my order A1003?"))

    assert model.bound_tools == ["lookup_order", "search_policy", "issue_refund"]
    system = model.calls[0][0]
    assert isinstance(system, SystemMessage)
    assert "order_status" in system.content
    assert "A1003" in system.content


def test_small_refund_runs_without_pausing(make_app, store):
    graph, model = make_app(
        [
            tool_call(
                "issue_refund",
                {"order_id": "A1001", "amount": 20, "reason": "scratched case"},
                "call-small",
            ),
            reply("Done, $20.00 is on its way back to you."),
        ]
    )
    result = asyncio.run(say(graph, "t-small", "Can I get $20 back on A1001? The case is scratched."))

    assert "__interrupt__" not in result
    assert [refund.amount_cents for refund in store.refunds_for("A1001")] == [2000]
    assert result.get("review_log", []) == []
    assert len(model.calls) == 2
```

## tests/test_interrupt.py

```python
import asyncio

from langchain.messages import ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from helpers import ScriptedModel, config_for, large_refund, reply, say
from triage_desk.graph import build_graph

ASK = "The standing desk from A1002 arrived with a cracked leg. I want a refund of $120."


def test_large_refund_pauses_before_any_money_moves(make_app, store):
    graph, _ = make_app([large_refund()])

    async def scenario():
        result = await say(graph, "t-pause", ASK)
        snapshot = await graph.aget_state(config_for("t-pause"))
        return result, snapshot

    result, snapshot = asyncio.run(scenario())

    assert "__interrupt__" in result
    assert snapshot.next == ("human_review",)
    payload = snapshot.interrupts[0].value
    assert payload["kind"] == "refund_approval"
    assert payload["threshold"] == 50.0
    assert payload["refunds"][0]["order_id"] == "A1002"
    assert payload["refunds"][0]["amount"] == 120
    assert store.refunds_for("A1002") == []


def test_approval_resumes_and_pays_once(make_app, store):
    graph, model = make_app([large_refund(), reply("Approved: $120.00 is on its way back.")])
    decision = {"approved": True, "note": "photo checks out", "reviewer": "sam"}

    async def scenario():
        await say(graph, "t-approve", ASK)
        return await graph.ainvoke(Command(resume=decision), config_for("t-approve"))

    result = asyncio.run(scenario())

    assert "__interrupt__" not in result
    assert [refund.amount_cents for refund in store.refunds_for("A1002")] == [12000]
    assert result["review_log"] == [
        {
            "order_id": "A1002",
            "amount": 120.0,
            "approved": True,
            "reviewer": "sam",
            "note": "photo checks out",
        }
    ]
    assert len(model.calls) == 2
    tool_result = model.calls[1][-1]
    assert isinstance(tool_result, ToolMessage)
    assert "issued" in tool_result.content


def test_rejection_goes_back_to_the_model_without_a_refund(make_app, store):
    graph, model = make_app([large_refund(), reply("Sorry, the refund was not approved.")])
    decision = {"approved": False, "note": "no photo yet", "reviewer": "sam"}

    async def scenario():
        await say(graph, "t-reject", ASK)
        return await graph.ainvoke(Command(resume=decision), config_for("t-reject"))

    result = asyncio.run(scenario())

    assert store.refunds_for("A1002") == []
    assert result["review_log"][0]["approved"] is False
    rejection = model.calls[1][-1]
    assert isinstance(rejection, ToolMessage)
    assert rejection.content.startswith("REJECTED")
    assert "no photo yet" in rejection.content
    assert result["messages"][-1].content == "Sorry, the refund was not approved."


def test_unrecognised_resume_value_counts_as_rejection(make_app, store):
    graph, _ = make_app([large_refund(), reply("I could not get that approved.")])

    async def scenario():
        await say(graph, "t-maybe", ASK)
        return await graph.ainvoke(Command(resume="maybe"), config_for("t-maybe"))

    result = asyncio.run(scenario())

    assert store.refunds_for("A1002") == []
    assert result["review_log"][0]["approved"] is False


def test_pause_survives_a_restart(store, settings):
    """Pause on one graph, then resume on a brand-new graph, model and connection."""

    async def scenario():
        async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db) as saver:
            first = build_graph(ScriptedModel([large_refund()]), store, settings, saver)
            await say(first, "t-restart", ASK)

        # What a new process sees: fresh objects, the same SQLite file, the same thread id.
        async with AsyncSqliteSaver.from_conn_string(settings.checkpoint_db) as saver:
            model = ScriptedModel([reply("Your refund has been approved and sent.")])
            second = build_graph(model, store, settings, saver)
            pending = await second.aget_state(config_for("t-restart"))
            result = await second.ainvoke(
                Command(resume={"approved": True, "note": "", "reviewer": "sam"}),
                config_for("t-restart"),
            )
            return pending, result, model

    pending, result, model = asyncio.run(scenario())

    assert pending.next == ("human_review",)
    assert [refund.amount_cents for refund in store.refunds_for("A1002")] == [12000]
    # The new model is asked once, after the refund: the run did not start over.
    assert len(model.calls) == 1
    assert result["messages"][-1].content == "Your refund has been approved and sent."


def test_threads_do_not_share_state(make_app):
    graph, _ = make_app([large_refund(), reply("Our hours are 9 to 5.")])

    async def scenario():
        await say(graph, "t-a", ASK)
        await say(graph, "t-b", "What are your opening hours?")
        return (
            await graph.aget_state(config_for("t-a")),
            await graph.aget_state(config_for("t-b")),
        )

    thread_a, thread_b = asyncio.run(scenario())

    assert thread_a.next == ("human_review",)
    assert thread_b.next == ()
    assert len(thread_b.values["messages"]) == 2
```

## tests/test_reliability.py

```python
import asyncio

from langchain.messages import ToolMessage

from helpers import Stall, reply, say, tool_call


def test_dropped_connection_is_retried(make_app):
    graph, model = make_app([ConnectionError("connection reset"), reply("Hello! How can I help?")])
    result = asyncio.run(say(graph, "t-retry", "hi there"))

    assert len(model.calls) == 2
    assert result["messages"][-1].content == "Hello! How can I help?"
    assert not result.get("escalated")


def test_programming_error_is_not_retried_and_hands_off(make_app):
    graph, model = make_app([ValueError("bad prompt template")])
    result = asyncio.run(say(graph, "t-bug", "hi there"))

    assert len(model.calls) == 1
    assert result["escalated"] is True
    assert "ValueError" in result["error"]


def test_retries_used_up_hands_off(make_app):
    # The test settings allow two attempts.
    graph, model = make_app([ConnectionError("down"), ConnectionError("still down")])
    result = asyncio.run(say(graph, "t-down", "hi there"))

    assert len(model.calls) == 2
    assert result["escalated"] is True
    assert "ConnectionError" in result["error"]


def test_hung_model_call_times_out_then_hands_off(make_app):
    # The test settings cap each agent attempt at 0.5 seconds.
    graph, model = make_app([Stall(5), Stall(5)])
    result = asyncio.run(say(graph, "t-hang", "hi there"))

    assert len(model.calls) == 2
    assert result["escalated"] is True
    assert "NodeTimeoutError" in result["error"]


def test_tool_error_is_reported_to_the_model(make_app):
    graph, model = make_app(
        [
            tool_call("lookup_order", {"order_id": "Z9999"}, "c-missing"),
            reply("I could not find that order."),
        ]
    )
    asyncio.run(say(graph, "t-tool-error", "Where is order Z9999?"))

    tool_result = model.calls[1][-1]
    assert isinstance(tool_result, ToolMessage)
    assert "No order Z9999" in tool_result.content


def test_model_cannot_reach_another_customers_order(make_app, store):
    graph, model = make_app(
        [
            tool_call(
                "issue_refund",
                {"order_id": "B2001", "amount": 10, "reason": "asked nicely"},
                "c-other",
            ),
            reply("I could not find that order on your account."),
        ]
    )
    asyncio.run(say(graph, "t-other", "Refund B2001 please"))

    assert store.refunds_for("B2001") == []
    assert "No order B2001" in model.calls[1][-1].content
```

## tests/test_store.py

```python
import pytest

from triage_desk.store import OrderError, search_policies, to_cents


def test_refund_is_idempotent_per_key(store):
    first, created = store.issue_refund(
        order_id="A1001", amount_cents=2000, reason="scratch", customer_id="cus_maria",
        idempotency_key="call-1",
    )
    again, created_again = store.issue_refund(
        order_id="A1001", amount_cents=2000, reason="scratch", customer_id="cus_maria",
        idempotency_key="call-1",
    )

    assert created is True
    assert created_again is False
    assert again.refund_id == first.refund_id
    assert len(store.refunds_for("A1001")) == 1


def test_refunds_cannot_exceed_what_was_paid(store):
    store.issue_refund(
        order_id="A1001", amount_cents=5000, reason="first", customer_id="cus_maria",
        idempotency_key="call-1",
    )
    with pytest.raises(OrderError, match="left to refund"):
        store.issue_refund(
            order_id="A1001", amount_cents=5000, reason="second", customer_id="cus_maria",
            idempotency_key="call-2",
        )


def test_in_transit_orders_cannot_be_refunded(store):
    with pytest.raises(OrderError, match="in transit"):
        store.issue_refund(
            order_id="A1003", amount_cents=500, reason="late", customer_id="cus_maria",
            idempotency_key="call-1",
        )


def test_orders_are_scoped_to_their_customer(store):
    with pytest.raises(OrderError, match="No order B2001"):
        store.get_order("B2001", "cus_maria")
    assert store.get_order("b2001", "cus_dev").item == "Mechanical keyboard"


@pytest.mark.parametrize(
    ("amount", "cents"),
    [(19.99, 1999), (0.1 + 0.2, 30), ("12.345", 1235), (120, 12000)],
)
def test_to_cents(amount, cents):
    assert to_cents(amount) == cents


def test_to_cents_rejects_nonsense():
    with pytest.raises(OrderError):
        to_cents("fifty")


def test_policy_search_finds_the_refund_window():
    assert "30 days" in search_policies("refund after 30 days")
    assert search_policies("zebra").startswith("No matching policy")
```
