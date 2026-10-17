"""Halaman web REPTIL: login, dashboard, logout (server-rendered + cookie JWT)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reptil.core.config import get_settings
from reptil.core.db import get_db
from reptil.core.security import TOKEN_COOKIE_NAME
from reptil.modules.identity.service import AuthError, authenticate, issue_token, permission_codes, role_names
from reptil.modules.inventory.service import stock_summary
from reptil.modules.masterdata.models import Item, Partner, Warehouse
from reptil.modules.purchasing.service import summary as purchase_summary
from reptil.modules.sales.service import summary as sales_summary
from reptil.web.common import context_publik, page_user, redirect_login, render
from reptil.web.templating import templates

router = APIRouter(tags=["web"])


# ------------------------------------------------------------------- auth
@router.get("/", include_in_schema=False)
def index(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(
        "/dashboard" if page_user(request, db) else "/login", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, db: Session = Depends(get_db)):
    if page_user(request, db):
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", context_publik(request, db))


@router.post("/login", response_class=HTMLResponse, include_in_schema=False)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user = authenticate(db, email, password)
    except AuthError as exc:
        return templates.TemplateResponse(
            request,
            "login.html",
            context_publik(request, db, error=str(exc), email=email),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = issue_token(db, user)
    response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    settings = get_settings()
    response.set_cookie(
        key=TOKEN_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return response


@router.get("/logout", include_in_schema=False)
def logout(request: Request):
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(TOKEN_COOKIE_NAME, path="/")
    return response


# -------------------------------------------------------------- dashboard
@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = page_user(request, db)
    if user is None:
        return redirect_login()

    org_id = user.organisation_id

    def hitung(model) -> int:
        return db.execute(
            select(func.count()).select_from(model).where(model.organisation_id == org_id)
        ).scalar_one()

    return render(
        request,
        "dashboard.html",
        user,
        "dashboard",
        cards={
            "partner": hitung(Partner),
            "item": hitung(Item),
            "warehouse": hitung(Warehouse),
        },
        stok=stock_summary(db, org_id),
        beli=purchase_summary(db, org_id),
        jual=sales_summary(db, org_id),
        roles=role_names(user),
        permissions=sorted(permission_codes(user)),
        hari_ini=date.today(),
        selambatnya=(date.today() + timedelta(days=30)),
        sekarang=datetime.now(),
    )
