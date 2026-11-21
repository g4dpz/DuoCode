#!/usr/bin/env python3
# Specification verification (not application code and not a migration).
# It extracts the DDL from database-schema.md, applies it to a throwaway PostgreSQL cluster,
# and tests the constraints and the SQL statements the specification relies on:
# nickname rules, guess limits, one rematch ever, rate-limit buckets, cleanup, and the durable
# key-usage reservation counter (rollback, crash, concurrency, restore).
#
# Usage:
#   python3 verify-schema.py --server-bin /path/to/pg/bin [--psql /path/to/psql]
# --server-bin must contain initdb, pg_ctl and postgres of the version under test.
# Exit code 0 only when every test passed.
import argparse, json, os, random, re, shutil, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--server-bin", required=True)
ap.add_argument("--psql", default="psql")
ap.add_argument("--port", type=int, default=54343)
ap.add_argument("--pg-dump", default=None, help="pg_dump of the SAME major version as the server (default: <server-bin>/pg_dump if present)")
ap.add_argument("--pg-restore", default=None, help="pg_restore of the same major version (default: <server-bin>/pg_restore if present)")
args = ap.parse_args()

work = Path(tempfile.mkdtemp(prefix="dcv_", dir="/tmp"))
data = work / "data"
sock = work
PORT = args.port
SB = Path(args.server_bin)
env = dict(os.environ)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, env=env, **kw)


