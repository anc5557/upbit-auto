from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any

import time
import uuid
import hashlib
from urllib.parse import urlencode

import httpx
import jwt
import random
from ua.broker.errors import (
    AuthenticationError,
    PermissionError,
    RateLimitError,
    InvalidRequestError,
    NotFoundError,
    ExchangeError,
)


@dataclass
class OrderRequest:
    side: str  # buy/sell
    market: str
    size: float | None = None
    price: float | None = None
    order_type: str = "limit"  # limit | price | market
    identifier: Optional[str] = None  # idempotency key


class UpbitBroker:
    """Upbit broker adapter (stub).

    Real implementation should handle auth, rate limiting, idempotency,
    and order lifecycle. This is a placeholder for wiring.
    """

    def __init__(self, access_key: Optional[str], secret_key: Optional[str]):
        self._ak = access_key
        self._sk = secret_key


    # --- Below: compliance stubs (auth/sign) ---
    def _require_keys(self) -> None:
        if not self._ak or not self._sk:
            raise RuntimeError("Upbit API 키가 필요합니다. config 또는 환경변수를 확인하세요.")

    def build_headers(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """Build auth headers per Upbit docs.

        NOTE: Placeholder implementation. Upbit 인증은 JWT 기반으로, access_key, nonce,
        (선택적으로 query_hash) 등을 포함합니다. 실제 구현에서는 PyJWT 등을 사용해
        RS256/HS256 서명을 생성해야 합니다.
        """
        self._require_keys()
        nonce = str(uuid.uuid4())
        ts = str(int(time.time()))
        # Placeholder token; do NOT use in production.
        payload: Dict[str, Any] = {
            "access_key": self._ak,
            "nonce": nonce,
        }
        if params:
            # Build query string in a deterministic way and hash with SHA512
            query_string = urlencode(params, doseq=True)
            qh = hashlib.sha512(query_string.encode()).hexdigest()
            payload["query_hash"] = qh
            payload["query_hash_alg"] = "SHA512"
        token = jwt.encode(payload, self._sk, algorithm="HS256")
        return {
            "Authorization": f"Bearer {token}",
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        sign_params: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: float = 20.0,
        max_retries: int = 5,
    ) -> httpx.Response:
        backoff = 0.5
        for attempt in range(max_retries):
            headers = self.build_headers(sign_params)
            try:
                with httpx.Client(timeout=timeout) as client:
                    r = client.request(method, url, params=params, data=data, headers=headers)
                    r.raise_for_status()
                    return r
            except httpx.HTTPStatusError as e:
                status = e.response.status_code if e.response else None
                if status in (429, 500, 502, 503, 504):
                    ra = 0.0
                    try:
                        raf = e.response.headers.get("Retry-After") if e.response else None
                        if raf:
                            ra = float(raf)
                    except Exception:
                        ra = 0.0
                    wait = max(backoff, ra)
                    wait = wait * (1.0 + 0.2 * random.random())
                    time.sleep(wait)
                    backoff = min(backoff * 2.0, 8.0)
                    continue
                self._raise_http_error(e)
            except httpx.RequestError:
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 8.0)
                continue
        raise RateLimitError("Upbit API request exceeded retry limit")

    # --- API calls ---
    def get_accounts(self) -> list:
        self._require_keys()
        url = "https://api.upbit.com/v1/accounts"
        r = self._request("GET", url, sign_params=None, params=None, data=None, timeout=15)
        return r.json()

    def place_order(self, req: OrderRequest) -> dict:  # type: ignore[override]
        self._require_keys()
        url = "https://api.upbit.com/v1/orders"
        # Map to Upbit fields
        side = "bid" if req.side.lower() in ("buy", "bid") else "ask"
        ord_type = req.order_type
        params: Dict[str, Any] = {
            "market": req.market,
            "side": side,
            "ord_type": ord_type,
        }
        if ord_type == "limit":
            if req.size is None or req.price is None:
                raise ValueError("limit 주문에는 size와 price가 필요합니다.")
            params["volume"] = f"{req.size}"
            params["price"] = f"{req.price}"
        elif ord_type == "price":
            # 시장가 매수: price(원)만 필요
            if req.price is None:
                raise ValueError("market buy(price) 주문에는 price(원)이 필요합니다.")
            params["price"] = f"{req.price}"
        elif ord_type == "market":
            # 시장가 매도: volume만 필요
            if req.size is None:
                raise ValueError("market sell 주문에는 size가 필요합니다.")
            params["volume"] = f"{req.size}"
        else:
            raise ValueError("ord_type 은 limit|price|market 중 하나여야 합니다.")

        # Add idempotency identifier if not set
        if not req.identifier:
            req.identifier = str(uuid.uuid4())
        params["identifier"] = req.identifier

        r = self._request("POST", url, sign_params=params, data=params, timeout=20)
        return r.json()

    def get_order(self, uuid_str: str) -> dict:
        self._require_keys()
        url = "https://api.upbit.com/v1/order"
        params = {"uuid": uuid_str}
        r = self._request("GET", url, sign_params=params, params=params, timeout=15)
        return r.json()

    def cancel_order(self, uuid_str: str) -> dict:  # type: ignore[override]
        self._require_keys()
        url = "https://api.upbit.com/v1/order"
        params = {"uuid": uuid_str}
        r = self._request("DELETE", url, sign_params=params, params=params, timeout=15)
        return r.json()

    def _raise_http_error(self, e: httpx.HTTPStatusError) -> None:
        status = e.response.status_code if e.response else None
        try:
            payload = e.response.json()
            err = payload.get("error") if isinstance(payload, dict) else None
            name = (err or {}).get("name") if isinstance(err, dict) else None
            message = (err or {}).get("message") if isinstance(err, dict) else str(e)
        except Exception:
            name = None
            message = str(e)
        if status == 401:
            raise AuthenticationError(message)
        if status == 403:
            raise PermissionError(message)
        if status == 404:
            raise NotFoundError(message)
        if status == 429:
            raise RateLimitError(message)
        if status and 400 <= status < 500:
            raise InvalidRequestError(message)
        raise ExchangeError(message)

    # Validation helpers using orders/chance
    def get_order_chance(self, market: str, side: str) -> Dict[str, Any]:
        self._require_keys()
        url = "https://api.upbit.com/v1/orders/chance"
        params = {"market": market}
        r = self._request("GET", url, sign_params=params, params=params, timeout=15)
        return r.json()

    @staticmethod
    def quantize_price(price: float, price_unit: Optional[float]) -> float:
        if not price_unit or price_unit <= 0:
            return price
        return (int(price / price_unit)) * price_unit

    def get_market_limits(self, market: str) -> Dict[str, Any]:
        """Extract key limits from orders/chance.

        Returns: { price_unit: float|None, min_total: float|None }
        """
        chance = self.get_order_chance(market, "buy")
        limits: Dict[str, Any] = {"price_unit": None, "min_total": None}
        try:
            market_info = chance.get("market") or {}
            bid_info = market_info.get("bid") or {}
            ask_info = market_info.get("ask") or {}
            limits["price_unit"] = float((bid_info.get("price_unit") or ask_info.get("price_unit")))
        except Exception:
            pass
        try:
            limits["min_total"] = float(chance.get("market_bid", {}).get("min_total"))
        except Exception:
            # Fallback: some payloads may have different nesting
            try:
                limits["min_total"] = float(chance.get("bid_account", {}).get("min_total"))
            except Exception:
                pass
        return limits
