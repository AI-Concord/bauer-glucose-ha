"""Thin async client for the (unofficial) LibreLinkUp follower API.

Endpoint paths, headers and response field names verified against the
LibreLinkUp app protocol as of 2026 (mirrors timoschlueter/nightscout-
librelink-up, the actively-maintained reference for this API). Abbott has
no public/official API for this — expect the exact header fingerprint
(product/User-Agent/Content-Type) to need chasing again in the future if
requests start returning HTTP 430 with an empty body: that status is an
edge/WAF-level rejection of the header combination, not a credentials or
version problem. The Android product string + a generic Android UA is
known to trigger it; the iOS fingerprint below is what's currently accepted.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp

from .const import REGION_HOSTS, TREND_ARROW_MAP

_LOGGER = logging.getLogger(__name__)

LLU_VERSION = "4.16.0"
LLU_PRODUCT = "llu.ios"
LLU_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU OS 17_4.1 like Mac OS X) AppleWebKit/536.26 "
    "(KHTML, like Gecko) Version/17.4.1 Mobile/10A5355d Safari/8536.25"
)

_TIMESTAMP_FORMAT = "%m/%d/%Y %I:%M:%S %p"


class LibreLinkUpError(Exception):
    """Base error."""


class LibreLinkUpAuthError(LibreLinkUpError):
    """Raised on bad credentials, expired session, or a required step-up."""


@dataclass
class GlucoseReading:
    mgdl: float
    timestamp: datetime
    trend: str  # one of TREND_ARROW_MAP values, or "stable" if not computable


@dataclass
class PatientConnection:
    patient_id: str
    first_name: str
    last_name: str


@dataclass
class GlucoseSnapshot:
    current: GlucoseReading | None
    history: list[GlucoseReading] = field(default_factory=list)


def _parse_factory_timestamp(raw: str) -> datetime:
    """FactoryTimestamp is the sensor's own clock, reported in UTC."""
    return datetime.strptime(raw, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)


def _reading_from_glucose_item(item: dict) -> GlucoseReading:
    trend_num = item.get("TrendArrow") or 0
    trend = TREND_ARROW_MAP.get(trend_num, "stable")
    return GlucoseReading(
        mgdl=float(item["ValueInMgPerDl"]),
        timestamp=_parse_factory_timestamp(item["FactoryTimestamp"]),
        trend=trend,
    )


class LibreLinkUpClient:
    """Minimal client: login (with region redirect), list connections, fetch graph."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str, region: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._base_url = f"https://{REGION_HOSTS.get(region, REGION_HOSTS['us'])}"
        self._token: str | None = None
        self._account_id_hash: str | None = None

    def _headers(self, *, authenticated: bool) -> dict[str, str]:
        headers = {
            "product": LLU_PRODUCT,
            "version": LLU_VERSION,
            "accept-encoding": "gzip",
            "cache-control": "no-cache",
            "connection": "Keep-Alive",
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json",
            "user-agent": LLU_USER_AGENT,
        }
        if authenticated:
            if not self._token or not self._account_id_hash:
                raise LibreLinkUpAuthError("not logged in")
            headers["authorization"] = f"Bearer {self._token}"
            headers["account-id"] = self._account_id_hash
        return headers

    async def _post(self, url: str, *, json: dict, authenticated: bool) -> dict:
        async with self._session.post(url, json=json, headers=self._headers(authenticated=authenticated)) as resp:
            if resp.status == 401:
                raise LibreLinkUpAuthError("session expired")
            resp.raise_for_status()
            return await resp.json()

    async def _get(self, url: str, *, authenticated: bool, params: dict | None = None) -> dict:
        async with self._session.get(url, params=params, headers=self._headers(authenticated=authenticated)) as resp:
            if resp.status == 401:
                raise LibreLinkUpAuthError("session expired")
            resp.raise_for_status()
            return await resp.json()

    async def async_login(self) -> None:
        payload = await self._post(
            f"{self._base_url}/llu/auth/login",
            json={"email": self._email, "password": self._password},
            authenticated=False,
        )
        await self._handle_login_response(payload)

    async def _handle_login_response(self, payload: dict) -> None:
        data = payload.get("data", {})

        if data.get("redirect"):
            region = data.get("region")
            country_payload = await self._get(
                f"{self._base_url}/llu/config/country",
                authenticated=False,
                params={"country": region or "US"},
            )
            regional_map = country_payload.get("data", {}).get("regionalMap", {})
            new_base = regional_map.get(region, {}).get("lslApi")
            if not new_base:
                raise LibreLinkUpAuthError(f"could not resolve API host for region '{region}'")
            self._base_url = new_base.rstrip("/")
            payload = await self._post(
                f"{self._base_url}/llu/auth/login",
                json={"email": self._email, "password": self._password},
                authenticated=False,
            )
            data = payload.get("data", {})

        status = payload.get("status", 0)
        if status == 2:
            raise LibreLinkUpAuthError("invalid LibreLinkUp email or password")
        if status == 4:
            step = data.get("step", {}).get("componentName", "unknown")
            raise LibreLinkUpAuthError(
                f"LibreLinkUp requires an in-app step before API access works (step: {step}); "
                "open the LibreLinkUp app once, accept any prompts, then retry"
            )
        if status != 0:
            raise LibreLinkUpAuthError(f"unexpected login status {status}")

        auth_ticket = data.get("authTicket", {})
        token = auth_ticket.get("token")
        user_id = data.get("user", {}).get("id")
        if not token or not user_id:
            raise LibreLinkUpAuthError("login succeeded but response was missing token/user id")

        self._token = token
        self._account_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

    async def async_get_connections(self) -> list[PatientConnection]:
        payload = await self._get(f"{self._base_url}/llu/connections", authenticated=True)
        return [
            PatientConnection(
                patient_id=item["patientId"],
                first_name=item.get("firstName", ""),
                last_name=item.get("lastName", ""),
            )
            for item in payload.get("data", [])
        ]

    async def async_get_snapshot(self, patient_id: str) -> GlucoseSnapshot:
        payload = await self._get(
            f"{self._base_url}/llu/connections/{patient_id}/graph", authenticated=True
        )
        data = payload.get("data", {})

        current_item = data.get("connection", {}).get("glucoseMeasurement")
        current = _reading_from_glucose_item(current_item) if current_item else None

        history = [_reading_from_glucose_item(item) for item in data.get("graphData", [])]

        return GlucoseSnapshot(current=current, history=history)
