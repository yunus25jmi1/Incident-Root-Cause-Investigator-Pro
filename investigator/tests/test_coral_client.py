import json
import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import Any, Optional

from investigator.agent.coral_client import (
    CoralClient,
    CoralError,
    QueryErrorCode,
    ReadOnlyValidator,
    QueryResult,
    CatalogEntry,
    ColumnInfo,
)


@dataclass
class MockTextContent:
    type: str = "text"
    text: str = ""
    mimeType: Optional[str] = None


@dataclass
class MockCallToolResult:
    content: list
    isError: bool = False


class TestReadOnlyValidator:
    def test_valid_select(self):
        sql = "SELECT * FROM sentry.issues"
        assert ReadOnlyValidator.validate(sql) == sql

    def test_valid_select_with_where(self):
        sql = "SELECT id, title FROM github.pull_requests WHERE merged_at >= '2024-01-01'"
        assert ReadOnlyValidator.validate(sql) == sql

    def test_valid_with_cte(self):
        sql = "WITH recent AS (SELECT * FROM sentry.issues) SELECT * FROM recent"
        assert ReadOnlyValidator.validate(sql) == sql

    def test_valid_complex_join(self):
        sql = (
            "SELECT g.title, g.merged_at, s.title "
            "FROM github.pull_requests g "
            "JOIN sentry.issues s ON s.first_seen >= g.merged_at "
            "WHERE g.merged_at >= CURRENT_TIMESTAMP - INTERVAL '4 hours' "
            "AND s.level IN ('error', 'fatal')"
        )
        assert ReadOnlyValidator.validate(sql) == sql

    def test_rejects_insert(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("INSERT INTO sentry.issues VALUES (1)")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_rejects_update(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("UPDATE sentry.issues SET status='resolved'")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_rejects_delete(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("DELETE FROM sentry.issues")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_rejects_drop(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("DROP TABLE sentry.issues")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_rejects_alter(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("ALTER TABLE sentry.issues ADD COLUMN foo TEXT")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_rejects_create(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("CREATE TABLE foo (id INT)")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_rejects_truncate(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("TRUNCATE TABLE sentry.issues")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_rejects_execute(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("EXECUTE some_procedure")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_rejects_empty_string(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_rejects_whitespace_only(self):
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate("   \n  \t  ")
        assert exc.value.code == QueryErrorCode.INVALID_SQL

    def test_passes_select_with_insert_in_string(self):
        sql = "SELECT * FROM tbl WHERE name = 'INSERT test'"
        assert ReadOnlyValidator.validate(sql) == sql

    def test_passes_select_with_drop_in_string(self):
        sql = "SELECT * FROM information_schema.tables WHERE table_name = 'DROP TABLE'"
        assert ReadOnlyValidator.validate(sql) == sql

    def test_strips_whitespace(self):
        sql = "  SELECT * FROM tbl  "
        assert ReadOnlyValidator.validate(sql) == "SELECT * FROM tbl"

    def test_select_lowercase(self):
        sql = "select * from sentry.issues"
        assert ReadOnlyValidator.validate(sql) == sql

    def test_with_lowercase(self):
        sql = "with cte as (select 1) select * from cte"
        assert ReadOnlyValidator.validate(sql) == sql

    def test_passes_select_with_insert_in_string_lowercase(self):
        sql = "SELECT * FROM tbl WHERE name = 'insert'"
        assert ReadOnlyValidator.validate(sql) == sql

    def test_passes_select_with_like_drop(self):
        sql = "SELECT * FROM tbl WHERE name LIKE '%DROP%'"
        assert ReadOnlyValidator.validate(sql) == sql

    def test_rejects_double_dash_comment_with_drop(self):
        sql = "SELECT 1; -- DROP TABLE foo"
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate(sql)
        assert exc.value.code == QueryErrorCode.INVALID_SQL


class TestCoralClientConnect:
    @pytest.mark.asyncio
    @patch("investigator.agent.coral_client.stdio_client")
    @patch("investigator.agent.coral_client.ClientSession")
    @patch("investigator.agent.coral_client.AsyncExitStack")
    async def test_connect_success(self, mock_exit_stack_cls, mock_session_cls, mock_stdio):
        mock_stack = AsyncMock()
        mock_exit_stack_cls.return_value = mock_stack

        mock_read = AsyncMock()
        mock_write = AsyncMock()

        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio.return_value = mock_stdio_cm

        mock_session = AsyncMock()
        mock_session_cls.return_value = mock_session

        enter_results = [
            (mock_read, mock_write),
            mock_session,
        ]
        mock_stack.enter_async_context = AsyncMock(side_effect=enter_results)

        client = CoralClient()
        await client.connect()
        assert client.is_connected is True
        await client.disconnect()

    @pytest.mark.asyncio
    @patch("investigator.agent.coral_client.stdio_client")
    async def test_connect_double_fails(self, mock_stdio):
        mock_read = AsyncMock()
        mock_write = AsyncMock()
        mock_stdio.return_value.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))

        client = CoralClient()
        client._session = AsyncMock()
        client._connected = True
        client._exit_stack = AsyncMock()
        client._lock = asyncio.Lock()

        with pytest.raises(CoralError) as exc:
            await client.connect()
        assert exc.value.code == QueryErrorCode.ALREADY_CONNECTED

    @pytest.mark.asyncio
    @patch("investigator.agent.coral_client.stdio_client")
    async def test_connect_file_not_found(self, mock_stdio):
        mock_stdio.side_effect = FileNotFoundError("No such file or directory: 'coral'")
        client = CoralClient()
        with pytest.raises(CoralError) as exc:
            await client.connect()
        assert exc.value.code == QueryErrorCode.CONNECTION_FAILED
        assert "Coral executable not found" in str(exc.value)

    @pytest.mark.asyncio
    async def test_query_before_connect_raises(self):
        client = CoralClient()
        with pytest.raises(CoralError) as exc:
            await client.query("SELECT 1")
        assert exc.value.code == QueryErrorCode.NOT_CONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        client = CoralClient()
        await client.disconnect()
        assert client.is_connected is False


class TestCoralClientQuery:
    @pytest_asyncio.fixture
    async def connected_client(self):
        client = CoralClient()
        mock_session = AsyncMock()
        client._session = mock_session
        client._connected = True
        client._exit_stack = AsyncMock()
        client._lock = asyncio.Lock()
        yield client, mock_session
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_query_returns_rows(self, connected_client):
        client, mock_session = connected_client
        expected_rows = [
            {"id": "1", "title": "Error spike", "level": "error", "count": 100},
        ]
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text=json.dumps(expected_rows))])
        )
        result = await client.query("SELECT * FROM sentry.issues")
        assert isinstance(result, QueryResult)
        assert result.row_count == 1
        assert result.rows == expected_rows
        assert result.columns == ["id", "title", "level", "count"]
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_query_multiple_rows(self, connected_client):
        client, mock_session = connected_client
        rows = [
            {"id": "1", "title": "Error A", "level": "error"},
            {"id": "2", "title": "Error B", "level": "fatal"},
        ]
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text=json.dumps(rows))])
        )
        result = await client.query("SELECT * FROM sentry.issues")
        assert result.row_count == 2

    @pytest.mark.asyncio
    async def test_query_empty_result(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text=json.dumps([]))])
        )
        result = await client.query("SELECT * FROM sentry.issues WHERE false")
        assert result.row_count == 0
        assert result.rows == []

    @pytest.mark.asyncio
    async def test_query_empty_content(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[])
        )
        result = await client.query("SELECT * FROM sentry.issues")
        assert result.row_count == 0

    @pytest.mark.asyncio
    async def test_query_null_text(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text=None)])
        )
        result = await client.query("SELECT * FROM sentry.issues")
        assert result.row_count == 0

    @pytest.mark.asyncio
    async def test_query_truncated_large_result(self, connected_client):
        client, mock_session = connected_client
        client.MAX_RESULT_SIZE = 5
        rows = [{"id": str(i)} for i in range(20)]
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text=json.dumps(rows))])
        )
        result = await client.query("SELECT * FROM large_table")
        assert result.row_count == 5
        assert result.truncated is True

    @pytest.mark.asyncio
    async def test_query_malformed_json(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text="not valid json")])
        )
        with pytest.raises(CoralError) as exc:
            await client.query("SELECT * FROM sentry.issues")
        assert exc.value.code == QueryErrorCode.MALFORMED_RESPONSE

    @pytest.mark.asyncio
    async def test_query_timeout(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())
        with pytest.raises(CoralError) as exc:
            await client.query("SELECT * FROM sentry.issues")
        assert exc.value.code == QueryErrorCode.TIMEOUT

    @pytest.mark.asyncio
    async def test_query_table_not_found(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            side_effect=Exception("table not found: nonexistent_table")
        )
        with pytest.raises(CoralError) as exc:
            await client.query("SELECT * FROM nonexistent_table")
        assert exc.value.code == QueryErrorCode.TABLE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_query_source_not_found(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            side_effect=Exception("source 'badsource' not found")
        )
        with pytest.raises(CoralError) as exc:
            await client.query("SELECT * FROM badsource.issues")
        assert exc.value.code == QueryErrorCode.SOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_query_unknown_error(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            side_effect=Exception("internal server error")
        )
        with pytest.raises(CoralError) as exc:
            await client.query("SELECT * FROM sentry.issues")
        assert exc.value.code == QueryErrorCode.UNKNOWN

    @pytest.mark.asyncio
    async def test_query_called_with_correct_args(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text="[]")])
        )
        await client.query("SELECT * FROM sentry.issues WHERE level = 'error'")
        mock_session.call_tool.assert_called_once_with(
            "sql",
            {"sql": "SELECT * FROM sentry.issues WHERE level = 'error'"},
        )

    @pytest.mark.asyncio
    async def test_query_rejects_write(self, connected_client):
        client, mock_session = connected_client
        with pytest.raises(CoralError) as exc:
            await client.query("DROP TABLE sentry.issues")
        assert exc.value.code == QueryErrorCode.INVALID_SQL
        mock_session.call_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_blocks_double_dash_comment_with_delete(self, connected_client):
        client, mock_session = connected_client
        with pytest.raises(CoralError) as exc:
            await client.query("SELECT 1; DELETE FROM sentry.issues")
        assert exc.value.code == QueryErrorCode.INVALID_SQL
        mock_session.call_tool.assert_not_called()


