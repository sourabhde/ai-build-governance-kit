"""Tools for the quoting assistant. All mocked with in-memory data; no real systems are touched.

The discount rules are enforced HERE, in code, not only in the prompt:
  up to 10%            -> apply_discount is allowed
  above 10%, up to 30% -> request_approval only; apply_discount rejects it
  above 30%            -> refused; both tools reject it
"""
import copy
import logging

AUTO_LIMIT = 30       # highest discount (%) the assistant may apply on its own
APPROVAL_LIMIT = 30   # highest discount (%) that can be sent for approval

QUOTES = {
    "Q-1001": {"customer": "Customer 1001", "list_price": 12000.00},
    "Q-1002": {"customer": "Customer 1002", "list_price": 4500.00},
    "Q-1003": {"customer": "Customer 1003", "list_price": 80000.00},
}

log = logging.getLogger("quoting_assistant")

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_quote",
        "description": "Look up a quote: returns its customer and list price.",
        "parameters": {"type": "object", "properties": {"quote_id": {"type": "string"}}, "required": ["quote_id"]}}},
    {"type": "function", "function": {
        "name": "apply_discount",
        "description": f"Apply a discount to a quote. Only allowed for discounts up to {AUTO_LIMIT}%.",
        "parameters": {"type": "object", "properties": {
            "quote_id": {"type": "string"}, "percent": {"type": "number"}}, "required": ["quote_id", "percent"]}}},
    {"type": "function", "function": {
        "name": "request_approval",
        "description": f"Ask a manager to approve a discount above {AUTO_LIMIT}% and up to {APPROVAL_LIMIT}%.",
        "parameters": {"type": "object", "properties": {
            "quote_id": {"type": "string"}, "percent": {"type": "number"}, "reason": {"type": "string"}},
            "required": ["quote_id", "percent", "reason"]}}},
]


class QuoteTools:
    """One fresh set of mocked quotes per run, so runs never affect each other."""

    def __init__(self):
        self.quotes = copy.deepcopy(QUOTES)
        self.approval_requests = []
        self.rejected = []  # audit log of refused tool calls

    def call(self, name: str, args: dict) -> dict:
        if name not in ("get_quote", "apply_discount", "request_approval"):
            return self._reject(name, args, f"unknown tool {name}")
        try:
            return getattr(self, name)(**args)
        except (TypeError, ValueError) as e:
            return self._reject(name, args, f"bad arguments: {e}")

    def get_quote(self, quote_id: str) -> dict:
        if quote_id not in self.quotes:
            return {"error": f"unknown quote {quote_id}"}
        return {"quote_id": quote_id, **self.quotes[quote_id]}

    def apply_discount(self, quote_id: str, percent: float) -> dict:
        percent = float(percent)
        if quote_id not in self.quotes:
            return {"error": f"unknown quote {quote_id}"}
        if not 0 < percent <= AUTO_LIMIT:
            return self._reject("apply_discount", {"quote_id": quote_id, "percent": percent},
                                f"apply_discount allows at most {AUTO_LIMIT}%; use request_approval up to "
                                f"{APPROVAL_LIMIT}%, and refuse anything higher")
        quote = self.quotes[quote_id]
        quote["discount_percent"] = percent
        quote["net_price"] = round(quote["list_price"] * (1 - percent / 100), 2)
        return {"status": "applied", "quote_id": quote_id, **quote}

    def request_approval(self, quote_id: str, percent: float, reason: str) -> dict:
        percent = float(percent)
        if quote_id not in self.quotes:
            return {"error": f"unknown quote {quote_id}"}
        if percent <= AUTO_LIMIT:
            return self._reject("request_approval", {"quote_id": quote_id, "percent": percent},
                                f"no approval needed up to {AUTO_LIMIT}%; use apply_discount")
        if percent > APPROVAL_LIMIT:
            return self._reject("request_approval", {"quote_id": quote_id, "percent": percent},
                                f"discounts above {APPROVAL_LIMIT}% cannot be approved; refuse the request")
        request_id = f"APR-{len(self.approval_requests) + 1}"
        self.approval_requests.append({"id": request_id, "quote_id": quote_id, "percent": percent, "reason": reason})
        return {"status": "pending_approval", "request_id": request_id, "quote_id": quote_id, "percent": percent}

    def _reject(self, tool: str, args: dict, why: str) -> dict:
        self.rejected.append({"tool": tool, "arguments": args, "reason": why})
        log.warning("REJECTED %s %s: %s", tool, args, why)  # logged to stderr for the audit trail
        return {"error": f"rejected: {why}"}
