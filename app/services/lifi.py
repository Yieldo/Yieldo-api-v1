import httpx
from app.core.constants import LIFI_BASE_URL, LIFI_INTEGRATOR
from app.config import get_settings

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


def _headers() -> dict:
    settings = get_settings()
    h = {"Content-Type": "application/json"}
    if settings.lifi_api_key:
        h["x-lifi-api-key"] = settings.lifi_api_key
    return h


async def get_quote(
    from_chain: int,
    from_token: str,
    from_amount: str,
    to_chain: int,
    to_token: str,
    from_address: str,
    slippage: float = 0.03,
    allowed_bridges: list[str] | None = None,
) -> dict | None:
    client = get_client()
    params = {
        "fromChain": str(from_chain),
        "fromToken": from_token,
        "fromAmount": from_amount,
        "toChain": str(to_chain),
        "toToken": to_token,
        "fromAddress": from_address,
        "slippage": str(slippage),
        "order": "CHEAPEST",
        "integrator": LIFI_INTEGRATOR,
    }
    if allowed_bridges:
        params["allowBridges"] = ",".join(allowed_bridges)
    resp = await client.get(f"{LIFI_BASE_URL}/quote", params=params, headers=_headers())
    if resp.status_code != 200:
        return None
    return resp.json()


async def get_routes(
    from_chain: int,
    from_token: str,
    from_amount: str,
    to_chain: int,
    to_token: str,
    from_address: str,
    slippage: float = 0.03,
) -> list[dict]:
    """Fetch multiple bridge route options from LiFi's advanced/routes endpoint."""
    client = get_client()
    body = {
        "fromChainId": from_chain,
        "fromTokenAddress": from_token,
        "fromAmount": from_amount,
        "toChainId": to_chain,
        "toTokenAddress": to_token,
        "fromAddress": from_address,
        "slippage": slippage,
        "integrator": LIFI_INTEGRATOR,
    }
    resp = await client.post(
        f"{LIFI_BASE_URL}/advanced/routes",
        json=body,
        headers=_headers(),
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data.get("routes", [])


def extract_route_info(route: dict) -> dict:
    """Extract bridge tool, name, logo, amounts, time, and gas from a route."""
    step = route.get("steps", [{}])[0] if route.get("steps") else {}
    tool_details = step.get("toolDetails", {})
    estimate = step.get("estimate", {})
    gas_costs = estimate.get("gasCosts", [])
    gas_usd = sum(float(g.get("amountUSD", "0")) for g in gas_costs) if gas_costs else None
    return {
        "bridge": tool_details.get("key") or step.get("tool", ""),
        "bridge_name": tool_details.get("name") or step.get("tool", ""),
        "bridge_logo": tool_details.get("logoURI"),
        "to_amount": route.get("toAmount", "0"),
        "to_amount_min": route.get("toAmountMin", "0"),
        "estimated_time": estimate.get("executionDuration"),
        "gas_cost_usd": str(round(gas_usd, 2)) if gas_usd else None,
        "tags": route.get("tags", []),
    }


async def get_contract_calls_quote(
    from_chain: int,
    from_token: str,
    from_amount: str,
    to_chain: int,
    to_token: str,
    from_address: str,
    contract_address: str,
    contract_call_data: str,
    contract_call_amount: str,
    preferred_bridges: list[str] | None = None,
    slippage: float = 0.03,
    contract_call_value: str = "0",
) -> dict | None:
    client = get_client()
    is_same_chain = from_chain == to_chain

    contract_call: dict = {
        "fromAmount": contract_call_amount,
        "fromTokenAddress": to_token,
        "toTokenAddress": to_token,
        "toContractAddress": contract_address,
        "toContractCallData": contract_call_data,
        "toContractGasLimit": "2000000",
        "toApprovalAddress": contract_address,
        "requiresDeposit": True,
    }
    if contract_call_value and contract_call_value != "0":
        contract_call["toContractCallValue"] = contract_call_value

    body: dict = {
        "fromChain": from_chain,
        "fromToken": from_token,
        "fromAmount": from_amount,
        "fromAddress": from_address,
        "toChain": to_chain,
        "toToken": to_token,
        "toAddress": from_address,
        "contractCalls": [contract_call],
        "slippage": slippage,
        "integrator": LIFI_INTEGRATOR,
    }

    if is_same_chain and preferred_bridges:
        valid_exchanges = {
            "sushiswap": "sushiswap",
            "1inch": "1inch",
            "paraswap": "paraswap",
            "openocean": "openocean",
            "0x": "0x",
            "uniswap": "uniswap",
        }
        mapped = [valid_exchanges[b.lower()] for b in preferred_bridges if b.lower() in valid_exchanges]
        if mapped:
            body["allowExchanges"] = mapped
    elif not is_same_chain and preferred_bridges:
        body["allowBridges"] = preferred_bridges

    resp = await client.post(
        f"{LIFI_BASE_URL}/quote/contractCalls",
        json=body,
        headers=_headers(),
    )

    if resp.status_code != 200:
        error_data = {}
        try:
            error_data = resp.json()
        except Exception:
            pass
        if error_data.get("code") in (1002, 1011) and not is_same_chain and "allowBridges" in body:
            retry_body = {k: v for k, v in body.items() if k != "allowBridges"}
            retry_resp = await client.post(
                f"{LIFI_BASE_URL}/quote/contractCalls",
                json=retry_body,
                headers=_headers(),
            )
            if retry_resp.status_code == 200:
                quote = retry_resp.json()
                if quote and quote.get("transactionRequest"):
                    return quote
        return None

    quote = resp.json()
    if not quote or not quote.get("transactionRequest"):
        return None
    return quote


async def get_status(tx_hash: str, from_chain: int, to_chain: int) -> dict | None:
    client = get_client()
    params = {
        "txHash": tx_hash,
        "fromChain": str(from_chain),
        "toChain": str(to_chain),
    }
    resp = await client.get(f"{LIFI_BASE_URL}/status", params=params, headers=_headers())
    if resp.status_code != 200:
        return None
    return resp.json()


async def get_tokens(chain_id: int) -> list[dict]:
    client = get_client()
    resp = await client.get(
        f"{LIFI_BASE_URL}/tokens",
        params={"chains": str(chain_id)},
        headers=_headers(),
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data.get("tokens", {}).get(str(chain_id), [])


async def get_connections(from_chain: int, to_chain: int) -> dict | None:
    client = get_client()
    params = {
        "fromChain": str(from_chain),
        "toChain": str(to_chain),
    }
    resp = await client.get(f"{LIFI_BASE_URL}/connections", params=params, headers=_headers())
    if resp.status_code != 200:
        return None
    return resp.json()


def extract_bridge_from_quote(quote: dict | None) -> str | None:
    if not quote:
        return None
    if quote.get("tool") and quote["tool"] != "lifi":
        return quote["tool"]
    if quote.get("toolDetails", {}).get("key") and quote["toolDetails"]["key"] != "lifi":
        return quote["toolDetails"]["key"]
    for step in quote.get("includedSteps", []):
        if step.get("type") in ("cross", "lifi") and step.get("tool") and step["tool"] != "lifi":
            return step["tool"]
    for step in quote.get("steps", []):
        if step.get("type") in ("cross", "lifi"):
            if step.get("tool") and step["tool"] != "lifi":
                return step["tool"]
            for inc in step.get("includedSteps", []):
                if inc.get("type") == "cross" and inc.get("tool") and inc["tool"] != "lifi":
                    return inc["tool"]
    return None


def extract_quote_amounts(quote: dict) -> tuple[str, str]:
    estimate = quote.get("estimate", {})
    action = quote.get("action", {})
    to_amount = (
        estimate.get("toAmount")
        or action.get("toAmount")
        or quote.get("toAmount")
        or "0"
    )
    to_amount_min = (
        estimate.get("toAmountMin")
        or action.get("toAmountMin")
        or quote.get("toAmountMin")
        or to_amount
    )
    return to_amount, to_amount_min


def extract_quote_metadata(quote: dict) -> dict:
    estimate = quote.get("estimate", {})
    gas_costs = estimate.get("gasCosts", [])
    gas_usd = sum(float(g.get("amountUSD", "0")) for g in gas_costs) if gas_costs else None
    from_amount_usd = estimate.get("fromAmountUSD")
    to_amount_usd = estimate.get("toAmountUSD")
    price_impact = None
    if from_amount_usd and to_amount_usd:
        f_usd = float(from_amount_usd)
        t_usd = float(to_amount_usd)
        if f_usd > 0 and t_usd > 0:
            price_impact = round(abs((f_usd - t_usd) / f_usd) * 100, 4)
    steps = []
    for s in quote.get("includedSteps", quote.get("steps", [])):
        steps.append({
            "type": s.get("type", ""),
            "tool": s.get("toolDetails", {}).get("name") or s.get("tool", ""),
            "estimated_time": s.get("estimate", {}).get("executionDuration"),
        })
    return {
        "from_amount_usd": from_amount_usd,
        "gas_cost_usd": str(round(gas_usd, 2)) if gas_usd else None,
        "price_impact": price_impact,
        "estimated_time": estimate.get("executionDuration"),
        "steps": steps,
    }