class TestCoralClientCatalog:
    @pytest_asyncio.fixture
    async def connected_client(self):
        client = CoralClient()
        mock_session = AsyncMock()
        client._session = mock_session
        client._connected = True
        client._exit_stack = AsyncMock()
        client._lock = asyncio.Lock()
        yield client, mock_session

    @pytest.mark.asyncio
    async def test_list_catalog(self, connected_client):
        client, mock_session = connected_client
        catalog_data = [
            {"name": "sentry.issues", "type": "table", "source": "sentry"},
            {"name": "github.pull_requests", "type": "table", "source": "github"},
            {"name": "datadog.incidents", "type": "table", "source": "datadog"},
        ]
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text=json.dumps(catalog_data))])
        )
        result = await client.list_catalog()
        assert len(result) == 3
        assert isinstance(result[0], CatalogEntry)
        assert result[0].name == "sentry.issues"
        assert result[0].type == "table"
        assert result[0].source == "sentry"

    @pytest.mark.asyncio
    async def test_list_catalog_empty(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[])
        )
        result = await client.list_catalog()
        assert result == []

    @pytest.mark.asyncio
    async def test_search_catalog(self, connected_client):
        client, mock_session = connected_client
        search_data = [
            {"name": "sentry.issues", "type": "table", "source": "sentry"},
        ]
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text=json.dumps(search_data))])
        )
        result = await client.search_catalog("sentry")
        assert len(result) == 1
        mock_session.call_tool.assert_called_once_with(
            "search_tables", {"pattern": "sentry"}
        )

    @pytest.mark.asyncio
    async def test_describe_table(self, connected_client):
        client, mock_session = connected_client
        describe_data = {
            "name": "sentry.issues",
            "columns": [
                {"name": "id", "type": "Utf8", "nullable": False},
                {"name": "title", "type": "Utf8", "nullable": True},
            ]
        }
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text=json.dumps(describe_data))])
        )
        result = await client.describe_table("sentry.issues")
        assert result["name"] == "sentry.issues"
        mock_session.call_tool.assert_called_once_with(
            "describe_table", {"schema": "sentry", "table": "issues"}
        )

    @pytest.mark.asyncio
    async def test_list_columns(self, connected_client):
        client, mock_session = connected_client
        columns_data = [
            {"name": "id", "type": "Utf8", "nullable": False},
            {"name": "title", "type": "Utf8", "nullable": True},
        ]
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text=json.dumps(columns_data))])
        )
        result = await client.list_columns("sentry.issues")
        assert len(result) == 2
        assert isinstance(result[0], ColumnInfo)
        assert result[0].name == "id"
        assert result[0].nullable is False
        mock_session.call_tool.assert_called_once_with(
            "list_columns", {"schema": "sentry", "table": "issues"}
        )

    @pytest.mark.asyncio
    async def test_list_catalog_not_connected(self):
        client = CoralClient()
        with pytest.raises(CoralError) as exc:
            await client.list_catalog()
        assert exc.value.code == QueryErrorCode.NOT_CONNECTED

    @pytest.mark.asyncio
    async def test_search_catalog_not_connected(self):
        client = CoralClient()
        with pytest.raises(CoralError) as exc:
            await client.search_catalog("test")
        assert exc.value.code == QueryErrorCode.NOT_CONNECTED

    @pytest.mark.asyncio
    async def test_describe_table_not_connected(self):
        client = CoralClient()
        with pytest.raises(CoralError) as exc:
            await client.describe_table("sentry.issues")
        assert exc.value.code == QueryErrorCode.NOT_CONNECTED

    @pytest.mark.asyncio
    async def test_list_columns_not_connected(self):
        client = CoralClient()
        with pytest.raises(CoralError) as exc:
            await client.list_columns("sentry.issues")
        assert exc.value.code == QueryErrorCode.NOT_CONNECTED

    @pytest.mark.asyncio
    async def test_list_columns_empty_result(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[])
        )
        result = await client.list_columns("sentry.issues")
        assert result == []

    @pytest.mark.asyncio
    async def test_describe_table_not_found(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            side_effect=Exception("table 'foo.bar' not found")
        )
        with pytest.raises(CoralError) as exc:
            await client.describe_table("foo.bar")
        assert exc.value.code == QueryErrorCode.TABLE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_catalog_malformed_json(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text="bad json{{{")])
        )
        with pytest.raises(CoralError) as exc:
            await client.list_catalog()
        assert exc.value.code == QueryErrorCode.MALFORMED_RESPONSE

    @pytest.mark.asyncio
    async def test_columns_malformed_json(self, connected_client):
        client, mock_session = connected_client
        mock_session.call_tool = AsyncMock(
            return_value=MockCallToolResult(content=[MockTextContent(text="not json")])
        )
        with pytest.raises(CoralError) as exc:
            await client.list_columns("sentry.issues")
        assert exc.value.code == QueryErrorCode.MALFORMED_RESPONSE


