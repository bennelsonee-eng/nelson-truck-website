<?php
/**
 * Read-only Titan + Nelson MySQL explorer — for the website rebuild.
 *
 * Upload to TigerTech web root once.  Modes:
 *
 *   ?token=X&list                              → JSON list of every table
 *   ?token=X&describe=tte_rcv390               → JSON column list + row count
 *   ?token=X&table=tte_rcv390                  → CSV dump (capped at MAX_ROWS)
 *   ?token=X&table=tte_rcv390&limit=500        → first 500 rows
 *   ?token=X&table=tte_rcv390&format=json      → JSON instead of CSV
 *   ?token=X&query=SELECT...                   → arbitrary SELECT (capped)
 *
 * SECURITY:
 *   - Long random shared-secret token in EXPECTED_TOKEN
 *   - Read-only: only SELECT / SHOW / DESCRIBE / EXPLAIN allowed
 *   - INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/etc. blocked
 *   - Multiple-statement protection (no chained `;`)
 *   - Hard 50,000-row cap per request
 *   - Logs hits to /tmp/titan_php_access.log if writeable
 *
 * If the token leaks, change EXPECTED_TOKEN and re-upload.
 *
 * Created 2026-04-25, expanded 2026-04-26.  Targets PHP 5.4+.
 * DELETE WHEN MIGRATION IS DONE.
 */

// ======================================================================
// CONFIG
// ======================================================================

$EXPECTED_TOKEN = "ttn-x8e2-9qa1-y3h7-r5b6-mc4f-2026-rebuild";
$MAX_ROWS = 50000;
$BLOCKED_KEYWORDS = array(
    "INSERT", "UPDATE", "DELETE", "REPLACE",
    "CREATE", "DROP", "ALTER", "TRUNCATE", "RENAME",
    "GRANT", "REVOKE",
    "LOAD", "INTO OUTFILE", "INTO DUMPFILE",
    "CALL", "DO", "HANDLER",
    "SET", "USE",
    "LOCK", "UNLOCK",
    "BEGIN", "COMMIT", "ROLLBACK", "START TRANSACTION", "SAVEPOINT",
);

// ======================================================================
// HELPERS — PHP 5 compatible
// ======================================================================

function gp($key, $default = "") {
    return isset($_GET[$key]) ? $_GET[$key] : $default;
}

function srv($key, $default = "?") {
    return isset($_SERVER[$key]) ? $_SERVER[$key] : $default;
}

function send_json($data) {
    header("Content-Type: application/json");
    echo json_encode($data);
    exit;
}

function send_text($status, $msg) {
    http_response_code($status);
    header("Content-Type: text/plain");
    echo $msg . "\n";
    exit;
}

function send_csv_headers($filename) {
    header("Content-Type: text/csv; charset=utf-8");
    header("Content-Disposition: attachment; filename=\"" . $filename . "\"");
    header("Cache-Control: no-store, no-cache, must-revalidate");
    header("Pragma: no-cache");
}

function db_error_response() {
    send_text(500, "Query failed: " . @mysql_error());
}

function ensure_safe_query($sql, $blocked) {
    // Strip /* */ and -- comments first
    $cleaned = preg_replace("#/\\*.*?\\*/#s", "", $sql);
    $cleaned = preg_replace("/--.*?\$/m", "", $cleaned);
    $upper = strtoupper($cleaned);
    if (!preg_match("/^\\s*(SELECT|SHOW|DESCRIBE|EXPLAIN)\\b/", $upper)) {
        send_text(400, "Only SELECT / SHOW / DESCRIBE / EXPLAIN allowed.");
    }
    foreach ($blocked as $kw) {
        if (preg_match('/\\b' . preg_quote($kw, "/") . '\\b/i', $cleaned)) {
            send_text(400, "Blocked keyword in query: " . $kw);
        }
    }
    $stmts = array_filter(array_map("trim", explode(";", $cleaned)));
    if (count($stmts) > 1) {
        send_text(400, "Multiple statements not allowed.");
    }
}

function emit_rows_as_csv($result, $max_rows, $filename) {
    send_csv_headers($filename);
    $out = fopen("php://output", "w");
    $first = true;
    $n = 0;
    while ($row = @mysql_fetch_assoc($result)) {
        if ($first) {
            fputcsv($out, array_keys($row), ",", "\"");
            $first = false;
        }
        fputcsv($out, array_values($row), ",", "\"");
        $n++;
        if ($n >= $max_rows) break;
    }
    fclose($out);
}