def psql_cmd(db):
    return [args.psql, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-h", str(sock), "-p", str(PORT), "-U", "tester", "-d", db]


def sql(text, db="dc", expect_error=None):
    r = run(psql_cmd(db) + ["-f", "-"], input=text)
    if expect_error is None:
        if r.returncode != 0:
            raise AssertionError(f"SQL failed: {r.stderr.strip()[:300]}")
        return r.stdout.strip()
    if r.returncode == 0:
        raise AssertionError(f"expected error containing {expect_error!r}, but statement succeeded: {text[:80]!r}")
    if expect_error not in r.stderr:
        raise AssertionError(f"expected {expect_error!r} in error, got: {r.stderr.strip()[:300]}")
    return r.stderr.strip()


def start():
    r = run([str(SB / "pg_ctl"), "-D", str(data), "-o", f"-p {PORT} -k {sock} -c listen_addresses=''", "-l", str(work / "log"), "-w", "start"])
    assert r.returncode == 0, r.stderr + r.stdout


def stop():
    run([str(SB / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"])


def ddl():
    text = (HERE / "database-schema.md").read_text()
    return re.findall(r"```sql\n(.*?)```", text, re.S)


G1 = "00000000-0000-0000-0000-0000000000"  # uuid prefix helper


def u(n):
    return f"00000000-0000-0000-0000-{n:012d}"


results = []


def test(name):
    def deco(fn):
        try:
            fn()
            results.append((name, True, ""))
        except Exception as e:  # noqa
            results.append((name, False, str(e)))
        return fn
    return deco


def reset_data():
    sql("TRUNCATE games, players, credentials, secret_codes, guesses, idempotency_keys, token_rotations, rematch_markers, game_results, rate_limits, key_usage CASCADE;")


def new_game(n, state="ACTIVE"):
    sql(f"INSERT INTO games(id,state,config,expires_at) VALUES ('{u(n)}','{state}','{{}}',now()+interval '1 day');")


def new_player(n, game, seat, nick="Ann"):
    sql(f"INSERT INTO players(id,game_id,seat,nickname) VALUES ('{u(n)}','{u(game)}',{seat},$${nick}$$);")


# ---------------------------------------------------------------------------
init = run([str(SB / "initdb"), "-D", str(data), "-U", "tester", "-E", "UTF8", "--locale=C"])
if init.returncode != 0:
    print("initdb failed:", init.stderr)
    sys.exit(2)
start()
try:
    sql("CREATE DATABASE dc;", db="postgres")
    version = sql("SHOW server_version;")
    blocks = ddl()
    sql(blocks[0])

    # ----- constraints ------------------------------------------------------
    @test("DDL applies to an empty database")
    def _():
        assert sql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public';") == "12"

    @test("at most two seats per game, seat 3 rejected")
    def _():
        reset_data(); new_game(1); new_player(11, 1, 1); new_player(12, 1, 2)
        sql(f"INSERT INTO players(id,game_id,seat,nickname) VALUES ('{u(13)}','{u(1)}',3,'x');", expect_error="players_seat_check")
        sql(f"INSERT INTO players(id,game_id,seat,nickname) VALUES ('{u(14)}','{u(1)}',2,'dup');", expect_error="players_game_id_seat_key")

    @test("nickname: 24 code points accepted, 25 rejected, counted in code points")
    def _():
        reset_data(); new_game(1)
        new_player(11, 1, 1, "😀" * 24)
        sql(f"INSERT INTO players(id,game_id,seat,nickname) VALUES ('{u(12)}','{u(1)}',2,$${'é' * 25}$$);", expect_error="players_nickname_check")

    @test("nickname: control characters rejected")
    def _():
        reset_data(); new_game(1)
        for cp in (0x09, 0x0A, 0x1F, 0x7F, 0x80, 0x9F):
            sql(f"INSERT INTO players(id,game_id,seat,nickname) VALUES ('{u(12)}','{u(1)}',2,'a'||chr({cp})||'b');", expect_error="nickname_check")

    @test("nickname: bidi embedding, override and isolate controls rejected (RD-5)")
    def _():
        reset_data(); new_game(1)
        for cp in list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A)):
            sql(f"INSERT INTO players(id,game_id,seat,nickname) VALUES ('{u(12)}','{u(1)}',2,'a'||chr({cp})||'b');", expect_error="nickname_check")

    @test("nickname: LRM, RLM, ALM, ZWNJ, ZWJ, emoji sequence and Arabic accepted (CH-1)")
    def _():
        reset_data(); new_game(1)
        samples = ["x\u200Ey", "x\u200Fy", "x\u061Cy", "a\u200Cb", "a\u200Db", "👨\u200D👩\u200D👧", "مرحبا بالعالم"]
        for i, nick in enumerate(samples):
            sql("DELETE FROM players;")
            sql(f"INSERT INTO players(id,game_id,seat,nickname) VALUES ('{u(20)}','{u(1)}',1,$${nick}$$);")

    @test("guess chain: no gap, no duplicate, no guess after a solving guess")
    def _():
        reset_data(); new_game(1); new_player(11, 1, 1)
        ins = lambda n, e, m=0: f"INSERT INTO guesses(player_id,guess_number,key_id,guess_ciphertext,exact,misplaced) VALUES ('{u(11)}',{n},1,decode(repeat('0{n % 10}',32),'hex'),{e},{m});"
        sql(ins(2, 0), expect_error="guesses_player_id_prev_guess_number_prev_solved_fkey")
        sql(ins(1, 1, 1)); sql(ins(2, 4, 0))
        sql(ins(3, 0), expect_error="guesses_player_id_prev_guess_number_prev_solved_fkey")
        sql(ins(2, 0), expect_error="guesses_player_id_guess_number_key")
        sql(ins(11, 0), expect_error="guesses_guess_number_check")

    @test("ten guesses accepted, the eleventh rejected")
    def _():
        reset_data(); new_game(1); new_player(11, 1, 1)
        for n in range(1, 11):
            sql(f"INSERT INTO guesses(player_id,guess_number,key_id,guess_ciphertext,exact,misplaced) VALUES ('{u(11)}',{n},1,decode(repeat('0a',32),'hex'),0,1);")
        sql(f"INSERT INTO guesses(player_id,guess_number,key_id,guess_ciphertext,exact,misplaced) VALUES ('{u(11)}',11,1,decode(repeat('0a',32),'hex'),0,1);", expect_error="guess_number_check")

    @test("credential bound to a player of its own game; one live access token per player")
    def _():
        reset_data(); new_game(1); new_game(2); new_player(11, 1, 1)
        h = lambda x: f"decode(repeat('{x}',32),'hex')"
        sql(f"INSERT INTO credentials(id,type,game_id,player_id,token_hash) VALUES (gen_random_uuid(),'ACCESS','{u(2)}','{u(11)}',{h('aa')});", expect_error="credentials_player_id_game_id_fkey")
        sql(f"INSERT INTO credentials(id,type,game_id,player_id,token_hash) VALUES (gen_random_uuid(),'ACCESS','{u(1)}','{u(11)}',{h('ab')});")
        sql(f"INSERT INTO credentials(id,type,game_id,player_id,token_hash) VALUES (gen_random_uuid(),'ACCESS','{u(1)}','{u(11)}',{h('ac')});", expect_error="credentials_one_access_per_player")

    @test("one rematch ever: second marker rejected, also after the rematch game is deleted")
    def _():
        reset_data(); new_game(1, "WAITING_FOR_PLAYER"); new_game(2, "WAITING_FOR_PLAYER")
        sql(f"INSERT INTO rematch_markers(original_game_id,rematch_game_id) VALUES ('{u(1)}','{u(2)}');")
        sql(f"INSERT INTO rematch_markers(original_game_id) VALUES ('{u(1)}');", expect_error="rematch_markers_pkey")
        sql(f"DELETE FROM games WHERE id='{u(2)}';")
        assert sql("SELECT count(*)||':'||coalesce(max(rematch_game_id::text),'null') FROM rematch_markers;") == "1:null"
        sql(f"INSERT INTO rematch_markers(original_game_id) VALUES ('{u(1)}');", expect_error="rematch_markers_pkey")

    @test("deleting the original removes the marker, the rematch game survives")
    def _():
        reset_data(); new_game(1, "WAITING_FOR_PLAYER"); new_game(2, "WAITING_FOR_PLAYER")
        sql(f"INSERT INTO rematch_markers(original_game_id,rematch_game_id) VALUES ('{u(1)}','{u(2)}');")
        sql(f"DELETE FROM games WHERE id='{u(1)}';")
        assert sql("SELECT (SELECT count(*) FROM rematch_markers)||':'||(SELECT count(*) FROM games);") == "0:1"

    @test("idempotency: one key per guess and one guess per key")
    def _():
        reset_data(); new_game(1); new_player(11, 1, 1)
        sql(f"INSERT INTO guesses(player_id,guess_number,key_id,guess_ciphertext,exact,misplaced) VALUES ('{u(11)}',1,1,decode(repeat('01',32),'hex'),0,0);")
        gid = sql("SELECT id FROM guesses;")
        ins = lambda k: f"INSERT INTO idempotency_keys(player_id,key,guess_id,fingerprint,fingerprint_key_id,response_status,response_body) VALUES ('{u(11)}','{k}',{gid},decode(repeat('00',32),'hex'),1,201,'{{}}');"
        sql(ins(u(100)))
        sql(ins(u(100)), expect_error="idempotency_keys_pkey")
        sql(ins(u(101)), expect_error="idempotency_keys_guess_id_key")

    @test("rotation record: one per key and one per old credential")
    def _():
        reset_data(); new_game(1); new_player(11, 1, 1)
        h = lambda x: f"decode(repeat('{x}',32),'hex')"
        sql(f"INSERT INTO credentials(id,type,game_id,player_id,token_hash,revoked_at,revoked_reason) VALUES ('{u(50)}','ACCESS','{u(1)}','{u(11)}',{h('01')},now(),'ROTATED'),('{u(51)}','ACCESS','{u(1)}','{u(11)}',{h('02')},NULL,NULL);")
        ins = lambda i, k: f"INSERT INTO token_rotations(id,game_id,player_id,idempotency_key,from_credential_id,to_credential_id,fingerprint,replay_until) VALUES ('{u(i)}','{u(1)}','{u(11)}','{k}','{u(50)}','{u(51)}',{h('03')},now()+interval '10 minutes');"
        sql(ins(60, u(70)))
        sql(ins(61, u(70)), expect_error="token_rotations")
        sql(ins(62, u(71)), expect_error="token_rotations")

    @test("game result at most once; completed state needs completion time")
    def _():
        reset_data()
        sql(f"INSERT INTO games(id,state,config,expires_at) VALUES ('{u(1)}','COMPLETED','{{}}',now());", expect_error="games_check")

    # ----- statements -------------------------------------------------------
    RL = ("INSERT INTO rate_limits (scope, subject, tokens, refilled_at) VALUES ('t', decode(repeat('01',32),'hex'), {cap} - 1, clock_timestamp()) "
          "ON CONFLICT (scope, subject) DO UPDATE SET tokens = LEAST({cap}, rate_limits.tokens + EXTRACT(EPOCH FROM (clock_timestamp() - rate_limits.refilled_at)) * {refill}) - 1, "
          "refilled_at = clock_timestamp() WHERE LEAST({cap}, rate_limits.tokens + EXTRACT(EPOCH FROM (clock_timestamp() - rate_limits.refilled_at)) * {refill}) >= 1 RETURNING tokens;")

    @test("rate-limit bucket: allows capacity, denies the next, refills")
    def _():
        reset_data()
        outs = [sql(RL.format(cap=3, refill=0)) for _ in range(4)]
        assert outs[:3] == ["2", "1", "0"] and outs[3] == "", outs
        time.sleep(0.02)
        assert sql(RL.format(cap=3, refill=1000)) != ""

    @test("rate-limit bucket: 40 parallel requests against capacity 10 allow exactly 10")
    def _():
        reset_data()
        with ThreadPoolExecutor(40) as ex:
            outs = list(ex.map(lambda _: sql(RL.format(cap=10, refill=0)), range(40)))
        allowed = sum(1 for o in outs if o != "")
        assert allowed == 10, allowed

    @test("cleanup statement deletes only games with expires_at <= now (>= rule), cascades, and is repeatable")
    def _():
        reset_data()
        sql(f"INSERT INTO games(id,state,config,expires_at) VALUES ('{u(1)}','ACTIVE','{{}}',now()),('{u(2)}','ACTIVE','{{}}',now()+interval '1 hour'),('{u(3)}','ACTIVE','{{}}',now()-interval '1 day');")
        new_player(11, 1, 1)
        cleanup_block = next(b for b in blocks if "WITH batch AS" in b)
        stmt = cleanup_block.split("-- Maintenance")[0].split("\n", 1)[1].replace("$1", "200")
        first = sql(stmt)
        assert set(first.split("\n")) == {u(1), u(3)}, first
        assert sql(stmt) == ""
        assert sql("SELECT count(*) FROM games;") == "1" and sql("SELECT count(*) FROM players;") == "0"

    @test("maintenance statements (rotation ciphertext clearing, idle rate-limit rows) run")
    def _():
        reset_data()
        sql("UPDATE token_rotations SET token_ciphertext = NULL, token_key_id = NULL WHERE token_ciphertext IS NOT NULL AND replay_until <= clock_timestamp();")
        sql(RL.format(cap=3, refill=0)); sql("UPDATE rate_limits SET refilled_at = now() - interval '2 hours';")
        sql("DELETE FROM rate_limits WHERE ctid IN (SELECT ctid FROM rate_limits WHERE refilled_at < clock_timestamp() - interval '1 hour' FOR UPDATE SKIP LOCKED);")
        assert sql("SELECT count(*) FROM rate_limits;") == "0"

    # ----- key usage reservation: strict global hard stop (RD-10, RD-13, CR-9) -----------------
    # The statements below are TAKEN FROM database-schema.md, so the specification and the test cannot drift apart.
    spec_text = (HERE / "database-schema.md").read_text()
    reserve_sql = next(b for b in blocks if "UPDATE key_usage" in b and "RETURNING reserved" in b)
    register_sql = next(b for b in blocks if "INSERT INTO key_usage (key_id) VALUES ($1)" in b)
    seal_sql = re.search(r"`(INSERT INTO key_usage \(key_id, reserved, sealed\) VALUES \(\$1, 1073741824, true\) ON CONFLICT \(key_id\) DO UPDATE SET reserved = 1073741824, sealed = true;)`", spec_text).group(1)
    check_sql = next(b for b in blocks if "SELECT NOT sealed AS usable FROM key_usage" in b)
    L = 2 ** 30
    BLOCK = 1024

    def reserve(k, block=BLOCK, limit=L):
        """The real reservation statement on its own connection. Returns the new total, or None if refused."""
        text = reserve_sql.replace("$1", str(k)).replace("$2", str(block)).replace("$3", str(limit))
        out = sql(text)
        return int(out) if out else None

    def register(k):
        sql(register_sql.replace("$1", str(k)))

    def seal(k):
        sql(seal_sql.replace("$1", str(k)))

    def usable(k):
        """The pre-encryption check taken from the specification. No row (unregistered key) counts as unusable."""
        return sql(check_sql.replace("$1", str(k))) == "t"

    def R(k=1):
        out = sql(f"SELECT coalesce(sum(reserved),0) FROM key_usage WHERE key_id={k};")
        return int(out)

    def set_R(k, v):
        sql(f"INSERT INTO key_usage(key_id, reserved) VALUES ({k},{v}) ON CONFLICT (key_id) DO UPDATE SET reserved = EXCLUDED.reserved;")

    class Refused(Exception):
        pass

    class Instance:
        """Model of ONE application instance's allowance. Reservations go to the real PostgreSQL statement."""
        def __init__(self, key=1, block=BLOCK, limit=L):
            self.key, self.block, self.limit = key, block, limit
            self.allowance = 0
            self.invocations = 0

        def reserve_block(self):
            total = reserve(self.key, self.block, self.limit)
            if total is None:
                raise Refused()
            self.allowance += self.block
            return total

        def request(self):
            """One encrypting request: the pre-encryption check first (spec statement), then the invocation."""
            if not usable(self.key):
                raise Refused()
            self.encrypt()

        def encrypt(self):
            if self.allowance == 0:
                self.reserve_block()          # raises Refused when the hard stop is reached
            self.allowance -= 1               # every invocation consumes a unit, committed or not
            self.invocations += 1

    @test("key_usage: one row per key, CHECK at 2^30, negative and over-limit values rejected")
    def _():
        reset_data()
        register(1); register(1)              # idempotent
        assert sql("SELECT count(*) FROM key_usage;") == "1"
        sql(f"INSERT INTO key_usage(key_id, reserved) VALUES (1, 5);", expect_error="key_usage_pkey")
        sql(f"UPDATE key_usage SET reserved = {L + 1} WHERE key_id = 1;", expect_error="key_usage_reserved_check")
        sql("UPDATE key_usage SET reserved = -1 WHERE key_id = 1;", expect_error="key_usage_reserved_check")
        set_R(1, L)                           # exactly 2^30 is allowed

    @test("hard stop: a reservation that takes R exactly to 2^30 is granted, the next is refused")
    def _():
        reset_data(); set_R(1, L - BLOCK)
        assert reserve(1) == L
        assert reserve(1) is None and R() == L

    @test("hard stop: a reservation that would go beyond 2^30 is refused whole and changes nothing")
    def _():
        reset_data(); set_R(1, L - BLOCK // 2)
        assert reserve(1) is None and R() == L - BLOCK // 2
        set_R(1, L - 1)
        assert reserve(1) is None and R() == L - 1
        assert reserve(1, block=1) == L        # a smaller block that fits is granted

    @test("reservation under an unregistered key is refused")
    def _():
        reset_data()
        assert reserve(7) is None

    @test("concurrent instances: 16 then 32 connections reserve against one key; exactly the available blocks are granted, R never above 2^30")
    def _():
        for workers, available in ((16, 40), (32, 64)):
            reset_data(); set_R(1, L - available * BLOCK)
            granted = []
            stop = {"v": False}
            seen_max = {"v": 0}

            def sampler():
                while not stop["v"]:
                    seen_max["v"] = max(seen_max["v"], R())
                    time.sleep(0.005)

            def instance(i):
                n = 0
                for _ in range(available + 5):
                    if reserve(1) is None:
                        break
                    n += 1
                return n

            with ThreadPoolExecutor(workers + 1) as ex:
                sf = ex.submit(sampler)
                try:
                    counts = list(ex.map(instance, range(workers)))
                finally:
                    stop["v"] = True              # a failing worker must never leave the sampler running (CR-11)
                sf.result()
            assert sum(counts) == available, (workers, sum(counts), available)
            assert R() == L, R()
            assert seen_max["v"] <= L, seen_max

    def session(cmds):
        a = subprocess.Popen(psql_cmd("dc"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        a.stdin.write(cmds + "\nSELECT 'ready';\n"); a.stdin.flush()
        while True:
            line = a.stdout.readline()
            assert line != "", "session ended early: " + a.stderr.read()[:200]
            if "ready" in line:
                return a

    def finish(a, cmds=""):
        a.stdin.write(cmds + "\n\\q\n"); a.stdin.flush()
        out, err = a.communicate(timeout=30)
        return out.strip()

    @test("negative control: the REPLACED 32-shard design overshoots the limit with two instances (why it was replaced)")
    def _():
        reset_data()
        sql("DROP TABLE IF EXISTS old_key_usage; CREATE TABLE old_key_usage(key_id smallint, shard smallint, reserved bigint, PRIMARY KEY(key_id, shard));")
        sql(f"INSERT INTO old_key_usage VALUES (1, 0, {L - BLOCK});")           # room for exactly one more block
        chk = f"SELECT CASE WHEN sum(reserved) + {BLOCK} <= {L} THEN 'room' ELSE 'full' END FROM old_key_usage WHERE key_id=1;"
        A = session("BEGIN;\n" + chk)
        B = session("BEGIN;\n" + chk)                                          # both saw room
        add = lambda sh: f"INSERT INTO old_key_usage VALUES (1,{sh},{BLOCK}) ON CONFLICT (key_id, shard) DO UPDATE SET reserved = old_key_usage.reserved + EXCLUDED.reserved;"
        finish(A, add(1) + "\nCOMMIT;")
        finish(B, add(2) + "\nCOMMIT;")                                        # different shards, so no lock conflict
        total = int(sql("SELECT sum(reserved) FROM old_key_usage;"))
        assert total == L + BLOCK, total                                        # the old design exceeded 2^30
        sql("DROP TABLE old_key_usage;")

    @test("the same interleaving with the real statement: the second reservation waits, re-checks, and is refused")
    def _():
        reset_data(); set_R(1, L - BLOCK)
        A = session("BEGIN;\n" + reserve_sql.replace("$1", "1").replace("$2", str(BLOCK)).replace("$3", str(L)))   # A holds the row lock, uncommitted
        try:
            with ThreadPoolExecutor(1) as ex:
                fut = ex.submit(reserve, 1)                                     # B blocks on the row lock
                time.sleep(1.0)
                waited = not fut.done()
                finish(A, "COMMIT;"); A = None                                  # always release A, even if the assertion below fails (CR-11)
                assert fut.result(timeout=30) is None                           # B re-evaluated against the committed total and was refused
                assert waited, "B did not wait for A: the reservations are not serialised"
        finally:
            if A is not None:
                finish(A, "ROLLBACK;")
        assert R() == L

    @test("outstanding allowance: A holds a block, B takes the last block, C is refused, nobody exceeds the units reserved")
    def _():
        reset_data(); start_R = L - 2 * BLOCK; set_R(1, start_R)
        A, B, C = Instance(), Instance(), Instance()
        A.reserve_block()                                  # A holds 1024 unused units
        B.reserve_block()                                  # B takes the last block, R == 2^30
        assert R() == L
        try:
            C.reserve_block(); raise AssertionError("C should have been refused")
        except Refused:
            pass
        for _ in range(BLOCK): A.encrypt()
        for _ in range(BLOCK): B.encrypt()
        for inst in (A, B):
            try:
                inst.encrypt(); raise AssertionError("an instance encrypted without a reserved unit")
            except Refused:
                pass
        invocations = A.invocations + B.invocations
        assert invocations == 2 * BLOCK == R() - start_R and R() == L

    @test("failed and rolled-back transactions still consume units (real rolled-back transactions)")
    def _():
        reset_data(); register(1)
        inst = Instance()
        for i in range(60):
            inst.encrypt()                                 # consumed at the invocation
            sql(f"BEGIN; INSERT INTO games(id,state,config,expires_at) VALUES ('{u(i + 1)}','ACTIVE','{{}}',now()); ROLLBACK;")
        assert sql("SELECT count(*) FROM games;") == "0"
        assert inst.invocations == 60 and R() >= inst.invocations and R() == BLOCK

    @test("reservation is not undone when another connection's application transaction rolls back")
    def _():
        reset_data(); register(1)
        a = subprocess.Popen(psql_cmd("dc"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        a.stdin.write("BEGIN;\n"); a.stdin.write(f"INSERT INTO games(id,state,config,expires_at) VALUES ('{u(1)}','ACTIVE','{{}}',now());\n"); a.stdin.write("SELECT 'ready';\n"); a.stdin.flush()
        assert "ready" in a.stdout.readline()
        assert reserve(1) == BLOCK                         # separate connection, own transaction, commits
        a.stdin.write("ROLLBACK;\n\\q\n"); a.stdin.flush(); a.wait(timeout=20)
        assert R() == BLOCK and sql("SELECT count(*) FROM games;") == "0"

    @test("reservation survives an application transaction aborted by an error")
    def _():
        reset_data(); register(1)
        cmd = [c if c != "ON_ERROR_STOP=1" else "ON_ERROR_STOP=0" for c in psql_cmd("dc")]
        a = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        a.stdin.write("BEGIN;\nSELECT 1/0;\nSELECT 'ready';\n"); a.stdin.flush()
        assert reserve(1) == BLOCK
        a.stdin.write("ROLLBACK;\n\\q\n"); a.stdin.flush(); a.communicate(timeout=20)
        assert R() == BLOCK

    @test("crash and restart with an unused allowance: the counter does not decrease and still covers every invocation")
    def _():
        reset_data(); register(1)
        a = Instance()
        for _ in range(10): a.encrypt()
        before = R()
        del a                                              # crash: the 1014 unused units are lost, but stay counted
        assert R() == before == BLOCK
        b = Instance()
        for _ in range(5): b.encrypt()                     # restarted instance reserves a fresh block
        assert R() == 2 * BLOCK and 15 <= R()

    @test("eight instances, 100 reservations each, no lost increment")
    def _():
        reset_data(); register(1)
        def instance(i):
            for _ in range(100):
                assert reserve(1) is not None
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(instance, range(8)))
        assert R() == 8 * 100 * BLOCK

    @test("thresholds with the real statement: warning, rotation overdue (still granted), then refusal at the hard stop")
    def _():
        reset_data(); register(1)
        hard, warn, rot = 10 * BLOCK, 3 * BLOCK, 6 * BLOCK
        states, granted = [], 0
        for _ in range(12):
            total = reserve(1, BLOCK, hard)
            if total is None:
                states.append("refused"); continue
            granted += 1
            states.append("overdue" if total >= rot else "warning" if total >= warn else "ok")
        assert granted == 10 and R() == hard
        assert states[0] == "ok" and "warning" in states and "overdue" in states
        assert states[5:10] == ["overdue"] * 5, states           # reservations still granted between 2^28 and 2^30 (RD-14)
        assert states[10:] == ["refused", "refused"], states

    @test("start-up validation rule: hard stop <= 2^30, multiple of the block, WARN <= ROTATE <= HARD")
    def _():
        def valid(warn, rot, hard, block):
            return warn <= rot <= hard <= L and block >= 1 and hard % block == 0 and block <= 2 ** 20 and L % block == 0
        assert valid(2 ** 27, 2 ** 28, L, 1024)
        assert not valid(2 ** 27, 2 ** 28, L + 1024, 1024)
        assert not valid(2 ** 27, 2 ** 28, L - 1, 1024)
        assert not valid(2 ** 29, 2 ** 28, L, 1024)
        assert not valid(2 ** 27, 2 ** 28, L, 0) and not valid(2 ** 27, 2 ** 28, L, -1024)

    @test("policy model: R is never below actual encryptions under random interleavings, rollbacks and crashes")
    def _():
        rnd = random.Random(2026)
        B = 8
        for trial in range(300):
            db_total, performed = 0, 0
            inst = [{"allow": 0} for _ in range(rnd.randrange(1, 6))]
            for step in range(rnd.randrange(50, 300)):
                i = rnd.choice(inst)
                op = rnd.choices(["encrypt", "rollback_after_encrypt", "crash", "reserve_unknown"], [6, 3, 1, 1])[0]
                if op in ("encrypt", "rollback_after_encrypt"):
                    if i["allow"] < 1:
                        db_total += B; i["allow"] += B
                    i["allow"] -= 1; performed += 1
                elif op == "crash":
                    i["allow"] = 0
                else:
                    db_total += B
                assert db_total >= performed, (trial, step, db_total, performed)

    @test("invariant check: rows under a key cannot exceed R; a lowered counter is detected")
    def _():
        reset_data(); new_game(1); new_player(11, 1, 1); new_player(12, 1, 2)
        register(1); assert reserve(1) == BLOCK
        sql(f"INSERT INTO secret_codes(player_id,key_id,ciphertext) VALUES ('{u(11)}',1,decode(repeat('01',32),'hex')),('{u(12)}',1,decode(repeat('02',32),'hex'));")
        inv = ("SELECT (SELECT count(*) FROM secret_codes WHERE key_id=1) + (SELECT count(*) FROM guesses WHERE key_id=1) "
               "+ (SELECT count(*) FROM token_rotations WHERE token_key_id=1) <= (SELECT coalesce(sum(reserved),0) FROM key_usage WHERE key_id=1);")
        assert sql(inv) == "t"
        sql("UPDATE key_usage SET reserved = 1;")
        assert sql(inv) == "f"

    @test("zero and negative reservations match no row and change nothing; no statement can lower the counter (CR-11)")
    def _():
        reset_data(); register(1); set_R(1, BLOCK)
        for units in (0, -1, -BLOCK, -10 * BLOCK):
            assert reserve(1, block=units) is None and R() == BLOCK, units

    @test("whole blocks sized to the operation: a block of 1 still gets 22 units in one statement; no partial grant near the limit (CR-11)")
    def _():
        reset_data(); register(1)
        assert reserve(1, block=22) == 22 and R() == 22
        set_R(1, L - 10)
        assert reserve(1, block=22) is None and R() == L - 10           # refused whole, nothing changes
        assert reserve(1, block=10) == L                                # the exact remainder fits

    @test("sealing a key whose row is missing inserts a sealed row; a later registration cannot reset it (CR-11)")
    def _():
        reset_data()
        assert sql("SELECT count(*) FROM key_usage WHERE key_id = 7;") == "0"
        seal(7)
        assert R(7) == L and usable(7) is False and reserve(7) is None
        register(7)                                                     # ON CONFLICT DO NOTHING: stays sealed
        assert R(7) == L and usable(7) is False and reserve(7) is None

    @test("atomic claims: with one unit left and 16 racing requests on one instance exactly one claims it, the rest defer (CR-11 model, real reservation)")
    def _():
        import threading
        reset_data(); register(1)
        lock = threading.Lock()                  # models the single-threaded synchronous claim step of one process
        allowance = {"v": 1}
        claimed, deferred, consumed = [], [], []
        def request(i):
            with lock:
                if allowance["v"] >= 1:
                    allowance["v"] -= 1; claimed.append(i); got = True
                else:
                    deferred.append(i); got = False
            if got:
                consumed.append(i)               # the claimed unit is used by exactly this request
        with ThreadPoolExecutor(16) as ex:
            list(ex.map(request, range(16)))
        assert len(claimed) == 1 and len(deferred) == 15 and len(consumed) == 1 and allowance["v"] == 0
        with lock:                               # an operation that ends without encrypting returns its claim
            allowance["v"] += 1
        assert allowance["v"] == 1

    @test("sealing: the old key is refused for ever, sealing never lowers a counter, is idempotent, and sealed forces the counter to 2^30")
    def _():
        reset_data(); register(1); assert reserve(1) == BLOCK
        before = R()
        seal(1)
        assert R() == L >= before and reserve(1) is None
        seal(1); assert R() == L
        register(2)
        sql("UPDATE key_usage SET sealed = true WHERE key_id = 2;", expect_error="key_usage_check")   # sealed without the counter at 2^30

    @test("pre-encryption check: unsealed key usable, sealed key not usable, unregistered key not usable")
    def _():
        reset_data(); register(1)
        assert usable(1) is True
        assert usable(9) is False                      # no row
        seal(1)
        assert usable(1) is False

    @test("rotation completed AFTER 2^28: a stale allowance cannot be used by any request that begins after the seal; unused units stay counted (RD-14, CR-10)")
    def _():
        reset_data(); register(1); set_R(1, 2 ** 28 + 5 * BLOCK)          # key already past the rotation threshold
        A = Instance(key=1)
        A.request()                                       # A reserves a block and holds 1023 unused units
        assert A.allowance == BLOCK - 1 and reserve(1) is not None       # reservations were still granted past 2^28 (RD-14)
        before_seal = R()
        register(2); seal(1)                              # rotation completes: new key registered, old key sealed
        assert R() == L and R() >= before_seal            # unused reservations stay counted, the counter never decreased
        try:
            A.request(); raise AssertionError("A encrypted under the sealed key although it still held an allowance")
        except Refused:
            pass
        assert A.allowance == BLOCK - 1                   # the allowance is untouched but unusable
        try:
            A.reserve_block(); raise AssertionError("a reservation was granted under the sealed key")
        except Refused:
            pass
        fresh = Instance(key=2)                           # a restarted instance with the new ring has no allowance and uses the new key
        assert fresh.allowance == 0
        fresh.request(); assert R(2) == BLOCK and R(1) == L
        assert A.invocations <= before_seal               # every invocation under key 1 was covered by reserved units

    @test("restore hazard and recovery: restored counter is behind, sealing the old key and registering a new key stops it resuming (RD-13)")
    def _():
        reset_data(); register(1); assert reserve(1) == BLOCK
        stop(); backup = work / "backup"
        shutil.copytree(data, backup); start()
        before_backup = R()
        for _ in range(5): assert reserve(1) is not None   # encryptions reserved after the backup
        pre_restore = R()
        stop(); shutil.rmtree(data); shutil.copytree(backup, data); start()   # restore
        restored = R()
        assert pre_restore > restored == before_backup, (pre_restore, restored, before_backup)
        def must_activate_new_key(pre, rest):
            return not (pre is not None and pre <= rest)
        assert must_activate_new_key(pre_restore, restored) and not must_activate_new_key(restored, restored) and must_activate_new_key(None, restored)
        # without the procedure the restored counter would let the old key resume: prove the hazard
        assert reserve(1) is not None
        # the procedure: new key registered and sealing of every older key, even though the (model) ring wrongly still lists key 1 as active
        register(2); seal(1)
        ring_wrongly_active = Instance(key=1)
        try:
            ring_wrongly_active.request(); raise AssertionError("encryption resumed under the sealed key")
        except Refused:
            pass
        new_inst = Instance(key=2)
        new_inst.encrypt()
        assert R(2) == BLOCK and R(1) == L


    @test("restore that goes back past a key's registration: the newest ring still lets us seal that key, and the next identifier is above highestKeyId (CR-11)")
    def _():
        reset_data(); register(1); assert reserve(1) == BLOCK
        stop(); backup = work / "backup2"
        shutil.copytree(data, backup); start()
        register(2); assert reserve(2) == BLOCK                       # key 2 registered and used AFTER the backup
        ring_newest = {"generation": 9, "highestKeyId": 2, "keys": {"1": "DECRYPT_ONLY", "2": "ACTIVE"}}
        stop(); shutil.rmtree(data); shutil.copytree(backup, data); start()   # restore
        assert sql("SELECT count(*) FROM key_usage WHERE key_id = 2;") == "0"  # key 2 has no row in the restored database
        for kid in map(int, ring_newest["keys"]):                    # procedure: seal EVERY id of the newest ring
            seal(kid)
        assert usable(2) is False and reserve(2) is None and usable(1) is False
        new_id = ring_newest["highestKeyId"] + 1                      # a new key never reuses an identifier
        assert new_id == 3
        register(new_id); assert usable(new_id) is True and reserve(new_id) == BLOCK

    def tool(name, override):
        cand = override or (str(SB / name) if (SB / name).exists() else None)
        if not cand:
            return None
        v = run([cand, "--version"]).stdout
        sv = sql("SHOW server_version_num;")[:2]
        m = re.search(r"(\d+)(?:\.\d+)?", v)
        return cand if m and m.group(1)[:2] == sv[:2] else None

    dump_tool = tool("pg_dump", args.pg_dump)
    restore_tool = tool("pg_restore", args.pg_restore)

    if dump_tool and restore_tool:
        @test("logical restore (pg_dump / pg_restore): counter rolls back, rate_limits excluded from the backup, new key and sealing stop the old key resuming (RD-13, CH-2)")
        def _():
            reset_data(); register(1); assert reserve(1) == BLOCK
            sql(RL.format(cap=3, refill=0))                           # live rate-limit row, must NOT be in the backup
            dumpfile = work / "dc.dump"
            conn = ["-h", str(sock), "-p", str(PORT), "-U", "tester"]
            r = run([dump_tool, "-Fc", "--exclude-table-data=rate_limits", "-f", str(dumpfile), *conn, "dc"]); assert r.returncode == 0, r.stderr
            before_backup = R()
            for _ in range(5): assert reserve(1) is not None           # reservations after the backup
            pre_restore = R()
            assert sql("SELECT count(*) FROM rate_limits;") == "1"
            sql("DROP DATABASE dc;", db="postgres"); sql("CREATE DATABASE dc;", db="postgres")
            r = run([restore_tool, "-d", "dc", *conn, str(dumpfile)]); assert r.returncode == 0, r.stderr
            assert R() == before_backup < pre_restore                 # the restored counter is behind
            assert sql("SELECT count(*) FROM rate_limits;") == "0"    # excluded from the backup (CH-2)
            assert sql("SELECT count(*) FROM games;") == "0"
            register(2); seal(1)                                      # the procedure
            assert usable(1) is False and reserve(1) is None and R(1) == L
            stale = Instance(key=1)
            try:
                stale.request(); raise AssertionError("encryption resumed under the sealed key after a logical restore")
            except Refused:
                pass
            fresh = Instance(key=2); fresh.request(); assert R(2) == BLOCK
    else:
        results.append(("logical restore (pg_dump / pg_restore): SKIPPED, no pg_dump/pg_restore of the server's major version available", None, ""))

finally:
    stop()
    shutil.rmtree(work, ignore_errors=True)

width = max(len(n) for n, _, _ in results)
failed = 0
print(f"PostgreSQL {version}  (server-bin {SB})")
skipped = 0
for name, ok, detail in results:
    if ok is None:
        print("SKIP  " + name); skipped += 1; continue
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        {detail}"))
    failed += 0 if ok else 1
ran = len(results) - skipped
print(f"\n{ran - failed} of {ran} tests passed on PostgreSQL {version}" + (f" ({skipped} skipped)" if skipped else ""))
sys.exit(1 if failed else 0)
