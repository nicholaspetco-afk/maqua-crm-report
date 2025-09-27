"""Flask application exposing simplified endpoints for CRM follow-up assets."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, request, send_from_directory

try:
    from . import config  # type: ignore
except ImportError:  # pragma: no cover
    from . import config_example as config  # type: ignore

from .crm_client import CRM_CLIENT
from .token_service import TOKEN_SERVICE

ROOT_DIR = Path(__file__).resolve().parent.parent

app = Flask(__name__)
app.logger.setLevel("DEBUG")


@app.route("/")
def index_page() -> Any:  # pragma: no cover - static file helper
    return send_from_directory(ROOT_DIR, "index.html")


@app.route("/report.html")
def report_page() -> Any:  # pragma: no cover - static file helper
    return send_from_directory(ROOT_DIR, "report.html")


@app.route("/records.html")
def records_page() -> Any:  # pragma: no cover - static file helper
    return send_from_directory(ROOT_DIR, "records.html")


@app.route("/style.css")
def style_file() -> Any:  # pragma: no cover - static file helper
    return send_from_directory(ROOT_DIR, "style.css")


@app.route("/assets/<path:filename>")
def assets_file(filename: str) -> Any:  # pragma: no cover - static file helper
    return send_from_directory(ROOT_DIR / "assets", filename)


@app.route("/api/token")
def api_token() -> Any:  # pragma: no cover - debug endpoint
    token = TOKEN_SERVICE.get_token(force_refresh=request.args.get("refresh") == "1")
    return jsonify({"access_token": token})


@app.route("/api/followups", methods=["POST"])
def api_save_followup() -> Any:
    """保存跟進記錄"""
    try:
        # 獲取請求數據
        request_data = request.get_json()
        if not request_data:
            return jsonify({"code": 400, "message": "請求數據不能為空"}), 400
        
        # 驗證必填字段
        required_fields = ["followContext", "code", "followTime", "org", "_status"]
        for field in required_fields:
            if field not in request_data:
                return jsonify({"code": 400, "message": f"缺少必填字段: {field}"}), 400
        
        # 調用CRM客戶端保存跟進記錄
        result = CRM_CLIENT.save_followup(request_data)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"code": 500, "message": f"保存失敗: {str(e)}"}), 500


@app.route("/api/customers/<customer_code>/followups")
def api_customer_followups(customer_code: str) -> Any:
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("pageSize", config.DEFAULT_PAGE_SIZE))
    followup_data = CRM_CLIENT.get_followups(customer_code, page=page, page_size=page_size)

    records: List[Dict[str, Any]] = []
    for item in followup_data.get("data", {}).get("recordList", []):
        owner = str(item.get("ower_name") or "")
        if "維修幫" not in owner:
            continue

        followup_id = str(item.get(config.FOLLOWUP_ID_FIELD, ""))
        service_date = _extract_nested(item, getattr(config, "FOLLOWUP_SERVICE_DATE_FIELD", ""))
        next_date = _extract_nested(item, getattr(config, "FOLLOWUP_NEXT_SERVICE_DATE_FIELD", ""))
        photo_ids = _collect_photo_ids(item)
        app.logger.debug("[Followup] %s photo candidates: %s", followup_id, photo_ids)
        files: List[Dict[str, Any]] = []
        if photo_ids:
            try:
                files_response = CRM_CLIENT.query_followup_files(photo_ids)
            except RuntimeError as exc:
                app.logger.warning(
                    "[Followup] %s photo lookup failed: %s", followup_id, exc
                )
                files_response = {"data": {}}
            files = _extract_query_files(files_response, photo_ids)
            app.logger.debug("[Followup] %s fetched %s files", followup_id, len(files))

        photos, documents = _split_files(files)
        if not photos:
            continue

        records.append({
            "followupId": followup_id,
            "serviceDate": service_date,
            "nextServiceDate": next_date,
            "raw": item,
            "files": files,
            "photos": photos,
            "documents": documents,
        })

    records_with_photos = [rec for rec in records if rec["photos"]]
    if records_with_photos:
        records = [records_with_photos[0]]

    return jsonify({
        "code": "OK",
        "customerCode": customer_code,
        "records": records,
        "raw": followup_data,
    })


def _extract_files(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    data = response.get("data")
    items: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        if "list" in data:
            items = data.get("list", [])
        elif "bussinessId" in data:
            items = data.get("bussinessId", [])
    elif isinstance(data, list):
        items = data

    for entry in items:
        file_url = (
            entry.get("filePath")
            or entry.get("url")
            or entry.get("fileUrl")
            or entry.get("previewUrl")
        )
        file_id = entry.get("fileId") or entry.get("id")
        if not file_url and file_id:
            if config.FILE_DOWNLOAD_PATH:
                try:
                    file_url = CRM_CLIENT.get_file_download_url(str(file_id))
                except Exception:  # pragma: no cover - optional fallback
                    file_url = None
        files.append({
            "fileId": file_id,
            "fileName": entry.get("fileName") or entry.get("name"),
            "fileUrl": file_url,
            "raw": entry,
        })
    return files


def _extract_query_files(
    response: Dict[str, Any], requested_ids: List[str] | None = None
) -> List[Dict[str, Any]]:
    """從 query_followup_files API 響應中提取文件信息"""
    files: List[Dict[str, Any]] = []
    data = response.get("data", [])

    items: List[Dict[str, Any]] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        keys = requested_ids or list(data.keys())
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                items.extend(value)
    elif isinstance(data, (tuple, set)):
        items = [entry for entry in data if isinstance(entry, dict)]

    for entry in items:
        file_url = (
            entry.get("signedUrl")
            or entry.get("fileUrl")
            or entry.get("url")
            or entry.get("filePath")
        )

        files.append({
            "fileId": entry.get("fileId") or entry.get("id"),
            "fileName": entry.get("fileName") or entry.get("name"),
            "fileUrl": file_url,
            "fileSize": entry.get("fileSize"),
            "uploadTime": entry.get("uploadTime"),
            "fileType": entry.get("fileType"),
            "fileExtension": _guess_extension(entry),
            "raw": entry,
        })
    return files


def _collect_photo_ids(record: Dict[str, Any]) -> List[str]:
    """從跟進紀錄中提取照片欄位（picture1~picture5）的附件 ID。"""
    candidates: List[str] = []
    seen: set[str] = set()

    def _push(value: Any) -> None:
        if value in (None, ""):
            return
        if isinstance(value, (list, tuple, dict)):
            return
        text = str(value).strip()
        if not text or text.lower() in {"none", "null"}:
            return
        if not _looks_like_attachment_id(text):
            return
        if text in seen:
            return
        seen.add(text)
        candidates.append(text)

    for picture_key in ("picture1", "picture2", "picture3", "picture4", "picture5"):
        _push(record.get(picture_key))

    return candidates


def _looks_like_attachment_id(text: str) -> bool:
    if len(text) < 8:
        return False
    allowed = set("0123456789abcdefABCDEF-")
    return all(ch in allowed for ch in text)


def _split_files(files: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    photos: List[Dict[str, Any]] = []
    documents: List[Dict[str, Any]] = []

    for file in files:
        if _is_image_file(file):
            photos.append(file)
        else:
            documents.append(file)

    return photos, documents


def _is_image_file(file_entry: Dict[str, Any]) -> bool:
    extension = (file_entry.get("fileExtension") or "").lower()
    name = (file_entry.get("fileName") or file_entry.get("name") or "").lower()

    for candidate in (extension, name):
        if candidate.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic")):
            return True
    return False


def _guess_extension(entry: Dict[str, Any]) -> str:
    for key in ("fileExtension", "extension"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value

    name = entry.get("fileName") or entry.get("name")
    if isinstance(name, str) and '.' in name:
        return name[name.rfind('.'):]
    return ""


def _extract_nested(source: Dict[str, Any], path: str) -> Any:
    if not path:
        return None
    current: Any = source
    for part in path.split('.'):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


if __name__ == "__main__":  # pragma: no cover
    app.run(host="0.0.0.0", port=5000, debug=True)