function emit_rows_as_json($result, $max_rows) {
    $rows = array();
    $n = 0;
    while ($row = @mysql_fetch_assoc($result)) {
        $rows[] = $row;
        $n++;
        if ($n >= $max_rows) break;
    }
    send_json(array("rows" => $rows, "count" => $n, "truncated" => $n >= $max_rows));
}

// ======================================================================
// AUTH
// ======================================================================

if (gp("token", "") !== $EXPECTED_TOKEN) {
    send_text(403, "Forbidden");
}

// ======================================================================
// LOG (best effort)
// ======================================================================

$log_line = sprintf("[%s] ip=%s qs=%s\n",
    date("Y-m-d H:i:s"),
    srv("REMOTE_ADDR"),
    substr(srv("QUERY_STRING", ""), 0, 500));
@file_put_contents("/tmp/titan_php_access.log", $log_line, FILE_APPEND | LOCK_EX);

// ======================================================================
// DB CONNECT (legacy mysql_* extension; TigerTech still ships PHP 5)
// ======================================================================

$db = @mysql_connect("localhost", "nelsontruck1", "91chicken5", false, 128);
if (!$db) send_text(500, "DB connection failed");
@mysql_select_db("nelsontruck1");
@mysql_query("SET NAMES utf8");

// ======================================================================
// DISPATCH
// ======================================================================

// MODE: list all tables
if (isset($_GET["list"])) {
    $r = @mysql_query("SHOW TABLES");
    if (!$r) db_error_response();
    $tables = array();
    while ($row = @mysql_fetch_array($r, MYSQL_NUM)) {
        $tables[] = $row[0];
    }
    sort($tables);
    send_json(array("count" => count($tables), "tables" => $tables));
}

// MODE: describe a table
$describe = gp("describe", "");
if ($describe !== "") {
    if (!preg_match('/^[A-Za-z0-9_]+$/', $describe)) send_text(400, "Bad table name");
    $r = @mysql_query("SHOW COLUMNS FROM `" . $describe . "`");
    if (!$r) db_error_response();
    $cols = array();
    while ($row = @mysql_fetch_assoc($r)) $cols[] = $row;

    $row_count = null;
    $cr = @mysql_query("SELECT COUNT(*) AS n FROM `" . $describe . "`");
    if ($cr) {
        $cw = @mysql_fetch_assoc($cr);
        $row_count = isset($cw["n"]) ? intval($cw["n"]) : null;
    }
    send_json(array("table" => $describe, "row_count" => $row_count, "columns" => $cols));
}

// MODE: arbitrary SELECT query
$query = gp("query", "");
if ($query !== "") {
    ensure_safe_query($query, $BLOCKED_KEYWORDS);
    $r = @mysql_query($query);
    if (!$r) db_error_response();

    $format = gp("format", "json");
    $limit = intval(gp("limit", $MAX_ROWS));
    if ($limit < 1) $limit = 1;
    if ($limit > $MAX_ROWS) $limit = $MAX_ROWS;

    if ($format === "csv") {
        emit_rows_as_csv($r, $limit, "query_" . date("Ymd_His") . ".csv");
    } else {
        emit_rows_as_json($r, $limit);
    }
    exit;
}

// MODE: dump a table
$table = gp("table", "");
if ($table === "" || !preg_match('/^[A-Za-z0-9_]+$/', $table)) {
    send_text(400,
        "Usage:\n" .
        "  ?token=X&list\n" .
        "  ?token=X&describe=tablename\n" .
        "  ?token=X&table=tablename [&limit=N] [&format=json|csv]\n" .
        "  ?token=X&query=SELECT... [&limit=N] [&format=json|csv]"
    );
}

$limit = intval(gp("limit", $MAX_ROWS));
if ($limit < 1) $limit = 1;
if ($limit > $MAX_ROWS) $limit = $MAX_ROWS;
$format = gp("format", "csv");

$sql = "SELECT * FROM `" . $table . "` LIMIT " . $limit;
$r = @mysql_query($sql);
if (!$r) db_error_response();

if ($format === "json") {
    emit_rows_as_json($r, $limit);
} else {
    emit_rows_as_csv($r, $limit, $table . "_" . date("Ymd_His") . ".csv");
}
@mysql_free_result($r);
@mysql_close($db);