class TestCoralClientDisconnectEdgeCases:
    @pytest.mark.asyncio
    async def test_disconnect_without_connect(self):
        client = CoralClient()
        await client.disconnect()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect_twice(self):
        client = CoralClient()
        client._connected = True
        client._exit_stack = AsyncMock()
        client._lock = asyncio.Lock()
        client._session = AsyncMock()

        await client.disconnect()
        assert client.is_connected is False

        await client.disconnect()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect_cleans_session_and_stack(self):
        mock_stack = AsyncMock()
        mock_session = AsyncMock()

        client = CoralClient()
        client._exit_stack = mock_stack
        client._session = mock_session
        client._connected = True
        client._lock = asyncio.Lock()

        await client.disconnect()
        mock_stack.aclose.assert_awaited_once()
        assert client._session is None
        assert client._exit_stack is None

    @pytest.mark.asyncio
    async def test_disconnect_when_exit_stack_aclose_fails(self):
        mock_stack = AsyncMock()
        mock_stack.aclose.side_effect = Exception("cleanup error")

        client = CoralClient()
        client._exit_stack = mock_stack
        client._session = AsyncMock()
        client._connected = True
        client._lock = asyncio.Lock()

        await client.disconnect()
        assert client._session is None
        assert client._exit_stack is None

    @pytest.mark.asyncio
    async def test_disconnect_when_session_is_none(self):
        client = CoralClient()
        client._connected = True
        client._exit_stack = None
        client._session = None
        client._lock = asyncio.Lock()

        await client.disconnect()
        assert client.is_connected is False

    @pytest.mark.asyncio
    @patch("investigator.agent.coral_client.stdio_client")
    @patch("investigator.agent.coral_client.ClientSession")
    @patch("investigator.agent.coral_client.AsyncExitStack")
    async def test_context_manager_disconnects_on_exit(
        self, mock_stack_cls, mock_session_cls, mock_stdio
    ):
        mock_stack = AsyncMock()
        mock_stack_cls.return_value = mock_stack

        mock_read = AsyncMock()
        mock_write = AsyncMock()
        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio.return_value = mock_stdio_cm

        mock_session = AsyncMock()
        mock_session_cls.return_value = mock_session

        mock_stack.enter_async_context = AsyncMock(side_effect=[
            (mock_read, mock_write),
            mock_session,
        ])

        async with CoralClient() as client:
            assert client.is_connected is True

        assert client.is_connected is False
        mock_stack.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_not_connected_noop(self):
        client = CoralClient()
        client._lock = asyncio.Lock()
        await client.disconnect()
        assert client._session is None
        assert client._exit_stack is None


