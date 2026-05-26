import json
import os
import re
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class QueryErrorCode(Enum):
    INVALID_SQL = "INVALID_SQL"
    TABLE_NOT_FOUND = "TABLE_NOT_FOUND"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    NOT_CONNECTED = "NOT_CONNECTED"
    ALREADY_CONNECTED = "ALREADY_CONNECTED"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    EMPTY_RESULT = "EMPTY_RESULT"
    UNKNOWN = "UNKNOWN"


class CoralError(Exception):
    def __init__(self, message: str, code: QueryErrorCode, details: Optional[dict] = None):
        self.code = code
        self.details = details or {}
        super().__init__(message)


class ReadOnlyValidator:
    SQL_BLOCK_KEYWORDS = [
        r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
        r"\bALTER\b", r"\bCREATE\b", r"\bTRUNCATE\b", r"\bREPLACE\b",
        r"\bEXEC\b", r"\bEXECUTE\b", r"\bCALL\b", r"\bMERGE\b",
        r"\bGRANT\b", r"\bREVOKE\b", r"\bRENAME\b", r"\bCOPY\b",
    ]
    SQL_BLOCK_PATTERN = re.compile(
        "|".join(SQL_BLOCK_KEYWORDS), re.IGNORECASE
    )

    @classmethod
    def validate(cls, sql: str) -> str:
        stripped = sql.strip()
        if not stripped:
            raise CoralError(
                "Empty SQL query",
                QueryErrorCode.INVALID_SQL,
                {"sql": sql},
            )
        upper = stripped.upper()
        if not upper.startswith("SELECT") and not upper.startswith("WITH"):
            raise CoralError(
                "Only SELECT and WITH queries are allowed (read-only)",
                QueryErrorCode.INVALID_SQL,
                {"sql": sql},
            )
        no_strings = re.sub(r"'[^']*'", "''", stripped)
        no_strings = re.sub(r'"[^"]*"', '""', no_strings)
        if cls.SQL_BLOCK_PATTERN.search(no_strings):
            raise CoralError(
                "Write operations are not allowed",
                QueryErrorCode.INVALID_SQL,
                {"sql": sql},
            )
        return stripped


@dataclass
class QueryResult:
    rows: list[dict[str, Any]]
    row_count: int
    columns: list[str]
    execution_time_ms: Optional[float] = None
    truncated: bool = False


@dataclass
class CatalogEntry:
    name: str
    type: str
    source: Optional[str] = None
    description: Optional[str] = None


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    description: Optional[str] = None


