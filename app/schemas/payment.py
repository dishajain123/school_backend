# Payment schemas are co-located in app/schemas/fee.py because Payment is
# tightly coupled to the fee lifecycle (ledger → payment → receipt).
# This file is intentionally left as a re-export shim for any import
# paths that reference app.schemas.payment directly.

from app.schemas.fee import PaymentCreate, PaymentResponse, PaymentListResponse

__all__ = ["PaymentCreate", "PaymentResponse", "PaymentListResponse"]