class TestCoralClientContextManager:
    @pytest.mark.asyncio
    @patch("investigator.agent.coral_client.stdio_client")
    @patch("investigator.agent.coral_client.ClientSession")
    @patch("investigator.agent.coral_client.AsyncExitStack")
    async def test_async_context_manager(self, mock_stack_cls, mock_session_cls, mock_stdio):
        mock_stack = AsyncMock()
        mock_stack_cls.return_value = mock_stack

        mock_read = AsyncMock()
        mock_write = AsyncMock()

        mock_stdio_cm = AsyncMock()
        mock_stdio_cm.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio.return_value = mock_stdio_cm

        mock_session = AsyncMock()
        mock_session_cls.return_value = mock_session

        mock_stack.enter_async_context = AsyncMock(side_effect=[
            (mock_read, mock_write),
            mock_session,
        ])

        async with CoralClient() as client:
            assert client.is_connected is True


class TestQueryResultDataclass:
    def test_query_result_defaults(self):
        result = QueryResult(rows=[], row_count=0, columns=[])
        assert result.row_count == 0
        assert result.rows == []
        assert result.columns == []
        assert result.execution_time_ms is None
        assert result.truncated is False

    def test_query_result_with_data(self):
        rows = [{"id": "1", "name": "test"}]
        result = QueryResult(rows=rows, row_count=1, columns=["id", "name"], execution_time_ms=42.5)
        assert result.row_count == 1
        assert result.execution_time_ms == 42.5


