"""POST /api/contact — the contact form endpoint."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ClientIPDep, ContactServiceDep, enforce_rate_limit
from app.core.database import get_session
from app.schemas.common import ErrorResponse
from app.schemas.contact import ContactRequest, ContactResponse

router = APIRouter(tags=["contact"])


@router.post(
    "/contact",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_rate_limit)],
    summary="Submit the contact form",
    description=(
        "Validates the payload, analyses the message with AI, stores the request, "
        "and emails both the site owner and the sender.\n\n"
        "The AI step degrades gracefully: if every configured provider is "
        "unreachable the submission is still stored and both emails are still "
        "sent, with `ai_status` reported as `fallback`."
    ),
    responses={
        201: {"description": "Submission accepted and stored"},
        422: {"model": ErrorResponse, "description": "Validation failed"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        503: {"model": ErrorResponse, "description": "Submission could not be stored"},
    },
)
async def submit_contact_form(
    payload: ContactRequest,
    service: ContactServiceDep,
    client_ip: ClientIPDep,
    session: AsyncSession = Depends(get_session),
) -> ContactResponse:
    data = await service.submit(payload, client_ip, session)
    return ContactResponse(data=data)
