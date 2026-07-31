import asyncio
import json
import logging
import re
from typing import Any

import httpx
import pymysql

from app.core.config import settings

logger = logging.getLogger("stratroom.java_bridge")

DEFAULT_TIMEOUT = 30.0


class JavaBridgeError(Exception):
    def __init__(self, message: str, status_code: int | None = None, response: dict | None = None):
        self.status_code = status_code
        self.response = response
        super().__init__(message)


class JavaBridge:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, verify=False)
        self._mysql_conn: pymysql.Connection | None = None
        self._mysql_lock = asyncio.Lock()

    @property
    def auth_service(self) -> str:
        return settings.JAVA_AUTH_URL

    @property
    def db_service(self) -> str:
        return settings.JAVA_DB_URL

    @property
    def user_service(self) -> str:
        return settings.JAVA_USER_URL

    @property
    def scorecard_service(self) -> str:
        return settings.JAVA_SCORECARD_URL

    # ── MySQL helpers ──

    def _mysql_connect(self):
        if self._mysql_conn is None or not self._mysql_conn.open:
            self._mysql_conn = pymysql.connect(
                host=settings.MYSQL_HOST,
                port=settings.MYSQL_PORT,
                user=settings.MYSQL_USER,
                password=settings.MYSQL_PASSWORD,
                database=settings.MYSQL_DATABASE,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=10,
                read_timeout=30,
                autocommit=True,
            )
        self._mysql_conn.ping(reconnect=True)
        return self._mysql_conn

    def _query_all(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = self._mysql_connect()
        with conn.cursor() as c:
            c.execute(sql, params)
            return c.fetchall()

    def _query_one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self._query_all(sql, params)
        return rows[0] if rows else None

    async def _mysql(self, sql: str, params: tuple = (), one: bool = False) -> Any:
        async with self._mysql_lock:
            fn = self._query_one if one else self._query_all
            return await asyncio.to_thread(fn, sql, params)

    # ── Route known Java DB paths to MySQL ──

    def _route_db_get(self, path: str, params: dict | None = None) -> tuple[str | None, tuple]:
        """Return (SQL, params_tuple) for a known GET path, or (None, ()) to fall through to HTTP."""
        if path == "/riskListView":
            return "SELECT ID, risk_value, active, owner, created_time, updated_time, page_id, status FROM risk_details ORDER BY created_time DESC", ()
        if path.startswith("/riskList/"):
            eid = path.split("/")[-1]
            return f"SELECT ID, risk_value, active, owner, created_time, updated_time, page_id, status FROM risk_details WHERE owner = %s ORDER BY created_time DESC", (eid,)
        if path == "/budgetsListview":
            return "SELECT id, budgetvalues, create_time, update_time, deptid, owner, active, page_id, status FROM budget_detail ORDER BY id DESC", ()
        if path == "/universalIncidentList":
            return "SELECT ID, incident_value, active, owner, created_time, updated_time, page_id, department_id FROM universal_incident", ()
        if path.startswith("/initiativesList/"):
            return "SELECT id, initiative_value, active, owner, created_time, updated_time, page_id FROM initiatives_details ORDER BY updated_time DESC", ()
        if path == "/auditManagementList":
            return "SELECT ID, managementvalue, active, owner, created_time, updated_time, page_id FROM audit_management", ()
        if path.startswith("/retrieveTaskList/"):
            return "SELECT ID, task_value, active, owner, created_time, updated_time, priority, status FROM task_details ORDER BY updated_time DESC", ()
        if path.startswith("/meetingManagementList/"):
            return "SELECT ID, meetingManagementValue, active, owner, created_time, updated_time, page_id FROM meeting_management ORDER BY updated_time DESC", ()
        if path == "/compliance" or path.startswith("/compliance/"):
            return "SELECT ID, complain_value, active, owner, created_time, updated_time, page_id, status, risklevel FROM compliance_details", ()
        if path == "/findByUser":
            email = (params or {}).get("email", "")
            if email:
                return "SELECT emp_id, org_id, first_name, last_name, title, email_address, status, department, phone_number, parent_emp_id, location FROM employee_details WHERE LOWER(email_address) = LOWER(%s) LIMIT 1", (email,)
            return None, ()
        if path == "/employeeDetailsList":
            return "SELECT emp_id, org_id, dept_id, first_name, last_name, title, email_address, status, department, phone_number, parent_emp_id, location FROM employee_details ORDER BY first_name ASC", ()
        if path == "/userList":
            return "SELECT emp_id, org_id, user_name, email_address, status FROM employee_credentials ORDER BY email_address ASC", ()
        if path.startswith("/scoreCardList"):
            return "SELECT id, score_card_val, active, owner, created_time, updated_time, page_id, score_name FROM score_card ORDER BY created_time DESC", ()
        if path == "/orgStructureList":
            return "SELECT Id, empId, parent_id, status, start_date, end_date, active FROM org_structure_details", ()
        if path == "/userRoleMgmt":
            return "SELECT emp_id, org_id, name, email_address, designation, role, department, location, status, created_date FROM user_role_management", ()
        if path.startswith("/projectsList"):
            return "SELECT ID, planningvalue, active, owner, created_by, updated_by, created_time, updated_time, department_id FROM project_planning ORDER BY ID ASC", ()
        if path == "/swotList":
            return "SELECT ID, flag_type, swot_analysis_value, active, owner, created_time, updated_time, page_id, dept_id FROM swot_analysis", ()
        if path == "/pestelList":
            return "SELECT ID, flagType, pestelAnalysisValue, active, owner, created_time, updated_time, page_id, dept_id FROM pestel_analysis", ()
        if path == "/bcpList":
            return "SELECT id, posvalues, owner, deptid, page_id, status, version FROM processenabler ORDER BY id ASC", ()
        if path == "/complaints":
            is_admin = (params or {}).get("is_admin", False)
            is_manager = (params or {}).get("is_manager", False)
            org_id = (params or {}).get("org_id", 0)
            user_id = (params or {}).get("user_id", 0)
            if is_admin or is_manager:
                return (
                    "SELECT id, org_id, title, description, category, severity, status, "
                    "assigned_user_id, submitted_by, created_at, resolved_at "
                    "FROM complaints WHERE org_id = %s "
                    "ORDER BY CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, id",
                    (org_id,),
                )
            else:
                return (
                    "SELECT id, org_id, title, description, category, severity, status, "
                    "assigned_user_id, submitted_by, created_at, resolved_at "
                    "FROM complaints WHERE org_id = %s AND assigned_user_id = %s "
                    "ORDER BY CASE severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END, id",
                    (org_id, user_id),
                )
        if path.startswith("/complaints/"):
            cid = path.split("/")[-1]
            org_id = (params or {}).get("org_id", 0)
            return (
                "SELECT id, org_id, title, description, category, severity, status, "
                "assigned_user_id, submitted_by, created_at, resolved_at "
                "FROM complaints WHERE id = %s AND org_id = %s",
                (cid, org_id),
            )
        # ── Document routes ──
        if path == "/documents":
            is_admin = (params or {}).get("is_admin", False)
            is_manager = (params or {}).get("is_manager", False)
            org_id = (params or {}).get("org_id", 0)
            user_id = (params or {}).get("user_id", 0)
            if is_admin or is_manager:
                return (
                    "SELECT id, org_id, user_id, original_filename, content_type, file_size, "
                    "uploaded_by, created_at FROM documents WHERE org_id = %s ORDER BY created_at DESC LIMIT 100",
                    (org_id,),
                )
            else:
                return (
                    "SELECT id, org_id, user_id, original_filename, content_type, file_size, "
                    "uploaded_by, created_at FROM documents WHERE org_id = %s AND user_id = %s ORDER BY created_at DESC LIMIT 100",
                    (org_id, user_id),
                )
        if path == "/documents/search":
            q = (params or {}).get("q", "")
            is_admin = (params or {}).get("is_admin", False)
            is_manager = (params or {}).get("is_manager", False)
            org_id = (params or {}).get("org_id", 0)
            user_id = (params or {}).get("user_id", 0)
            like = f"%{q}%"
            if is_admin or is_manager:
                return (
                    "SELECT d.id, d.org_id, d.user_id, d.original_filename, d.content_type, d.file_size, "
                    "d.uploaded_by, d.created_at FROM documents d WHERE d.org_id = %s "
                    "AND (d.original_filename LIKE %s OR d.extracted_text LIKE %s "
                    "OR EXISTS (SELECT 1 FROM document_summaries ds WHERE ds.document_id = d.id AND ds.summary LIKE %s)) "
                    "ORDER BY d.created_at DESC LIMIT 50",
                    (org_id, like, like, like),
                )
            else:
                return (
                    "SELECT d.id, d.org_id, d.user_id, d.original_filename, d.content_type, d.file_size, "
                    "d.uploaded_by, d.created_at FROM documents d WHERE d.org_id = %s AND d.user_id = %s "
                    "AND (d.original_filename LIKE %s OR d.extracted_text LIKE %s "
                    "OR EXISTS (SELECT 1 FROM document_summaries ds WHERE ds.document_id = d.id AND ds.summary LIKE %s)) "
                    "ORDER BY d.created_at DESC LIMIT 50",
                    (org_id, user_id, like, like, like),
                )
        if path.startswith("/documents/") and path.endswith("/download"):
            did = path.split("/")[-2]
            org_id = (params or {}).get("org_id", 0)
            return (
                "SELECT original_filename, storage_path, content_type FROM documents WHERE id = %s AND org_id = %s",
                (did, org_id),
            )
        if path.startswith("/documents/") and path.endswith("/summaries"):
            did = path.split("/")[-2]
            return (
                "SELECT id, summary, provider, model, created_at FROM document_summaries WHERE document_id = %s ORDER BY created_at DESC",
                (did,),
            )
        if path.startswith("/documents/") and path.endswith("/text"):
            did = path.split("/")[-2]
            return (
                "SELECT original_filename, extracted_text FROM documents WHERE id = %s",
                (did,),
            )
        if path.startswith("/documents/"):
            did = path.split("/")[-1]
            org_id = (params or {}).get("org_id", 0)
            return (
                "SELECT id, org_id, user_id, original_filename, content_type, file_size, extracted_text, "
                "uploaded_by, created_at FROM documents WHERE id = %s AND org_id = %s",
                (did, org_id),
            )
        # ── Conversation routes ──
        if path == "/conversations":
            uid = (params or {}).get("uid", 0)
            oid = (params or {}).get("oid", 0)
            agent = (params or {}).get("agent")
            if agent:
                return (
                    "SELECT id, agent_name, title, created_at FROM agent_conversations "
                    "WHERE agent_name = %s AND user_id = %s AND org_id = %s "
                    "ORDER BY created_at DESC LIMIT 50",
                    (agent, uid, oid),
                )
            return (
                "SELECT id, agent_name, title, created_at FROM agent_conversations "
                "WHERE user_id = %s AND org_id = %s ORDER BY created_at DESC LIMIT 50",
                (uid, oid),
            )
        if path.startswith("/conversations/") and path.endswith("/messages"):
            cid = path.split("/")[-2]
            return (
                "SELECT id, role, content, created_at FROM agent_messages "
                "WHERE conversation_id = %s ORDER BY id",
                (cid,),
            )
        if path.startswith("/conversations/"):
            cid = path.split("/")[-1]
            uid = (params or {}).get("uid", 0)
            return (
                "SELECT id, agent_name, title, created_at FROM agent_conversations "
                "WHERE id = %s AND user_id = %s",
                (cid, uid),
            )
        return None, ()

    def _rows_to_json(self, path: str, rows: list[dict]) -> list[dict]:
        """Format MySQL rows into the same JSON shape the Java endpoint would return."""
        result = []
        for r in rows:
            if path in ("/riskListView",) or path.startswith("/riskList/"):
                obj = self._parse_json_col(r, "risk_value")
                obj["id"] = r.get("ID")
                obj["active"] = r.get("active")
                obj["owner"] = r.get("owner")
                obj["created_time"] = str(r.get("created_time") or "")
                obj["updated_time"] = str(r.get("updated_time") or "")
                obj["page_id"] = r.get("page_id")
                obj["status"] = r.get("status")
                result.append(obj)
            elif path == "/budgetsListview":
                obj = self._parse_json_col(r, "budgetvalues")
                obj["id"] = r.get("id")
                obj["deptid"] = r.get("deptid")
                obj["owner"] = r.get("owner")
                obj["active"] = r.get("active")
                obj["page_id"] = r.get("page_id")
                result.append(obj)
            elif path == "/universalIncidentList":
                obj = self._parse_json_col(r, "incident_value")
                obj["id"] = r.get("ID")
                obj["owner"] = r.get("owner")
                obj["active"] = r.get("active")
                obj["page_id"] = r.get("page_id")
                obj["department_id"] = r.get("department_id")
                result.append(obj)
            elif path.startswith("/initiativesList/"):
                obj = self._parse_json_col(r, "initiative_value")
                obj["id"] = r.get("id")
                obj["owner"] = r.get("owner")
                obj["active"] = r.get("active")
                result.append(obj)
            elif path == "/auditManagementList":
                obj = self._parse_json_col(r, "managementvalue")
                obj["id"] = r.get("ID")
                obj["owner"] = r.get("owner")
                obj["active"] = r.get("active")
                obj["page_id"] = r.get("page_id")
                result.append(obj)
            elif path.startswith("/retrieveTaskList/"):
                obj = self._parse_json_col(r, "task_value")
                obj["id"] = r.get("ID")
                obj["owner"] = r.get("owner")
                obj["active"] = r.get("active")
                obj["priority"] = r.get("priority")
                obj["status"] = r.get("status")
                result.append(obj)
            elif path.startswith("/meetingManagementList/"):
                obj = self._parse_json_col(r, "meetingManagementValue")
                obj["id"] = r.get("ID")
                obj["owner"] = r.get("owner")
                obj["active"] = r.get("active")
                obj["page_id"] = r.get("page_id")
                result.append(obj)
            elif path == "/compliance" or path.startswith("/compliance/"):
                obj = self._parse_json_col(r, "complain_value")
                obj["id"] = r.get("ID")
                obj["owner"] = r.get("owner")
                obj["active"] = r.get("active")
                obj["page_id"] = r.get("page_id")
                obj["status"] = r.get("status")
                obj["risklevel"] = r.get("risklevel")
                result.append(obj)
            elif path == "/employeeDetailsList" or path == "/findByUser":
                result.append(r)
            elif path == "/userList":
                result.append(r)
            elif path.startswith("/scoreCardList"):
                obj = self._parse_json_col(r, "score_card_val")
                obj["id"] = r.get("id")
                obj["active"] = r.get("active")
                obj["owner"] = r.get("owner")
                obj["score_name"] = r.get("score_name")
                obj["page_id"] = r.get("page_id")
                result.append(obj)
            elif path == "/orgStructureList":
                result.append({
                    "Id": r.get("Id"),
                    "empId": r.get("empId"),
                    "parent_id": r.get("parent_id"),
                    "status": r.get("status"),
                    "start_date": str(r.get("start_date") or ""),
                    "end_date": str(r.get("end_date") or ""),
                    "active": r.get("active"),
                })
            elif path == "/userRoleMgmt":
                result.append({
                    "emp_id": r.get("emp_id"),
                    "org_id": r.get("org_id"),
                    "name": r.get("name") or "",
                    "email_address": r.get("email_address") or "",
                    "designation": r.get("designation") or "",
                    "role": r.get("role") or "",
                    "department": r.get("department") or "",
                    "location": r.get("location") or "",
                    "status": r.get("status"),
                    "created_date": str(r.get("created_date") or ""),
                })
            elif path.startswith("/projectsList"):
                obj = self._parse_json_col(r, "planningvalue")
                obj["id"] = r.get("ID")
                obj["active"] = r.get("active")
                obj["owner"] = r.get("owner")
                obj["dept_id"] = r.get("department_id")
                status_map = {
                    "Not Started": "on_hold",
                    "In Progress": "on_track",
                    "Completed": "completed",
                    "On Hold": "on_hold",
                    "Cancelled": "at_risk",
                    "Delayed": "at_risk",
                }
                raw_status = (obj.get("status") or "").strip()
                obj["status"] = status_map.get(raw_status, "on_track")
                obj["name"] = obj.pop("projectName", (obj.get("name") or ""))
                obj["budget"] = str(obj.get("budget") or 0)
                obj["due_date"] = (obj.get("enddate") or obj.get("fromdate") or "")
                obj["progress"] = 0
                result.append(obj)
            elif path == "/swotList":
                parsed = self._parse_json_col(r, "swot_analysis_value")
                quadrant_map = {
                    "Strengths": "strength",
                    "Weaknesses": "weakness",
                    "Oppurtunities": "opportunity",
                    "Threats": "threat",
                }
                raw_quadrant = (r.get("flag_type") or "").strip()
                result.append({
                    "id": r.get("ID"),
                    "quadrant": quadrant_map.get(raw_quadrant, raw_quadrant.lower()),
                    "content": parsed.get("name") or "",
                    "sort_order": r.get("ID") or 0,
                    "active": r.get("active"),
                    "owner": r.get("owner"),
                })
            elif path == "/pestelList":
                parsed = self._parse_json_col(r, "pestelAnalysisValue")
                category_map = {
                    "Political": "political",
                    "Economical": "economic",
                    "Social": "social",
                    "Technological": "technology",
                    "Environmental": "environmental",
                    "Legal": "legal",
                }
                impact_map = {
                    "danger": "high",
                    "warning": "medium",
                    "success": "low",
                }
                raw_category = (r.get("flagType") or "").strip()
                raw_impact = (parsed.get("status_flag") or "").strip().lower()
                result.append({
                    "id": r.get("ID"),
                    "category": category_map.get(raw_category, raw_category.lower()),
                    "impact": impact_map.get(raw_impact, "medium"),
                    "content": parsed.get("name") or "",
                    "sort_order": r.get("ID") or 0,
                    "active": r.get("active"),
                    "owner": r.get("owner"),
                })
            elif path == "/bcpList":
                parsed = self._parse_json_col(r, "posvalues")
                raw_process = parsed.get("process")
                if isinstance(raw_process, list) and len(raw_process) > 0:
                    name = str(raw_process[0]).strip()
                elif isinstance(raw_process, str):
                    name = raw_process.strip()
                else:
                    name = ""
                if name.startswith("[") and name.endswith("]"):
                    name = name.strip("[]").strip('"').strip("'").strip()
                result.append({
                    "id": r.get("id"),
                    "name": name,
                    "owner": parsed.get("ownerName") or "",
                    "category": (parsed.get("departmentName") or "").upper(),
                    "rto": (parsed.get("rto") or ""),
                    "rpo": "",
                    "mtd": "",
                    "impact": "",
                    "status": r.get("status") or "",
                    "parent_id": None,
                    "sort_order": r.get("id") or 0,
                    "deptid": r.get("deptid"),
                })
            elif path == "/complaints" or path.startswith("/complaints/"):
                result.append({
                    "id": r.get("id"),
                    "org_id": r.get("org_id"),
                    "title": r.get("title"),
                    "description": r.get("description"),
                    "category": r.get("category"),
                    "severity": r.get("severity"),
                    "status": r.get("status"),
                    "assigned_user_id": r.get("assigned_user_id"),
                    "submitted_by": r.get("submitted_by"),
                    "created_at": str(r.get("created_at") or ""),
                    "resolved_at": str(r.get("resolved_at") or ""),
                })
            # ── Document routes ──
            elif path in ("/documents", "/documents/search"):
                result.append({
                    "id": r.get("id"),
                    "original_filename": r.get("original_filename"),
                    "content_type": r.get("content_type"),
                    "file_size": r.get("file_size"),
                    "uploaded_by": r.get("uploaded_by"),
                    "created_at": str(r.get("created_at") or ""),
                })
            elif path.endswith("/download"):
                result.append({
                    "original_filename": r.get("original_filename"),
                    "storage_path": r.get("storage_path"),
                    "content_type": r.get("content_type"),
                })
            elif path.endswith("/summaries"):
                result.append({
                    "id": r.get("id"),
                    "summary": r.get("summary"),
                    "provider": r.get("provider"),
                    "model": r.get("model"),
                    "created_at": str(r.get("created_at") or ""),
                })
            elif path.endswith("/text"):
                result.append({
                    "original_filename": r.get("original_filename"),
                    "extracted_text": r.get("extracted_text") or "",
                })
            elif re.match(r"^/documents/\d+$", path):
                result.append({
                    "id": r.get("id"),
                    "original_filename": r.get("original_filename"),
                    "content_type": r.get("content_type"),
                    "file_size": r.get("file_size"),
                    "extracted_text": r.get("extracted_text") or "",
                    "uploaded_by": r.get("uploaded_by"),
                    "created_at": str(r.get("created_at") or ""),
                })
            # ── Conversation routes ──
            elif path == "/conversations" or path.startswith("/conversations/"):
                if path.endswith("/messages"):
                    result.append({
                        "id": r.get("id"),
                        "role": r.get("role"),
                        "content": r.get("content"),
                        "created_at": str(r.get("created_at") or ""),
                    })
                else:
                    result.append({
                        "id": r.get("id"),
                        "agent_name": r.get("agent_name"),
                        "title": r.get("title"),
                        "created_at": str(r.get("created_at") or ""),
                    })
            else:
                result.append(r)
        return result

    @staticmethod
    def _parse_json_col(row: dict, col: str) -> dict:
        val = row.get(col)
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return {}
        if isinstance(val, (dict, list)):
            return val if isinstance(val, dict) else {}
        if isinstance(val, bytes):
            try:
                return json.loads(val.decode("utf-8"))
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
                return {}
        return {}

    # ── Public API (same interface for routers) ──

    async def get(self, service: str, path: str, **kwargs) -> Any:
        if service in (self.db_service, self.user_service, self.scorecard_service):
            params = kwargs.get("params") or {}
            sql, sql_params = self._route_db_get(path, params)
            if sql is not None:
                try:
                    rows = await self._mysql(sql, sql_params)
                    return self._rows_to_json(path, rows)
                except Exception as e:
                    logger.error("MySQL query failed for %s: %s", path, e)
                    raise JavaBridgeError(f"MySQL query failed: {e}") from e
        return await self._do("GET", service, path, **kwargs)

    def _route_db_post(self, path: str, data: dict) -> tuple[str | None, tuple]:
        if path == "/scoreCardList" or path.startswith("/scoreCardList/"):
            return (
                "INSERT INTO score_card (score_card_val, active, owner, created_time, updated_time, page_id, score_name) "
                "VALUES (%s, %s, %s, NOW(), NOW(), %s, %s)",
                (json.dumps(data), data.get("active", 1), data.get("owner", ""), data.get("page_id"), data.get("score_name", "")),
            )
        if path.startswith("/riskList/"):
            return (
                "INSERT INTO risk_details (risk_value, active, owner, created_time, updated_time, page_id, status) "
                "VALUES (%s, %s, %s, NOW(), NOW(), %s, %s)",
                (json.dumps(data), data.get("active", 1), data.get("owner", ""), data.get("page_id"), data.get("status", "open")),
            )
        if path.startswith("/retrieveTaskList/"):
            return (
                "INSERT INTO task_details (task_value, active, owner, created_time, updated_time, priority, status) "
                "VALUES (%s, %s, %s, NOW(), NOW(), %s, %s)",
                (json.dumps(data), data.get("active", 1), data.get("owner", ""), data.get("priority", "medium"), data.get("status", "pending")),
            )
        if path.startswith("/initiativesList/"):
            return (
                "INSERT INTO initiatives_details (initiative_value, active, owner, created_time, updated_time, page_id) "
                "VALUES (%s, %s, %s, NOW(), NOW(), %s)",
                (json.dumps(data), data.get("active", 1), data.get("owner", ""), data.get("page_id")),
            )
        if path == "/auditManagementList" or path.startswith("/auditManagementList/"):
            return (
                "INSERT INTO audit_management (managementvalue, active, owner, created_time, updated_time, page_id) "
                "VALUES (%s, %s, %s, NOW(), NOW(), %s)",
                (json.dumps(data), data.get("active", 1), data.get("owner", ""), data.get("page_id")),
            )
        if path.startswith("/meetingManagementList/"):
            return (
                "INSERT INTO meeting_management (meetingManagementValue, active, owner, created_time, updated_time, page_id) "
                "VALUES (%s, %s, %s, NOW(), NOW(), %s)",
                (json.dumps(data), data.get("active", 1), data.get("owner", ""), data.get("page_id")),
            )
        if path == "/universalIncidentList" or path.startswith("/universalIncidentList/"):
            return (
                "INSERT INTO universal_incident (incident_value, active, owner, created_time, updated_time, page_id, department_id) "
                "VALUES (%s, %s, %s, NOW(), NOW(), %s, %s)",
                (json.dumps(data), data.get("active", 1), data.get("owner", ""), data.get("page_id"), data.get("department_id")),
            )
        if path == "/swotList":
            return (
                "INSERT INTO swot_analysis (swot_analysis_value, active, owner, page_id, flag_type, created_time, updated_time) "
                "VALUES (%s, %s, %s, %s, %s, NOW(), NOW())",
                (json.dumps(data), data.get("active", 1), data.get("owner"), data.get("page_id"), data.get("flag_type")),
            )
        if path == "/pestelList":
            return (
                "INSERT INTO pestel_analysis (pestelAnalysisValue, active, owner, page_id, flagType, created_time, updated_time) "
                "VALUES (%s, %s, %s, %s, %s, NOW(), NOW())",
                (json.dumps(data), data.get("active", 1), data.get("owner"), data.get("page_id"), data.get("flagType")),
            )
        if path.startswith("/projectsList"):
            return (
                "INSERT INTO project_planning (planningvalue, active, owner, page_id, start_date, end_date, department_id, created_time, updated_time) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())",
                (json.dumps(data), data.get("active", 1), data.get("owner"), data.get("page_id"), data.get("start_date"), data.get("end_date"), data.get("department_id")),
            )
        if path == "/complaints":
            return (
                "INSERT INTO complaints (org_id, title, description, category, severity, status, assigned_user_id, submitted_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                (data.get("org_id"), data.get("title"), data.get("description"), data.get("category"),
                 data.get("severity"), data.get("status"), data.get("assigned_user_id"), data.get("submitted_by")),
            )
        # ── Document routes ──
        if path == "/documents/upload":
            return (
                "INSERT INTO documents (org_id, user_id, filename, original_filename, content_type, file_size, "
                "extracted_text, storage_path, uploaded_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                (data.get("org_id"), data.get("user_id"), data.get("filename"), data.get("original_filename"),
                 data.get("content_type"), data.get("file_size"), data.get("extracted_text"),
                 data.get("storage_path"), data.get("uploaded_by")),
            )
        if re.match(r"^/documents/\d+/summarize$", path):
            did = path.split("/")[-2]
            return (
                "INSERT INTO document_summaries (document_id, summary, provider, model, created_at) "
                "VALUES (%s, %s, %s, %s, NOW())",
                (did, data.get("summary"), data.get("provider"), data.get("model")),
            )
        # ── Conversation routes ──
        if path == "/conversations":
            return (
                "INSERT INTO agent_conversations (agent_name, user_id, org_id, title, created_at) "
                "VALUES (%s, %s, %s, %s, NOW())",
                (data.get("agent_name"), data.get("user_id"), data.get("org_id"), data.get("title")),
            )
        if re.match(r"^/conversations/\d+/messages$", path):
            cid = path.split("/")[-2]
            return (
                "INSERT INTO agent_messages (conversation_id, role, content, created_at) "
                "VALUES (%s, %s, %s, NOW())",
                (cid, data.get("role"), data.get("content")),
            )
        return None, ()

    def _route_db_put(self, path: str, data: dict) -> tuple[str | None, tuple]:
        if path.startswith("/scoreCardList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE score_card SET score_card_val=%s, updated_time=NOW() WHERE id=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/riskList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE risk_details SET risk_value=%s, updated_time=NOW() WHERE ID=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/retrieveTaskList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE task_details SET task_value=%s, updated_time=NOW() WHERE ID=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/initiativesList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE initiatives_details SET initiative_value=%s, updated_time=NOW() WHERE id=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/auditManagementList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE audit_management SET managementvalue=%s, updated_time=NOW() WHERE ID=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/meetingManagementList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE meeting_management SET meetingManagementValue=%s, updated_time=NOW() WHERE ID=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/universalIncidentList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE universal_incident SET incident_value=%s, updated_time=NOW() WHERE ID=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/swotList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE swot_analysis SET swot_analysis_value=%s, updated_time=NOW() WHERE ID=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/pestelList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE pestel_analysis SET pestelAnalysisValue=%s, updated_time=NOW() WHERE ID=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/projectsList/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE project_planning SET planningvalue=%s, updated_time=NOW() WHERE ID=%s",
                (json.dumps(data), pk),
            )
        if path.startswith("/complaints/"):
            pk = path.split("/")[-1]
            return (
                "UPDATE complaints SET title=%s, description=%s, category=%s, severity=%s, status=%s, "
                "assigned_user_id=%s, submitted_by=%s, resolved_at=NOW() WHERE id=%s",
                (data.get("title"), data.get("description"), data.get("category"),
                 data.get("severity"), data.get("status"), data.get("assigned_user_id"),
                 data.get("submitted_by"), pk),
            )
        return None, ()

    def _route_db_delete(self, path: str) -> tuple[str | None, tuple]:
        if path.startswith("/scoreCardList/"):
            return "DELETE FROM score_card WHERE id=%s", (path.split("/")[-1],)
        if path.startswith("/riskList/"):
            return "DELETE FROM risk_details WHERE ID=%s", (path.split("/")[-1],)
        if path.startswith("/retrieveTaskList/"):
            return "DELETE FROM task_details WHERE ID=%s", (path.split("/")[-1],)
        if path.startswith("/initiativesList/"):
            return "DELETE FROM initiatives_details WHERE id=%s", (path.split("/")[-1],)
        if path.startswith("/auditManagementList/"):
            return "DELETE FROM audit_management WHERE ID=%s", (path.split("/")[-1],)
        if path.startswith("/meetingManagementList/"):
            return "DELETE FROM meeting_management WHERE ID=%s", (path.split("/")[-1],)
        if path.startswith("/universalIncidentList/"):
            return "DELETE FROM universal_incident WHERE ID=%s", (path.split("/")[-1],)
        if path.startswith("/swotList/"):
            return "DELETE FROM swot_analysis WHERE ID=%s", (path.split("/")[-1],)
        if path.startswith("/pestelList/"):
            return "DELETE FROM pestel_analysis WHERE ID=%s", (path.split("/")[-1],)
        if path.startswith("/projectsList/"):
            return "DELETE FROM project_planning WHERE ID=%s", (path.split("/")[-1],)
        if path.startswith("/complaints/"):
            return "DELETE FROM complaints WHERE id=%s", (path.split("/")[-1],)
        # ── Document routes ──
        if path.startswith("/documents/") and path.endswith("/summaries"):
            did = path.split("/")[-2]
            return "DELETE FROM document_summaries WHERE document_id=%s", (did,)
        if path.startswith("/documents/"):
            did = path.split("/")[-1]
            return "DELETE FROM documents WHERE id=%s", (did,)
        # ── Conversation routes ──
        if path.startswith("/conversations/") and path.endswith("/messages"):
            cid = path.split("/")[-2]
            return "DELETE FROM agent_messages WHERE conversation_id=%s", (cid,)
        if path.startswith("/conversations/"):
            cid = path.split("/")[-1]
            return "DELETE FROM agent_conversations WHERE id=%s", (cid,)
        return None, ()


    async def post(self, service: str, path: str, **kwargs) -> Any:
        if service in (self.db_service, self.user_service, self.scorecard_service):
            data = kwargs.get("json") or kwargs.get("data") or {}
            sql, sql_params = self._route_db_post(path, data)
            if sql is not None:
                try:
                    last_id = await self._mysql_write(sql, sql_params)
                    result = {"status": "created"}
                    if last_id:
                        result["id"] = last_id
                    return result
                except Exception as e:
                    logger.error("MySQL POST failed for %s: %s", path, e)
                    raise JavaBridgeError(f"MySQL POST failed: {e}") from e
        return await self._do("POST", service, path, **kwargs)

    async def put(self, service: str, path: str, **kwargs) -> Any:
        if service in (self.db_service, self.user_service, self.scorecard_service):
            data = kwargs.get("json") or kwargs.get("data") or {}
            sql, sql_params = self._route_db_put(path, data)
            if sql is not None:
                try:
                    await self._mysql_write(sql, sql_params)
                    return {"status": "updated"}
                except Exception as e:
                    logger.error("MySQL PUT failed for %s: %s", path, e)
                    raise JavaBridgeError(f"MySQL PUT failed: {e}") from e
        return await self._do("PUT", service, path, **kwargs)

    async def delete(self, service: str, path: str, **kwargs) -> Any:
        if service in (self.db_service, self.user_service, self.scorecard_service):
            sql, sql_params = self._route_db_delete(path)
            if sql is not None:
                try:
                    await self._mysql_write(sql, sql_params)
                    return {"status": "deleted"}
                except Exception as e:
                    logger.error("MySQL DELETE failed for %s: %s", path, e)
                    raise JavaBridgeError(f"MySQL DELETE failed: {e}") from e
        return await self._do("DELETE", service, path, **kwargs)

    async def _mysql_write(self, sql: str, params: tuple = ()) -> int:
        async with self._mysql_lock:
            return await asyncio.to_thread(self._execute_write, sql, params)

    def _execute_write(self, sql: str, params: tuple) -> int:
        conn = self._mysql_connect()
        with conn.cursor() as c:
            c.execute(sql, params)
        conn.commit()
        return c.lastrowid

    async def _do(self, method: str, base: str, path: str, **kwargs) -> Any:
        url = f"{base}{path}"
        headers = kwargs.pop("headers", {})
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        h.update(headers)
        try:
            resp = await self._client.request(method, url, headers=h, **kwargs)
            if resp.status_code >= 400 and resp.status_code != 404:
                logger.warning("Java bridge: %s %s -> %s", method, url, resp.status_code)
            ct = resp.headers.get("content-type", "")
            if "application/json" in ct:
                return resp.json()
            return resp.text
        except httpx.RequestError as e:
            raise JavaBridgeError(f"Request failed: {e}") from e

    async def close(self):
        await self._client.aclose()
        if self._mysql_conn is not None and self._mysql_conn.open:
            self._mysql_conn.close()


bridge = JavaBridge()
