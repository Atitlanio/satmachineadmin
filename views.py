# Description: DCA Admin page endpoints.

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer

satmachineadmin_generic_router = APIRouter()


def satmachineadmin_renderer():
    return template_renderer(["satmachineadmin/templates"])


# DCA Admin page
@satmachineadmin_generic_router.get("/", response_class=HTMLResponse)
async def index(req: Request, user: User = Depends(check_user_exists)):
    return satmachineadmin_renderer().TemplateResponse(
        "satmachineadmin/index.html", {"request": req, "user": user.json()}
    )