class CoralClient:
    DEFAULT_COMMAND = "coral"
    DEFAULT_ARGS = ["mcp-stdio"]
    DEFAULT_TIMEOUT = 30.0
    MAX_RESULT_SIZE = 10_000

    def __init__(
        self,
        command: Optional[str] = None,
        args: Optional[list[str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._command = command or os.environ.get("CORAL_COMMAND", self.DEFAULT_COMMAND)
        self._args = args or (
            os.environ.get("CORAL_ARGS", "mcp-stdio").split()
            if os.environ.get("CORAL_ARGS")
            else self.DEFAULT_ARGS.copy()
        )
        self._timeout = timeout
        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._connected = False
        self._read = None
        self._write = None
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connected and self._session is not None

    async def connect(self) -> None:
        if self.is_connected:
            raise CoralError(
                "Already connected to Coral MCP",
                QueryErrorCode.ALREADY_CONNECTED,
            )
        self._exit_stack = AsyncExitStack()
        try:
            server_params = StdioServerParameters(
                command=self._command,
                args=self._args,
            )
            stdio_transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self._read, self._write = stdio_transport
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(self._read, self._write)
            )
            await self._session.initialize()
            self._connected = True
            logger.info(
                "Connected to Coral MCP (command=%s, args=%s)",
                self._command,
                self._args,
            )
        except FileNotFoundError as e:
            self._connected = False
            raise CoralError(
                f"Coral executable not found: {self._command}. "
                f"Ensure Coral is installed and available in PATH.",
                QueryErrorCode.CONNECTION_FAILED,
                {"command": self._command, "error": str(e)},
            ) from e
        except Exception as e:
            self._connected = False
            raise CoralError(
                f"Failed to connect to Coral MCP: {e}",
                QueryErrorCode.CONNECTION_FAILED,
                {"command": self._command, "args": self._args, "error": str(e)},
            ) from e

    async def disconnect(self) -> None:
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning("Error during Coral disconnect: %s", e)
            finally:
                self._exit_stack = None
                self._session = None
                self._read = None
                self._write = None
                self._connected = False
                logger.info("Disconnected from Coral MCP")

    async def query(self, sql: str) -> QueryResult:
        if not self.is_connected:
            raise CoralError(
                "Not connected to Coral MCP. Call connect() first.",
                QueryErrorCode.NOT_CONNECTED,
            )
        safe_sql = ReadOnlyValidator.validate(sql)
        async with self._lock:
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool("sql", {"sql": safe_sql}),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                raise CoralError(
                    f"Query timed out after {self._timeout}s",
                    QueryErrorCode.TIMEOUT,
                    {"sql": safe_sql, "timeout": self._timeout},
                )
            except Exception as e:
                error_str = str(e).lower()
                if "source" in error_str and "not found" in error_str:
                    code = QueryErrorCode.SOURCE_NOT_FOUND
                elif "table" in error_str and "not found" in error_str:
                    code = QueryErrorCode.TABLE_NOT_FOUND
                elif "not found" in error_str:
                    code = QueryErrorCode.TABLE_NOT_FOUND
                else:
                    code = QueryErrorCode.UNKNOWN
                raise CoralError(
                    f"Query execution failed: {e}",
                    code,
                    {"sql": safe_sql, "error": str(e)},
                ) from e
        return self._parse_query_result(result, safe_sql)

    async def list_catalog(self) -> list[CatalogEntry]:
        if not self.is_connected:
            raise CoralError(
                "Not connected to Coral MCP", QueryErrorCode.NOT_CONNECTED
            )
        async with self._lock:
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool("list_tables"),
                    timeout=self._timeout,
                )
            except Exception as e:
                raise CoralError(
                    f"Failed to list catalog: {e}",
                    QueryErrorCode.UNKNOWN,
                    {"error": str(e)},
                ) from e
        return self._parse_catalog_result(result)

    async def search_catalog(self, pattern: str) -> list[CatalogEntry]:
        if not self.is_connected:
            raise CoralError(
                "Not connected to Coral MCP", QueryErrorCode.NOT_CONNECTED
            )
        async with self._lock:
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool("search_tables", {"pattern": pattern}),
                    timeout=self._timeout,
                )
            except Exception as e:
                raise CoralError(
                    f"Failed to search catalog: {e}",
                    QueryErrorCode.UNKNOWN,
                    {"pattern": pattern, "error": str(e)},
                ) from e
        return self._parse_catalog_result(result)

    async def describe_table(self, table: str) -> dict[str, Any]:
        if not self.is_connected:
            raise CoralError(
                "Not connected to Coral MCP", QueryErrorCode.NOT_CONNECTED
            )
        parts = table.split(".")
        schema = parts[0] if len(parts) > 1 else "public"
        table_name = parts[-1]
        async with self._lock:
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool("describe_table", {"schema": schema, "table": table_name}),
                    timeout=self._timeout,
                )
            except Exception as e:
                raise CoralError(
                    f"Failed to describe table '{table}': {e}",
                    QueryErrorCode.TABLE_NOT_FOUND,
                    {"table": table, "error": str(e)},
                ) from e
        return self._parse_describe_result(result)

    async def list_columns(self, table: str) -> list[ColumnInfo]:
        if not self.is_connected:
            raise CoralError(
                "Not connected to Coral MCP", QueryErrorCode.NOT_CONNECTED
            )
        parts = table.split(".")
        schema = parts[0] if len(parts) > 1 else "public"
        table_name = parts[-1]
        async with self._lock:
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool("list_columns", {"schema": schema, "table": table_name}),
                    timeout=self._timeout,
                )
            except Exception as e:
                raise CoralError(
                    f"Failed to list columns for '{table}': {e}",
                    QueryErrorCode.TABLE_NOT_FOUND,
                    {"table": table, "error": str(e)},
                ) from e
        return self._parse_columns_result(result)

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    def _parse_query_result(self, result: Any, sql: str) -> QueryResult:
        try:
            content = getattr(result, "content", None)
            if not content:
                return QueryResult(rows=[], row_count=0, columns=[])
            raw_text = self._extract_text(content)
            if not raw_text or not raw_text.strip():
                return QueryResult(rows=[], row_count=0, columns=[])
            data = json.loads(raw_text)
            if not isinstance(data, list):
                data = [data]
            # Coral wraps SQL results as [{"rows": [actual_row_1, ...]}]
            # Unwrap the inner "rows" key if present
            if data and isinstance(data[0], dict) and "rows" in data[0]:
                rows = data[0]["rows"]
            else:
                rows = data
            if not isinstance(rows, list):
                rows = [rows]
            if len(rows) > self.MAX_RESULT_SIZE:
                rows = rows[: self.MAX_RESULT_SIZE]
                truncated = True
            else:
                truncated = False
            columns = list(rows[0].keys()) if rows else []
            return QueryResult(
                rows=rows,
                row_count=len(rows),
                columns=columns,
                truncated=truncated,
            )
        except json.JSONDecodeError as e:
            raise CoralError(
                f"Failed to parse query result as JSON: {e}",
                QueryErrorCode.MALFORMED_RESPONSE,
                {"sql": sql, "raw": raw_text[:500] if "raw_text" in dir() else ""},
            ) from e
        except Exception as e:
            raise CoralError(
                f"Unexpected error parsing query result: {e}",
                QueryErrorCode.UNKNOWN,
                {"sql": sql, "error": str(e)},
            ) from e

    @staticmethod
    def _extract_text(content: list) -> str:
        text_parts = []
        for item in content:
            text_val = None
            if hasattr(item, "text"):
                text_val = item.text
            elif isinstance(item, dict) and "text" in item:
                text_val = item["text"]
            if text_val is not None:
                text_parts.append(text_val)
        return "".join(text_parts)

    def _parse_catalog_result(self, result: Any) -> list[CatalogEntry]:
        try:
            content = getattr(result, "content", None)
            if not content:
                return []
            raw_text = self._extract_text(content)
            if not raw_text.strip():
                return []
            data = json.loads(raw_text)
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                entries = data.get("tables", data.get("entries", [data]))
            else:
                return []
            catalog = []
            for entry in entries:
                if isinstance(entry, dict):
                    catalog.append(CatalogEntry(
                        name=entry.get("name", entry.get("table_name", "")),
                        type=entry.get("type", entry.get("table_type", "table")),
                        source=entry.get("source"),
                        description=entry.get("description"),
                    ))
                elif isinstance(entry, str):
                    catalog.append(CatalogEntry(name=entry, type="table"))
            return catalog
        except json.JSONDecodeError as e:
            raise CoralError(
                f"Failed to parse catalog result: {e}",
                QueryErrorCode.MALFORMED_RESPONSE,
            ) from e

    def _parse_describe_result(self, result: Any) -> dict[str, Any]:
        try:
            content = getattr(result, "content", None)
            if not content:
                return {}
            raw_text = self._extract_text(content)
            if not raw_text.strip():
                return {}
            data = json.loads(raw_text)
            if isinstance(data, dict):
                return data
            if isinstance(data, list) and data:
                return data[0]
            return {}
        except json.JSONDecodeError as e:
            raise CoralError(
                f"Failed to parse describe result: {e}",
                QueryErrorCode.MALFORMED_RESPONSE,
            ) from e

    def _parse_columns_result(self, result: Any) -> list[ColumnInfo]:
        try:
            content = getattr(result, "content", None)
            if not content:
                return []
            raw_text = self._extract_text(content)
            if not raw_text.strip():
                return []
            data = json.loads(raw_text)
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                entries = data.get("columns", [data])
            else:
                return []
            columns = []
            for entry in entries:
                if isinstance(entry, dict):
                    columns.append(ColumnInfo(
                        name=entry.get("name", entry.get("column_name", "")),
                        type=entry.get("type", entry.get("data_type", "Utf8")),
                        nullable=entry.get("nullable", entry.get("is_nullable", True)),
                        description=entry.get("description"),
                    ))
            return columns
        except json.JSONDecodeError as e:
            raise CoralError(
                f"Failed to parse columns result: {e}",
                QueryErrorCode.MALFORMED_RESPONSE,
            ) from e


