"""One refusal shape, and the argument for why every refusal wears it.

The largest design risk in Stage 5 is that a REST instinct collapses three different
outcomes onto 4xx and 5xx. This project's whole value is that it distinguishes them:

* a **panel that breaks the input contract** is rejected, and the column is named;
* a **descent to Mode B** is a completed assessment carrying its receipts, not an error;
* **infrastructure failing** is the job's status, with a cause, and never a stack trace.

Only the first and third are refusals at all. The second one is content, and nothing in
this module touches it — that is the point of writing them down together.

**Why one body for everything, including FastAPI's own validation errors.** A client
that has to parse two error shapes will parse one of them and guess at the other.
FastAPI's default 422 is a bare ``{"detail": [...]}`` list, so it is re-shaped here into
the same envelope as everything else. The cost is one handler; the alternative is that
the shape a client meets depends on which layer refused them.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from roadrisk.core.errors import ContractViolation, RoadRiskError
from roadrisk.store import InUse, NotFound, PayloadRejected

log = logging.getLogger("roadrisk.api")

#: Written as numbers rather than as Starlette's named constants.
#:
#: Starlette renamed both of these to follow RFC 9110 — 422 from *Unprocessable Entity*
#: to *Unprocessable Content*, 413 from *Request Entity Too Large* to *Content Too
#: Large* — and now warns on the old spellings while older releases do not have the new
#: ones. The status code is the contract; the constant's name is not, and this package
#: should not emit a deprecation warning per refusal for the privilege of spelling it.
HTTP_422 = 422
HTTP_413 = 413


class ErrorCode(StrEnum):
    """What kind of refusal this is, as something a client can branch on.

    Codes rather than status alone, because 422 is doing two jobs — a malformed request
    body and a panel that breaks the input contract are both 422 and are not the same
    problem. A client retries the first after fixing its JSON and the second after
    fixing its data.
    """

    #: No `X-Tenant-Id`. Every row in this system belongs to one.
    TENANT_REQUIRED = "tenant_required"
    #: The request body or path did not parse. FastAPI's own validation, re-shaped.
    INVALID_REQUEST = "invalid_request"
    #: The panel breaks the input contract. `roadrisk.core.errors.ContractViolation`.
    CONTRACT_VIOLATION = "contract_violation"
    #: A run payload does not conform to `roadrisk.contract`.
    PAYLOAD_REJECTED = "payload_rejected"
    #: No such row, for this tenant. Says nothing about whether it exists for another.
    NOT_FOUND = "not_found"
    #: The delete would have taken other rows with it.
    IN_USE = "in_use"
    #: The artefact is recorded but this server will not serve it. See the message.
    ARTEFACT_UNAVAILABLE = "artefact_unavailable"
    #: The request is larger than this deployment accepts.
    TOO_LARGE = "too_large"
    #: The engine or the registry refused for a reason of its own.
    ENGINE_REFUSED = "engine_refused"
    #: Something broke. The cause is logged; the client gets a reference, not a trace.
    INTERNAL = "internal"


class FieldError(BaseModel):
    """One thing wrong with the request, and where."""

    model_config = ConfigDict(extra="forbid")

    location: str = Field(description="Dotted path into the request, e.g. 'body.name'.")
    message: str


class Refusal(BaseModel):
    """Why the request was refused, in the terms the caller can act on."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(
        description="Written for a person. Names the column, the id or the setting."
    )
    field: str | None = Field(
        default=None, description="The single thing at fault, when there is one."
    )
    errors: list[FieldError] = Field(
        default_factory=list,
        description="Every fault found, when a request had more than one.",
    )


class ErrorBody(BaseModel):
    """The response body of every refusal this API makes."""

    model_config = ConfigDict(extra="forbid")

    error: Refusal


class ApiRefusal(Exception):
    """Raised by a route to refuse, with the status it deserves.

    Not `HTTPException`: that carries a `detail` of any shape, and the point here is
    that a refusal has exactly one shape.
    """

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        *,
        field: str | None = None,
        errors: list[FieldError] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = ErrorBody(
            error=Refusal(
                code=code, message=message, field=field, errors=errors or []
            )
        )


