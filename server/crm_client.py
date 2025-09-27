"""Client for calling YonBIP CRM APIs."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

import requests

try:
    from . import config  # type: ignore
except ImportError:  # pragma: no cover
    from . import config_example as config

from .token_service import TOKEN_SERVICE

# 導入模擬數據模塊
try:
    from . import mock_data
except ImportError:
    import mock_data


class CRMClient:
    def __init__(self) -> None:
        self.gateway_url = config.GATEWAY_URL.rstrip("/")

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                 json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.gateway_url + path
        token = TOKEN_SERVICE.get_token()
        req_params = {"access_token": token}
        if params:
            req_params.update(params)
        resp = requests.request(method, url, params=req_params, json=json_body, timeout=15)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            details: Any
            try:
                details = resp.json()
            except ValueError:  # pragma: no cover
                details = resp.text
            raise RuntimeError(
                f"HTTP {resp.status_code} calling {path}: {json.dumps(details, ensure_ascii=False)}"
            ) from exc

        data = resp.json()
        if data.get("code") not in {"00000", "200", 200, "200000"}:
            raise RuntimeError(f"CRM API error: {json.dumps(data, ensure_ascii=False)}")
        return data

    def get_followups(
        self, customer_code: str = "", page: int = 1, page_size: int = 10
    ) -> Dict[str, Any]:
        """獲取跟進記錄列表"""
        
        # 檢查是否使用模擬數據
        if getattr(mock_data, "USE_MOCK_DATA", False):
            print("使用模擬數據返回跟進記錄")
            return mock_data.generate_mock_followup_data(customer_code, page, page_size)
        
        # 原有的真實API調用邏輯
        payload = {
            "pageIndex": page,
            "pageSize": page_size,
        }
        
        # 如果指定了客戶代碼，添加查詢條件
        if customer_code:
            payload["simpleVOs"] = [
                {
                    "field": config.FOLLOWUP_CUSTOMER_FIELD,
                    "op": config.FOLLOWUP_CUSTOMER_OPERATOR,
                    "value1": customer_code,
                }
            ]
        
        return self._request("POST", config.FOLLOWUP_LIST_PATH, json_body=payload)

    def get_followup_files(self, followup_id: str) -> Dict[str, Any]:
        """獲取跟進記錄的附件信息"""
        
        # 檢查是否使用模擬數據
        if getattr(mock_data, "USE_MOCK_DATA", False):
            print("使用模擬數據返回跟進記錄附件")
            return mock_data.generate_mock_followup_files(followup_id)
        
        # 原有的真實API調用邏輯
        payload = {"businessIds": [followup_id]}
        return self._request("POST", config.FOLLOWUP_FILES_PATH, json_body=payload)

    def query_followup_files(self, business_ids: Iterable[str]) -> Dict[str, Any]:
        """批次查詢跟進記錄附件信息"""

        # 檢查是否使用模擬數據
        if getattr(mock_data, "USE_MOCK_DATA", False):
            print("使用模擬數據返回跟進記錄附件查詢結果")
            first_id = next(iter(business_ids), "")
            return mock_data.generate_mock_query_files_response(first_id)

        # 根據用戶提供的API文檔格式
        payload = {"businessIds": list(business_ids)}
        return self._request("POST", config.FOLLOWUP_QUERY_FILES_PATH, json_body=payload)

    def save_followup(self, followup_data: Dict[str, Any]) -> Dict[str, Any]:
        """保存跟進記錄"""
        
        # 檢查是否使用模擬數據
        if getattr(mock_data, "USE_MOCK_DATA", False):
            print("使用模擬數據保存跟進記錄")
            return mock_data.generate_mock_save_response(followup_data)
        
        # 構建請求體，根據API文檔格式
        payload = {
            "data": followup_data,
            "systemSource": "followupOpenAPIAdd"
        }
        
        return self._request("POST", config.FOLLOWUP_SAVE_PATH, payload)

    def get_file_download_url(self, file_id: str) -> str:
        # Some APIs return preview URL directly. If not, use this endpoint.
        if not config.FILE_DOWNLOAD_PATH:
            raise RuntimeError("FILE_DOWNLOAD_PATH is not configured")
        params = {"fileId": file_id}
        data = self._request("GET", config.FILE_DOWNLOAD_PATH, params=params)
        file_url = data.get("data")
        if isinstance(file_url, dict):
            file_url = file_url.get("url") or file_url.get("downloadUrl")
        if not file_url:
            raise RuntimeError("Download URL not found in response")
        return file_url


CRM_CLIENT = CRMClient()
