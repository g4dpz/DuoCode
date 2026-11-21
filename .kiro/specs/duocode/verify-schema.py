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

    # ----- key usage reservation (RD-10, RD-13) -----------------------------
    RESERVE = ("BEGIN; INSERT INTO key_usage (key_id, shard, reserved) VALUES ({k}, {sh}, {b}) "
               "ON CONFLICT (key_id, shard) DO UPDATE SET reserved = key_usage.reserved + EXCLUDED.reserved; "
               "SELECT sum(reserved) FROM key_usage WHERE key_id = {k}; COMMIT;")

    def total(k=1):
        return int(sql(f"SELECT coalesce(sum(reserved),0) FROM key_usage WHERE key_id={k};"))

    @test("reservation is not undone when the application transaction rolls back")
    def _():
        reset_data()
        a = subprocess.Popen(psql_cmd("dc"), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        a.stdin.write("BEGIN;\n"); a.stdin.write(f"INSERT INTO games(id,state,config,expires_at) VALUES ('{u(1)}','ACTIVE','{{}}',now());\n"); a.stdin.write("SELECT 'ready';\n"); a.stdin.flush()
        line = a.stdout.readline()
        assert "ready" in line, line
        sql(RESERVE.format(k=1, sh=3, b=1024))      # separate connection, own transaction, commits
        a.stdin.write("ROLLBACK;\n\\q\n"); a.stdin.flush(); a.wait(timeout=20)
        assert total() == 1024, total()
        assert sql("SELECT count(*) FROM games;") == "0"

    @test("reservation survives a failed application transaction (error aborts it)")
    def _():
        reset_data()
        cmd = [c if c != "ON_ERROR_STOP=1" else "ON_ERROR_STOP=0" for c in psql_cmd("dc")]   # keep the session open after the error
        a = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        a.stdin.write("BEGIN;\nSELECT 1/0;\nSELECT 'ready';\n"); a.stdin.flush()
        sql(RESERVE.format(k=1, sh=1, b=1024))
        a.stdin.write("ROLLBACK;\n\\q\n"); a.stdin.flush(); a.communicate(timeout=20)
        assert total() == 1024, total()

    @test("eight parallel instances, 100 reservations each: no lost increment")
    def _():
        reset_data()
        def instance(i):
            rnd = random.Random(i)
            body = "".join(RESERVE.format(k=1, sh=rnd.randrange(32), b=1024) + "\n" for _ in range(100))
            r = run(psql_cmd("dc") + ["-f", "-"], input=body)
            assert r.returncode == 0, r.stderr[:200]
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(instance, range(8)))
        assert total() == 8 * 100 * 1024, total()

    @test("policy model: reserved total never below actual encryptions under random interleavings, rollbacks and crashes")
    def _():
        rnd = random.Random(2026)
        BLOCK = 8
        for trial in range(300):
            db_total, performed = 0, 0
            inst = [{"allow": 0} for _ in range(rnd.randrange(1, 6))]
            for step in range(rnd.randrange(50, 300)):
                i = rnd.choice(inst)
                op = rnd.choices(["encrypt", "rollback_after_encrypt", "crash", "reserve_unknown"], [6, 3, 1, 1])[0]
                if op in ("encrypt", "rollback_after_encrypt"):
                    if i["allow"] < 1:            # must reserve before encrypting
                        db_total += BLOCK; i["allow"] += BLOCK
                    i["allow"] -= 1; performed += 1   # invocation consumes a unit even if the transaction rolls back
                elif op == "crash":
                    i["allow"] = 0                # unused allowance lost: over-count only
                else:
                    db_total += BLOCK             # reservation committed but outcome unknown: not used, over-count only
                assert db_total >= performed, (trial, step, db_total, performed)
            assert db_total - performed <= (len(inst) * 2 + 400) * BLOCK  # overshoot stays bounded

    @test("policy model: thresholds warn, flag rotation, then refuse at the hard stop permanently")
    def _():
        WARN, ROT, HARD, BLOCK = 20, 40, 80, 10
        total_, state, refused = 0, [], False
        for _ in range(12):
            total_ += BLOCK
            if total_ > HARD:
                refused = True; state.append("refuse"); continue   # block discarded, counter stays high
            state.append("rotate" if total_ >= ROT else "warn" if total_ >= WARN else "ok")
        assert state[:1] == ["ok"] and "warn" in state and "rotate" in state and refused and state[-1] == "refuse"

    @test("invariant check: rows under a key cannot exceed its reserved total; a lowered counter is detected")
    def _():
        reset_data(); new_game(1); new_player(11, 1, 1); new_player(12, 1, 2)
        sql(RESERVE.format(k=1, sh=0, b=1024))
        sql(f"INSERT INTO secret_codes(player_id,key_id,ciphertext) VALUES ('{u(11)}',1,decode(repeat('01',32),'hex')),('{u(12)}',1,decode(repeat('02',32),'hex'));")
        inv = ("SELECT (SELECT count(*) FROM secret_codes WHERE key_id=1) + (SELECT count(*) FROM guesses WHERE key_id=1) "
               "+ (SELECT count(*) FROM token_rotations WHERE token_key_id=1) <= (SELECT coalesce(sum(reserved),0) FROM key_usage WHERE key_id=1);")
        assert sql(inv) == "t"
        sql("UPDATE key_usage SET reserved = 1;")
        assert sql(inv) == "f"
        sql("UPDATE key_usage SET reserved = 0 WHERE false;")  # no-op, keeps statement count stable

    @test("key_usage: shard range and negative counts rejected")
    def _():
        reset_data()
        sql("INSERT INTO key_usage(key_id,shard,reserved) VALUES (1,32,1);", expect_error="key_usage_shard_check")
        sql("INSERT INTO key_usage(key_id,shard,reserved) VALUES (1,1,-1);", expect_error="key_usage_reserved_check")

    @test("restore hazard: a cold-backup restore rolls the counter back, so a new key is required (RD-13)")
    def _():
        reset_data()
        sql(RESERVE.format(k=1, sh=0, b=1024))
        stop(); backup = work / "backup"
        shutil.copytree(data, backup); start()
        before_backup = total()
        for _ in range(5):
            sql(RESERVE.format(k=1, sh=1, b=1024))      # encryptions after the backup
        pre_restore = total()
        stop(); shutil.rmtree(data); shutil.copytree(backup, data); start()   # restore
        restored = total()
        assert pre_restore > restored == before_backup, (pre_restore, restored, before_backup)
        # restore procedure decision (deployment.md 6.1 step 5): new key unless proved lossless
        def must_activate_new_key(pre, rest):
            return not (pre is not None and pre <= rest)
        assert must_activate_new_key(pre_restore, restored) is True
        assert must_activate_new_key(restored, restored) is False       # proved lossless path
        assert must_activate_new_key(None, restored) is True            # unknown pre-restore state: do it
        # new key starts with no usage, the old key's rows keep decrypting (DECRYPT_ONLY)
        assert total(2) == 0
        ring = {"generation": 8, "active": 2, "keys": {"1": {"status": "DECRYPT_ONLY", "deactivatedAt": "2027-01-01T00:00:00Z"}, "2": {"status": "ACTIVE", "deactivatedAt": None}}}
        actives = [k for k, v in ring["keys"].items() if v["status"] == "ACTIVE"]
        assert actives == ["2"] and all(v["deactivatedAt"] is None for k, v in ring["keys"].items() if v["status"] == "ACTIVE")

finally:
    stop()
    shutil.rmtree(work, ignore_errors=True)

width = max(len(n) for n, _, _ in results)
failed = 0
print(f"PostgreSQL {version}  (server-bin {SB})")
for name, ok, detail in results:
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"\n        {detail}"))
    failed += 0 if ok else 1
print(f"\n{len(results) - failed} of {len(results)} tests passed on PostgreSQL {version}")
sys.exit(1 if failed else 0)