def _respond(status_code: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _refusal(
    status_code: int, code: ErrorCode, message: str, field: str | None = None
) -> JSONResponse:
    return _respond(
        status_code,
        ErrorBody(error=Refusal(code=code, message=message, field=field)),
    )


def install(app: FastAPI) -> None:
    """Attach every handler. Called once, by :func:`roadrisk.api.app.create_app`."""

    @app.exception_handler(ApiRefusal)
    async def _api_refusal(_: Request, exc: ApiRefusal) -> JSONResponse:
        return _respond(exc.status_code, exc.body)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            FieldError(
                location=".".join(str(part) for part in error.get("loc", ())),
                message=str(error.get("msg", "")),
            )
            for error in exc.errors()
        ]
        first = errors[0] if errors else None
        return _respond(
            HTTP_422,
            ErrorBody(
                error=Refusal(
                    code=ErrorCode.INVALID_REQUEST,
                    message=(
                        f"{first.location}: {first.message}"
                        if first
                        else "The request did not parse."
                    ),
                    field=first.location if first else None,
                    errors=errors,
                )
            ),
        )

    @app.exception_handler(ContractViolation)
    async def _contract(_: Request, exc: ContractViolation) -> JSONResponse:
        # 422 with the column named, and no job created — the CLI's refusal receipt,
        # over the wire. The message comes from `roadrisk.core.contract` unchanged,
        # because it already says which column and what was required; rewording it here
        # would be a second description of the same rule.
        return _refusal(
            HTTP_422,
            ErrorCode.CONTRACT_VIOLATION,
            str(exc),
            field="panel",
        )

    @app.exception_handler(PayloadRejected)
    async def _payload(_: Request, exc: PayloadRejected) -> JSONResponse:
        return _refusal(
            HTTP_422,
            ErrorCode.PAYLOAD_REJECTED,
            str(exc),
            field="payload",
        )

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
        # The store deliberately does not distinguish "absent" from "someone else's",
        # and neither does this: telling them apart turns a list of guessed identifiers
        # into a census of another tenant's runs.
        return _refusal(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, str(exc))

    @app.exception_handler(InUse)
    async def _in_use(_: Request, exc: InUse) -> JSONResponse:
        return _refusal(status.HTTP_409_CONFLICT, ErrorCode.IN_USE, str(exc))

    @app.exception_handler(RoadRiskError)
    async def _engine(_: Request, exc: RoadRiskError) -> JSONResponse:
        # Everything the engine refuses that is not a contract violation: an unsourced
        # weight, a malformed registry, a transform that cannot apply. All of them are
        # decisions with a stated reason, so none of them is a 500.
        return _refusal(
            HTTP_422, ErrorCode.ENGINE_REFUSED, str(exc)
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Starlette's own 404s and 405s, wearing the same envelope as everything else.
        return _refusal(
            exc.status_code,
            ErrorCode.NOT_FOUND
            if exc.status_code == status.HTTP_404_NOT_FOUND
            else ErrorCode.INVALID_REQUEST,
            str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # "Never a 500 with a stack trace" is a promise to the client, not to the
        # operator: the traceback is logged in full, and what crosses the wire is a
        # sentence and the request id it was logged under.
        reference = request.headers.get("x-request-id") or f"{id(exc):x}"
        log.exception("Unhandled error on %s [%s]", request.url.path, reference)
        return _refusal(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ErrorCode.INTERNAL,
            "Something failed inside the service. The cause has been logged under "
            f"reference {reference}; nothing about it is your request's fault to fix.",
        )


#: Attached to every route so the OpenAPI document says what a refusal looks like,
#: rather than leaving a client to discover it from a 404.
REFUSAL_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorBody, "description": "Refused before anything was read."},
    401: {"model": ErrorBody, "description": "No tenant. See X-Tenant-Id."},
    404: {"model": ErrorBody, "description": "No such row, for this tenant."},
    422: {"model": ErrorBody, "description": "The request or the panel was refused."},
    500: {"model": ErrorBody, "description": "Logged, with a reference. Never a trace."},
}


__all__ = [
    "REFUSAL_RESPONSES",
    "ApiRefusal",
    "ErrorBody",
    "ErrorCode",
    "FieldError",
    "Refusal",
    "install",
]