class TestCoralError:
    def test_coral_error_with_code_and_details(self):
        error = CoralError("Something broke", QueryErrorCode.TIMEOUT, {"sql": "SELECT 1", "timeout": 30})
        assert error.code == QueryErrorCode.TIMEOUT
        assert error.details["sql"] == "SELECT 1"
        assert "Something broke" in str(error)

    def test_coral_error_default_details(self):
        error = CoralError("Failed", QueryErrorCode.UNKNOWN)
        assert error.details == {}

    def test_coral_error_subclass_of_exception(self):
        error = CoralError("test", QueryErrorCode.UNKNOWN)
        assert isinstance(error, Exception)


@pytest.mark.parametrize("sql,should_pass", [
    ("SELECT 1", True),
    ("select 1", True),
    ("SELECT * FROM tbl WHERE name = 'insert'", True),
    ("SELECT * FROM tbl WHERE name LIKE '%DROP%'", True),
    ("WITH cte AS (SELECT 1) SELECT * FROM cte", True),
    ("\nSELECT\n* FROM tbl", True),
    ("INSERT INTO tbl VALUES (1)", False),
    ("DROP TABLE tbl", False),
    ("DELETE FROM tbl", False),
    ("ALTER TABLE tbl ADD c INT", False),
    ("TRUNCATE TABLE tbl", False),
    ("CREATE TABLE t (i INT)", False),
    ("EXEC sp_help", False),
    ("EXECUTE sp_help", False),
    ("CALL some_proc()", False),
    ("MERGE INTO t USING s ON 1=1 WHEN MATCHED THEN UPDATE", False),
    ("RENAME TABLE a TO b", False),
    ("GRANT SELECT ON t TO user", False),
    ("REVOKE SELECT ON t FROM user", False),
    ("COPY t FROM 'file.csv'", False),
    ("REPLACE INTO t VALUES (1)", False),
])
def test_readonly_validator_parametrized(sql, should_pass):
    if should_pass:
        assert ReadOnlyValidator.validate(sql) == sql.strip()
    else:
        with pytest.raises(CoralError) as exc:
            ReadOnlyValidator.validate(sql)
        assert exc.value.code == QueryErrorCode.INVALID_SQL
