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
        assert sql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public';") == "14"
        assert sql("SELECT count(*) FROM ring_state;") == "1"        # the singleton is created by the schema itself (CR-19)

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
    register_sql = next(b for b in blocks if "INSERT INTO key_usage (key_id, fingerprint) VALUES ($1, $2)" in b)
    seal_sql = re.search(r"`(INSERT INTO key_usage \(key_id, fingerprint, reserved, sealed\) VALUES \(\$1, \$2, 1073741824, true\) ON CONFLICT \(key_id\) DO UPDATE SET reserved = 1073741824, sealed = true;)`", spec_text).group(1)
    check_sql = next(b for b in blocks if "SELECT NOT sealed AND fingerprint = $2 AS usable FROM key_usage" in b)
    commit_check_sql = next(b for b in blocks if "SELECT sealed FROM key_usage WHERE key_id = $1 FOR SHARE" in b).strip()
    report_sql = next(b for b in blocks if "INSERT INTO instance_ring_reports" in b)
    activation_sql = next(b for b in blocks if "AS all_staged" in b)
    offline_sql = next(b for b in blocks if "AS no_readers" in b)
    presence_sql = next(b for b in blocks if "SELECT pg_advisory_lock(4242002, $1);" in b).strip()
    admission_sql = next(b for b in blocks if "AS admitted FROM ring_state" in b).strip()
    require_sql = next(b for b in blocks if "UPDATE ring_state SET required_key_ids = array_append" in b).strip()
    reconcile_sql = next(b for b in blocks if "UPDATE ring_state SET required_key_ids = $1::smallint[]" in b).strip()
    L = 2 ** 30
    BLOCK = 1024

    def fp(k, material=None):
        """Stand-in for the key fingerprint: SHA-256 of the key material (the material is a label here)."""
        return f"sha256(convert_to('material-{material if material is not None else k}','UTF8'))"

    def reserve(k, block=BLOCK, limit=L, material=None):
        """The real reservation statement on its own connection. Returns the new total, or None if refused."""
        text = reserve_sql.replace("$1", str(k)).replace("$2", str(block)).replace("$3", str(limit)).replace("$4", fp(k, material))
        out = sql(text)
        return int(out) if out else None

    def register(k, material=None, expect_error=None):
        return sql(register_sql.replace("$1", str(k)).replace("$2", fp(k, material)), expect_error=expect_error)

    def seal(k, material=None):
        sql(seal_sql.replace("$1", str(k)).replace("$2", fp(k, material)))

    def usable(k, material=None):
        """The pre-encryption check taken from the specification. No row (unregistered key) counts as unusable."""
        return sql(check_sql.replace("$1", str(k)).replace("$2", fp(k, material))) == "t"

    def R(k=1):
        out = sql(f"SELECT coalesce(sum(reserved),0) FROM key_usage WHERE key_id={k};")
        return int(out)

    def set_R(k, v):
        sql(f"INSERT INTO key_usage(key_id, fingerprint, reserved) VALUES ({k},{fp(k)},{v}) ON CONFLICT (key_id) DO UPDATE SET reserved = EXCLUDED.reserved;")

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

        def claim(self):
            """Claim one unit for an operation, reserving first if the allowance is empty (claim BEFORE the check)."""
            if self.allowance == 0:
                self.reserve_block()          # raises Refused when no unit can be reserved
            self.allowance -= 1
            return 1

        def request(self):
            """One encrypting request in the specified order: claim, then the pre-encryption check (spec statement) as the
            last step, returning the claim if the check fails, then consume exactly that claim."""
            c = self.claim()
            if not usable(self.key):
                self.allowance += c           # return the unused claim
                raise Refused()
            self.invocations += 1             # consume the claimed unit

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
        sql(f"INSERT INTO key_usage(key_id, fingerprint, reserved) VALUES (1, {fp(1, 'other')}, 5);", expect_error="key_usage_pkey")
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
        try:
            a.stdin.write(cmds + "\n\\q\n"); a.stdin.flush()
            out, err = a.communicate(timeout=30)
            return out.strip()
        except Exception:
            a.kill()                          # terminate and reap a stalled session so its locks are released (CR-15)
            try:
                a.communicate(timeout=10)
            except Exception:
                pass
            raise

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
        A = session("BEGIN;\n" + reserve_sql.replace("$1", "1").replace("$2", str(BLOCK)).replace("$3", str(L)).replace("$4", fp(1)))   # A holds the row lock, uncommitted
        bounded = "SET lock_timeout = '20s';\n" + reserve_sql.replace("$1", "1").replace("$2", str(BLOCK)).replace("$3", str(L)).replace("$4", fp(1))
        ex = ThreadPoolExecutor(1)
        try:
            fut = ex.submit(lambda: sql(bounded))                               # B blocks on the row lock, bounded by lock_timeout
            time.sleep(1.0)
            waited = not fut.done()
        finally:
            finish(A, "COMMIT;")                                                # release A BEFORE the executor shuts down (CR-13)
        try:
            out = fut.result(timeout=40)
        finally:
            ex.shutdown(wait=False)
        assert out.replace("SET", "").strip() == "", out                       # B re-evaluated against the committed total and was refused
        assert waited, "B did not wait for A: the reservations are not serialised"
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
        try:
            assert "ready" in a.stdout.readline()
            got = reserve(1)                               # separate connection, own transaction, commits
        finally:
            try:
                a.stdin.write("ROLLBACK;\n\\q\n"); a.stdin.flush(); a.wait(timeout=20)
            except Exception:
                a.kill(); a.wait(timeout=20)               # termination as a fallback (CR-14)
        assert got == BLOCK
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
            return warn <= rot <= hard <= L and block >= 1 and hard % block == 0 and block <= 2 ** 20
        assert valid(2 ** 27, 2 ** 28, L, 1024)
        assert not valid(2 ** 27, 2 ** 28, L + 1024, 1024)
        assert not valid(2 ** 27, 2 ** 28, L - 1, 1024)
        assert not valid(2 ** 29, 2 ** 28, L, 1024)
        assert not valid(2 ** 27, 2 ** 28, L, 0) and not valid(2 ** 27, 2 ** 28, L, -1024)
        assert valid(2 ** 27, 2 ** 28, 268435458, 3)        # a block only has to divide the configured hard stop (CR-13)

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

    @test("atomic claims: one reserved unit, 16 racing requests: exactly one claims and consumes it; a consumed claim is never returned, an unused claim is (CR-11, CR-12)")
    def _():
        import threading
        reset_data(); register(1)
        assert reserve(1, block=1) == 1                  # the unit really is reserved: R = 1
        lock = threading.Lock()                          # models the single-threaded synchronous claim step of one process
        st = {"allowance": 1, "consumed": 0}
        claimed, deferred = [], []
        def request(i):
            with lock:
                if st["allowance"] >= 1:
                    st["allowance"] -= 1; claimed.append(i); got = True
                else:
                    deferred.append(i); got = False
            if got:
                with lock:
                    st["consumed"] += 1                  # used: spent for ever, never returned
        with ThreadPoolExecutor(16) as ex:
            list(ex.map(request, range(16)))
        assert len(claimed) == 1 and len(deferred) == 15 and st["consumed"] == 1 and st["allowance"] == 0
        assert st["consumed"] <= R() == 1
        # phase 2: one more real unit. A request that claims but ends without encrypting returns its claim. Another then uses it.
        assert reserve(1, block=1) == 2
        with lock: st["allowance"] += 1
        with lock: st["allowance"] -= 1                  # request A claims
        with lock: st["allowance"] += 1                  # request A ends without encrypting: returns the UNUSED claim
        with lock: st["allowance"] -= 1; st["consumed"] += 1   # request B claims the returned unit and consumes it
        assert st["allowance"] == 0 and st["consumed"] == 2 and st["consumed"] <= R() == 2

    @test("claim recheck after a pending reservation: no claim ever exceeds the allowance that really exists (CR-12 model, real reservations)")
    def _():
        import threading
        reset_data(); register(1)
        lock = threading.Lock()
        st = {"allowance": 0, "claims": 0, "min_allowance": 0}
        def acquire(m=1):
            while True:
                with lock:                                # synchronous check-and-decrement, AFTER any wait
                    if st["allowance"] >= m:
                        st["allowance"] -= m; st["claims"] += m
                        st["min_allowance"] = min(st["min_allowance"], st["allowance"])
                        return True
                    shortfall = m - st["allowance"]       # recomputed from the allowance as it is now
                blocks_needed = -(-shortfall // 4)
                granted = reserve(1, block=4 * blocks_needed)   # the (slow) reservation, outside the lock
                if granted is None:
                    return False
                with lock:
                    st["allowance"] += 4 * blocks_needed  # units join the allowance only after the statement returned
        with ThreadPoolExecutor(12) as ex:
            results = list(ex.map(lambda i: acquire(1), range(12)))
        assert all(results) and st["claims"] == 12 and st["min_allowance"] >= 0
        assert R() >= st["claims"] and R() - st["claims"] == st["allowance"]   # every unit is either claimed or still in the allowance

    @test("fingerprint uniqueness: retired key material cannot be registered again under a new identifier (CR-12)")
    def _():
        reset_data()
        register(1, material="A"); assert reserve(1, material="A") == BLOCK
        seal(1, material="A")                              # key 1 superseded and sealed. Its row is never deleted
        register(2, material="A", expect_error="key_usage_fingerprint_key")   # same material under a new id: refused by the database
        register(3, material="B")                          # new material is accepted
        assert sql("SELECT count(*) FROM key_usage;") == "2" and R(3) == 0

    @test("keys:generate order: reservation under an unregistered key is refused, so register first, reserve second, and a new key starts at 1 or more (CR-12)")
    def _():
        reset_data()
        assert reserve(5, block=1) is None                 # unregistered
        register(5); assert reserve(5, block=1) == 1       # the self-test unit
        assert R(5) >= 1 and usable(5) is True

    @test("restore procedure seals exactly the identifiers of the ring before the new key was added, never the new key (CR-12)")
    def _():
        reset_data()
        ring_before = [1, 2]                               # the newest ring, captured BEFORE adding the new key
        new_id = max(ring_before) + 1
        register(1); register(2); assert reserve(2) == BLOCK
        for kid in ring_before: seal(kid)                  # the procedure
        register(new_id)                                   # the new key is generated and registered after the set was captured
        assert usable(1) is False and usable(2) is False and usable(new_id) is True and reserve(new_id) == BLOCK
        seal(new_id)                                       # what the procedure must NOT do: this test documents the failure it would cause
        assert usable(new_id) is False

    @test("health by key role: only the active key can be warning, degraded or critical; a sealed non-active key is 'sealed' with no alert; a sealed active key is critical (CR-12 rule)")
    def _():
        W, RT, H = 2 ** 27, 2 ** 28, L
        def health(active, sealed, r):
            if sealed:
                return "critical" if active else "sealed"
            if not active:
                return "ok"
            return "critical" if r >= H else "degraded" if r >= RT else "warning" if r >= W else "ok"
        assert health(True, False, 10) == "ok" and health(True, False, W) == "warning"
        assert health(True, False, RT) == "degraded" and health(True, False, H) == "critical"
        assert health(False, True, L) == "sealed"          # a normal rotation leaves no alarm behind
        assert health(True, True, L) == "critical"         # misconfiguration
        assert health(False, False, RT) == "ok"

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
        A.request()                                       # A claims (reserving a block), passes the check, consumes: 1023 left
        assert A.allowance == BLOCK - 1 and A.invocations == 1 and reserve(1) is not None   # reservations still granted past 2^28 (RD-14)
        before_seal = R()
        register(2); seal(1)                              # rotation completes: new key registered, old key sealed
        assert R() == L and R() >= before_seal            # unused reservations stay counted, the counter never decreased
        try:
            A.request(); raise AssertionError("A encrypted under the sealed key although it still held an allowance")
        except Refused:
            pass
        assert A.allowance == BLOCK - 1                   # the claim was returned when the check failed: allowance unchanged but unusable
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

    @test("commit-time check: the seal waits for a transaction holding the key row FOR SHARE; a transaction checking after the seal reads sealed and rolls back (CR-13)")
    def _():
        reset_data(); register(1); new_game(1); new_player(11, 1, 1)
        chk = commit_check_sql.replace("$1", "1")
        T = session("BEGIN;\n"
                    f"INSERT INTO secret_codes(player_id,key_id,ciphertext) VALUES ('{u(11)}',1,decode(repeat('01',32),'hex'));\n" + chk)
        ex = ThreadPoolExecutor(1)
        try:
            fut = ex.submit(lambda: sql("SET lock_timeout = '20s';\n" + seal_sql.replace("$1", "1").replace("$2", fp(1))))
            time.sleep(1.0)
            seal_waited = not fut.done()
        finally:
            finish(T, "COMMIT;")                         # T saw 'f' and commits its ciphertext BEFORE the seal
        try:
            fut.result(timeout=40)
        finally:
            ex.shutdown(wait=False)
        assert seal_waited, "the seal did not wait for the transaction in its commit-time check"
        assert usable(1) is False and sql("SELECT count(*) FROM secret_codes WHERE key_id=1;") == "1"
        # a later transaction reaches its check after the seal: it must see 'sealed' and roll back
        new_player(12, 1, 2)
        out = sql("BEGIN;\n"
                  f"INSERT INTO secret_codes(player_id,key_id,ciphertext) VALUES ('{u(12)}',1,decode(repeat('02',32),'hex'));\n"
                  + chk + "\nROLLBACK;")                # the application rolls back when it reads 't'
        assert out.strip().splitlines()[-1] == "t", out
        assert sql("SELECT count(*) FROM secret_codes WHERE key_id=1;") == "1"   # nothing committed after the seal

    @test("registration: idempotent for the same material, refused for different material on the same id or the same material on a new id (CR-13)")
    def _():
        reset_data()
        assert register(1, material="A") == "1"            # new
        assert register(1, material="A") == "1"            # repeat after an interrupted run: same material, row returned
        assert register(1, material="B") == ""             # same id, different material: no row, nothing changed
        assert sql(f"SELECT fingerprint = {fp(1, 'A')} FROM key_usage WHERE key_id=1;") == "t"
        register(2, material="A", expect_error="key_usage_fingerprint_key")
        next_id = max(2, int(sql("SELECT max(key_id) FROM key_usage;"))) + 1   # above ring highestKeyId (2 here) and the registry
        assert next_id == 3

    @test("restore seals every identifier in the fingerprint history, restoring the registry for a key retired early (CR-13)")
    def _():
        reset_data()
        register(1, material="A"); register(2, material="B"); assert reserve(2, material="B") == BLOCK
        stop(); backup = work / "backup3"; shutil.copytree(data, backup); start()
        register(3, material="C"); assert reserve(3, material="C") == BLOCK               # key 3 registered after the backup ...
        history = {1: "A", 2: "B", 3: "C"}                                  # ... then retired early and removed from the ring (history keeps it)
        stop(); shutil.rmtree(data); shutil.copytree(backup, data); start()  # restore
        assert sql("SELECT count(*) FROM key_usage WHERE key_id=3;") == "0"
        for kid, mat in history.items():                                    # S = every id in the history, before the new key
            seal(kid, material=mat)
        assert usable(3, material="C") is False and R(3) == L
        register(4, material="C", expect_error="key_usage_fingerprint_key")  # the registry backstop is back
        assert register(4, material="D") == "4" and usable(4, material="D") is True

    @test("lossless proof covers every key that can still encrypt, including STAGED keys (CR-13 rule)")
    def _():
        def lossless(pre, restored, can_encrypt):
            for k in can_encrypt:
                if k not in restored: return False
                if restored[k]["sealed"] != pre[k]["sealed"]: return False
                if restored[k]["reserved"] < pre[k]["reserved"]: return False
            return True
        pre = {1: {"reserved": 5000, "sealed": False}, 2: {"reserved": 1, "sealed": False}}
        assert lossless(pre, dict(pre), [1, 2]) is True
        assert lossless(pre, {1: pre[1]}, [1, 2]) is False                  # staged key 2's row missing
        assert lossless(pre, {1: pre[1], 2: {"reserved": 0, "sealed": False}}, [1, 2]) is False   # staged key behind
        assert lossless(pre, {1: pre[1]}, [1]) is True                      # checking only the active key would wrongly pass

    @test("retry after a refused reservation: a unit returned between the refusal and the final check is claimed by the same call (CR-13, CR-14 model, real reservations)")
    def _():
        import threading
        reset_data(); register(1); set_R(1, L)                             # no further reservation is possible
        lock = threading.Lock(); st = {"allowance": 0}

        def acquire(between_refusal_and_recheck=None, recheck=True):
            with lock:
                if st["allowance"] >= 1:
                    st["allowance"] -= 1; return "fast"
            if reserve(1, block=1) is not None:
                with lock: st["allowance"] += 1
            elif between_refusal_and_recheck:
                between_refusal_and_recheck()                              # another request returns an unused unit now
            if recheck:
                with lock:                                                 # one more synchronous check before giving up
                    if st["allowance"] >= 1:
                        st["allowance"] -= 1; return "recheck"
            return None

        def give_back():
            with lock: st["allowance"] += 1

        assert acquire() is None                                           # nothing anywhere
        assert acquire(give_back) == "recheck" and st["allowance"] == 0     # claimed only because of the recheck
        assert acquire(give_back, recheck=False) is None                   # without the recheck the same scenario fails
        st["allowance"] = 0

    @test("material bound to the registry: reservation and pre-encryption check refuse a key whose loaded material differs from the registered fingerprint (CR-14)")
    def _():
        reset_data(); register(1, material="A"); register(2, material="B")
        assert usable(2, material="B") is True and reserve(2, material="B") == BLOCK
        assert usable(2, material="A") is False                            # retired material A pasted into key 2's ring entry
        assert reserve(2, material="A") is None and R(2) == BLOCK

    @test("lossless proof also covers every history key: a missing row or an undone seal is not lossless (CR-14 rule)")
    def _():
        def lossless(pre, restored, can_encrypt, history):
            for k in can_encrypt:
                if k not in restored or restored[k]["sealed"] != pre[k]["sealed"] or restored[k]["reserved"] < pre[k]["reserved"]:
                    return False
            for k in history:
                if k not in restored or restored[k]["fp"] != pre[k]["fp"] or restored[k]["sealed"] != pre[k]["sealed"]:
                    return False
            return True
        pre = {1: {"reserved": L, "sealed": True, "fp": "a"}, 2: {"reserved": 50, "sealed": False, "fp": "b"}}
        assert lossless(pre, dict(pre), [2], [1, 2]) is True
        assert lossless(pre, {2: pre[2]}, [2], [1, 2]) is False                                   # history key 1 row missing
        assert lossless(pre, {1: {"reserved": L, "sealed": False, "fp": "a"}, 2: pre[2]}, [2], [1, 2]) is False   # seal undone

    @test("retired keys keep their row for ever; the material stays refused under a new identifier (CR-14)")
    def _():
        reset_data(); register(1, material="A"); seal(1, material="A")
        assert sql("SELECT count(*) FROM key_usage WHERE key_id=1;") == "1"   # retirement never deletes the row
        register(9, material="A", expect_error="key_usage_fingerprint_key")

    @test("in-flight request between check and seal: it passed the check before the seal, its commit-time check after the seal rolls it back (CR-15)")
    def _():
        reset_data(); register(1); new_game(1); new_player(11, 1, 1)
        A = Instance(key=1)
        c = A.claim()
        assert usable(1) is True                          # the request passed its pre-encryption check ...
        seal(1)                                           # ... then the key is sealed before its transaction commits
        out = sql("BEGIN;\n"
                  f"INSERT INTO secret_codes(player_id,key_id,ciphertext) VALUES ('{u(11)}',1,decode(repeat('01',32),'hex'));\n"
                  + commit_check_sql.replace("$1", "1") + "\nROLLBACK;")
        assert out.strip().splitlines()[-1] == "t"        # the commit-time check sees the seal, the application rolls back
        A.invocations += c                                # the unit was consumed by the (rolled-back) encryption and stays counted
        assert sql("SELECT count(*) FROM secret_codes WHERE key_id=1;") == "0"
        assert A.invocations <= R(1) == L

    @test("ring single-writer lock: a second ring-changing operation cannot take the advisory lock while the first holds it (CR-15)")
    def _():
        lock_key = re.search(r"pg_advisory_lock\((\d+)\)", spec_text).group(1)   # the key from the specification
        A = session(f"SELECT pg_advisory_lock({lock_key});")
        try:
            assert sql(f"SELECT pg_try_advisory_lock({lock_key});") == "f"
        finally:
            finish(A, f"SELECT pg_advisory_unlock({lock_key});")
        assert sql(f"SELECT pg_try_advisory_lock({lock_key}); SELECT pg_advisory_unlock({lock_key});").splitlines()[0] == "t"

    @test("staged-activation roster: live presence locks, not recent reports, decide; a stopped process is not counted, a silent live one blocks (CR-16, CR-17)")
    def _():
        sql("TRUNCATE instance_ring_reports;")
        procs = {}
        def start_proc(pid, report_keys=None):
            procs[pid] = session(presence_sql.replace("$1", str(pid)))      # the live presence connection
            if report_keys is not None:
                sql(report_sql.replace("$1", str(pid)).replace("$2", "8").replace("$3", "ARRAY[" + ",".join(map(str, report_keys)) + "]::smallint[]"))
        def stop_proc(pid):
            finish(procs.pop(pid))
        def all_staged(n, key=2):
            return sql(activation_sql.replace("$1", str(n)).replace("$2", str(key)))
        try:
            assert all_staged(0) == "f"                                     # empty roster: false, never NULL
            start_proc(11, [1, 2]); start_proc(12, [1, 2])
            assert all_staged(2) == "t" and all_staged(3) == "f"
            start_proc(13, None)                                            # live reader that has NOT reported
            assert all_staged(3) == "f"
            stop_proc(11)                                                   # a stopped process with a fresh report ...
            assert all_staged(2) == "f"                                     # ... is not counted, and the silent live reader still blocks
            sql(report_sql.replace("$1", "13").replace("$2", "7").replace("$3", "ARRAY[1]::smallint[]"))   # reports without the staged key
            assert all_staged(2) == "f"
            sql(report_sql.replace("$1", "13").replace("$2", "8").replace("$3", "ARRAY[1,2]::smallint[]"))
            assert all_staged(2) == "t"
            V = session("SELECT pg_advisory_lock(4242003, 99);")            # a running keyverify blocks activation
            try:
                assert all_staged(2) == "f"
                assert sql(offline_sql) == "f"
            finally:
                finish(V)
            assert all_staged(2) == "t" and sql(offline_sql) == "f"         # readers live: offline activation refused
        finally:
            for pid in list(procs): stop_proc(pid)
        assert sql(offline_sql) == "t"                                      # nobody live: offline activation allowed

    @test("report privileges: the restricted application role can upsert its report and cleanup can prune (CR-17)")
    def _():
        sql("TRUNCATE instance_ring_reports;")
        sql("DROP ROLE IF EXISTS duocode_app_t; CREATE ROLE duocode_app_t; GRANT SELECT, INSERT, UPDATE, DELETE ON instance_ring_reports TO duocode_app_t;")
        prune = "DELETE FROM instance_ring_reports" + next(b for b in blocks if "WITH batch AS" in b).split("DELETE FROM instance_ring_reports", 1)[1]
        try:
            up = report_sql.replace("$1", "21").replace("$2", "8").replace("$3", "ARRAY[1]::smallint[]")
            sql("SET ROLE duocode_app_t;\n" + up + "\n" + up)                 # insert, then the ON CONFLICT path
            sql("UPDATE instance_ring_reports SET reported_at = now() - interval '2 hours';")
            sql("SET ROLE duocode_app_t;\n" + prune)
            assert sql("SELECT count(*) FROM instance_ring_reports;") == "0"
        finally:
            sql("REVOKE ALL ON instance_ring_reports FROM duocode_app_t; DROP ROLE duocode_app_t;")

    @test("role separation: keymgmt can change key_usage but cannot read game ciphertext; keyverify can read but not change (CR-16)")
    def _():
        sql("DROP ROLE IF EXISTS duocode_keymgmt; DROP ROLE IF EXISTS duocode_keyverify;")
        sql("CREATE ROLE duocode_keymgmt; GRANT SELECT, INSERT, UPDATE ON key_usage TO duocode_keymgmt; GRANT SELECT ON instance_ring_reports TO duocode_keymgmt;")
        sql("CREATE ROLE duocode_keyverify; GRANT SELECT ON key_usage, secret_codes, guesses, idempotency_keys, token_rotations TO duocode_keyverify; GRANT SELECT (id, game_id) ON players TO duocode_keyverify;")
        try:
            sql("SET ROLE duocode_keymgmt; SELECT count(*) FROM key_usage; UPDATE key_usage SET reserved = reserved WHERE false; SELECT count(*) FROM instance_ring_reports;")
            sql("SET ROLE duocode_keymgmt; SELECT count(*) FROM secret_codes;", expect_error="permission denied")
            sql("SET ROLE duocode_keymgmt; SELECT count(*) FROM guesses;", expect_error="permission denied")
            sql("SET ROLE duocode_keyverify; SELECT count(*) FROM secret_codes; SELECT count(*) FROM guesses; SELECT count(*) FROM key_usage;")
            sql("SET ROLE duocode_keyverify; SELECT count(*) FROM secret_codes s JOIN players p ON p.id = s.player_id; SELECT count(*) FROM guesses g JOIN players p ON p.id = g.player_id; SELECT p.game_id FROM players p LIMIT 1;")   # AAD needs game_id
            sql("SET ROLE duocode_keyverify; SELECT nickname FROM players;", expect_error="permission denied")
            sql("SET ROLE duocode_keyverify; UPDATE key_usage SET reserved = reserved WHERE false;", expect_error="permission denied")
        finally:
            sql("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM duocode_keymgmt, duocode_keyverify; DROP ROLE duocode_keymgmt; DROP ROLE duocode_keyverify;")

    @test("admission gate: after activation commits the staged key, a reader without it is refused; a reader admitted just before is counted and blocks until it reports the key (CR-18)")
    def _():
        sql("TRUNCATE instance_ring_reports; UPDATE ring_state SET required_key_ids = '{}';")   # the row comes from the DDL
        assert sql(require_sql.replace("$1", "1")).strip() != ""         # RETURNING: exactly one row changed
        def admit(conn_cmds, keys):
            return conn_cmds + "\n" + admission_sql.replace("$1", "ARRAY[" + ",".join(map(str, keys)) + "]::smallint[]")
        def report(pid, keys):
            sql(report_sql.replace("$1", str(pid)).replace("$2", "8").replace("$3", "ARRAY[" + ",".join(map(str, keys)) + "]::smallint[]"))
        early = session(admit(presence_sql.replace("$1", "31"), [1]))     # admitted BEFORE the activation commit, ring lacks key 2
        try:
            report(31, [1])
            sql(require_sql.replace("$1", "2"))                          # activation step 1: commit the requirement
            # a reader starting now with the old ring is refused by the admission check
            late_out = sql(presence_sql.replace("$1", "32") + "\n" + admission_sql.replace("$1", "ARRAY[1]::smallint[]") + "\nSELECT pg_advisory_unlock(4242002, 32);")
            assert late_out.splitlines()[0] == "f", late_out   # (pg_advisory_lock returns void, so the first line is the admission result)
            # activation step 2: the early reader is in the roster and its report lacks key 2, so activation is refused
            assert sql(activation_sql.replace("$1", "1").replace("$2", "2")) == "f"
            report(31, [1, 2])                                           # (in practice: restarted with the staged ring)
            assert sql(activation_sql.replace("$1", "1").replace("$2", "2")) == "t"
            ok_out = sql(presence_sql.replace("$1", "33") + "\n" + admission_sql.replace("$1", "ARRAY[1,2]::smallint[]") + "\nSELECT pg_advisory_unlock(4242002, 33);")
            assert ok_out.splitlines()[0] == "t"                         # a reader with the staged key is admitted
        finally:
            finish(early)

    @test("bounded locks: keyverify's shared try-lock fails during a ring change, keymgmt's exclusive try-lock fails during a verification, both free afterwards (CR-18)")
    def _():
        lock_key = re.search(r"pg_advisory_lock\((\d+)\)", spec_text).group(1)
        M = session(f"SELECT pg_advisory_lock({lock_key});")             # keymgmt changing the ring
        try:
            assert sql(f"SELECT pg_try_advisory_lock_shared({lock_key});") == "f"   # keyverify exits "busy" at once
        finally:
            finish(M)
        V = session(f"SELECT pg_try_advisory_lock_shared({lock_key});")  # keyverify running
        try:
            assert sql(f"SELECT pg_try_advisory_lock({lock_key});") == "f"          # keymgmt's try fails, it retries until its deadline
        finally:
            finish(V)                                                    # the session lock goes with the connection
        out = sql(f"SELECT pg_try_advisory_lock({lock_key}); SELECT pg_advisory_unlock({lock_key});")
        assert out.splitlines()[0] == "t"

    @test("retry is a fresh attempt: a rolled-back attempt's spent unit is never reused; the retry claims again before beginning (CR-18 model, real reservation and rollback)")
    def _():
        reset_data(); register(1); new_game(1); new_player(11, 1, 1)
        inst = Instance(key=1, block=1)
        class Claim:
            def __init__(self, n): self.n = n; self.spent = 0
        def attempt(claim, fail):
            assert claim.n - claim.spent >= 1, "encryption without an unspent unit of THIS attempt's claim"
            claim.spent += 1; inst.invocations += 1          # unit consumed before the cipher is called
            out = sql("BEGIN;\n" f"INSERT INTO secret_codes(player_id,key_id,ciphertext) VALUES ('{u(11)}',1,decode(repeat('01',32),'hex'));\n"
                      + ("ROLLBACK;" if fail else "COMMIT;"))
            return not fail
        c1 = Claim(inst.claim())
        assert attempt(c1, fail=True) is False               # deadlock-style failure after the encryption
        try:
            attempt(c1, fail=False); raise AssertionError("retry reused a spent unit")
        except AssertionError as e:
            assert "unspent unit" in str(e)
        c2 = Claim(inst.claim())                             # the retry claims again (reserving: block of 1)
        assert attempt(c2, fail=False) is True
        assert inst.invocations == 2 <= R(1) == 2
        assert sql("SELECT count(*) FROM secret_codes;") == "1"

    @test("gate privileges: keymgmt updates the gate; application and keyverify roles can only run the admission check (CR-19)")
    def _():
        sql("DROP ROLE IF EXISTS t_km; DROP ROLE IF EXISTS t_app; DROP ROLE IF EXISTS t_kv;")
        sql("CREATE ROLE t_km; GRANT SELECT, UPDATE ON ring_state TO t_km; CREATE ROLE t_app; GRANT SELECT ON ring_state TO t_app; CREATE ROLE t_kv; GRANT SELECT ON ring_state TO t_kv;")
        adm = admission_sql.replace("$1", "ARRAY[1,2]::smallint[]")
        try:
            assert sql("SET ROLE t_km;\n" + require_sql.replace("$1", "2")).strip() != ""
            for r in ("t_app", "t_kv"):
                assert sql(f"SET ROLE {r};\n" + adm).strip() in ("t", "f")
                sql(f"SET ROLE {r};\n" + require_sql.replace("$1", "3"), expect_error="permission denied")
        finally:
            sql("REVOKE ALL ON ring_state FROM t_km, t_app, t_kv; DROP ROLE t_km; DROP ROLE t_app; DROP ROLE t_kv;")

    @test("gate reconciliation after restore: stale retired and abandoned requirements are replaced by the newest ring's keys; refused while a reader is live (CR-19)")
    def _():
        reset_data(); sql("TRUNCATE instance_ring_reports;")
        sql("UPDATE ring_state SET required_key_ids = ARRAY[1,2,5,9]::smallint[];")   # restored: 9 retired since, 5 a staged key now abandoned
        newest_ring = [1, 2, 6]                                                         # what the newest ring loads after recovery
        new_game(1); new_player(11, 1, 1)
        sql(f"INSERT INTO secret_codes(player_id,key_id,ciphertext) VALUES ('{u(11)}',2,decode(repeat('01',32),'hex'));")
        referenced = {int(x) for x in sql("SELECT DISTINCT key_id FROM secret_codes UNION SELECT DISTINCT key_id FROM guesses UNION SELECT DISTINCT token_key_id FROM token_rotations WHERE token_key_id IS NOT NULL;").split()}
        assert referenced <= set(newest_ring)                            # the tool's pre-check passes
        arr = "ARRAY[" + ",".join(map(str, newest_ring)) + "]::smallint[]"
        adm_old = admission_sql.replace("$1", arr)
        assert sql(adm_old) == "f"                                       # before reconciliation every reader with the newest ring is refused
        R1 = session(presence_sql.replace("$1", "41"))                   # a live reader
        try:
            assert sql(reconcile_sql.replace("$1", arr)).strip() == ""    # refused while any reader is live
        finally:
            finish(R1)
        assert sql(reconcile_sql.replace("$1", arr)).strip() == "{1,2,6}"
        assert sql(adm_old) == "t"                                       # verifier and restarted readers are admitted
        assert not ({9} <= set(newest_ring))                             # a referenced key outside the ring would stop the tool:
        sql(f"UPDATE secret_codes SET key_id = 9;")
        referenced = {int(x) for x in sql("SELECT DISTINCT key_id FROM secret_codes;").split()}
        assert not (referenced <= set(newest_ring))

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
